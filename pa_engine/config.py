"""Paths. PA_ENGINE_HOME overrides the project folder (e.g. to run the same code on another domain pack)."""
import os
from pathlib import Path

HOME = Path(os.environ.get("PA_ENGINE_HOME") or Path(__file__).absolute().parent.parent)
CORPUS = HOME / "corpus"
GOLDEN = HOME / "golden_set"
RUNS = HOME / "runs"
