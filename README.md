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

## Honest limitations (this is a PoC)

- **Heuristic type resolution**, not full Java type inference. Handles the
  common intra-project patterns; would miss e.g. deep generic inference,
  reflection, or dependency-injected receivers with no declared type.
- **Single project scope** — no cross-repo / external-artifact resolution.
- **Test mapping is static** (who references whom). Real coverage data
  (JaCoCo) would make it exact.
- **The "AI explanation" is a template** here so the PoC runs with no API key.
  It consumes only graph facts — swap `explain()` for a real LLM call and
  nothing else changes.

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

- Swap the template narrator for a real LLM (the `explain()` seam).
- Add GitHub PR ingestion (Octokit / REST) so it runs in CI on every PR.
- Integrate JaCoCo coverage to make test mapping exact.
- Add a second language, then a web UI showing the graph.
