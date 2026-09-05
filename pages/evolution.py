"""Page Évolution : dépenses mois par mois, par catégorie, épargne, prévision détaillée."""
from __future__ import annotations

import streamlit as st

from analytics import calculations as calc
from analytics.recommendations import build_context
from utils import charts, ui
from utils.helpers import fmt_money, fmt_pct, month_label


def render(month: str) -> None:
    st.title("📈 Évolution dans le temps")
    ctx = build_context(month)
    monthly, expenses = ctx["monthly"], ctx["expenses"]
    if monthly.empty:
        ui.empty_state("Aucune donnée : commencez par saisir des dépenses ou importer un historique.")
        return

    tabs = st.tabs(["Mensuel", "Par catégorie", "Épargne", "Prévision du mois"])

    with tabs[0]:
        st.plotly_chart(charts.monthly_chart(monthly), width="stretch")
        tr = calc.trend(monthly["consumption"].tail(6))
        if tr["n"] >= 3:
            st.markdown(f"Tendance sur les {tr['n']} derniers mois : **{tr['direction']}** "
                        f"({fmt_money(tr['slope'])} par mois, soit {fmt_pct(tr['pct_per_period'], 1, signed=True)} / mois).")
        pivot = calc.category_monthly(expenses)
        if not pivot.empty:
            st.plotly_chart(charts.stacked_monthly_chart(pivot), width="stretch")
        show = monthly.copy()
        show["month"] = show["month"].map(month_label)
        st.dataframe(
            ui.money_table(show[["month", "income", "consumption", "savings_transfers", "savings", "savings_rate", "n_expenses"]].rename(
                columns={"month": "Mois", "income": "Revenus", "consumption": "Dépenses", "savings_transfers": "Mis de côté",
                         "savings": "Épargne", "savings_rate": "Taux d'épargne", "n_expenses": "Opérations"}),
                ["Revenus", "Dépenses", "Mis de côté", "Épargne"]),
            hide_index=True, width="stretch",
            column_config={"Taux d'épargne": st.column_config.NumberColumn(format="%.0f %%")})

    with tabs[1]:
        pivot = calc.category_monthly(expenses)
        if pivot.empty:
            ui.empty_state("Aucune dépense.")
        else:
            cats = list(pivot.columns)
            chosen = st.selectbox("Catégorie", cats, index=0, key="evo_cat")
            st.plotly_chart(charts.category_trend_chart(pivot, chosen), width="stretch")
            s = pivot[chosen]
            tr = calc.trend(s.tail(6))
            cols = st.columns(4)
            cols[0].metric("Dernier mois", fmt_money(s.iloc[-1]))
            cols[1].metric("Moyenne", fmt_money(s.mean()))
            cols[2].metric("Maximum", fmt_money(s.max()), month_label(s.idxmax()))
            cols[3].metric("Tendance", tr["direction"], fmt_pct(tr["pct_per_period"], 1, signed=True) + " / mois")
            detail = s.reset_index()
            detail.columns = ["Mois", "Montant"]
            detail["Mois"] = detail["Mois"].map(month_label)
            detail["Variation"] = s.pct_change().values * 100
            st.dataframe(ui.money_table(detail, ["Montant"]), hide_index=True, width="stretch",
                         column_config={"Variation": st.column_config.NumberColumn(format="%+.1f %%")})

    with tabs[2]:
        goal = ctx["kpis"]["savings_goal"]
        st.plotly_chart(charts.savings_chart(monthly, goal), width="stretch")
        last = monthly.iloc[-1]
        cols = st.columns(4)
        cols[0].metric("Épargne du mois", fmt_money(last["savings"]))
        cols[1].metric("Épargne cumulée (historique)", fmt_money(last["cumulative_savings"]))
        cols[2].metric("Objectif mensuel", fmt_money(goal) if goal else "—")
        cols[3].metric("Écart à l'objectif", fmt_money(last["savings"] - goal) if goal else "—")
        st.caption("Épargne = revenus − dépenses de consommation. Les virements vers l'épargne (Finance › Épargne) "
                   "ne sont pas des dépenses : ils sont affichés à part (« mis de côté »).")

    with tabs[3]:
        fc, k = ctx["forecast"], ctx["kpis"]
        st.subheader(f"Prévision de fin de mois — {month_label(month)}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Prévision", fmt_money(fc["projected"]), f"{fmt_money(fc['projected_low'])} – {fmt_money(fc['projected_high'])}")
        c2.metric("Budget", fmt_money(k["budget_consumption"]) if k["budget_consumption"] else "—")
        if k["budget_consumption"]:
            c3.metric("Écart prévisionnel", fmt_money(fc["gap"]), "dépassement" if fc["over_budget"] else "marge",
                      delta_color="inverse")
        st.plotly_chart(charts.cumulative_chart(ctx["daily"], k["budget_consumption"], k["days_in_month"]), width="stretch")
        st.markdown("**Comment cette prévision est construite**")
        st.markdown(
            f"- Dépensé à ce jour : {fmt_money(fc['spent'])} sur {fc['days_elapsed']} jours "
            f"(dont {fmt_money(fc['paid_recurring'])} de charges récurrentes déjà payées"
            + (f" et {fmt_money(fc['excluded_anomalies'])} de dépenses inhabituelles, non prolongées" if fc["excluded_anomalies"] else "") + ").\n"
            f"- Rythme variable observé ce mois : {fmt_money(fc['observed_daily'])} / jour ; "
            f"rythme historique (3 mois) : {fmt_money(fc['prior_daily']) if fc['prior_daily'] is not None else '—'} / jour ; "
            f"rythme retenu : **{fmt_money(fc['blended_daily'])} / jour** sur {fc['days_remaining']} jours restants.\n"
            f"- Charges récurrentes encore attendues : {fmt_money(fc['pending_recurring_total'])}.")
        if not fc["pending_recurring"].empty:
            st.dataframe(ui.money_table(fc["pending_recurring"].rename(
                columns={"category": "Catégorie", "subcategory": "Sous-catégorie",
                         "expected_amount": "Montant attendu", "n_months": "Mois observés"}), ["Montant attendu"]),
                         hide_index=True, width="stretch")
        if fc["days_remaining"] > 0 and k["budget_consumption"]:
            st.info(f"Pour finir le mois dans le budget : au plus **{fmt_money(max(fc['allowed_daily'], 0))} / jour** "
                    f"de dépenses variables.")
