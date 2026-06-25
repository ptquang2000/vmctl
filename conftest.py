"""Make ``import sss`` resolve to the editable-installed package during tests.

When pytest runs from the repo root, the root is on ``sys.path``, so Python's
PathFinder finds the bare ``./sss`` submodule *directory* as a namespace package
and returns it before setuptools' editable finder is consulted -- shadowing the
real ``sss/sss`` package, whose ``connect`` / ``Profile`` then appear missing.

Explicitly load the real package from the submodule and cache it in
``sys.modules`` so every later ``import sss`` gets it. This is test-only: the
installed ``vmctl`` console script runs without the repo root on ``sys.path``,
so it resolves ``sss`` via the editable finder and never hits this shadow.
"""

import importlib.util
import os
import sys

_existing = sys.modules.get("sss")
if _existing is None or getattr(_existing, "connect", None) is None:
    _pkg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sss", "sss")
    _init = os.path.join(_pkg, "__init__.py")
    if os.path.isfile(_init):
        sys.modules.pop("sss", None)
        _spec = importlib.util.spec_from_file_location(
            "sss", _init, submodule_search_locations=[_pkg]
        )
        _real = importlib.util.module_from_spec(_spec)
        sys.modules["sss"] = _real
        _spec.loader.exec_module(_real)
