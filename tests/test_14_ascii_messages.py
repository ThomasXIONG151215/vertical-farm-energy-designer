"""P2-1 regression: every runtime output message in vfed/ is pure ASCII.

Windows Chinese consoles default to GBK (cp936); any non-ASCII character
(em-dash, degree sign, ...) in a WARNING or exception message renders as
mojibake.  This test walks every module under ``vfed/`` with ``ast`` and
asserts that all string literals passed to runtime emitters --
``warnings.warn``, ``print``, ``logging.*`` and ``raise ...Error(...)`` --
satisfy ``str.isascii()``.

Known limitations (documented, not errors):
- strings assembled through intermediate variables
  (``msg = ...; msg += ...; raise ValueError(msg)``) are not traced; the AST
  pass only sees literal arguments at the emission site;
- messages that are fully dynamic (built from DB/config data, e.g. tariff
  labels) are not checked here; those sources are kept ASCII by convention.
"""

import ast
from pathlib import Path

import pytest

_VFED_ROOT = Path(__file__).resolve().parent.parent / "vfed"

_EMITTER_NAMES = {
    "warn",
    "warning",
    "error",
    "info",
    "debug",
    "critical",
    "log",
    "exception",
    "print",
    "echo",
    "secho",
}


def _iter_string_constants(node):
    """Yield string Constant nodes inside literals (incl. f-string parts)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node
    elif isinstance(node, ast.JoinedStr):
        for part in node.values:
            yield from _iter_string_constants(part)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        yield from _iter_string_constants(node.left)
        yield from _iter_string_constants(node.right)


def _call_name(func):
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _nonascii_runtime_strings(tree, rel):
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node.func) in _EMITTER_NAMES:
            args = list(node.args) + [kw.value for kw in node.keywords]
            for arg in args:
                for const in _iter_string_constants(arg):
                    if not const.value.isascii():
                        hits.append((rel, const.lineno, const.value))
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for arg in node.exc.args:
                for const in _iter_string_constants(arg):
                    if not const.value.isascii():
                        hits.append((rel, const.lineno, const.value))
    return hits


@pytest.mark.parametrize(
    "py_file",
    sorted(_VFED_ROOT.rglob("*.py")),
    ids=lambda p: str(p.relative_to(_VFED_ROOT)),
)
def test_runtime_messages_are_ascii(py_file):
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    hits = _nonascii_runtime_strings(tree, str(py_file.relative_to(_VFED_ROOT)))
    assert not hits, f"non-ASCII runtime message string(s) found: {hits}"
