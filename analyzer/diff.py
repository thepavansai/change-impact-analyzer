"""Changed-symbol detection.

Instead of trusting raw line diffs, we parse BOTH the old and the new version
of every changed file and compare them at the *symbol* level. This yields
precise, semantic changes such as:

    field  Customer.email : String -> Optional<String>   (MODIFIED)
    method Customer.getEmail : String -> Optional<String> (MODIFIED)

which is exactly what the impact engine needs to seed its traversal.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List, Optional

import javalang

from .parser import _base_type, _type_name


@dataclass
class ChangedSymbol:
    kind: str            # field | method | class
    owner: str           # simple class name
    name: str
    change: str          # ADDED | REMOVED | MODIFIED
    before: Optional[str] = None
    after: Optional[str] = None

    def label(self) -> str:
        loc = f"{self.owner}.{self.name}" if self.name else self.owner
        if self.change == "MODIFIED" and self.before and self.after:
            return f"{self.kind} {loc} : {self.before} -> {self.after}"
        return f"{self.kind} {loc} ({self.change})"


def _git(args: List[str], cwd: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    ).stdout


def changed_files(repo: str, base: str = "HEAD") -> List[str]:
    """Java files that differ between `base` and the working tree."""
    out = _git(["diff", "--name-only", base], cwd=repo)
    files = [f for f in out.splitlines() if f.endswith(".java")]
    return files


def _index_symbols(src: str):
    """Return {('field'|'method', owner, name): signature} for one source string."""
    result = {}
    try:
        tree = javalang.parse.parse(src)
    except Exception:
        return result
    for _, cls in tree.filter(javalang.tree.ClassDeclaration):
        for m in cls.body:
            if isinstance(m, javalang.tree.FieldDeclaration):
                ftype = _type_name(m.type)
                for d in m.declarators:
                    result[("field", cls.name, d.name)] = ftype
            elif isinstance(m, javalang.tree.MethodDeclaration):
                params = ",".join(_type_name(p.type) for p in m.parameters)
                sig = f"{_type_name(m.return_type)} ({params})"
                result[("method", cls.name, m.name)] = sig
    return result


def diff_symbols(repo: str, base: str = "HEAD") -> List[ChangedSymbol]:
    """Compare old vs new for each changed file -> list of ChangedSymbol."""
    changes: List[ChangedSymbol] = []
    for rel in changed_files(repo, base):
        old_src = _git(["show", f"{base}:{rel}"], cwd=repo)
        try:
            with open(f"{repo}/{rel}", "r", encoding="utf-8") as fh:
                new_src = fh.read()
        except FileNotFoundError:
            new_src = ""

        old = _index_symbols(old_src)
        new = _index_symbols(new_src)

        for key, new_sig in new.items():
            kind, owner, name = key
            if key not in old:
                changes.append(ChangedSymbol(kind, owner, name, "ADDED", after=new_sig))
            elif old[key] != new_sig:
                changes.append(ChangedSymbol(kind, owner, name, "MODIFIED",
                                             before=old[key], after=new_sig))
        for key, old_sig in old.items():
            if key not in new:
                kind, owner, name = key
                changes.append(ChangedSymbol(kind, owner, name, "REMOVED", before=old_sig))
    return changes
