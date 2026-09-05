"""
Initialise la base SQLite (tables + catégories et paramètres par défaut).
Sans effet si la base existe déjà : peut être relancé sans risque.

Usage :  python scripts/init_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import db  # noqa: E402

if __name__ == "__main__":
    db.init_db()
    print(f"Base prête : {db.DB_PATH}")
    print(f"Catégories : {', '.join(db.get_categories()['name'])}")
