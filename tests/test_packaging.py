"""Packaging guarantees for the three shipped packages.

The invariant under test: **no module in `kg_contracts`, `kgis` or `kg_eval` may
import anything outside the declared runtime dependency closure at import time**,
apart from an explicitly enumerated set of test-support modules that no runtime
`__init__` chain may reach. Violating it is what made `import kgis` fail for every
consumer who installed without the `[dev]` extra (issue #37).

Two properties of the check matter, because the obvious versions of it are unsound:

*It cannot run in-process.* CI's `test` job installs `.[dev]`, so `pytest` is
importable there by construction — an in-process `import kgis` proves nothing. The
sweep runs in a subprocess with an import hook installed.

*The hook is an allowlist, not a denylist.* Blocking `pytest` by name lets a
transitive dev dependency — `pluggy`, `iniconfig` — sail through here and fail in a
real consumer's environment. The allowlist is the stdlib plus the distribution
closure of this project's *non-extra* requirements, computed from installed
metadata so it tracks `pyproject.toml` instead of restating it.

One known deviation from a genuinely absent module: the hook raises from
`find_spec`, so `importlib.util.find_spec("pytest")` propagates instead of
returning `None`. Nothing in these packages soft-probes for an optional import, so
the deviation is unreachable; it is recorded here rather than silently relied on.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RUNTIME_PACKAGES = ("kg_contracts", "kgis", "kg_eval")

# Modules that legitimately import a dev-only dependency. Every one is a reusable
# pytest suite an implementor subclasses; none may be reachable from a runtime
# `__init__` chain, which the sweep enforces by importing everything else.
#
# This set is the review checkpoint: adding a module here is a deliberate act, and
# adding `import pytest` to any module *not* here turns the sweep red. That is what
# closes the fault class — `kgis/structured/testing.py` and `kgis/ledger/contract.py`
# are reusable suites eagerly re-exported from runtime packages today, and they are
# safe only for as long as they stay pytest-free. They are not listed, so the day
# one of them grows a `pytest.raises` this test fails.
DEV_ONLY_MODULES = frozenset(
    {
        "kg_contracts.testing.contract",
        "kgis.evidence.contract",
    }
)

_SWEEP = '''
import importlib
import importlib.machinery
import importlib.util
import json
import os
import pkgutil
import re
import sys
import sysconfig
from importlib.metadata import distribution, packages_distributions

OWN = __OWN__
DEV_ONLY = frozenset(__DEV_ONLY__)


def _canon(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _runtime_distribution_closure(root):
    """Distributions reachable from `root` through non-extra requirements only."""
    seen, stack = set(), [root]
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
        for req in dist.requires or []:
            head, sep, marker = req.partition(";")
            if sep and "extra" in marker:
                continue
            match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", head.strip())
            if match:
                stack.append(match.group(0))
    return seen


_dists = _runtime_distribution_closure("agentic-kgis")
_allowed = set(sys.stdlib_module_names) | set(OWN)
for _mod, _owners in packages_distributions().items():
    if any(_canon(owner) in _dists for owner in _owners):
        _allowed.add(_mod)
# Interpreter/site machinery, never a project dependency.
_allowed |= {"__main__", "sitecustomize", "usercustomize", "_distutils_hack"}


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
    `sys.stdlib_module_names` — `_sysconfigdata_*` is generated at build time,
    so it is named per-platform and cannot be enumerated ahead of time."""
    origin = getattr(spec, "origin", None)
    if not origin or not os.path.isabs(origin):
        return False
    real = os.path.realpath(origin)
    return real.startswith(_STDLIB_DIRS) and "site-packages" not in real


class _RuntimeClosureOnly:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in _allowed or fullname in sys.builtin_module_names:
            return None
        # Resolve through PathFinder directly rather than walking sys.meta_path,
        # so this cannot recurse back into this finder.
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if _is_stdlib(spec):
            return spec
        raise ModuleNotFoundError(
            "No module named %r: outside the runtime dependency closure of "
            "agentic-kgis (blocked by tests/test_packaging.py)" % fullname,
            name=fullname,
        )


# An `assert` here would vanish under PYTHONOPTIMIZE, which the subprocess
# inherits from the developer's shell.
if {"pytest", "_pytest"} & set(sys.modules):
    raise SystemExit("pytest was already in sys.modules before the hook was installed")

sys.meta_path.insert(0, _RuntimeClosureOnly())


def _module_names(package):
    """Every module in `package`, found on disk without importing anything."""
    spec = importlib.util.find_spec(package)
    paths = list(spec.submodule_search_locations)

    def walk(prefix, search_paths):
        yield prefix
        for info in pkgutil.iter_modules(search_paths):
            name = prefix + "." + info.name
            if info.ispkg:
                sub = [
                    os.path.join(p, info.name)
                    for p in search_paths
                    if os.path.isdir(os.path.join(p, info.name))
                ]
                yield from walk(name, sub)
            else:
                yield name

    return list(walk(package, paths))


found, failures = [], []
for _package in OWN:
    found.extend(_module_names(_package))

for _name in sorted(found):
    if _name in DEV_ONLY:
        continue
    try:
        importlib.import_module(_name)
    except BaseException as exc:  # noqa: BLE001 - the failure is the result
        failures.append("%s -> %s: %s" % (_name, type(exc).__name__, exc))

print(
    "RESULT "
    + json.dumps(
        {
            "checked": len(found) - len(DEV_ONLY),
            "found": sorted(found),
            "failures": failures,
            "allowed_sample": sorted(_allowed - set(sys.stdlib_module_names)),
        }
    )
)
'''


def _sweep_result() -> dict[str, object]:
    """Run the import sweep in a subprocess and return its parsed result."""
    import kgis

    # Works for an editable install (repo `src/`) and a wheel install
    # (site-packages) alike: in both cases this is where the packages import from.
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
    result: dict[str, object] = json.loads(marker[-1][len("RESULT ") :])
    return result


def test_packages_import() -> None:
    import kg_contracts
    import kg_eval
    import kgis

    assert kg_contracts.__name__ == "kg_contracts"
    assert kgis.__name__ == "kgis"
    assert kg_eval.__name__ == "kg_eval"


def test_no_module_imports_outside_the_runtime_dependency_closure() -> None:
    """Regression guard for issue #37, swept over every module in all three packages.

    Covers the entry points an adopter actually uses — `kgis`, `kgis.testing`,
    `kgis.ledger`, `kgis.structured`, `kg_eval` — not just the three top-level
    names, and catches a transitive dev dependency as readily as `pytest` itself.
    """
    result = _sweep_result()
    assert result["failures"] == [], (
        "modules that import outside the runtime dependency closure:\n  "
        + "\n  ".join(str(f) for f in result["failures"])  # type: ignore[union-attr]
    )
    assert int(result["checked"]) > 50, f"sweep found too few modules: {result['checked']}"


def test_dev_only_allowlist_is_accurate() -> None:
    """Every allowlisted module must exist and must really need the dev extra.

    Without this the allowlist rots silently: a renamed or deleted module would
    keep its exemption and quietly stop being swept.
    """
    found = set(_sweep_result()["found"])  # type: ignore[arg-type]
    assert DEV_ONLY_MODULES <= found, f"stale allowlist entries: {DEV_ONLY_MODULES - found}"
    for name in sorted(DEV_ONLY_MODULES):
        module = __import__(name, fromlist=["*"])
        assert "pytest" in sys.modules, f"{name} is allowlisted but does not need pytest"
        assert module.__name__ == name


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
