"""Deterministic Java parser -> SystemModel.

Uses `javalang` to build a real AST (not regex). For each class we extract
fields, methods and, crucially, the *references* each method makes to other
symbols: method calls, object creation, field reads/writes, inheritance and
type usage. Receiver types are resolved with a lightweight scope-based type
environment (class fields + method params + local variable declarations).

This resolution is heuristic (no full Java type inference) but is accurate for
the common intra-project patterns that matter for change-impact analysis.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import javalang

from .model import ClassInfo, Edge, Field, Method, SystemModel


def _type_name(t) -> str:
    """Render a javalang type node into a readable string like 'Optional<String>'."""
    if t is None:
        return "void"
    name = getattr(t, "name", None) or str(t)
    args = getattr(t, "arguments", None)
    if args:
        inner = []
        for a in args:
            at = getattr(a, "type", None)
            inner.append(_type_name(at) if at is not None else "?")
        name = f"{name}<{','.join(inner)}>"
    dims = getattr(t, "dimensions", None)
    if dims:
        name += "[]" * len(dims)
    return name


def _base_type(type_str: str) -> str:
    """Strip generics/arrays to the base simple type: 'Optional<String>' -> 'Optional'."""
    return type_str.split("<")[0].replace("[]", "").strip()


class RepoParser:
    def __init__(self) -> None:
        self.model = SystemModel()
        # maps simple type name -> owning class, resolved after all files parsed
        self._known_types: set = set()

    # ------------------------------------------------------------------ public
    def parse_repo(self, root: str) -> SystemModel:
        java_files = self._find_java_files(root)
        parsed = []
        for path in java_files:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    src = fh.read()
                tree = javalang.parse.parse(src)
                parsed.append((path, tree))
            except Exception as exc:  # keep going; a broken file shouldn't kill the run
                print(f"  [warn] failed to parse {path}: {exc}")

        # pass 1: register all classes so we know the full type universe
        for path, tree in parsed:
            self._register_classes(path, tree)
        self._known_types = set(self.model.classes.keys())

        # pass 2: extract references / edges now that types are known
        for path, tree in parsed:
            self._extract_edges(tree)

        return self.model

    # ------------------------------------------------------------------ pass 1
    def _register_classes(self, path: str, tree) -> None:
        package = tree.package.name if tree.package else ""
        imports = [imp.path for imp in tree.imports]
        is_test = "/test/" in path.replace("\\", "/") or path.endswith("Test.java")

        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            ci = ClassInfo(
                name=node.name,
                package=package,
                file=path,
                is_test=is_test,
                extends=_base_type(_type_name(node.extends)) if node.extends else None,
                implements=[_base_type(_type_name(i)) for i in (node.implements or [])],
                imports=imports,
            )
            for member in node.body:
                if isinstance(member, javalang.tree.FieldDeclaration):
                    ftype = _type_name(member.type)
                    for decl in member.declarators:
                        ci.fields[decl.name] = Field(
                            name=decl.name, type=ftype, owner=node.name,
                            line=(member.position.line if member.position else 0),
                        )
                elif isinstance(member, javalang.tree.MethodDeclaration):
                    params = [(_type_name(p.type), p.name) for p in member.parameters]
                    ci.methods[member.name] = Method(
                        name=member.name, owner=node.name,
                        return_type=_type_name(member.return_type),
                        params=params,
                        line=(member.position.line if member.position else 0),
                    )
            self.model.add_class(ci)

    # ------------------------------------------------------------------ pass 2
    def _extract_edges(self, tree) -> None:
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            ci = self.model.classes.get(node.name)
            if ci is None:
                continue

            # class-level inheritance edges
            if ci.extends and ci.extends in self._known_types:
                self.model.add_edge(Edge(ci.name, None, ci.extends, None, "extends"))
            for impl in ci.implements:
                if impl in self._known_types:
                    self.model.add_edge(Edge(ci.name, None, impl, None, "implements"))

            for member in node.body:
                if isinstance(member, javalang.tree.MethodDeclaration):
                    self._extract_method_edges(ci, member)
                    # signature-level type usage edges
                    rt = _base_type(_type_name(member.return_type))
                    if rt in self._known_types and rt != ci.name:
                        self.model.add_edge(Edge(ci.name, member.name, rt, None, "return_type"))
                    for p in member.parameters:
                        pt = _base_type(_type_name(p.type))
                        if pt in self._known_types and pt != ci.name:
                            self.model.add_edge(Edge(ci.name, member.name, pt, None, "param_type"))
                elif isinstance(member, javalang.tree.FieldDeclaration):
                    ft = _base_type(_type_name(member.type))
                    if ft in self._known_types and ft != ci.name:
                        self.model.add_edge(Edge(ci.name, None, ft, None, "field_type"))

    def _extract_method_edges(self, ci: ClassInfo,
                              method: javalang.tree.MethodDeclaration) -> None:
        """Walk a single method body and emit call / new / field edges."""
        # Build a local type environment: field -> type, param -> type, local -> type
        env: Dict[str, str] = {}
        for fname, f in ci.fields.items():
            env[fname] = _base_type(f.type)
        for ptype, pname in [(_type_name(p.type), p.name) for p in method.parameters]:
            env[pname] = _base_type(ptype)

        if method.body is None:
            return

        # local variable declarations
        for _, ld in method.filter(javalang.tree.LocalVariableDeclaration):
            ltype = _base_type(_type_name(ld.type))
            for d in ld.declarators:
                env[d.name] = ltype

        # object creation: new Foo()
        for _, cc in method.filter(javalang.tree.ClassCreator):
            tname = _base_type(_type_name(cc.type))
            if tname in self._known_types and tname != ci.name:
                self.model.add_edge(Edge(ci.name, method.name, tname, None, "new"))

        # method invocations: resolve receiver type
        for _, inv in method.filter(javalang.tree.MethodInvocation):
            target_class = self._resolve_receiver(inv.qualifier, env, ci)
            if target_class and target_class in self._known_types:
                self.model.add_edge(
                    Edge(ci.name, method.name, target_class, inv.member, "call")
                )

        # member references: field reads (and this.field writes)
        for _, ref in method.filter(javalang.tree.MemberReference):
            q = ref.qualifier
            member_name = ref.member
            if not q or q == "this":
                # unqualified / this.x -> own field?
                if member_name in ci.fields:
                    self.model.add_edge(
                        Edge(ci.name, method.name, ci.name, member_name, "field_read")
                    )
            else:
                target_class = self._resolve_receiver(q, env, ci)
                if target_class and target_class in self._known_types:
                    tci = self.model.classes[target_class]
                    if member_name in tci.fields:
                        self.model.add_edge(
                            Edge(ci.name, method.name, target_class, member_name, "field_read")
                        )

    def _resolve_receiver(self, qualifier: Optional[str], env: Dict[str, str],
                          ci: ClassInfo) -> Optional[str]:
        """Resolve a call/field receiver expression to a class name."""
        if qualifier is None or qualifier == "":
            return ci.name                      # unqualified -> own class
        if qualifier == "this":
            return ci.name
        head = qualifier.split(".")[0]          # first segment of a chain
        if head in env:                         # a known variable
            return env[head]
        if head in self._known_types:           # static-style reference to a class
            return head
        return None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _find_java_files(root: str) -> List[str]:
        out = []
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if fn.endswith(".java"):
                    out.append(os.path.join(dirpath, fn))
        return sorted(out)
