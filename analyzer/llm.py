"""Real LLM explanation — the seam described in report.py's docstring.

This module is the ONLY place that talks to an LLM. It takes graph facts
(already computed by diff.py / impact.py / risk.py) and turns them into
prose. It cannot see source code, cannot re-derive the graph, and cannot
change what "affected" or "risk" mean — it only narrates numbers and names
it's handed.

Three provider backends, chosen by whichever environment variable is set
(checked in this order):

  1. ANTHROPIC_API_KEY        -> native Anthropic Messages API
  2. OPENAI_API_KEY / LLM_API_KEY + LLM_BASE_URL
                               -> any OpenAI-compatible chat/completions
                                  endpoint: OpenAI, Groq, Together, Mistral,
                                  DeepSeek, OpenRouter, xAI, Azure OpenAI, etc.
  3. LLM_PROVIDER=ollama (or OLLAMA_HOST set)
                               -> local Ollama server, no key needed

No provider configured -> explain() falls back automatically, silently, to
the deterministic template in report.py. A malformed response, timeout, or
network error also falls back rather than crashing the report. Zero extra
pip dependencies — everything here is stdlib (urllib, json).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

from .diff import ChangedSymbol
from .impact import AffectedComponent
from .risk import RiskResult

TIMEOUT_SECONDS = 20

SYSTEM_PROMPT = (
    "You are the explanation layer of a deterministic code-change-impact "
    "analyzer. A separate, non-LLM system has already parsed the codebase, "
    "built a dependency graph, traversed it, and computed a risk score — "
    "you did not do any of that and cannot verify it independently. Your "
    "only job is to narrate the JSON facts you are given, in plain English, "
    "for a developer about to review a pull request.\n\n"
    "Hard rules:\n"
    "- Use ONLY the facts in the JSON. Do not invent affected components, "
    "tests, file names, or reasons that are not present in the input.\n"
    "- Do not speculate about business impact, deadlines, or team process.\n"
    "- Do not contradict the risk score or level given — explain it, don't "
    "re-score it.\n"
    "- 3-5 sentences. No headers, no bullet points, no markdown.\n"
    "- Write for a developer who is about to click 'approve' on a PR and "
    "needs to know what to double-check before they do."
)


class LLMUnavailable(Exception):
    """Raised internally when the LLM path can't be used; callers should
    catch this and fall back to the deterministic template."""


# --------------------------------------------------------------------------
# Provider selection
# --------------------------------------------------------------------------

def _select_provider() -> Optional[str]:
    """Returns 'anthropic' | 'openai' | 'ollama' | None, in priority order."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY"):
        return "openai"
    if os.environ.get("LLM_PROVIDER", "").lower() == "ollama" or os.environ.get("OLLAMA_HOST"):
        return "ollama"
    return None


def is_configured() -> bool:
    """True if any provider env var is set. report.py uses this instead of
    checking ANTHROPIC_API_KEY directly, so it doesn't need to know which
    provider is in play."""
    return _select_provider() is not None


# --------------------------------------------------------------------------
# Facts payload — identical across all providers
# --------------------------------------------------------------------------

def _facts_payload(changes: List[ChangedSymbol],
                    affected: Dict[str, AffectedComponent],
                    risk: RiskResult) -> dict:
    """The ONLY information any model receives. Same shape as report.to_json,
    deliberately — the model sees exactly what the JSON report shows."""
    prod = [v for v in affected.values() if not v.is_test]
    return {
        "changed_symbols": [c.label() for c in changes],
        "risk_score": risk.score,
        "risk_level": risk.level,
        "risk_breakdown": [
            {"signal": n, "normalized": r, "points": p}
            for n, r, p in risk.breakdown
        ],
        "affected_components": [
            {
                "class": c.cls,
                "depth": c.depth,
                "is_public_api": c.is_api,
                "reasons": c.reasons,
            }
            for c in sorted(prod, key=lambda x: (x.depth, x.cls))
        ],
    }


def _user_content(facts: dict) -> str:
    return (
        "Here are the graph-derived facts for one code change. Narrate "
        "them for a reviewer:\n\n" + json.dumps(facts, indent=2)
    )


def _http_post_json(url: str, headers: dict, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise LLMUnavailable(f"{url} returned HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise LLMUnavailable(f"Could not reach {url}: {e.reason}") from e
    except (TimeoutError, OSError) as e:
        raise LLMUnavailable(f"Request to {url} timed out or failed: {e}") from e


# --------------------------------------------------------------------------
# Anthropic — native Messages API
# --------------------------------------------------------------------------

def _call_anthropic(user_content: str) -> str:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    model = os.environ.get("CIA_LLM_MODEL", "claude-haiku-4-5-20251001")
    url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com") + "/v1/messages"

    data = _http_post_json(
        url,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        body={
            "model": model,
            "max_tokens": 400,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_content}],
        },
    )
    text_blocks = [b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text"]
    text = "".join(text_blocks).strip()
    if not text:
        raise LLMUnavailable("Anthropic API response had no text content")
    return text


# --------------------------------------------------------------------------
# OpenAI-compatible — covers OpenAI, Groq, Together, Mistral, DeepSeek,
# OpenRouter, xAI, Azure OpenAI (with LLM_BASE_URL override), etc.
# --------------------------------------------------------------------------

_OPENAI_COMPAT_DEFAULTS: Dict[str, Tuple[str, str]] = {
    # name hint in LLM_PROVIDER -> (base_url, default model)
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "together": ("https://api.together.xyz/v1", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest"),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    "xai": ("https://api.x.ai/v1", "grok-2-latest"),
}


def _call_openai_compatible(user_content: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    provider_hint = os.environ.get("LLM_PROVIDER", "").lower()
    default_base, default_model = _OPENAI_COMPAT_DEFAULTS.get(
        provider_hint, ("https://api.openai.com/v1", "gpt-4o-mini")
    )
    base_url = os.environ.get("LLM_BASE_URL", default_base).rstrip("/")
    model = os.environ.get("CIA_LLM_MODEL", default_model)
    url = f"{base_url}/chat/completions"

    data = _http_post_json(
        url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        body={
            "model": model,
            "max_tokens": 400,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        },
    )
    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise LLMUnavailable(f"Unexpected response shape from {url}: {e}") from e
    if not text:
        raise LLMUnavailable(f"{url} returned an empty completion")
    return text


# --------------------------------------------------------------------------
# Ollama — local models, no API key
# --------------------------------------------------------------------------

def _call_ollama(user_content: str) -> str:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("CIA_LLM_MODEL", "llama3.2")
    url = f"{host}/api/chat"

    data = _http_post_json(
        url,
        headers={"Content-Type": "application/json"},
        body={
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        },
    )
    try:
        text = data["message"]["content"].strip()
    except (KeyError, TypeError) as e:
        raise LLMUnavailable(f"Unexpected response shape from {url}: {e}") from e
    if not text:
        raise LLMUnavailable(f"{url} returned an empty completion")
    return text


# --------------------------------------------------------------------------
# Public entrypoint
# --------------------------------------------------------------------------

_DISPATCH = {
    "anthropic": _call_anthropic,
    "openai": _call_openai_compatible,
    "ollama": _call_ollama,
}


def explain_with_llm(changes: List[ChangedSymbol],
                      affected: Dict[str, AffectedComponent],
                      risk: RiskResult) -> str:
    """Raises LLMUnavailable on any failure — callers must catch and fall
    back to the deterministic template in report.py."""
    provider = _select_provider()
    if provider is None:
        raise LLMUnavailable(
            "No LLM provider configured. Set ANTHROPIC_API_KEY, or "
            "OPENAI_API_KEY/LLM_API_KEY (+ optional LLM_BASE_URL) for any "
            "OpenAI-compatible endpoint, or LLM_PROVIDER=ollama for a local "
            "model."
        )
    facts = _facts_payload(changes, affected, risk)
    user_content = _user_content(facts)
    return _DISPATCH[provider](user_content)