"""Page Recommandations : conseils chiffrés, basés sur les données du mois, et plan d'action."""
from __future__ import annotations

import streamlit as st

from analytics.recommendations import build_context, generate_recommendations, monthly_report
from utils import charts, ui
from utils.helpers import fmt_money, month_label


def render(month: str) -> None:
    st.title(f"🤖 Recommandations — {month_label(month)}")
    ctx = build_context(month)
    k, fc, score = ctx["kpis"], ctx["forecast"], ctx["score"]

    left, right = st.columns([1, 2])
    with left:
        st.plotly_chart(charts.score_gauge(score["score"]), width="stretch", config={"displayModeBar": False})
        st.markdown(f"<div style='text-align:center;font-weight:600'>{score['label']}</div>", unsafe_allow_html=True)
    with right:
        st.markdown("**Situation en bref**")
        st.markdown(
            f"- Dépensé {fmt_money(k['spent'])} sur {fmt_money(k['budget_consumption'])} de budget "
            f"({k['budget_usage']:.0f} %), mois écoulé à {k['month_progress']:.0f} %.\n"
            f"- Prévision de fin de mois : {fmt_money(fc['projected'])}"
            + (f", soit un **dépassement de {fmt_money(fc['gap'])}**." if fc["over_budget"] else
               f", soit une marge de {fmt_money(-fc['gap'])}." if k["budget_consumption"] else ".") + "\n"
            f"- Épargne actuelle : {fmt_money(k['savings'])} ({k['savings_rate']:.0f} % du revenu)"
            + (f", objectif {fmt_money(k['savings_goal'])}." if k["savings_goal"] else "."))
        with st.expander("Détail du score"):
            for name, pts, mx, expl in score["components"]:
                st.markdown(f"- **{name}** : {pts} / {mx} — {expl}")

    st.divider()
    st.subheader("Recommandations du moment")
    st.caption("Chaque recommandation est calculée à partir de vos dépenses réelles ; les montants proposés sont "
               "des ordres de grandeur à adapter.")
    recs = generate_recommendations(ctx)
    for r in recs:
        ui.alert_box(r)

    st.divider()
    st.subheader("Plan d'action pour le mois prochain")
    rep = monthly_report(ctx)
    for i, action in enumerate(rep["next_actions"], 1):
        st.markdown(f"{i}. {action}")
    st.caption("Ces actions sont reprises dans le rapport mensuel (page Analyses › Rapport mensuel).")
