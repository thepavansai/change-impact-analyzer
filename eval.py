#!/usr/bin/env python3
"""Accuracy evaluation harness.

This is the "prove it's worth it" step. We hand-label the GROUND TRUTH — which
production classes genuinely depend on Customer.email (directly or
transitively) — then run the analyzer and measure precision / recall / F1
against that answer key, including an explicit negative-control check.

Ground truth is derived by manual inspection of demo-repo:
  TRUE dependents of Customer.email / getEmail / setEmail:
    BillingService, InvoiceService, NotificationService,
    CustomerApi, CustomerService, OrderProcessor (transitive via BillingService)
  TRUE non-dependents (must NOT be flagged):
    ShippingService (uses only Customer.getName())
"""
from __future__ import annotations

from analyzer.diff import diff_symbols
from analyzer.impact import analyze_impact
from analyzer.parser import RepoParser

REPO = "demo-repo"

GROUND_TRUTH_AFFECTED = {
    "BillingService",
    "InvoiceService",
    "NotificationService",
    "CustomerApi",
    "CustomerService",
    "OrderProcessor",
}
NEGATIVE_CONTROLS = {"ShippingService"}


def main() -> int:
    changes = diff_symbols(REPO, "HEAD")
    model = RepoParser().parse_repo(REPO)
    affected = analyze_impact(model, changes)
    predicted = {c for c, v in affected.items() if not v.is_test}

    tp = predicted & GROUND_TRUTH_AFFECTED
    fp = predicted - GROUND_TRUTH_AFFECTED
    fn = GROUND_TRUTH_AFFECTED - predicted

    precision = len(tp) / len(predicted) if predicted else 0.0
    recall = len(tp) / len(GROUND_TRUTH_AFFECTED) if GROUND_TRUTH_AFFECTED else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    neg_leaked = predicted & NEGATIVE_CONTROLS

    print("=" * 60)
    print("  ACCURACY EVALUATION  —  Customer.email change")
    print("=" * 60)
    print(f"\nGround-truth affected ({len(GROUND_TRUTH_AFFECTED)}): "
          f"{', '.join(sorted(GROUND_TRUTH_AFFECTED))}")
    print(f"Predicted affected    ({len(predicted)}): "
          f"{', '.join(sorted(predicted))}")
    print(f"\n  True Positives  ({len(tp)}): {', '.join(sorted(tp)) or '-'}")
    print(f"  False Positives ({len(fp)}): {', '.join(sorted(fp)) or '-'}")
    print(f"  False Negatives ({len(fn)}): {', '.join(sorted(fn)) or '-'}")
    print("\n" + "-" * 60)
    print(f"  Precision : {precision:.2f}")
    print(f"  Recall    : {recall:.2f}")
    print(f"  F1 score  : {f1:.2f}")
    print("-" * 60)
    print(f"\nNegative-control check (ShippingService must be EXCLUDED):")
    if neg_leaked:
        print(f"  FAIL — leaked: {', '.join(sorted(neg_leaked))}")
    else:
        print(f"  PASS — ShippingService correctly excluded "
              f"(uses only getName(), not email).")
    print("=" * 60)

    ok = (precision == 1.0 and recall == 1.0 and not neg_leaked)
    print(f"\nRESULT: {'PASS ✅' if ok else 'NEEDS WORK ❌'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
