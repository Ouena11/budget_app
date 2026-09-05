"""Page Dashboard : situation financière du mois en moins de 30 secondes."""
from __future__ import annotations

import streamlit as st

from analytics import calculations as calc
from analytics.recommendations import build_context, generate_alerts, generate_recommendations
from utils import charts, ui
from utils.helpers import fmt_money, fmt_pct, month_label


def render(month: str) -> None:
    ctx = build_context(month)
    k, fc, score = ctx["kpis"], ctx["forecast"], ctx["score"]

    st.title(f"🏠 Tableau de bord — {month_label(month)}")
    if k["income_is_reference"]:
        st.caption("Aucun revenu saisi pour ce mois : le revenu de référence du profil est utilisé.")

    # ---- Ligne 1 : KPI essentiels ------------------------------------------------
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        ui.kpi_card("Revenu", fmt_money(k["income"]),
                    "référence" if k["income_is_reference"] else "saisi", "info")
    with c2:
        ui.kpi_card("Dépenses", fmt_money(k["spent"]),
                    f"{k['n_expenses']} opérations", "warning" if fc["over_budget"] else None)
    with c3:
        lvl = "ok" if k["savings"] >= k["savings_goal"] else "warning" if k["savings"] > 0 else "danger"
        ui.kpi_card("Épargne", fmt_money(k["savings"]),
                    f"objectif {fmt_money(k['savings_goal'])}" if k["savings_goal"] else "revenu − dépenses", lvl)
    with c4:
        lvl = "ok" if k["budget_remaining"] > 0.2 * max(k["budget_consumption"], 1) else "warning" if k["budget_remaining"] > 0 else "danger"
        ui.kpi_card("Budget restant", fmt_money(k["budget_remaining"]),
                    f"sur {fmt_money(k['budget_consumption'])}" if k["budget_consumption"] else "aucun budget", lvl)
    with c5:
        lvl = "ok" if k["savings_rate"] >= 20 else "warning" if k["savings_rate"] >= 10 else "danger"
        ui.kpi_card("Taux d'épargne", fmt_pct(k["savings_rate"]), "cible indicative 20 %", lvl)
    with c6:
        ui.kpi_card("Score financier", f"{score['score']} / 100", score["label"], score["level"])

    # ---- Ligne 2 : KPI secondaires -----------------------------------------------
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        ui.kpi_card("Budget total", fmt_money(k["budget_total"]),
                    f"dont épargne {fmt_money(k['budget_total'] - k['budget_consumption'])}" if k["budget_total"] != k["budget_consumption"] else None)
    with c2:
        lvl = "danger" if k["budget_usage"] > 100 else "warning" if k["budget_usage"] > k["month_progress"] + 10 else "ok"
        ui.kpi_card("Budget consommé", fmt_pct(k["budget_usage"]), f"mois écoulé à {k['month_progress']:.0f} %", lvl)
    with c3:
        ui.kpi_card("Dépense moyenne / jour", fmt_money(k["avg_daily"]), f"sur {k['days_elapsed']} jours")
    with c4:
        lvl = "danger" if fc["over_budget"] and fc["gap"] > 0.1 * max(k["budget_consumption"], 1) else "warning" if fc["over_budget"] else "ok"
        ui.kpi_card("Prévision fin de mois", fmt_money(fc["projected"]),
                    f"{fmt_money(fc['projected_low'])} – {fmt_money(fc['projected_high'])}", lvl)
    with c5:
        ui.kpi_card("Épargne mise de côté", fmt_money(k["savings_transfers"]), "virements Finance > Épargne")
    with c6:
        vs = k["vs_prev_pct"]
        ui.kpi_card("vs mois précédent", fmt_pct(vs, signed=True) if vs == vs else "—",
                    f"préc. {fmt_money(k['prev_spent'])}" + (f" au {k['days_elapsed']}" if k["prev_is_partial"] else ""),
                    "warning" if vs == vs and vs > 15 else None)

    if fc["days_remaining"] > 0 and k["budget_consumption"] > 0:
        if fc["over_budget"]:
            st.warning(f"⚠️ Dépassement prévisionnel : **+{fmt_money(fc['gap'])}**. Pour tenir le budget, il faudrait "
                       f"limiter les dépenses à **{fmt_money(max(fc['allowed_daily'], 0))} / jour** sur les "
                       f"{fc['days_remaining']} jours restants"
                       + (f" (charges récurrentes encore attendues : {fmt_money(fc['pending_recurring_total'])})." if fc["pending_recurring_total"] else "."))
        else:
            st.success(f"✅ Prévision de fin de mois **{fmt_money(fc['projected'])}** pour un budget de "
                       f"{fmt_money(k['budget_consumption'])} : marge d'environ {fmt_money(-fc['gap'])}.")

    st.divider()

    # ---- Graphiques principaux ---------------------------------------------------
    left, right = st.columns([3, 2])
    with left:
        st.subheader("📈 Évolution des dépenses")
        budget_daily = k["budget_consumption"] / k["days_in_month"] if k["budget_consumption"] else None
        st.plotly_chart(charts.daily_chart(ctx["daily"], budget_daily), width="stretch")
    with right:
        st.subheader("📊 Dépenses par catégorie")
        em = calc.split_consumption(calc.month_slice(ctx["expenses"], month))[0]
        cats = calc.category_totals(em)
        if cats.empty:
            ui.empty_state("Aucune dépense ce mois-ci.")
        else:
            st.plotly_chart(charts.category_bar(cats), width="stretch")

    st.subheader("🎯 Budget vs réel")
    if ctx["bva"].empty:
        ui.empty_state("Définissez des budgets dans ⚙️ Paramètres pour activer cette comparaison.")
    else:
        st.plotly_chart(charts.budget_vs_actual_chart(ctx["bva"]), width="stretch")

    st.divider()
    left, right = st.columns(2)
    with left:
        st.subheader("🚨 Alertes prioritaires")
        alerts = [a for a in generate_alerts(ctx) if a["level"] != "info"][:5]
        for a in alerts:
            ui.alert_box(a)
        if len(alerts) == 5:
            st.caption("Voir toutes les alertes dans la page 🚨 Alertes.")
    with right:
        st.subheader("🤖 Recommandations")
        for r in generate_recommendations(ctx)[:4]:
            ui.alert_box(r)

    with st.expander("Comment est calculé le score ?"):
        st.caption("Le score est un indicateur de lecture, pas un jugement définitif : il combine six volets, "
                   "chacun expliqué ci-dessous.")
        for name, pts, mx, expl in score["components"]:
            st.markdown(f"- **{name}** : {pts} / {mx} — {expl}")
