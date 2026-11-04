"""Architecture layering guard — zero-dependency, AST-only.

Encodes the layering rules documented in ``docs/architecture.md``:

    Layer 3 (entry):    cli.py · agent/evaluator.py
    Layer 2 (design):   design/
    Layer 1 (domain):   physics/ · devices/ · plants/ · weather/ · pvbes/
    Standalone:         calibration/ (imports plants only; nothing imports it)
    Frozen archive:     research/ (imported by nothing)

Rules:
1. Layer-1 packages never import design/agent/cli/calibration.
2. calibration/ imports plants only (beyond itself).
3. design/ imports layer-1 packages only (never agent/cli/calibration).
4. agent/ imports design + weather only.
5. cli.py may import anything inside vfed/ (composition root — not restricted).
6. Nothing imports research/ (frozen archive).

The test parses source files with ``ast`` — it never imports vfed, so a broken
import elsewhere in the suite cannot mask a layering violation, and the guard
stays valid across the planned ``engine.py`` split (rules are package-level).

Companion map: docs/architecture.md (single source of truth).
"""

import ast
from pathlib import Path

VFED_ROOT = Path(__file__).resolve().parents[1] / "vfed"

LAYER1 = {"physics", "devices", "plants", "weather", "pvbes"}

# Allowed internal vfed.* top-level modules per package (own package always allowed).
# Intra-layer-1 edges (verified 2026-11-04): devices and plants use physics
# psychrometrics (COP / SMER curves; saturation-deficit transpiration).
ALLOWED_IMPORTS = {
    "physics": set(),
    "devices": {"physics"},
    "plants": {"physics"},
    "weather": set(),
    "pvbes": set(),
    "calibration": {"plants"},
    "design": LAYER1,
    "agent": {"design", "weather"},
}

# vfed/*.py top-level files: cli.py is the composition root; __init__.py holds metadata.
ALLOWED_ROOT_FILES = {"cli.py", "__init__.py"}


def _iter_python_files():
    for path in sorted(VFED_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _file_top_package(path: Path) -> str:
    """Map a file under vfed/ to its top-level package ('design', 'cli-root', ...)."""
    rel = path.relative_to(VFED_ROOT)
    if len(rel.parts) == 1:
        return "root"  # vfed/cli.py, vfed/__init__.py
    return rel.parts[0]


def _internal_imports(path: Path):
    """Yield (top_module, node) for every vfed-internal or research import in the file.

    Absolute forms:   ``import vfed.x`` / ``from vfed.x.y import z`` / ``from vfed import x``
    Relative forms:   ``from ..physics.psychrometrics import X`` (resolved against the
                      file's location under vfed/, so a resolved relative import is
                      ALWAYS internal and its first resolved part is the top package).
    """
    parts_from_root = path.relative_to(VFED_ROOT).parts[:-1]  # this file's package dirs
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name_parts = alias.name.split(".")
                if name_parts[0] == "vfed":
                    yield name_parts[1], node
                elif name_parts[0] == "research":
                    yield "research", node
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if not node.module:
                    continue
                mod_parts = node.module.split(".")
                if mod_parts[0] == "vfed":
                    if len(mod_parts) > 1:
                        yield mod_parts[1], node
                    else:  # ``from vfed import cli`` — aliases are submodules
                        for alias in node.names:
                            yield alias.name.split(".")[0], node
                elif mod_parts[0] == "research":
                    yield "research", node
            else:
                # level 1 = current package, 2 = parent, ...
                keep = len(parts_from_root) - (node.level - 1)
                base_parts = parts_from_root[: max(keep, 0)]
                module_parts = tuple(node.module.split(".")) if node.module else ()
                full = base_parts + module_parts
                if full:
                    yield full[0], node


def _violations(pkg, allowed):
    out = []
    for path in _iter_python_files():
        if _file_top_package(path) != pkg:
            continue
        for top, node in _internal_imports(path):
            if top == pkg:
                continue
            if top not in allowed:
                out.append(
                    f"{path.relative_to(VFED_ROOT.parent)}:{node.lineno} "
                    f"imports vfed.{top} (allowed: {sorted(allowed) or 'nothing'})"
                )
    return out


def test_vfed_package_inventory():
    """Every layer documented in docs/architecture.md exists and has files."""
    expected = LAYER1 | {"design", "agent", "calibration"}
    found = {_file_top_package(p) for p in _iter_python_files()}
    missing = expected - found
    assert not missing, f"vfed/ lost documented package(s): {sorted(missing)}"


def test_layer1_never_imports_upper_layers():
    for pkg in sorted(LAYER1):
        violations = _violations(pkg, ALLOWED_IMPORTS[pkg])
        assert not violations, f"{pkg}/ layering violations:\n" + "\n".join(violations)


def test_calibration_imports_plants_only():
    violations = _violations("calibration", ALLOWED_IMPORTS["calibration"])
    assert not violations, "calibration/ violations:\n" + "\n".join(violations)


def test_design_imports_layer1_only():
    violations = _violations("design", ALLOWED_IMPORTS["design"])
    assert not violations, "design/ violations:\n" + "\n".join(violations)


def test_agent_imports_design_and_weather_only():
    violations = _violations("agent", ALLOWED_IMPORTS["agent"])
    assert not violations, "agent/ violations:\n" + "\n".join(violations)


def test_nothing_imports_research():
    violations = []
    for path in _iter_python_files():
        for top, node in _internal_imports(path):
            if top == "research":
                violations.append(
                    f"{path.relative_to(VFED_ROOT.parent)}:{node.lineno} imports research/ "
                    f"— frozen archive, never imported by vfed/"
                )
    assert not violations, "research/ import violations:\n" + "\n".join(violations)


def test_root_files_are_only_cli_and_init():
    """No surprise top-level modules in vfed/ outside the documented packages."""
    root_files = {p.name for p in _iter_python_files() if _file_top_package(p) == "root"}
    unexpected = root_files - ALLOWED_ROOT_FILES
    assert not unexpected, (
        f"Unexpected file(s) at vfed/ top level: {sorted(unexpected)} — "
        f"new modules belong in a documented package (docs/architecture.md)"
    )
