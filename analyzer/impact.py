"""Impact traversal + test recommendation.

Given the set of changed symbols, we seed a reverse BFS over the dependency
graph to find every component that (transitively) depends on the change. Each
affected component keeps: the depth at which it was reached, WHY it was reached
(the edge kind + path), and whether it sits on a public API / test boundary.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .diff import ChangedSymbol
from .model import Edge, SystemModel


@dataclass
class AffectedComponent:
    cls: str
    depth: int
    reasons: List[str] = field(default_factory=list)
    via_members: Set[str] = field(default_factory=set)
    is_test: bool = False
    is_api: bool = False

    def primary_reason(self) -> str:
        return self.reasons[0] if self.reasons else "Transitively depends on the change"


REASON_TEXT = {
    "call": "calls {dst}.{member}()",
    "field_read": "reads field {dst}.{member}",
    "field_write": "writes field {dst}.{member}",
    "new": "instantiates {dst}",
    "extends": "extends {dst}",
    "implements": "implements {dst}",
    "return_type": "returns {dst} from {member}()",
    "param_type": "accepts {dst} in {member}()",
    "field_type": "holds a {dst} field",
}


def _is_api(cls_name: str, model: SystemModel) -> bool:
    ci = model.classes.get(cls_name)
    if not ci:
        return False
    pkg = (ci.package or "").lower()
    return (
        "api" in pkg or "controller" in pkg or "rest" in pkg
        or cls_name.endswith("Api") or cls_name.endswith("Controller")
        or cls_name.endswith("Resource")
    )


def analyze_impact(model: SystemModel,
                   changes: List[ChangedSymbol]) -> Dict[str, AffectedComponent]:
    # ---- seed set: (class, member) pairs that actually changed --------------
    seeds: Set[Tuple[str, Optional[str]]] = set()
    seed_classes: Set[str] = set()
    for ch in changes:
        seed_classes.add(ch.owner)
        if ch.kind in ("field", "method"):
            seeds.add((ch.owner, ch.name))
        else:
            seeds.add((ch.owner, None))

    # index edges by (dst_class, dst_member) and (dst_class, None) for fast reverse BFS
    by_dst: Dict[Tuple[str, Optional[str]], List[Edge]] = {}
    for e in model.edges:
        by_dst.setdefault((e.dst_class, e.dst_member), []).append(e)
        by_dst.setdefault((e.dst_class, None), []).append(e)

    affected: Dict[str, AffectedComponent] = {}
    visited_members: Set[Tuple[str, Optional[str]]] = set()
    queue: deque = deque()

    for s in seeds:
        queue.append((s, 0))

    while queue:
        (dst_class, dst_member), depth = queue.popleft()
        if (dst_class, dst_member) in visited_members:
            continue
        visited_members.add((dst_class, dst_member))

        # Collect incoming edges.
        #  - For a MEMBER-level node we take ONLY edges to that exact member.
        #    (A class that merely instantiates Customer or reads getName() is
        #     NOT affected by a change to `email` — this keeps precision high.)
        #  - For a CLASS-level node (dst_member is None) we take every edge into
        #    the class, since a class-level change affects all consumers.
        if dst_member is not None:
            incoming = by_dst.get((dst_class, dst_member), [])
        else:
            incoming = by_dst.get((dst_class, None), [])

        for e in incoming:
            src = e.src_class
            if src in seed_classes and depth == 0:
                # skip self-references inside the changed class at the seed level
                pass
            reason = REASON_TEXT.get(e.kind, e.kind).format(
                dst=e.dst_class, member=e.dst_member or ""
            )
            comp = affected.get(src)
            if comp is None:
                comp = AffectedComponent(
                    cls=src, depth=depth + 1,
                    is_test=model.classes.get(src).is_test if src in model.classes else False,
                    is_api=_is_api(src, model),
                )
                affected[src] = comp
            comp.depth = min(comp.depth, depth + 1)
            full_reason = f"{src} {reason}"
            if full_reason not in comp.reasons:
                comp.reasons.append(full_reason)
            if e.src_member:
                comp.via_members.add(e.src_member)
            # enqueue the source member so we keep propagating the blast radius
            queue.append(((src, e.src_member), depth + 1))

    # don't report the changed classes themselves as "affected"
    for c in seed_classes:
        affected.pop(c, None)
    return affected


# --------------------------------------------------------------------------- tests
def recommend_tests(model: SystemModel,
                    affected: Dict[str, AffectedComponent],
                    changes: List[ChangedSymbol]) -> List[Tuple[str, str]]:
    """Return [(test_class, why)] for tests that cover impacted production code."""
    impacted_classes = set(affected.keys()) | {c.owner for c in changes}
    recs: List[Tuple[str, str]] = []
    for tname in model.test_classes():
        # a test 'covers' an impacted class if it depends on it
        covered = set()
        for e in model.edges:
            if e.src_class == tname and e.dst_class in impacted_classes:
                covered.add(e.dst_class)
        if covered:
            why = "exercises " + ", ".join(sorted(covered))
            recs.append((tname, why))
    # sort: tests touching changed class first, then by breadth of coverage
    changed_owners = {c.owner for c in changes}
    recs.sort(key=lambda r: (0 if any(o in r[1] for o in changed_owners) else 1, r[0]))
    return recs
