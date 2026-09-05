"""Page Calendrier : vue mensuelle jour par jour (montant, nombre d'opérations, catégorie dominante)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics import calculations as calc
from analytics.anomaly_detection import unusual_daily_totals
from database import db
from utils import charts, ui
from utils.helpers import WEEKDAYS_FR, fmt_money, month_bounds, month_label


def render(month: str) -> None:
    st.title(f"📅 Calendrier — {month_label(month)}")
    expenses = db.get_expenses()
    em = calc.split_consumption(calc.month_slice(expenses, month))[0]
    if em.empty:
        ui.empty_state("Aucune dépense ce mois-ci.")
        return
    first, last = month_bounds(month)
    # Toute la grille du mois (même les jours futurs, à zéro) pour un calendrier complet
    daily = calc.daily_series(em, month, today=last)
    dominant = em.groupby([em["date"].dt.normalize(), "category"])["amount"].sum().reset_index()
    dominant = dominant.sort_values("amount", ascending=False).drop_duplicates("date").set_index("date")["category"]
    daily["dominant"] = daily["date"].map(dominant).fillna("")

    budget = db.get_budgets(month)
    budget_cons = float(budget.loc[budget["category"] != "Finance", "amount"].sum()) if not budget.empty else 0.0
    daily_budget = budget_cons / len(daily) if budget_cons else None

    st.plotly_chart(charts.calendar_heatmap(daily, month_label(month)), width="stretch")

    active = daily[daily["amount"] > 0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Jours avec dépense", f"{len(active)} / {len(daily)}")
    c2.metric("Jour le plus cher", fmt_money(active["amount"].max()) if len(active) else "—",
              f"{active.loc[active['amount'].idxmax(), 'date']:%d/%m}" if len(active) else None)
    c3.metric("Médiane des jours actifs", fmt_money(active["amount"].median()) if len(active) else "—")
    c4.metric("Rythme budget / jour", fmt_money(daily_budget) if daily_budget else "—")

    unusual = unusual_daily_totals(daily)
    if not unusual.empty:
        st.warning("Jours nettement au-dessus de l'habitude (> 2,5 × la médiane des jours actifs) : " +
                   " · ".join(f"{r['date']:%d/%m} ({fmt_money(r['amount'])})" for _, r in unusual.iterrows()))

    st.subheader("Détail par jour")
    show = daily[daily["amount"] != 0].copy()
    show["Jour"] = show["date"].dt.weekday.map(lambda i: WEEKDAYS_FR[i])
    show["date"] = show["date"].dt.date
    show["niveau"] = show["amount"].apply(
        lambda v: "🔴" if daily_budget and v > 2 * daily_budget else "🟡" if daily_budget and v > daily_budget else "🟢")
    st.dataframe(
        ui.money_table(show[["date", "Jour", "amount", "count", "dominant", "niveau"]].rename(
            columns={"date": "Date", "amount": "Montant", "count": "Opérations", "dominant": "Catégorie dominante", "niveau": ""}),
            ["Montant"]),
        hide_index=True, width="stretch",
        column_config={"Date": st.column_config.DateColumn(format="DD/MM/YYYY")},
    )
    selected = st.date_input("Voir les opérations d'un jour", value=None, min_value=first, max_value=last, key="cal_day")
    if selected:
        day = em[em["date"].dt.date == selected].sort_values("amount", ascending=False)
        if day.empty:
            st.caption("Aucune dépense ce jour-là.")
        else:
            st.dataframe(ui.money_table(day[["amount", "category", "subcategory", "payment_method", "description"]].rename(
                columns={"amount": "Montant", "category": "Catégorie", "subcategory": "Sous-catégorie",
                         "payment_method": "Paiement", "description": "Description"}), ["Montant"]),
                hide_index=True, width="stretch")
