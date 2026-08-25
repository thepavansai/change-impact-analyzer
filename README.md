# AI Change Impact Analyzer — Java PoC

A working proof-of-concept for the question:

> **"If I merge this change, what could I break?"**

This PoC proves the *hard* part of the product (per Section 14 of the problem
statement): building an **accurate deterministic representation** of a Java
codebase and using it to trace the downstream impact of a code change — *before*
it is merged. The LLM is deliberately kept as a thin, swappable layer that only
*explains* the facts the graph produces.

---

## What it does

Given a Git repo and a change, it runs this pipeline:

```
git diff  →  changed symbols  →  parse repo (AST)  →  dependency graph
          →  reverse BFS (impact)  →  test mapping  →  risk score  →  report
```

and produces:

- **Changed symbols** at semantic granularity (`Customer.email : String → Optional<String>`)
- **Potentially affected components** with depth + *why* (the exact edge)
- **A public-API `[API]` flag** for contract-breaking changes
- **Recommended tests** that cover the impacted code
- **A transparent, weighted risk score** (no black box — full breakdown shown)
- **A plain-English explanation** (LLM seam)

---

## Why this is not just "an AI code reviewer"

A code reviewer asks *"is this code wrong?"*. This asks *"what are the
**consequences** of this change on the rest of the system?"* — which requires an
actual dependency graph, not a prompt.

**Core principle:** deterministic analysis *understands* the system; AI only
*reasons about and communicates* the consequences.

---

## Tech

- **Language analyzed:** Java (one language, per MVP scope)
- **Parser:** [`javalang`](https://pypi.org/project/javalang/) — a real AST, not regex
- **Analyzer:** pure Python, no build tools required
- **Resolution:** scope-based type environment (class fields + params + locals)
  resolves method-call/field receivers to concrete types

---

## Run it

```bash
pip install -r requirements.txt

# one-time: give demo-repo a real git baseline so cli.py has something to
# diff against (demo-repo ships with the "after" state already checked in)
./setup.sh

# analyze the demo change (Customer.email String -> Optional<String>)
python cli.py --repo demo-repo --pr "PR #1842" --json impact-report.json

# measure accuracy vs a hand-labelled answer key
python eval.py
```

---

## Result on the demo scenario

The demo repo implements the exact scenario from the problem statement
(`Customer → Billing → Invoice → Notification → API`), plus:

- a **negative control** (`ShippingService`, uses only `getName()`)
- a **transitive** case (`OrderProcessor` → `BillingService.charge()`)

Analyzer output:

| | Result |
|---|---|
| Risk | **HIGH — 82/100** |
| Affected components | 6 (5 direct + 1 transitive at depth 2) |
| API contract flagged | ✅ `CustomerApi [API]` |
| Recommended tests | `InvoiceGenerationTest`, `EmailNotificationTest`, `CustomerApiTest`, `CustomerSerializationTest` |

Accuracy vs ground truth:

| Metric | Value |
|---|---|
| Precision | **1.00** |
| Recall | **1.00** |
| F1 | **1.00** |
| Negative control (`ShippingService` excluded) | **PASS** |

---

## Project layout

```
change-impact-analyzer/
├── cli.py                 # entrypoint (the 5-step pipeline)
├── eval.py                # precision/recall harness vs ground truth
├── analyzer/
│   ├── model.py           # SystemModel: classes, members, edges
│   ├── parser.py          # javalang AST -> symbols + dependency edges
│   ├── diff.py            # semantic changed-symbol detection (old vs new)
│   ├── impact.py          # reverse BFS traversal + test recommendation
│   ├── risk.py            # transparent weighted risk score
│   └── report.py          # terminal + JSON report, LLM explanation seam
└── demo-repo/             # sample Java project (git repo with baseline)
```

---

## Risk score (transparent by design)

```
score = 100 * Σ (weight_i · normalized_signal_i)
```

| Signal | Weight | Meaning |
|---|---|---|
| blast_radius | 0.25 | how many components are affected |
| api_exposure | 0.20 | is a public API / contract affected |
| fan_out | 0.15 | number of direct (depth-1) dependents |
| depth | 0.15 | longest dependency chain reached |
| type_change | 0.15 | did a field/method *type* change (backward-incompat) |
| test_gap | 0.10 | fraction of impacted code lacking tests |

Reviewers can always see *why* the number is what it is.

---

## Real LLM explanations

[#real-llm-explanations](#real-llm-explanations)

By default `explain()` (in `analyzer/report.py`) uses a deterministic
template — no API key, no network call, fully reproducible. Set one of the
following environment variables and it transparently switches to a real LLM
call instead, via `analyzer/llm.py`. Nothing else in the pipeline changes:
the LLM only ever receives the JSON facts the graph already computed
(changed symbols, affected components, risk breakdown) — never source code
— and any failure (missing key, network error, bad response) falls back to
the template automatically.

| Provider | Env vars | Notes |
| --- | --- | --- |
| **Anthropic** | `ANTHROPIC_API_KEY` | Model: `CIA_LLM_MODEL` (default `claude-haiku-4-5-20251001`) |
| **OpenAI-compatible** | `OPENAI_API_KEY` or `LLM_API_KEY`, optional `LLM_BASE_URL`, optional `LLM_PROVIDER` | Covers OpenAI, Groq, Together, Mistral, DeepSeek, OpenRouter, xAI, Azure OpenAI, or any other `/chat/completions`-compatible endpoint. `LLM_PROVIDER` (e.g. `groq`, `mistral`) just picks sane defaults for base URL + model; override either explicitly. |
| **Ollama (local)** | `LLM_PROVIDER=ollama` or `OLLAMA_HOST` | No API key needed. `OLLAMA_HOST` defaults to `http://localhost:11434`. Model: `CIA_LLM_MODEL` (default `llama3.2`) |

Example — Anthropic:

```
export ANTHROPIC_API_KEY=sk-ant-...
python cli.py --repo demo-repo --pr "PR #1842" --json impact-report.json
```

Example — Groq (OpenAI-compatible):

```
export LLM_PROVIDER=groq
export LLM_API_KEY=gsk_...
python cli.py --repo demo-repo --pr "PR #1842"
```

Example — local Ollama:

```
ollama pull llama3.2
export LLM_PROVIDER=ollama
python cli.py --repo demo-repo --pr "PR #1842"
```

If more than one provider's env vars are set, priority is Anthropic →
OpenAI-compatible → Ollama. Zero extra pip dependencies — provider calls use
only `urllib` from the standard library.

---

## Honest limitations (this is a PoC)

- **Heuristic type resolution**, not full Java type inference. Handles the
  common intra-project patterns; would miss e.g. deep generic inference,
  reflection, or dependency-injected receivers with no declared type.
- **Single project scope** — no cross-repo / external-artifact resolution.
- **Test mapping is static** (who references whom). Real coverage data
  (JaCoCo) would make it exact.
- **The "AI explanation" defaults to a deterministic template** so the PoC
  runs with no API key. Set any supported provider's env var to switch to a
  real LLM call instead — see "Real LLM explanations" below. Either way, the
  model only ever sees graph facts, never source code.

---

## What this proves

1. ✅ Accept a change and identify changed **files + symbols** semantically.
2. ✅ Build a real **dependency graph** from source.
3. ✅ Identify **potentially affected components** — accurately (P/R = 1.0 on the demo).
4. ✅ Explain **why** each is affected (concrete edge).
5. ✅ Generate useful **test recommendations**.
6. ✅ Produce a **transparent risk score**.
7. ✅ Discriminate real impact from noise (**negative control passes**).

## Natural next steps

- ~~Swap the template narrator for a real LLM (the `explain()` seam).~~
- Add GitHub PR ingestion (Octokit / REST) so it runs in CI on every PR.
- Integrate JaCoCo coverage to make test mapping exact.
- Add a second language, then a web UI showing the graph.
