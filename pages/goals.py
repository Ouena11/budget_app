"""Page Objectifs : création, suivi et projection des objectifs financiers."""
from __future__ import annotations

from datetime import date

import streamlit as st

from analytics.recommendations import build_context
from database import db
from database.models import GOAL_TYPES
from utils import charts, ui
from utils.helpers import fmt_money, fmt_pct, safe_div


def _months_until(target) -> int | None:
    if target is None or target != target:
        return None
    t = target.date() if hasattr(target, "date") else target
    today = date.today()
    return max((t.year - today.year) * 12 + (t.month - today.month), 0)


def render(month: str) -> None:
    st.title("🎯 Objectifs financiers")
    ctx = build_context(month)
    goals = db.get_goals()
    monthly = ctx["monthly"]
    avg_savings = float(monthly["savings"].tail(3).mean()) if not monthly.empty else 0.0

    if goals.empty:
        ui.empty_state("Aucun objectif. Créez-en un ci-dessous : épargne de sécurité, voyage, achat…")
    for _, g in goals.iterrows():
        pct = safe_div(g["current_amount"], g["target_amount"]) * 100
        remaining = max(g["target_amount"] - g["current_amount"], 0)
        n_months = _months_until(g["target_date"])
        recommended = safe_div(remaining, n_months) if n_months else None
        est_months = safe_div(remaining, avg_savings) if avg_savings > 0 and remaining > 0 else None
        with st.container(border=True):
            head = f"{'⭐ ' if g['is_main'] else ''}{g['name']}"
            st.markdown(f"#### {head}")
            st.plotly_chart(charts.goal_progress_chart(g["name"], g["current_amount"], g["target_amount"]),
                            width="stretch", config={"displayModeBar": False})
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Cible", fmt_money(g["target_amount"]))
            c2.metric("Actuel", fmt_money(g["current_amount"]), fmt_pct(pct))
            c3.metric("Restant", fmt_money(remaining))
            if recommended is not None and n_months:
                c4.metric("Mensualité recommandée", fmt_money(recommended), f"{n_months} mois restants")
            elif n_months == 0 and remaining > 0:
                c4.metric("Mensualité recommandée", "—", "échéance dépassée")
            else:
                c4.metric("Mensualité recommandée", "—", "pas de date cible")
            if est_months is not None:
                c5.metric("Durée estimée", f"{est_months:.0f} mois", f"à {fmt_money(avg_savings)}/mois")
            elif remaining == 0:
                c5.metric("Durée estimée", "Atteint ✅")
            else:
                c5.metric("Durée estimée", "—", "épargne récente nulle")
            if recommended and avg_savings > 0 and recommended > avg_savings:
                st.warning(f"La mensualité nécessaire ({fmt_money(recommended)}) dépasse votre épargne moyenne récente "
                           f"({fmt_money(avg_savings)}). Soit repousser l'échéance, soit dégager "
                           f"{fmt_money(recommended - avg_savings)} de plus par mois.")

            with st.expander("Modifier / mettre à jour"):
                with st.form(f"goal_edit_{g['id']}"):
                    c1, c2 = st.columns(2)
                    name = c1.text_input("Nom", g["name"])
                    target_amount = c2.number_input("Montant cible", min_value=1.0, value=float(g["target_amount"]), step=10000.0, format="%.0f")
                    c1, c2, c3 = st.columns(3)
                    current = c1.number_input("Montant actuel", min_value=0.0, value=float(g["current_amount"]), step=5000.0, format="%.0f")
                    has_date = g["target_date"] == g["target_date"] and g["target_date"] is not None
                    tdate = c2.date_input("Date cible", value=g["target_date"].date() if has_date else date.today(),
                                          min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))
                    no_date = c3.checkbox("Sans date cible", value=not has_date)
                    is_main = st.checkbox("Objectif principal", value=bool(g["is_main"]))
                    if st.form_submit_button("💾 Enregistrer"):
                        db.update_goal(int(g["id"]), name, target_amount, current, None if no_date else tdate, is_main)
                        ui.flash("Objectif mis à jour.")
                        st.rerun()
                if ui.confirm_delete(f"goal_{g['id']}", "Supprimer cet objectif"):
                    db.delete_goal(int(g["id"]))
                    st.rerun()

    st.divider()
    st.subheader("Créer un objectif")
    with st.form("goal_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        kind = c1.selectbox("Type", GOAL_TYPES)
        custom = c2.text_input("Nom personnalisé (facultatif)")
        c1, c2, c3 = st.columns(3)
        target_amount = c1.number_input("Montant cible (FCFA)", min_value=0.0, step=50000.0, format="%.0f")
        current = c2.number_input("Montant déjà disponible", min_value=0.0, step=5000.0, format="%.0f")
        tdate = c3.date_input("Date cible", value=date.today().replace(year=date.today().year + 1),
                              min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))
        c1, c2 = st.columns(2)
        no_date = c1.checkbox("Sans date cible")
        is_main = c2.checkbox("Définir comme objectif principal", value=goals.empty)
        if st.form_submit_button("➕ Créer", type="primary"):
            if target_amount <= 0:
                st.error("Le montant cible doit être supérieur à zéro.")
            else:
                db.add_goal(custom.strip() or kind, target_amount, current, None if no_date else tdate, is_main)
                if is_main:
                    db.set_setting("main_goal", custom.strip() or kind)
                ui.flash("Objectif créé.")
                st.rerun()
