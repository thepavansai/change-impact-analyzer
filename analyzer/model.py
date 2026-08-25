"""Core data model for the Change Impact Analyzer.

These are plain dataclasses that represent the *software system* extracted
deterministically from Java source. The quality of everything downstream
(impact, risk, tests) depends on how faithfully this model mirrors reality.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class Field:
    name: str
    type: str
    owner: str            # simple class name that declares this field
    line: int = 0


@dataclass
class Method:
    name: str
    owner: str            # simple class name that declares this method
    return_type: str = "void"
    params: List[Tuple[str, str]] = field(default_factory=list)  # (type, name)
    line: int = 0

    def signature(self) -> str:
        param_types = ",".join(t for t, _ in self.params)
        return f"{self.return_type} {self.name}({param_types})"


@dataclass
class ClassInfo:
    name: str                       # simple name, e.g. "Customer"
    package: str
    file: str
    is_test: bool = False
    extends: Optional[str] = None
    implements: List[str] = field(default_factory=list)
    fields: Dict[str, Field] = field(default_factory=dict)
    methods: Dict[str, Method] = field(default_factory=dict)   # keyed by method name
    imports: List[str] = field(default_factory=list)

    @property
    def fqcn(self) -> str:
        return f"{self.package}.{self.name}" if self.package else self.name


# An edge means: (src_class, src_member) depends on (dst_class, dst_member).
# src_member / dst_member may be None when the relationship is class-level
# (e.g. inheritance, field-type usage).
@dataclass(frozen=True)
class Edge:
    src_class: str
    src_member: Optional[str]
    dst_class: str
    dst_member: Optional[str]
    kind: str            # call | new | field_read | field_write | extends |
                         # implements | field_type | param_type | return_type


@dataclass
class SystemModel:
    classes: Dict[str, ClassInfo] = field(default_factory=dict)   # by simple name
    edges: List[Edge] = field(default_factory=list)

    def add_class(self, ci: ClassInfo) -> None:
        self.classes[ci.name] = ci

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    # --- convenience lookups -------------------------------------------------
    def dependents_of(self, dst_class: str,
                      dst_member: Optional[str] = None) -> List[Edge]:
        """Reverse lookup: who depends on this class (or specific member)?"""
        out = []
        for e in self.edges:
            if e.dst_class != dst_class:
                continue
            if dst_member is not None and e.dst_member != dst_member:
                continue
            out.append(e)
        return out

    def test_classes(self) -> List[str]:
        return [c.name for c in self.classes.values() if c.is_test]
