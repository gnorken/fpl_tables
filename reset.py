#!/usr/bin/env python3
from pathlib import Path
import sys
import subprocess

root = Path(__file__).resolve().parent
db = root / "page_views.db"
if db.exists():
    db.unlink()
subprocess.run([sys.executable, str(root / "db_setup.py")], check=True)
