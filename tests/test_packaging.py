"""Packaging guarantees for the three shipped packages.

The invariant under test: **no module in `kg_contracts`, `kgis` or `kg_eval` may
import anything outside the declared runtime dependency closure at import time**,
apart from an explicitly enumerated set of reusable `pytest` suites that no runtime
`__init__` chain may reach. Violating it is what made `import kgis` fail for every
consumer who installed without the `[dev]` extra (issue #37).

Four properties of the check matter, because the obvious versions of it are unsound
and each of these was arrived at by watching a reviewer defeat the previous one:

*It cannot run in-process.* CI's `test` job installs `.[dev]`, so `pytest` is
importable there by construction — an in-process `import kgis` proves nothing, and
neither does any assertion about `sys.modules`. Everything that must be able to fail
runs in the subprocess, under the hook.

*The hook is an allowlist, not a denylist.* Blocking `pytest` by name lets a
transitive dev dependency — `pluggy`, `iniconfig` — sail through here and fail in a
real consumer's environment. The allowlist is the stdlib plus the distribution
closure of this project's *non-extra* requirements, computed from installed metadata.

*Enumeration is filesystem-based, not `pkgutil`-based.* `pkgutil.iter_modules` does
not descend into a PEP 420 namespace package (a directory with no `__init__.py`),
which the wheel ships and an adopter can import perfectly well.

*Exemptions must prove themselves.* A module listed in `DEV_ONLY_MODULES` has to
actually fail under the hook, and fail *because of `pytest`* — see
`test_dev_only_exemptions_are_justified`.

**Scope, stated deliberately: this is an import-time invariant.** A module-level
`__getattr__` that reaches a dev-only dependency on attribute access is invisible to
the sweep, and that is the mechanism the #37 fix itself uses. So the other place a
dev-only dependency may legitimately hide is a lazy-export table —
`kgis/evidence/__init__.py`'s `_LAZY` is the only one today. Those tables carry the
same review burden as `DEV_ONLY_MODULES` below, and no test can carry it for them:
deferring an import is exactly the fix, so a guard cannot tell a good deferral from a
bad one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

RUNTIME_PACKAGES = ("kg_contracts", "kgis", "kg_eval")

# Modules that legitimately import a dev-only dependency: reusable pytest suites an
# implementor subclasses. None may be reachable from a runtime `__init__` chain,
# which the sweep enforces by importing everything else.
#
# This set is the review checkpoint, and it is machine-checked in both directions:
# a module here that imports cleanly, or that fails for any reason other than
# `pytest`, fails `test_dev_only_exemptions_are_justified`; a module *not* here that
# needs the dev extra fails the sweep. `kgis/structured/testing.py` and
# `kgis/ledger/contract.py` are reusable suites eagerly re-exported from runtime
# packages today, and are deliberately absent: they are safe only while they stay
# pytest-free, and the day either grows a `pytest.raises` this goes red.
DEV_ONLY_MODULES = frozenset(
    {
        "kg_contracts.testing.contract",
        "kgis.evidence.contract",
    }
)

# The only dev-only distribution a module under `src/` may legitimately import. The
# `[dev]` extra is pytest + ruff + mypy; the latter two are CLIs that nothing
# imports, and pytest's transitive dependencies (`pluggy`, `iniconfig`, ...) are not
# this project's to depend on. So "needs the dev extra" means precisely "is a pytest
# suite", and an exemption justified by anything else is a mislabelled bug.
DEV_ONLY_ROOTS = frozenset({"pytest", "_pytest"})

_SWEEP = '''
import importlib
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
import sysconfig
from importlib.metadata import distribution, packages_distributions

OWN = __OWN__
DEV_ONLY = frozenset(__DEV_ONLY__)


def _canon(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _direct_requirements(dist):
    """Requirement names from `dist`, excluding anything gated on an extra."""
    names = []
    for req in dist.requires or []:
        head, sep, marker = req.partition(";")
        if sep and "extra" in marker:
            continue
        match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", head.strip())
        if match:
            names.append(match.group(0))
    return names


def _runtime_distribution_closure(root):
    """Distributions reachable from `root` through non-extra requirements only."""
    seen, stack, direct = set(), [root], []
    while stack:
        raw = stack.pop()
        key = _canon(raw)
        if key in seen:
            continue
        seen.add(key)
        try:
            dist = distribution(raw)
        except Exception:
            continue
        requirements = _direct_requirements(dist)
        if _canon(raw) == _canon(root):
            direct = sorted({_canon(name) for name in requirements})
        stack.extend(requirements)
    return seen, direct


_dists, _direct = _runtime_distribution_closure("agentic-kgis")
_allowed = set(sys.stdlib_module_names) | set(OWN)
for _mod, _owners in packages_distributions().items():
    if any(_canon(owner) in _dists for owner in _owners):
        _allowed.add(_mod)
# `__main__` is this `-c` script itself. Nothing else is added: site machinery
# (`sitecustomize`, setuptools' `_distutils_hack`) is imported at interpreter
# startup, before the hook exists, so it never needs an entry -- and granting it one
# would let a src module import setuptools internals, which a 3.12+ venv does not
# even ship.
_allowed.add("__main__")

_STDLIB_DIRS = tuple(
    sorted(
        {
            os.path.realpath(path)
            for key in ("stdlib", "platstdlib")
            if (path := sysconfig.get_paths().get(key))
        }
    )
)


def _is_stdlib(spec):
    """True for a module that ships with CPython but is absent from
    `sys.stdlib_module_names` -- `_sysconfigdata_*` is generated at build time, so
    it is named per-platform and cannot be enumerated ahead of time."""
    origin = getattr(spec, "origin", None)
    if not origin or not os.path.isabs(origin):
        return False
    real = os.path.realpath(origin)
    return real.startswith(_STDLIB_DIRS) and "site-packages" not in real


class _RuntimeClosureOnly:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in _allowed or fullname in sys.builtin_module_names:
            return None
        # Resolve through PathFinder directly rather than walking sys.meta_path, so
        # this cannot recurse back into this finder.
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if _is_stdlib(spec):
            return spec
        raise ModuleNotFoundError(
            "No module named %r: outside the runtime dependency closure of "
            "agentic-kgis (blocked by tests/test_packaging.py)" % fullname,
            name=fullname,
        )


# An `assert` here would vanish under PYTHONOPTIMIZE, which the subprocess inherits
# from the developer's shell.
if {"pytest", "_pytest"} & set(sys.modules):
    raise SystemExit("pytest was already in sys.modules before the hook was installed")

sys.meta_path.insert(0, _RuntimeClosureOnly())


def _module_names(package):
    """Every module in `package`, walked from disk without importing anything.

    Filesystem rather than `pkgutil`: a PEP 420 namespace subpackage has no
    `__init__.py`, so `pkgutil.iter_modules` skips it and everything beneath it,
    while the wheel ships it and an adopter can import it.
    """
    spec = importlib.util.find_spec(package)
    names = set()
    for root in spec.submodule_search_locations:
        root = os.path.realpath(root)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames if d.isidentifier() and d != "__pycache__"
            ]
            relative = os.path.relpath(dirpath, root)
            prefix = package if relative == "." else package + "." + relative.replace(os.sep, ".")
            names.add(prefix)
            for filename in filenames:
                if not filename.endswith(".py") or filename == "__init__.py":
                    continue
                stem = filename[:-3]
                if stem.isidentifier():
                    names.add(prefix + "." + stem)
    return names


def _import(name):
    """Import `name` under the hook; return the blocked root, or None on success."""
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as exc:
        return (exc.name or "?").partition(".")[0]
    except BaseException as exc:
        return "!%s: %s" % (type(exc).__name__, exc)
    return None


found = set()
for _package in OWN:
    found |= _module_names(_package)

failures, exempt_outcome = {}, {}
for _name in sorted(found):
    blocked = _import(_name)
    if _name in DEV_ONLY:
        exempt_outcome[_name] = blocked
    elif blocked is not None:
        failures[_name] = blocked

print(
    "RESULT "
    + json.dumps(
        {
            "found": sorted(found),
            "swept": len(found) - len(DEV_ONLY),
            "failures": failures,
            "exempt_outcome": exempt_outcome,
            "direct_requirements": _direct,
            "allowed_beyond_stdlib": sorted(_allowed - set(sys.stdlib_module_names)),
        }
    )
)
'''


@lru_cache(maxsize=1)
def _sweep_json() -> str:
    """Run the import sweep in a subprocess. Cached: one subprocess per session."""
    import kgis

    # Works for an editable install (repo `src/`) and a wheel install (site-packages)
    # alike: in both cases this is where the packages import from.
    import_root = Path(kgis.__file__).resolve().parent.parent
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(import_root), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
    script = _SWEEP.replace("__OWN__", repr(list(RUNTIME_PACKAGES))).replace(
        "__DEV_ONLY__", repr(sorted(DEV_ONLY_MODULES))
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, f"sweep did not run\n--- stderr ---\n{proc.stderr}"
    marker = [line for line in proc.stdout.splitlines() if line.startswith("RESULT ")]
    assert marker, f"sweep produced no result\n--- stdout ---\n{proc.stdout}"
    return marker[-1][len("RESULT ") :]


def _sweep() -> dict:
    return json.loads(_sweep_json())


def test_packages_import() -> None:
    import kg_contracts
    import kg_eval
    import kgis

    assert kg_contracts.__name__ == "kg_contracts"
    assert kgis.__name__ == "kgis"
    assert kg_eval.__name__ == "kg_eval"


def test_no_module_imports_outside_the_runtime_dependency_closure() -> None:
    """Regression guard for issue #37, swept over every module in all three packages.

    Covers the entry points an adopter actually uses — `kgis.testing`, `kgis.ledger`,
    `kgis.structured`, `kg_eval` — not just the three top-level names, and catches a
    transitive dev dependency as readily as `pytest` itself.
    """
    result = _sweep()
    assert result["failures"] == {}, (
        "modules that import outside the runtime dependency closure:\n  "
        + "\n  ".join(f"{name} -> {blocked}" for name, blocked in result["failures"].items())
    )
    # Not a coverage target: a tripwire for the walker silently collapsing to a
    # handful of modules, which would make every other assertion here vacuous.
    assert result["swept"] > 50, f"sweep found too few modules: {result['swept']}"


def test_dev_only_exemptions_are_justified() -> None:
    """Every exemption must exist, must really fail, and must fail because of pytest.

    This has to be decided *inside* the sweep subprocess. The obvious in-process
    version — import the module here and check `"pytest" in sys.modules` — is
    vacuous, because these tests run under pytest and the answer is always yes. A
    reviewer exploited exactly that: a leaf module with a planted `import pluggy`,
    added to the exemption set, disappeared from both guards with the suite green.
    """
    result = _sweep()
    found = set(result["found"])
    outcome: dict[str, str | None] = result["exempt_outcome"]

    assert DEV_ONLY_MODULES <= found, f"exemptions naming no such module: {DEV_ONLY_MODULES - found}"

    imported_fine = sorted(name for name, blocked in outcome.items() if blocked is None)
    assert not imported_fine, (
        "exempt but needs no dev-only dependency — remove from DEV_ONLY_MODULES, "
        f"they are being silently excluded from the sweep: {imported_fine}"
    )

    misjustified = sorted(
        f"{name} -> {blocked}"
        for name, blocked in outcome.items()
        if blocked is not None and blocked not in DEV_ONLY_ROOTS
    )
    assert not misjustified, (
        "exempt, but the missing dependency is not pytest. The exemption exists for "
        f"reusable pytest suites; this is an undeclared dependency: {misjustified}"
    )


def test_runtime_dependency_metadata_matches_pyproject() -> None:
    """The allowlist is only as fresh as the `.dist-info` it is derived from.

    In CI the install is always fresh, but a local editable install snapshots the
    requirements at install time. Without this, adding a runtime dependency to
    `pyproject.toml` turns the sweep red with a message blaming the new import
    rather than the stale metadata.
    """
    import tomllib

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.is_file():  # installed-wheel test run; nothing to compare against
        return

    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]
    import re

    names = {
        re.sub(r"[-_.]+", "-", re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", spec.strip()).group(0)).lower()
        for spec in declared
    }
    installed = set(_sweep()["direct_requirements"])
    assert names == installed, (
        "installed metadata disagrees with pyproject.toml — reinstall the package "
        f"(`pip install -e .`). pyproject: {sorted(names)}; installed: {sorted(installed)}"
    )


def test_reusable_suite_is_reachable_by_both_supported_names() -> None:
    """The lazy export must not narrow the surface Plan 2 established."""
    import kgis.evidence
    from kgis.evidence import EvidenceRegistryContract as via_package
    from kgis.evidence.contract import EvidenceRegistryContract as via_module

    assert via_package is via_module
    # PEP 562's other half: `dir()`, tab-completion and pydoc still list the name.
    assert "EvidenceRegistryContract" in dir(kgis.evidence)
    assert set(kgis.evidence.__all__) <= set(dir(kgis.evidence))

    try:
        kgis.evidence.NoSuchName  # type: ignore[attr-defined]
    except AttributeError:
        pass
    else:  # pragma: no cover - only reached if __getattr__ regresses
        raise AssertionError("unknown attributes must still raise AttributeError")
