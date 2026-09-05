"""
Couche d'accès à la base SQLite.

Toutes les lectures renvoient des DataFrames pandas typés (dates en datetime,
montants en float) pour que le moteur analytique n'ait pas à re-nettoyer les données.
Le chemin de la base peut être forcé avec la variable d'environnement BUDGET_DB_PATH
(pratique pour les tests ou une future version multi-utilisateurs).
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from database.models import DEFAULT_CATEGORIES, DEFAULT_SETTINGS, SCHEMA

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("BUDGET_DB_PATH", PROJECT_ROOT / "data" / "budget.db"))

EXPENSE_COLUMNS = ["id", "date", "amount", "category", "subcategory", "payment_method",
                   "description", "necessary", "recurring", "refund", "created_at"]


@contextmanager
def get_connection():
    """Connexion SQLite avec commit automatique et clés étrangères activées."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Crée les tables si besoin et insère les valeurs par défaut (idempotent)."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        # Catégories par défaut, seulement si la table est vide
        count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if count == 0:
            for pos, (name, subs, essential) in enumerate(DEFAULT_CATEGORIES):
                conn.execute(
                    "INSERT INTO categories (name, subcategories, essential, position) VALUES (?, ?, ?, ?)",
                    (name, "|".join(subs), essential, pos),
                )
        # Paramètres par défaut manquants
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            conn.execute("INSERT INTO users (name) VALUES (?)", ("Utilisateur",))


def reset_db() -> None:
    """Supprime toutes les données (utilisé par le script de données fictives)."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


# ---------------------------------------------------------------------------
# Paramètres / profil
# ---------------------------------------------------------------------------
def get_settings() -> dict:
    with get_connection() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = dict(DEFAULT_SETTINGS)
    settings.update({r["key"]: r["value"] for r in rows})
    return settings


def get_setting(key: str, default=None):
    return get_settings().get(key, default)


def set_setting(key: str, value) -> None:
    with get_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


def get_setting_float(key: str, default: float = 0.0) -> float:
    try:
        return float(get_setting(key, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Catégories
# ---------------------------------------------------------------------------
def get_categories() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM categories ORDER BY position, name", conn)
    df["subcategories"] = df["subcategories"].fillna("").apply(
        lambda s: [x for x in s.split("|") if x])
    return df


def get_category_map() -> dict[str, list[str]]:
    """{'Alimentation': ['Courses', 'Restaurant', ...], ...}"""
    df = get_categories()
    return dict(zip(df["name"], df["subcategories"]))


def get_essential_categories() -> set[str]:
    df = get_categories()
    return set(df.loc[df["essential"] == 1, "name"])


def add_category(name: str, subcategories: list[str], essential: bool = False) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Le nom de la catégorie est vide.")
    with get_connection() as conn:
        pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM categories").fetchone()[0]
        conn.execute(
            "INSERT INTO categories (name, subcategories, essential, position) VALUES (?, ?, ?, ?)",
            (name, "|".join(s.strip() for s in subcategories if s.strip()), int(essential), pos),
        )


def update_category(category_id: int, name: str, subcategories: list[str], essential: bool) -> None:
    with get_connection() as conn:
        old = conn.execute("SELECT name FROM categories WHERE id = ?", (category_id,)).fetchone()
        conn.execute(
            "UPDATE categories SET name = ?, subcategories = ?, essential = ? WHERE id = ?",
            (name.strip(), "|".join(s.strip() for s in subcategories if s.strip()),
             int(essential), category_id),
        )
        # On propage le renommage aux dépenses et budgets existants
        if old and old["name"] != name.strip():
            conn.execute("UPDATE expenses SET category = ? WHERE category = ?", (name.strip(), old["name"]))
            conn.execute("UPDATE budgets SET category = ? WHERE category = ?", (name.strip(), old["name"]))


def delete_category(category_id: int, reassign_to: str = "Autres") -> None:
    """Supprime une catégorie ; ses dépenses sont réaffectées à `reassign_to`."""
    with get_connection() as conn:
        row = conn.execute("SELECT name FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not row:
            return
        conn.execute("UPDATE expenses SET category = ? WHERE category = ?", (reassign_to, row["name"]))
        conn.execute("DELETE FROM budgets WHERE category = ?", (row["name"],))
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))


# ---------------------------------------------------------------------------
# Revenus
# ---------------------------------------------------------------------------
def add_income(date_: str, amount: float, source: str = "Salaire", note: str = "") -> int:
    if amount < 0:
        raise ValueError("Un revenu ne peut pas être négatif.")
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO incomes (date, amount, source, note) VALUES (?, ?, ?, ?)",
            (str(date_), float(amount), source, note or ""),
        )
        return cur.lastrowid


def update_income(income_id: int, date_: str, amount: float, source: str, note: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE incomes SET date = ?, amount = ?, source = ?, note = ? WHERE id = ?",
                     (str(date_), float(amount), source, note or "", income_id))


def delete_income(income_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM incomes WHERE id = ?", (income_id,))


def get_incomes() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM incomes ORDER BY date DESC, id DESC", conn)
    if df.empty:
        return pd.DataFrame(columns=["id", "date", "amount", "source", "note", "created_at", "month"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["month"] = df["date"].dt.strftime("%Y-%m")
    return df


# ---------------------------------------------------------------------------
# Dépenses
# ---------------------------------------------------------------------------
def _validate_expense(amount: float, category: str, refund: bool) -> None:
    if not category or not str(category).strip():
        raise ValueError("La catégorie est obligatoire.")
    if amount is None or amount != amount:
        raise ValueError("Le montant est obligatoire.")
    if amount == 0:
        raise ValueError("Le montant ne peut pas être nul.")
    if amount < 0 and not refund:
        raise ValueError("Un montant négatif n'est accepté que pour un remboursement.")
    if amount > 0 and refund:
        raise ValueError("Un remboursement doit avoir un montant négatif.")


def expense_exists(date_: str, amount: float, category: str, description: str | None = None) -> bool:
    """Détection de doublon : même jour, même montant, même catégorie
    (et même description si `description` est fourni)."""
    query = "SELECT 1 FROM expenses WHERE date = ? AND ABS(amount - ?) < 0.01 AND category = ?"
    params: list = [str(date_), float(amount), category]
    if description is not None:
        query += " AND COALESCE(description, '') = ?"
        params.append(description)
    with get_connection() as conn:
        row = conn.execute(query + " LIMIT 1", params).fetchone()
    return row is not None


def add_expense(date_: str, amount: float, category: str, subcategory: str = "",
                payment_method: str = "Espèces", description: str = "",
                necessary: bool = True, recurring: bool = False, refund: bool = False) -> int:
    _validate_expense(amount, category, refund)
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO expenses (date, amount, category, subcategory, payment_method,
                                    description, necessary, recurring, refund)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(date_), float(amount), category, subcategory or "", payment_method,
             description or "", int(necessary), int(recurring), int(refund)),
        )
        return cur.lastrowid


def bulk_insert_expenses(rows: list[dict]) -> int:
    """Insertion en lot (import CSV/Excel). Chaque dict a les clés de add_expense."""
    inserted = 0
    with get_connection() as conn:
        for r in rows:
            _validate_expense(r["amount"], r["category"], bool(r.get("refund", False)))
            conn.execute(
                """INSERT INTO expenses (date, amount, category, subcategory, payment_method,
                                        description, necessary, recurring, refund)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(r["date"]), float(r["amount"]), r["category"], r.get("subcategory", "") or "",
                 r.get("payment_method", "Espèces") or "Espèces", r.get("description", "") or "",
                 int(r.get("necessary", True)), int(r.get("recurring", False)), int(r.get("refund", False))),
            )
            inserted += 1
    return inserted


def update_expense(expense_id: int, **fields) -> None:
    allowed = {"date", "amount", "category", "subcategory", "payment_method",
               "description", "necessary", "recurring", "refund"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    if "amount" in fields:
        _validate_expense(fields["amount"], fields.get("category", "x"), bool(fields.get("refund", False)))
    for key in ("necessary", "recurring", "refund"):
        if key in fields:
            fields[key] = int(bool(fields[key]))
    if "date" in fields:
        fields["date"] = str(fields["date"])
    sets = ", ".join(f"{k} = ?" for k in fields)
    with get_connection() as conn:
        conn.execute(f"UPDATE expenses SET {sets} WHERE id = ?", (*fields.values(), expense_id))


def delete_expense(expense_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))


def get_expenses(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Toutes les dépenses (ou entre deux dates AAAA-MM-JJ incluses), typées et enrichies."""
    query = "SELECT * FROM expenses"
    params: list = []
    if start and end:
        query += " WHERE date BETWEEN ? AND ?"
        params = [str(start), str(end)]
    query += " ORDER BY date DESC, id DESC"
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=params)
    return enrich_expenses(df)


def enrich_expenses(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les colonnes dérivées utilisées partout : month, weekday, day, flags booléens."""
    if df.empty:
        cols = EXPENSE_COLUMNS + ["month", "weekday", "weekday_name", "day"]
        return pd.DataFrame(columns=cols)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    for col in ("necessary", "recurring", "refund"):
        if col not in df:
            df[col] = 0
        df[col] = df[col].fillna(0).astype(int).astype(bool)
    df["subcategory"] = df["subcategory"].fillna("")
    df["description"] = df["description"].fillna("")
    df["month"] = df["date"].dt.strftime("%Y-%m")
    df["weekday"] = df["date"].dt.weekday
    from utils.helpers import WEEKDAYS_FR
    df["weekday_name"] = df["weekday"].map(lambda i: WEEKDAYS_FR[i])
    df["day"] = df["date"].dt.day
    return df


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
def set_budget(month: str, category: str, amount: float) -> None:
    if amount < 0:
        raise ValueError("Un budget ne peut pas être négatif.")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO budgets (month, category, amount) VALUES (?, ?, ?) "
            "ON CONFLICT(month, category) DO UPDATE SET amount = excluded.amount",
            (month, category, float(amount)),
        )


def get_budgets(month: str | None = None) -> pd.DataFrame:
    with get_connection() as conn:
        if month:
            df = pd.read_sql_query("SELECT * FROM budgets WHERE month = ?", conn, params=[month])
        else:
            df = pd.read_sql_query("SELECT * FROM budgets ORDER BY month", conn)
    if df.empty:
        return pd.DataFrame(columns=["id", "month", "category", "amount"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df


def get_budget_months() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT DISTINCT month FROM budgets ORDER BY month").fetchall()
    return [r["month"] for r in rows]


def copy_budgets(from_month: str, to_month: str) -> int:
    """Copie les budgets d'un mois vers un autre (sans écraser ceux déjà définis)."""
    src = get_budgets(from_month)
    existing = set(get_budgets(to_month)["category"])
    n = 0
    for _, r in src.iterrows():
        if r["category"] not in existing:
            set_budget(to_month, r["category"], r["amount"])
            n += 1
    return n


def ensure_budgets_for_month(month: str) -> None:
    """Si aucun budget n'existe pour ce mois, reprend ceux du dernier mois budgété."""
    if not get_budgets(month).empty:
        return
    months = [m for m in get_budget_months() if m < month]
    if months:
        copy_budgets(months[-1], month)


# ---------------------------------------------------------------------------
# Objectifs
# ---------------------------------------------------------------------------
def get_goals() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM goals ORDER BY is_main DESC, id", conn)
    if df.empty:
        return pd.DataFrame(columns=["id", "name", "target_amount", "current_amount",
                                     "target_date", "is_main", "created_at"])
    df["target_amount"] = pd.to_numeric(df["target_amount"], errors="coerce").fillna(0.0)
    df["current_amount"] = pd.to_numeric(df["current_amount"], errors="coerce").fillna(0.0)
    df["target_date"] = pd.to_datetime(df["target_date"], errors="coerce")
    return df


def add_goal(name: str, target_amount: float, current_amount: float = 0.0,
             target_date: str | None = None, is_main: bool = False) -> int:
    if target_amount <= 0:
        raise ValueError("Le montant cible doit être positif.")
    with get_connection() as conn:
        if is_main:
            conn.execute("UPDATE goals SET is_main = 0")
        cur = conn.execute(
            "INSERT INTO goals (name, target_amount, current_amount, target_date, is_main) VALUES (?, ?, ?, ?, ?)",
            (name.strip(), float(target_amount), float(current_amount),
             str(target_date) if target_date else None, int(is_main)),
        )
        return cur.lastrowid


def update_goal(goal_id: int, name: str, target_amount: float, current_amount: float,
                target_date: str | None, is_main: bool) -> None:
    with get_connection() as conn:
        if is_main:
            conn.execute("UPDATE goals SET is_main = 0")
        conn.execute(
            "UPDATE goals SET name = ?, target_amount = ?, current_amount = ?, target_date = ?, is_main = ? WHERE id = ?",
            (name.strip(), float(target_amount), float(current_amount),
             str(target_date) if target_date else None, int(is_main), goal_id),
        )


def delete_goal(goal_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))


# ---------------------------------------------------------------------------
# Vue d'ensemble
# ---------------------------------------------------------------------------
def available_months() -> list[str]:
    """Mois pour lesquels il existe au moins une dépense, un revenu ou un budget."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT substr(date, 1, 7) AS m FROM expenses "
            "UNION SELECT DISTINCT substr(date, 1, 7) FROM incomes "
            "UNION SELECT DISTINCT month FROM budgets ORDER BY m"
        ).fetchall()
    return [r[0] for r in rows if r[0]]
