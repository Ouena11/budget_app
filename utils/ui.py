"""
Composants d'interface Streamlit partagés : cartes KPI, encadrés d'alerte, sélecteur
de mois, CSS. Tout ce qui touche à Streamlit est ici ou dans pages/, jamais dans
analytics/ ou database/ (ce qui permettra de réutiliser le moteur dans une appli web).
"""
from __future__ import annotations

from datetime import date

import streamlit as st

from database import db
from utils.helpers import LEVEL_COLORS, LEVEL_ICONS, month_key, month_label, month_range, previous_month

CSS = """
<style>
.block-container { padding-top: 1.2rem; }
.kpi-card {
    border: 1px solid #e3e8ee; border-radius: 12px; padding: 14px 16px; background: #ffffff;
    box-shadow: 0 1px 3px rgba(16, 24, 40, 0.06); margin-bottom: 8px; min-height: 96px;
}
.kpi-label { font-size: 0.78rem; color: #5f6b7a; text-transform: uppercase; letter-spacing: .04em; }
.kpi-value { font-size: 1.25rem; font-weight: 700; color: #1b2733; margin-top: 2px; white-space: nowrap; }
.kpi-sub { font-size: 0.8rem; color: #6b7785; margin-top: 2px; }
.kpi-ok { border-left: 5px solid #2e7d32; }
.kpi-warning { border-left: 5px solid #f9a825; }
.kpi-danger { border-left: 5px solid #c62828; }
.kpi-info { border-left: 5px solid #1565c0; }
.alert-box {
    border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; border: 1px solid;
}
.alert-title { font-weight: 700; margin-bottom: 3px; }
.alert-msg { font-size: 0.93rem; line-height: 1.4; }
.alert-action { font-size: 0.93rem; margin-top: 6px; padding-top: 6px; border-top: 1px dashed rgba(0,0,0,.15); }
.alert-ok { background: #edf7ee; border-color: #a5d6a7; }
.alert-warning { background: #fff8e1; border-color: #ffe082; }
.alert-danger { background: #fdecea; border-color: #ef9a9a; }
.alert-info { background: #e8f1fb; border-color: #90caf9; }
.small-muted { color: #6b7785; font-size: 0.85rem; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def kpi_card(label: str, value: str, sub: str | None = None, level: str | None = None) -> None:
    cls = f"kpi-card kpi-{level}" if level else "kpi-card"
    sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    st.markdown(
        f'<div class="{cls}"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>{sub_html}</div>',
        unsafe_allow_html=True,
    )


def alert_box(item: dict, show_action: bool = True) -> None:
    level = item.get("level", "info")
    icon = LEVEL_ICONS.get(level, "")
    action = item.get("action")
    action_html = f'<div class="alert-action">💡 {action}</div>' if (show_action and action) else ""
    st.markdown(
        f'<div class="alert-box alert-{level}"><div class="alert-title">{icon} {item["title"]}</div>'
        f'<div class="alert-msg">{item["message"]}</div>{action_html}</div>',
        unsafe_allow_html=True,
    )


def level_badge(level: str) -> str:
    return f"{LEVEL_ICONS.get(level, '')}"


def month_selector(label: str = "Mois", key: str = "month") -> str:
    """Sélecteur de mois dans la barre latérale (mémorisé en session)."""
    months = db.available_months()
    current = month_key(date.today())
    if not months:
        months = [current]
    start = min(months[0], previous_month(current, 3))
    end = max(months[-1], current)
    options = month_range(start, end)[::-1]
    default = st.session_state.get(key, current)
    if default not in options:
        default = current if current in options else options[0]
    choice = st.sidebar.selectbox(label, options, index=options.index(default), format_func=month_label, key=f"{key}_select")
    st.session_state[key] = choice
    return choice


def current_month() -> str:
    return st.session_state.get("month", month_key(date.today()))


def rerun() -> None:
    st.rerun()


def confirm_delete(key: str, label: str = "Supprimer") -> bool:
    """Suppression en deux temps : premier clic = demande de confirmation, second = confirmation."""
    flag = f"confirm_{key}"
    if st.session_state.get(flag):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Confirmer la suppression", key=f"{key}_yes", type="primary"):
                st.session_state[flag] = False
                return True
        with col2:
            if st.button("Annuler", key=f"{key}_no"):
                st.session_state[flag] = False
                st.rerun()
        return False
    if st.button(f"🗑️ {label}", key=f"{key}_ask"):
        st.session_state[flag] = True
        st.rerun()
    return False


def empty_state(message: str) -> None:
    st.info(message)


def flash(message: str, kind: str = "success") -> None:
    """Mémorise un message à afficher après un st.rerun() (sinon il disparaît aussitôt)."""
    st.session_state["_flash"] = (kind, message)


def show_flash() -> None:
    item = st.session_state.pop("_flash", None)
    if not item:
        return
    kind, message = item
    getattr(st, kind, st.info)(message)


def money_table(df, columns) -> "pd.DataFrame":
    """Copie du tableau avec les colonnes monétaires formatées « 12 500 FCFA » (texte),
    car st.dataframe ne sait pas afficher un séparateur de milliers avec espace."""
    import pandas as pd  # import local pour garder ui léger
    from utils.helpers import fmt_money
    out = df.copy()
    for c in columns:
        if c in out.columns:
            out[c] = out[c].apply(lambda v: fmt_money(v) if pd.notna(v) else "—")
    return out
