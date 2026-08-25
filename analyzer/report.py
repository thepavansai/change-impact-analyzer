"""Report rendering: human-readable terminal report + JSON + explanation.

The `explain()` function is deliberately isolated. In the PoC it uses a
deterministic template that narrates the FACTS the graph produced. In the real
product this is the single seam where an LLM is plugged in:

    prompt = build_prompt(changes, affected, risk)   # facts from the graph
    text   = llm.complete(prompt)                     # LLM only *explains*

Per the core product principle: deterministic analysis understands the system,
the LLM only reasons about and communicates the consequences.
"""
from __future__ import annotations

import json
from typing import Dict, List, Tuple

from .diff import ChangedSymbol
from .impact import AffectedComponent
from .risk import RiskResult

BOLD = "\033[1m"
RED = "\033[91m"
YEL = "\033[93m"
GRN = "\033[92m"
CYN = "\033[96m"
DIM = "\033[2m"
RST = "\033[0m"

LEVEL_COLOR = {"HIGH": RED, "MEDIUM": YEL, "LOW": GRN}


def explain(changes: List[ChangedSymbol],
            affected: Dict[str, AffectedComponent],
            risk: RiskResult) -> str:
    """Template-based narrator (LLM seam). Turns graph facts into prose."""
    if not changes:
        return "No symbol-level changes were detected."

    prod = {k: v for k, v in affected.items() if not v.is_test}
    change_desc = "; ".join(c.label() for c in changes[:4])
    n = len(prod)

    lead = (
        f"This change modifies {change_desc}. "
        f"Deterministic dependency analysis found {n} production "
        f"component{'s' if n != 1 else ''} that depend on the changed symbol."
    )

    # highlight risky assumptions
    risky = [v for v in prod.values() if v.depth == 1]
    detail = ""
    if risky:
        names = ", ".join(sorted(v.cls for v in risky))
        detail = (
            f" Direct consumers ({names}) use the symbol immediately and may "
            f"assume its previous type/behaviour."
        )
    api = [v for v in prod.values() if v.is_api]
    if api:
        detail += (
            f" A public API boundary ({', '.join(v.cls for v in api)}) is affected, "
            f"so the external response contract may change — this makes the change "
            f"potentially backward-incompatible."
        )

    close = (
        f" Overall risk is {risk.level} ({risk.score}/100), driven mainly by "
        + ", ".join(
            n for n, raw, pts in sorted(risk.breakdown, key=lambda x: -x[2])[:2]
        ).replace("_", " ")
        + "."
    )
    return lead + detail + close


def render_terminal(pr_title: str,
                    changes: List[ChangedSymbol],
                    affected: Dict[str, AffectedComponent],
                    risk: RiskResult,
                    tests: List[Tuple[str, str]]) -> str:
    prod = sorted(
        [v for v in affected.values() if not v.is_test],
        key=lambda c: (c.depth, c.cls),
    )
    color = LEVEL_COLOR.get(risk.level, "")
    lines = []
    lines.append(f"\n{BOLD}{'='*66}{RST}")
    lines.append(f"{BOLD}  CHANGE IMPACT REPORT  —  {pr_title}{RST}")
    lines.append(f"{BOLD}{'='*66}{RST}\n")

    lines.append(f"{BOLD}Change:{RST}")
    for c in changes:
        lines.append(f"  • {c.label()}")
    lines.append("")

    lines.append(f"{BOLD}Risk:{RST}  {color}{BOLD}{risk.level} — {risk.score}/100{RST}")
    lines.append(f"  {DIM}score breakdown (signal / normalized / points):{RST}")
    for name, raw, pts in risk.breakdown:
        bar = "█" * int(raw * 12)
        lines.append(f"    {name:<14} {raw:>4}  {DIM}{bar}{RST}  +{pts}")
    lines.append("")

    lines.append(f"{BOLD}Potentially affected components ({len(prod)}):{RST}")
    for i, comp in enumerate(prod, 1):
        tag = f" {CYN}[API]{RST}" if comp.is_api else ""
        lines.append(f"  {i}. {BOLD}{comp.cls}{RST}  {DIM}(depth {comp.depth}){RST}{tag}")
        lines.append(f"       ↳ {comp.primary_reason()}")
    lines.append("")

    lines.append(f"{BOLD}Recommended tests ({len(tests)}):{RST}")
    for t, why in tests:
        lines.append(f"  • {GRN}{t}{RST}  {DIM}— {why}{RST}")
    lines.append("")

    lines.append(f"{BOLD}AI Explanation:{RST}")
    exp = explain(changes, affected, risk)
    # wrap to ~64 cols
    import textwrap
    for para in textwrap.wrap(exp, width=64):
        lines.append(f"  {para}")
    lines.append(f"\n{BOLD}{'='*66}{RST}\n")
    return "\n".join(lines)


def to_json(pr_title, changes, affected, risk, tests) -> str:
    prod = [v for v in affected.values() if not v.is_test]
    payload = {
        "pull_request": pr_title,
        "risk": {"score": risk.score, "level": risk.level,
                 "breakdown": [{"signal": n, "normalized": r, "points": p}
                               for n, r, p in risk.breakdown]},
        "changes": [c.label() for c in changes],
        "affected_components": [
            {"class": c.cls, "depth": c.depth, "is_api": c.is_api,
             "reasons": c.reasons}
            for c in sorted(prod, key=lambda x: (x.depth, x.cls))
        ],
        "recommended_tests": [{"test": t, "why": w} for t, w in tests],
        "explanation": explain(changes, affected, risk),
    }
    return json.dumps(payload, indent=2)
