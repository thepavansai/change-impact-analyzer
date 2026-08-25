#!/usr/bin/env python3
"""AI Change Impact Analyzer — CLI entrypoint (PoC).

Usage:
    python cli.py --repo demo-repo [--base HEAD] [--pr "PR #1842"] [--json out.json]

Pipeline:
    git diff -> changed symbols -> parse repo -> dependency graph
             -> reverse BFS (impact) -> test map -> risk score -> report
"""
from __future__ import annotations

import argparse
import sys

from analyzer.diff import diff_symbols
from analyzer.impact import analyze_impact, recommend_tests
from analyzer.parser import RepoParser
from analyzer.report import render_terminal, to_json
from analyzer.risk import score_risk


def main() -> int:
    ap = argparse.ArgumentParser(description="AI Change Impact Analyzer (PoC)")
    ap.add_argument("--repo", required=True, help="path to the git repo to analyze")
    ap.add_argument("--base", default="HEAD", help="git base to diff against (default HEAD)")
    ap.add_argument("--pr", default="Working-tree change", help="PR title/label for the report")
    ap.add_argument("--json", help="optional path to also write a JSON report")
    args = ap.parse_args()

    print(f"[1/5] Detecting changed symbols vs {args.base} ...")
    changes = diff_symbols(args.repo, args.base)
    if not changes:
        print("       No Java symbol changes detected. Nothing to analyze.")
        return 0
    for c in changes:
        print(f"       - {c.label()}")

    print("[2/5] Parsing repository & building dependency graph ...")
    model = RepoParser().parse_repo(args.repo)
    print(f"       {len(model.classes)} classes, {len(model.edges)} dependency edges")

    print("[3/5] Traversing dependents (reverse BFS) ...")
    affected = analyze_impact(model, changes)
    prod = [v for v in affected.values() if not v.is_test]
    print(f"       {len(prod)} affected production components")

    print("[4/5] Recommending tests ...")
    tests = recommend_tests(model, affected, changes)
    print(f"       {len(tests)} tests recommended")

    print("[5/5] Scoring risk ...")
    risk = score_risk(affected, changes, len(tests))
    print(f"       {risk.level} — {risk.score}/100")

    report = render_terminal(args.pr, changes, affected, risk, tests)
    print(report)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(to_json(args.pr, changes, affected, risk, tests))
        print(f"JSON report written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
