import sys
from pathlib import Path

# Ensure repo root is on sys.path when invoked via 'fastapi dev/run' CLI
_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.main import create_app

app = create_app(is_mock=True)

__all__ = ["app"]
