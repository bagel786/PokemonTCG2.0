"""Pytest path bootstrap: reuse the verified pinned dependency environment
(rlcard==1.2.0, ising-monte-carlo-toolkit==0.1.0 inside redesign/.venv) while
running with the interpreter that carries pytest."""

import sys
from pathlib import Path

_VENV_SITE = Path(__file__).resolve().parents[2] / "redesign" / ".venv" / \
    "lib" / "python3.11" / "site-packages"
if _VENV_SITE.exists() and str(_VENV_SITE) not in sys.path:
    sys.path.append(str(_VENV_SITE))
