"""Compatibility wrapper for the AU Task standalone runtime."""

from importlib import import_module
from pathlib import Path
import sys

_RUNTIME = Path(__file__).resolve().parent / "au-task-skill" / "runtime"
if str(_RUNTIME) not in sys.path:
    sys.path.append(str(_RUNTIME))
_IMPLEMENTATION = import_module("converter_runtime")
sys.modules[__name__] = _IMPLEMENTATION
