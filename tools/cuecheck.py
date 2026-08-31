#!/usr/bin/env python3
"""Cue architectural constraint checker.

AST-based static checks encoding Cue's architectural rules. Complements
ruff/pyright/py2_check and is wired in as a check in bin/lint.sh. Runs under
Python 3 (dev tooling, not runtime Cue code); it only PARSES cue_lib -- it
never modifies it.

Scope: every cue_lib/**/*.py. Never tests/ (white-box) or .rpy (bridge).

Rules (CUE0xx; the full design is docs/architectural-enforcement.md):
  CUE002  `_cue.<member>` used where DI is intended (outside runtime.py)
  CUE004  every non-exempt class inherits from NoRollback (or object)
  CUE005  `_cue` is never reassigned
  CUE006  duck-type over isinstance(x, list/dict/tuple/set)
  CUE007  forbidden version-specific APIs
  CUE008  py2 text-isinstance: isinstance(x, str) / (str, bytes) / type(x) is str

Usage:
  python3 tools/cuecheck.py [--no CUE002,CUE004] [path ...]

Exits 1 if any finding. With no path, walks cue_lib/**/*.py under the repo.
"""

import argparse
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- rule configuration ------------------------------------------------

# The bootstrap module where `_cue` access is legitimate (no instance to inject).
BOOTSTRAP_MODULES = ("runtime.py",)

# Bases allowed for a class that is NOT parked as mutable store state. Anything
# outside this set is a candidate for CUE004 (should subclass NoRollback).
_ALLOWED_BASES = {
    "object",
    "_renpy_python.NoRollback",
    "TypedDict",
    "Displayable",
    "Container",
    "Text",
    "DynamicDisplayable",
    "Exception",
    "Structure",  # ctypes.Structure
    "_HTTPRedirectHandler",
    "FieldValue",
    "FieldInputValue",
    "DictValue",
}

# Collection types that Revertable* can shadow; isinstance on these is the trap.
_COLLECTION_NAMES = {"list", "dict", "tuple", "set"}

# Every rule code (so a bare `# cuecheck: disable` disables all of them).
_ALL_RULES = {"CUE002", "CUE003", "CUE004", "CUE005", "CUE006", "CUE007", "CUE008"}

# `# cuecheck: disable|enable|ignore [CUE00x,...]` suppression directives.
_RE_DIRECTIVE = re.compile(r"#\s*cuecheck:\s*(disable|enable|ignore)\b(.*)")

# Rules that need a defined target list and are gated off until the base is
# agreed (see docs). CUE007 needs the specific forbidden-API list.
_CUE007_FORBIDDEN = (
    # attr-module use of `renpy.music` instead of `renpy.audio.music`
)
_DISABLED_BY_DEFAULT = {"CUE007"}


def _is_cue_class(name):
    return name.startswith("Cue") or name.startswith("_Cue") or name.startswith("_Preset")\
        or name.startswith("_Igroup")


class _Checker(ast.NodeVisitor):
    def __init__(self, filename, source, enabled):
        self.filename = filename
        self.source = source
        self.lines = source.splitlines()
        self.enabled = enabled
        self.findings = []
        self._in_runtime = filename.endswith(BOOTSTRAP_MODULES)
        self._disabled = self._scan_directives()

    def _scan_directives(self):
        """Parse `# cuecheck: disable|enable|ignore [CUE00x,...]` comments.

        disable [codes]  -- rules off from this line onward (no codes = all rules)
        enable  [codes]  -- rules back on from this line onward (no codes = all)
        ignore  [codes]  -- rules ignored on THIS line only (no codes = all)

        Bare-`disable` then `enable CUE00x` does NOT re-enable the named rule
        (a wildcard region sticks); scope the disable or use `ignore` instead.
        Returns {lineno(1-based): set-of-codes-or-'*'} for every line.
        """
        active = set()  # rules disabled in the current region; "*" = all
        disabled = {}
        for lineno, raw in enumerate(self.lines, start=1):
            m = _RE_DIRECTIVE.search(raw)
            if m:
                kind, codes = m.group(1), self._parse_codes(m.group(2))
                if kind == "disable":
                    if codes:
                        if "*" not in active:
                            active = active | codes
                    else:
                        active = {"*"}
                elif kind == "enable":
                    active = set() if not codes else active - codes
                elif kind == "ignore":
                    disabled.setdefault(lineno, set()).update(codes or {"*"})
            if active:
                disabled.setdefault(lineno, set()).update(active)
        return disabled

    @staticmethod
    def _parse_codes(text):
        codes = set()
        for piece in text.replace(",", " ").split():
            if piece.strip():
                codes.add(piece.strip().upper())
        return codes

    def _is_disabled(self, lineno, code):
        s = self._disabled.get(lineno)
        if not s:
            return False
        return "*" in s or code in s

    def _rel(self, node):
        return "{}:{}".format(self.filename, node.lineno)

    def _say(self, code, node, msg):
        if code not in self.enabled:
            return
        if self._is_disabled(node.lineno, code):
            return
        self.findings.append("{}: {} {}".format(self._rel(node), code, msg))

    # --- structural helpers ---

    def _base_name(self, node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            # `ctypes.Structure` and friends
            n = node.attr
            v = node.value
            if isinstance(v, ast.Name):
                return "{}.{}".format(v.id, n)
            return n
        return None

    def _is_typing_base(self, node):
        # TypedDict classes (class X(TypedDict, total=False)); total=False is a
        # keyword, and `TypedDict` may be the 2-arg form `TypedDict(name, {...})`.
        return self._base_name(node) == "TypedDict"

    # --- rules ---

    def visit_ClassDef(self, node):
        # CUE004 -- every non-exempt class must be NoRollback (or object).
        if "CUE004" in self.enabled and not self._class_ok(node):
            self._say("CUE004", node, "class inherits {}: subclass NoRollback (or object)"
                      .format(", ".join(self._base_name(b) or "?" for b in node.bases)))
        self.generic_visit(node)

    def _class_ok(self, node):
        if _is_cue_class(node.name):
            return True
        if not node.bases:
            return True  # implicit object
        for base in node.bases:
            n = self._base_name(base)
            if n in _ALLOWED_BASES:
                return True
            if self._is_typing_base(base):
                return True
        return False

    def _is_cue_definition(self, node):
        # `_cue = Cue()` (or NoRollback()) at module scope is the one-time
        # singleton definition, not a rebind.
        if not isinstance(node.value, ast.Call):
            return False
        f = node.value.func
        if isinstance(f, ast.Name):
            return f.id.endswith("Cue") or f.id.endswith("NoRollback")
        if isinstance(f, ast.Attribute):
            return f.attr.endswith("Cue") or f.attr.endswith("NoRollback")
        return False

    def visit_Assign(self, node):
        # CUE005 -- `_cue` is a singleton; never rebind it.
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "_cue":
                if not self._is_cue_definition(node):
                    self._say("CUE005", node, "'_cue' must never be reassigned (mutate its attrs)")
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if isinstance(node.target, ast.Name) and node.target.id == "_cue":
            if not self._is_cue_definition(node):
                self._say("CUE005", node, "'_cue' must never be reassigned (mutate its attrs)")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        # CUE002 -- `_cue.<member>` outside the bootstrap module.
        if "CUE002" in self.enabled and not self._in_runtime:
            if isinstance(node.value, ast.Name) and node.value.id == "_cue":
                if node.attr != "__class__":
                    self._say("CUE002", node, "global '_cue.<{}>' access outside bootstrap; inject the dep instead".format(node.attr))
        self.generic_visit(node)

    def visit_Call(self, node):
        # CUE006 / CUE008 -- isinstance second-arg inspection.
        if isinstance(node.func, ast.Name) and node.func.id == "isinstance" and len(node.args) >= 2:
            self._check_isinstance_2nd(node, node.args[1])
        self.generic_visit(node)

    def _check_isinstance_2nd(self, node, second):
        names = []
        if isinstance(second, ast.Name):
            names = [second.id]
        elif isinstance(second, (ast.Tuple, ast.List, ast.Set)):
            names = [e.id for e in second.elts if isinstance(e, ast.Name)]
        for n in names:
            if n == "str":
                self._say("CUE008", node, "isinstance(x, str)/(str, bytes) misses unicode on Py2; use util._cue_is_str() or bare bytes")
            elif n in _COLLECTION_NAMES:
                self._say("CUE006", node, "isinstance(x, {}) may be shadowed by Revertable*; duck-type instead".format(n))

    def visit_Compare(self, node):
        # CUE008 -- `type(x) is str` / `type(x) == str` on Py2.
        if len(node.ops) == 1 and len(node.comparators) == 1:
            lt = node.left
            if isinstance(lt, ast.Call) and isinstance(lt.func, ast.Name) and lt.func.id == "type":
                cmp_name = None
                if isinstance(node.comparators[0], ast.Name):
                    cmp_name = node.comparators[0].id
                if cmp_name == "str":
                    self._say("CUE008", node, "type(x) is/== str misses unicode on Py2; use util._cue_is_str()")
        self.generic_visit(node)


def _walk_py_files(paths):
    """Yield (filename, source) for every .py file under the given paths."""
    for path in paths:
        if os.path.isfile(path):
            if path.endswith(".py"):
                with open(path, encoding="utf-8") as fh:
                    yield path, fh.read()
            continue
        for base, _dirs, files in os.walk(path):
            for f in files:
                if f.endswith(".py") and not f.endswith(".pyi") and "__pycache__" not in base:
                    full = os.path.join(base, f)
                    with open(full, encoding="utf-8") as fh:
                        yield full, fh.read()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cue architectural constraint checker")
    ap.add_argument("paths", nargs="*", default=["cue_lib"], help="files/dirs (default: cue_lib)")
    ap.add_argument("--no", default="", help="comma-separated rule codes to disable")
    args = ap.parse_args(argv)

    enabled = {c for c in ("CUE002", "CUE004", "CUE005", "CUE006", "CUE007", "CUE008")
               if c not in _DISABLED_BY_DEFAULT}
    for code in args.no.split(","):
        enabled.discard(code.strip())

    findings = []
    modules = 0
    for filename, source in _walk_py_files(args.paths):
        modules += 1
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as exc:
            print("{}: syntax error: {}".format(filename, exc), file=sys.stderr)
            findups = "no"
        else:
            checker = _Checker(filename, source, enabled)
            checker.visit(tree)
            findings.extend(checker.findings)

    for line in findings:
        print(line)
    if findings:
        print("cuecheck: {} rule violation{} across {} module{}".format(
            len(findings), "" if len(findings) == 1 else "s", modules, "" if modules == 1 else "s"),
            file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
