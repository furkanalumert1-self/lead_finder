"""Vercel entrypoint (FastAPI preset): the registry app, with Lead Radar at /leads.

Vercel imports `app` from this file. The package lives under src/, so it is put on the path here
rather than installed; dependencies come from requirements.txt (scripts/vercel-prepare.sh).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from treg.api import app  # noqa: E402,F401
