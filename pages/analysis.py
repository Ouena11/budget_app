"""Page Analyses : réponses aux questions clés, répartition, jour de semaine,
dépenses évitables/récurrentes, anomalies, comparaison de mois, rapport mensuel."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics import calculations as calc
from analytics.recommendations import analysis_insights, build_context, monthly_report
from database import db
from utils import charts
from utils import import_export as ie
from utils import ui
from utils.helpers import fmt_money, fmt_pct, month_label, previous_month


def _insights(ctx: dict) -> None:
    st.subheader("🧠 Ce que disent vos données")
    for question, answer in analysis_insights(ctx):
        with st.container():
            st.markdown(f"**{question}**  \n{answer}")


def _breakdown(ctx: dict, month: str) -> None:
    em = calc.split_consumption(calc.month_slice(ctx["expenses"], month))[0]
    cats = calc.category_totals(em)
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Répartition des dépenses")
        if cats.empty:
            ui.empty_state("Aucune dépense ce mois-ci.")
        else:
            st.plotly_chart(charts.donut_chart(cats), width="stretch")
    with right:
        st.subheader("Détail par sous-catégorie")
        subs = calc.subcategory_totals(em)
        if subs.empty:
            ui.empty_state("Aucune dépense ce mois-ci.")
        else:
            subs = subs.copy()
            subs["part"] = subs["amount"] / subs["amount"].sum() * 100
            st.dataframe(
                ui.money_table(subs.rename(columns={"category": "Catégorie", "subcategory": "Sous-catégorie",
                                                    "amount": "Montant", "part": "Part"}), ["Montant"]),
                hide_index=True, width="stretch", height=360,
                column_config={"Part": st.column_config.ProgressColumn(format="%.0f %%", min_value=0, max_value=100)},
            )


def _weekday(ctx: dict) -> None:
    st.subheader("📆 Analyse par jour de la semaine")
    wd = ctx["weekday"]
    if wd.empty or wd["total"].sum() == 0:
        ui.empty_state("Pas assez de données.")
        return
    left, right = st.columns([2, 1])
    with left:
        st.plotly_chart(charts.weekday_chart(wd), width="stretch")
    with right:
        top = wd.sort_values("avg_per_day", ascending=False).iloc[0]
        low = wd.sort_values("avg_per_day").iloc[0]
        st.markdown(f"Jour le plus dépensier : **{top['weekday_name']}** — {fmt_money(top['avg_per_day'])} en moyenne, "
                    f"soit **{fmt_pct(top['vs_others_pct'], signed=True)}** par rapport aux autres jours.")
        st.markdown(f"Jour le plus calme : **{low['weekday_name']}** — {fmt_money(low['avg_per_day'])}.")
        st.caption(f"Calcul sur {int(wd['n_days'].sum())} jours d'historique (jours sans dépense inclus, comptés à zéro).")
        st.dataframe(ui.money_table(wd[["weekday_name", "avg_per_day", "n_tx"]].rename(
            columns={"weekday_name": "Jour", "avg_per_day": "Moyenne / jour", "n_tx": "Opérations"}), ["Moyenne / jour"]),
            hide_index=True, width="stretch")


def _avoidable_recurring(ctx: dict, month: str) -> None:
    left, right = st.columns(2)
    with left:
        st.subheader("✂️ Dépenses évitables")
        av = calc.avoidable_expenses(calc.month_slice(ctx["expenses"], month), ctx["essential"])
        if av.empty:
            ui.empty_state("Aucune dépense évitable identifiée ce mois-ci.")
        else:
            total = av["amount"].sum()
            st.markdown(f"**{fmt_money(total)}** ce mois-ci, soit {fmt_pct(calc.safe_div(total, ctx['kpis']['spent']) * 100)} "
                        f"des dépenses. Critères : déclarée non nécessaire, catégorie non essentielle, ou sous-catégorie "
                        f"de confort (restaurant, livraison, snacks, taxi, sorties, cadeaux, abonnements).")
            g = av.groupby(["category", "subcategory"])["amount"].agg(["sum", "count"]).reset_index()
            g.columns = ["Catégorie", "Sous-catégorie", "Montant", "Nombre"]
            st.dataframe(ui.money_table(g.sort_values("Montant", ascending=False), ["Montant"]),
                         hide_index=True, width="stretch")
    with right:
        st.subheader("🔁 Charges récurrentes")
        rec = calc.recurring_summary(ctx["expenses"])
        if rec.empty:
            ui.empty_state("Aucune dépense marquée comme récurrente.")
        else:
            st.markdown(f"**{fmt_money(rec['avg_monthly'].sum())}** par mois en moyenne, "
                        f"soit {fmt_pct(calc.safe_div(rec['avg_monthly'].sum(), ctx['kpis']['income']) * 100)} du revenu.")
            st.dataframe(ui.money_table(rec.rename(columns={"category": "Catégorie", "subcategory": "Sous-catégorie",
                                                            "avg_monthly": "Moyenne / mois", "n_months": "Mois observés"}),
                                        ["Moyenne / mois"]),
                         hide_index=True, width="stretch")


def _anomalies(ctx: dict) -> None:
    st.subheader("🔎 Dépenses inhabituelles")
    an = ctx["anomalies"]
    if an.empty:
        st.success("Aucune dépense inhabituelle détectée ce mois-ci.")
        return
    st.caption("Une dépense est signalée quand au moins deux méthodes la retiennent (ratio à la médiane, z-score "
               "robuste, IQR) ou quand elle dépasse 25 % du revenu mensuel. Seuil du ratio réglable dans Paramètres.")
    for _, a in an.iterrows():
        ui.alert_box({"level": a["severity"], "title": f"{a['category']}{' › ' + a['subcategory'] if a['subcategory'] else ''}",
                      "message": f"{a['message']} <span class='small-muted'>Méthodes : {a['methods']}.</span>"})


def _compare(ctx: dict, month: str) -> None:
    st.subheader("↔️ Comparaison entre mois")
    months = db.available_months()
    if len(months) < 2:
        ui.empty_state("Il faut au moins deux mois de données.")
        return
    default = [m for m in (previous_month(month), month) if m in months] or months[-2:]
    chosen = st.multiselect("Mois à comparer (le premier et le dernier servent au calcul de la variation)",
                            months, default=default, format_func=month_label, key="compare_months")
    if len(chosen) < 2:
        st.caption("Sélectionnez au moins deux mois.")
        return
    chosen = sorted(chosen)
    table = calc.compare_months(ctx["expenses"], chosen)
    if table.empty:
        ui.empty_state("Aucune dépense sur ces mois.")
        return
    shown = table.rename(columns={m: month_label(m) for m in chosen})

    def highlight(row):
        v = row.get("Variation %")
        if v != v or row.name == "TOTAL":
            return ["font-weight: bold" if row.name == "TOTAL" else ""] * len(row)
        color = "background-color: #fdecea" if v >= 20 else "background-color: #edf7ee" if v <= -20 else ""
        return [color] * len(row)

    fmt = {c: "{:,.0f}".format for c in shown.columns if c not in ("Variation %",)}
    fmt["Variation %"] = lambda v: "—" if v != v else f"{v:+.1f} %"
    st.dataframe(shown.style.apply(highlight, axis=1).format(fmt, thousands=" "), width="stretch")
    big = table.drop(index="TOTAL", errors="ignore")
    big = big[(big["Variation %"].abs() >= 20) & (big["Variation"].abs() >= 5000)] if "Variation %" in big else big.iloc[0:0]
    if not big.empty:
        st.markdown("**Variations importantes :** " + " · ".join(
            f"{cat} {fmt_pct(r['Variation %'], 1, signed=True)} ({fmt_money(r['Variation'])})" for cat, r in big.iterrows()))


def _report(ctx: dict, month: str) -> None:
    st.subheader("📄 Rapport mensuel")
    rep = monthly_report(ctx)
    k = rep["kpis"]
    if k["days_remaining"] > 0:
        st.caption(f"Le mois n'est pas terminé ({k['days_elapsed']} jours sur {k['days_in_month']}) : "
                   "le rapport est provisoire et sera complet en fin de mois.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Revenus", fmt_money(k["income"]))
    c2.metric("Dépenses", fmt_money(k["spent"]))
    c3.metric("Épargne", fmt_money(k["savings"]))
    c4.metric("Taux d'épargne", fmt_pct(k["savings_rate"]))
    left, right = st.columns(2)
    with left:
        st.markdown("**Catégories les plus coûteuses**")
        for _, r in rep["top_categories"].iterrows():
            st.markdown(f"- {r['category']} : {fmt_money(r['amount'])} ({r['share']:.0f} %)")
        st.markdown("**Dépassements**")
        if rep["overruns"].empty:
            st.markdown("- Aucun dépassement de budget.")
        for _, r in rep["overruns"].iterrows():
            st.markdown(f"- {r['category']} : +{fmt_money(r['spent'] - r['budget'])} ({r['ratio'] * 100:.0f} % du budget)")
    with right:
        st.markdown("**En hausse vs mois précédent**")
        if rep["increased"].empty:
            st.markdown("- Rien à signaler.")
        for _, r in rep["increased"].iterrows():
            pct = f" ({fmt_pct(r['delta_pct'], signed=True)})" if r["delta_pct"] == r["delta_pct"] else ""
            st.markdown(f"- {r['category']} : +{fmt_money(r['delta'])}{pct}")
        st.markdown("**En baisse**")
        if rep["decreased"].empty:
            st.markdown("- Rien à signaler.")
        for _, r in rep["decreased"].iterrows():
            pct = f" ({fmt_pct(r['delta_pct'], signed=True)})" if r["delta_pct"] == r["delta_pct"] else ""
            st.markdown(f"- {r['category']} : {fmt_money(r['delta'])}{pct}")
    st.markdown("**Alertes du mois**")
    if not rep["alerts"]:
        st.markdown("- Aucune alerte majeure.")
    for a in rep["alerts"]:
        st.markdown(f"- {ui.level_badge(a['level'])} {a['title']} — {a['message']}")
    st.markdown("**Recommandations pour le mois suivant**")
    for i, action in enumerate(rep["next_actions"], 1):
        st.markdown(f"{i}. {action}")

    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Rapport PDF", ie.report_to_pdf_bytes(rep), f"rapport_{month}.pdf", "application/pdf")
    analyses = {
        "Résumé": pd.DataFrame([{"Indicateur": key, "Valeur": val} for key, val in k.items()
                                if not isinstance(val, (dict, list))]),
        "Budget vs réel": ctx["bva"],
        "Par catégorie": rep["top_categories"],
        "Anomalies": ctx["anomalies"].drop(columns=["message"], errors="ignore"),
        "Score": pd.DataFrame(rep["score"]["components"], columns=["Composante", "Points", "Max", "Explication"]),
    }
    c2.download_button("⬇️ Analyses Excel", ie.to_excel_bytes(analyses), f"analyses_{month}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def render(month: str) -> None:
    st.title(f"📊 Analyses — {month_label(month)}")
    ctx = build_context(month)
    tabs = st.tabs(["Synthèse", "Répartition", "Jour de semaine", "Évitables / récurrentes",
                    "Anomalies", "Comparer des mois", "Rapport mensuel"])
    with tabs[0]:
        _insights(ctx)
    with tabs[1]:
        _breakdown(ctx, month)
    with tabs[2]:
        _weekday(ctx)
    with tabs[3]:
        _avoidable_recurring(ctx, month)
    with tabs[4]:
        _anomalies(ctx)
    with tabs[5]:
        _compare(ctx, month)
    with tabs[6]:
        _report(ctx, month)
