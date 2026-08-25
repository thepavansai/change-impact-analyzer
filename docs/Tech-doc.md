# AI Change Impact Analyzer — Technical Documentation (PoC)

**Version:** 0.1.0  ·  **Analyzes:** Java  ·  **Engine:** Python + `javalang`

This document explains **what was built**, **how it flows end-to-end**, and
**how each module works**, so anyone can run, understand, extend, or hand it off.

---

## 1. What this is

A proof-of-concept that answers, for a given code change:

> **"If I merge this, what could I break?"**

It reads a Java repository and a change, builds a **deterministic dependency
graph**, traces the **downstream impact**, recommends **tests**, and produces a
**transparent risk score** plus a **plain-English explanation**.

**Core principle:** deterministic analysis *understands* the system; the AI
layer only *explains* the consequences.

---

## 2. High-level architecture

```
                         ┌──────────────────────────────┐
                         │            cli.py            │  orchestrator
                         │   (runs the 5-step pipeline) │
                         └───────────────┬──────────────┘
                                         │
        ┌────────────────┬───────────────┼───────────────┬────────────────┐
        ▼                ▼               ▼               ▼                ▼
   ┌─────────┐     ┌──────────┐    ┌──────────┐    ┌────────┐      ┌──────────┐
   │ diff.py │     │parser.py │    │impact.py │    │risk.py │      │report.py │
   │ changed │     │ AST →    │    │ reverse  │    │ score  │      │ terminal │
   │ symbols │     │ graph    │    │ BFS +    │    │ (0-100)│      │ + JSON + │
   │(old/new)│     │          │    │ tests    │    │        │      │ explain  │
   └─────────┘     └────┬─────┘    └────┬─────┘    └────────┘      └──────────┘
                        │               │
                        ▼               │
                   ┌──────────┐         │
                   │ model.py │◀────────┘   shared data model
                   │ Classes, │             (SystemModel, Edge,
                   │ Members, │              ClassInfo, Method, Field)
                   │  Edges   │
                   └──────────┘
```

Supporting scripts:

- **`eval.py`** — accuracy harness (precision / recall / F1 vs. ground truth)
- **`setup_demo.py`** — rebuilds the demo repo's git baseline

---

## 3. End-to-end flow (the 5 steps in `cli.py`)

```
 INPUT: a git repo + a change (working-tree diff vs a base commit)

 ┌─ STEP 1 ─ DETECT CHANGED SYMBOLS ───────────────────────────────┐
 │ diff.py                                                          │
 │   git diff --name-only         → which .java files changed       │
 │   git show base:file (old)     → parse OLD version to symbols    │
 │   read working-tree (new)      → parse NEW version to symbols    │
 │   compare                      → ADDED / REMOVED / MODIFIED      │
 │ OUT: [ Customer.email : String -> Optional<String> , ... ]       │
 └─────────────────────────────┬───────────────────────────────────┘
                               ▼
 ┌─ STEP 2 ─ BUILD DEPENDENCY GRAPH ───────────────────────────────┐
 │ parser.py                                                        │
 │   walk every .java with javalang (real AST)                      │
 │   pass 1: register all classes/fields/methods (the type universe)│
 │   pass 2: emit EDGES for calls, field reads, new, extends,       │
 │           implements, param/return/field type usage              │
 │ OUT: SystemModel { classes, edges }                              │
 └─────────────────────────────┬───────────────────────────────────┘
                               ▼
 ┌─ STEP 3 ─ TRACE IMPACT (reverse BFS) ───────────────────────────┐
 │ impact.py                                                        │
 │   seed = the changed (class, member) pairs                       │
 │   walk edges BACKWARDS (who depends on the seed?)                │
 │   propagate transitively, tracking depth + WHY (edge kind)       │
 │ OUT: { class -> AffectedComponent(depth, reasons, is_api) }      │
 └─────────────────────────────┬───────────────────────────────────┘
                               ▼
 ┌─ STEP 4 ─ RECOMMEND TESTS ──────────────────────────────────────┐
 │ impact.py :: recommend_tests()                                   │
 │   a test "covers" an impacted class if it depends on it          │
 │   sort: tests touching the changed class first                   │
 │ OUT: [ (InvoiceGenerationTest, "exercises InvoiceService"), ...] │
 └─────────────────────────────┬───────────────────────────────────┘
                               ▼
 ┌─ STEP 5 ─ SCORE RISK + REPORT ──────────────────────────────────┐
 │ risk.py    weighted signals → 0-100 score + level + breakdown    │
 │ report.py  terminal report + JSON + explain() (LLM seam)         │
 │ OUT: HIGH — 82/100, full report                                  │
 └──────────────────────────────────────────────────────────────────┘
```

---

## 4. The data model (`model.py`)

Everything downstream depends on how faithfully this mirrors the real code.

| Type | Represents | Key fields |
|---|---|---|
| `Field` | a class field | `name, type, owner, line` |
| `Method` | a method | `name, owner, return_type, params, line` |
| `ClassInfo` | one class | `name, package, file, is_test, extends, implements, fields{}, methods{}, imports[]` |
| `Edge` | a dependency | `src_class, src_member, dst_class, dst_member, kind` |
| `SystemModel` | the whole graph | `classes{}, edges[]` + lookup helpers |

**Edge kinds** (the vocabulary of the graph):

| kind | meaning |
|---|---|
| `call` | method A calls method B |
| `field_read` / `field_write` | reads/writes a field |
| `new` | instantiates a class |
| `extends` / `implements` | inheritance |
| `param_type` / `return_type` / `field_type` | uses a type in a signature/field |

An `Edge` says: **(src_class, src_member) depends on (dst_class, dst_member) via `kind`.**
This member-level granularity is what makes the impact precise (a change to
`email` doesn't flag a class that only uses `getName()`).

---

## 5. Module reference

### `parser.py` — Java AST → dependency graph
- Uses **`javalang`** for a real AST (not regex).
- **Two passes:** first register all classes so the full type universe is known,
  then extract edges (so references can be resolved to known types).
- **Receiver resolution:** builds a per-method *type environment* from class
  fields + method params + local variable declarations, so it can resolve
  `x.getEmail()` to the class that owns `x`. Heuristic, but accurate for common
  intra-project patterns.

### `diff.py` — semantic changed-symbol detection
- Runs `git diff`, then parses **both** the old (`git show base:file`) and new
  versions and compares them at the **symbol** level.
- Emits `ChangedSymbol(kind, owner, name, change, before, after)` — e.g.
  `field Customer.email : String -> Optional<String>`.
- Semantic, not line-based: it knows a *type* changed, not just that a line moved.

### `impact.py` — traversal + test mapping
- **`analyze_impact()`**: reverse BFS from the changed members. Member-level
  nodes match only that exact member (precision); class-level changes match all
  consumers. Tracks minimum `depth` and a human `reason` per component. Flags
  API classes (`*Api`, `*Controller`, package contains `api`).
- **`recommend_tests()`**: maps impacted production classes → test classes that
  depend on them; ranks tests touching the changed class first.

### `risk.py` — transparent scoring
```
score = 100 · Σ (weight_i · normalized_signal_i)
```
| signal | weight | meaning |
|---|---|---|
| blast_radius | 0.25 | how many components affected |
| api_exposure | 0.20 | public API/contract affected? |
| fan_out | 0.15 | direct (depth-1) dependents |
| depth | 0.15 | longest dependency chain |
| type_change | 0.15 | did a field/method *type* change? |
| test_gap | 0.10 | impacted code lacking tests |

Returns the **full breakdown** so reviewers can see *why* the number is what it
is. Levels: HIGH ≥ 70, MEDIUM ≥ 40, else LOW.

### `report.py` — output + the LLM seam
- Renders a colored terminal report and a JSON payload.
- **`explain()`** is the single **LLM seam**: in the PoC it's a deterministic
  template that narrates *only the facts the graph produced*. Swap it for a real
  LLM call (`prompt = build_prompt(facts); text = llm.complete(prompt)`) and
  nothing else changes.

### `cli.py` — orchestrator
Runs steps 1→5 and prints progress. Flags: `--repo`, `--base`, `--pr`, `--json`.

### `eval.py` — the "is it accurate?" proof
Compares predictions to a hand-labelled answer key; prints precision / recall /
F1 and a **negative-control** check (a class using only `getName()` must NOT be
flagged).

---

## 6. How to run

```bash
# prerequisites: Python 3.8+ and Git (no Java/Maven needed)
pip install javalang

# first-time only: rebuild the demo git baseline
run setup.sh

# analyze the demo change
python cli.py --repo demo-repo --pr "PR #1842" --json my-report.json

# prove accuracy
python eval.py
```

**Other usages**
```bash
python cli.py --repo demo-repo --base HEAD~1     # diff vs an older commit
python cli.py --repo /path/to/your/java/repo     # point at a real repo
```

---

## 7. The demo repo (what it's designed to prove)

```
Customer.email  (String -> Optional<String>)
   ├─ CustomerService    setEmail / getEmail        depth 1
   ├─ InvoiceService     getEmail().toUpperCase()    depth 1   (assumes present)
   ├─ NotificationService getEmail().trim()          depth 1   (expects String)
   ├─ BillingService     getEmail()                  depth 1
   ├─ CustomerApi [API]  serializes email to JSON     depth 1   (contract break)
   └─ OrderProcessor     → BillingService.charge()    depth 2   (transitive)

   ShippingService  — uses only getName()  →  NEGATIVE CONTROL (must NOT flag)
```

Plus 4 tests: `InvoiceGenerationTest`, `EmailNotificationTest`,
`CustomerApiTest`, `CustomerSerializationTest`.

---

## 8. Verified results

| Metric | Value |
|---|---|
| Risk | **HIGH — 82/100** |
| Affected components | 6 (5 direct + 1 transitive @ depth 2) |
| API contract flagged | ✅ `CustomerApi` |
| Tests recommended | the correct 4 |
| Precision / Recall / F1 | **1.00 / 1.00 / 1.00** |
| Negative control | **PASS** (ShippingService excluded) |

---

## 9. Honest limitations (it's a PoC)

- **Heuristic type resolution**, not full Java inference — misses deep generics,
  reflection, and DI-injected receivers with no declared type.
- **Single-project scope** — no cross-repo/external-artifact resolution.
- **Static test mapping** — real coverage (JaCoCo) would make it exact.
- **Template explanation** — swap `explain()` for a real LLM.

---

## 10. Roadmap / next steps

1. **Swap in a real LLM** at the `explain()` seam.
2. **GitHub PR ingestion** so it runs in CI on every PR.
3. **JaCoCo coverage** for exact test mapping.
4. **Framework awareness** (Spring DI, interfaces) — the key to real-world accuracy.
5. **Web UI** visualizing the dependency graph + impact.

---

## 11. File map

```
change-impact-analyzer/
├── cli.py                 # orchestrator (5-step pipeline)
├── eval.py                # precision/recall harness
├── setup_demo.py          # rebuilds demo git baseline
├── README.md              # quick start + results
├── analyzer/
│   ├── model.py           # SystemModel, Edge, ClassInfo, Method, Field
│   ├── parser.py          # javalang AST → symbols + edges
│   ├── diff.py            # semantic changed-symbol detection
│   ├── impact.py          # reverse BFS + test recommendation
│   ├── risk.py            # transparent weighted risk score
│   └── report.py          # terminal + JSON + explain() (LLM seam)
└── demo-repo/             # sample Java project (Customer.email scenario)
```
