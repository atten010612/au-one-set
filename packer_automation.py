"""Compatibility wrapper for the AU Task standalone runtime."""

from importlib import import_module
from pathlib import Path
import sys

_RUNTIME = Path(__file__).resolve().parent / "au-task-skill" / "runtime"
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))
_IMPLEMENTATION = import_module("packer_runtime")
for _name, _value in vars(_IMPLEMENTATION).items():
    if _name not in {"__name__", "__loader__", "__package__", "__spec__"}:
        globals()[_name] = _value
