"""Create the SQLite schema. Idempotent."""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
from app.db import init_db

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
