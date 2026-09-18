"""Packaging guarantees for the three shipped packages.

The runtime import surface must hold under the *runtime* dependency set alone
(`pydantic`), not under `[dev]`. CI installs `.[dev]`, so an in-process import
check cannot see a dev-only dependency that has leaked into a runtime
`__init__` chain — the check below runs in a subprocess where `pytest` is made
unimportable, which is exactly the environment a consumer who ran
`pip install agentic-kgis` is in (issue #37).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RUNTIME_PACKAGES = ("kg_contracts", "kgis", "kg_eval")

# Blocks `pytest` (and its `_pytest` implementation package) at the import
# system level, then imports every runtime package. A meta-path finder is used
# rather than a second virtualenv so the check costs milliseconds and needs no
# network.
_IMPORT_WITHOUT_PYTEST = """
import sys

_DEV_ONLY = frozenset({"pytest", "_pytest"})


class _BlockDevOnly:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in _DEV_ONLY:
            raise ModuleNotFoundError(
                f"No module named {fullname!r} (dev-only dependency, blocked by the test)",
                name=fullname,
            )
        return None


sys.meta_path.insert(0, _BlockDevOnly())

import kg_contracts
import kg_eval
import kgis

assert "pytest" not in sys.modules
print("ok")
"""


def _run_isolated(script: str) -> subprocess.CompletedProcess[str]:
    import kgis

    # Works for an editable install (repo `src/`) and a wheel install
    # (site-packages) alike; in both cases this is the directory the packages
    # are imported from.
    import_root = Path(kgis.__file__).resolve().parent.parent
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(import_root), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_packages_import() -> None:
    import kg_contracts
    import kg_eval
    import kgis

    assert kg_contracts.__name__ == "kg_contracts"
    assert kgis.__name__ == "kgis"
    assert kg_eval.__name__ == "kg_eval"


def test_runtime_import_does_not_require_pytest() -> None:
    """No runtime package may pull a dev-only dependency at import time.

    Regression guard for issue #37: `kgis/evidence/__init__.py` eagerly
    imported a pytest-based contract suite, so `import kgis` failed outright
    for anyone who installed without the `[dev]` extra.
    """
    proc = _run_isolated(_IMPORT_WITHOUT_PYTEST)
    assert proc.returncode == 0, (
        "importing "
        + ", ".join(RUNTIME_PACKAGES)
        + " requires a dev-only dependency; pytest is not a runtime dependency"
        + f"\n--- stderr ---\n{proc.stderr}"
    )
    assert proc.stdout.strip().endswith("ok")


def test_reusable_suites_stay_importable() -> None:
    """The pytest-based suites still resolve, from both supported names."""
    from kgis.evidence import EvidenceRegistryContract as via_evidence
    from kgis.testing.evidence import EvidenceRegistryContract as via_testing

    assert via_evidence is via_testing
