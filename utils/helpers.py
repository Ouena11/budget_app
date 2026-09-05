"""
Fonctions utilitaires partagées : formatage des montants, gestion des mois, couleurs.
Aucune dépendance à Streamlit ici : ces fonctions sont réutilisables dans une future
version web ou dans des scripts en ligne de commande.
"""
from __future__ import annotations

import calendar
import unicodedata
from datetime import date, datetime, timedelta

CURRENCY = "FCFA"

MONTHS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]
WEEKDAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# Couleurs des niveaux d'alerte, utilisées dans toute l'interface
LEVEL_COLORS = {"ok": "#2e7d32", "warning": "#f9a825", "danger": "#c62828", "info": "#1565c0"}
LEVEL_ICONS = {"ok": "🟢", "warning": "🟡", "danger": "🔴", "info": "🔵"}


# ---------------------------------------------------------------------------
# Montants
# ---------------------------------------------------------------------------
def fmt_money(value, currency: str = CURRENCY, decimals: int = 0) -> str:
    """Formate un montant avec séparateur de milliers : 125 000 FCFA."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    if value != value:  # NaN
        return "—"
    sign = "-" if value < 0 else ""
    text = f"{abs(value):,.{decimals}f}".replace(",", " ")
    return f"{sign}{text} {currency}".strip()


def fmt_pct(value, decimals: int = 0, signed: bool = False) -> str:
    """Formate un pourcentage. `signed` ajoute le signe + pour les valeurs positives."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    if value != value:
        return "—"
    if signed:
        return f"{value:+.{decimals}f} %"
    return f"{value:.{decimals}f} %"


def safe_div(a, b, default: float = 0.0) -> float:
    """Division protégée contre la division par zéro et les valeurs manquantes."""
    try:
        if b in (0, None) or b != b:
            return default
        return float(a) / float(b)
    except (TypeError, ValueError, ZeroDivisionError):
        return default


# ---------------------------------------------------------------------------
# Mois
# ---------------------------------------------------------------------------
def month_key(d: date | datetime | str) -> str:
    """Retourne la clé 'AAAA-MM' d'une date."""
    if isinstance(d, str):
        return d[:7]
    return d.strftime("%Y-%m")


def month_label(key: str) -> str:
    """'2026-09' -> 'Septembre 2026'."""
    try:
        year, month = key.split("-")
        return f"{MONTHS_FR[int(month) - 1]} {year}"
    except (ValueError, IndexError, AttributeError):
        return str(key)


def month_short(key: str) -> str:
    """'2026-09' -> 'Sept. 26' (pour les axes de graphiques)."""
    try:
        year, month = key.split("-")
        return f"{MONTHS_FR[int(month) - 1][:4]}. {year[2:]}"
    except (ValueError, IndexError, AttributeError):
        return str(key)


def month_bounds(key: str) -> tuple[date, date]:
    """Premier et dernier jour du mois."""
    year, month = int(key[:4]), int(key[5:7])
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def days_in_month(key: str) -> int:
    year, month = int(key[:4]), int(key[5:7])
    return calendar.monthrange(year, month)[1]


def days_elapsed(key: str, today: date | None = None) -> int:
    """Nombre de jours écoulés dans le mois (le jour courant inclus).
    Pour un mois passé : tous les jours. Pour un mois futur : 0."""
    today = today or date.today()
    first, last = month_bounds(key)
    if today < first:
        return 0
    if today > last:
        return days_in_month(key)
    return today.day


def previous_month(key: str, n: int = 1) -> str:
    year, month = int(key[:4]), int(key[5:7])
    for _ in range(n):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return f"{year:04d}-{month:02d}"


def next_month(key: str) -> str:
    year, month = int(key[:4]), int(key[5:7])
    month += 1
    if month == 13:
        month = 1
        year += 1
    return f"{year:04d}-{month:02d}"


def month_range(start_key: str, end_key: str) -> list[str]:
    """Liste des mois entre deux clés incluses."""
    out = []
    k = start_key
    while k <= end_key:
        out.append(k)
        k = next_month(k)
    return out


# ---------------------------------------------------------------------------
# Texte
# ---------------------------------------------------------------------------
def normalize_text(text) -> str:
    """Minuscule, sans accents, sans espaces superflus : utile pour comparer des catégories."""
    if text is None:
        return ""
    text = str(text).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def level_from_ratio(ratio: float, warn: float = 0.8, danger: float = 1.0) -> str:
    """Traduit un taux de consommation de budget en niveau d'alerte."""
    if ratio >= danger:
        return "danger"
    if ratio >= warn:
        return "warning"
    return "ok"


def de_(word: str) -> str:
    """Élision française : de_('alimentation') -> \"d'alimentation\", de_('loisirs') -> 'de loisirs'."""
    w = str(word).strip()
    if not w:
        return "de"
    first = normalize_text(w[0])
    return f"d'{w}" if first and first[0] in "aeiouyh" else f"de {w}"
