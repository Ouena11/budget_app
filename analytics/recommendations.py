"""
Moteur d'alertes, de recommandations et de rapport mensuel.

Tout part d'un « contexte » (build_context) qui rassemble une seule fois les données
et les calculs du mois : KPI, budget vs réel, prévision, anomalies, séries mensuelles.
Les pages Streamlit appellent build_context puis les fonctions de ce module, ce qui
évite de recalculer dix fois la même chose et garantit que le dashboard, la page
Alertes et le rapport disent la même chose.

Chaque alerte / recommandation est un dict :
  {"level": "ok|warning|danger|info", "title": str, "message": str, "action": str|None,
   "category": str|None, "priority": int}
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from analytics import calculations as calc
from analytics.anomaly_detection import detect_anomalies
from analytics.forecasting import forecast_category, forecast_month
from database import db
from utils.helpers import (de_, fmt_money, fmt_pct, month_label, previous_month, safe_div)


# ---------------------------------------------------------------------------
# Contexte
# ---------------------------------------------------------------------------
def build_context(month: str, today: date | None = None) -> dict:
    today = today or date.today()
    settings = db.get_settings()
    expenses = db.get_expenses()
    incomes = db.get_incomes()
    budgets = db.get_budgets(month)
    goals = db.get_goals()
    essential = db.get_essential_categories()

    kpis = calc.month_kpis(expenses, incomes, budgets, settings, month, today)
    try:
        ratio_threshold = float(settings.get("anomaly_ratio", 3.0))
    except (TypeError, ValueError):
        ratio_threshold = 3.0
    anomalies = detect_anomalies(expenses, month, ratio_threshold, kpis["income"])
    anomaly_ids = set(anomalies["id"]) if not anomalies.empty else set()
    bva = calc.budget_vs_actual(calc.split_consumption(calc.month_slice(expenses, month))[0],
                                budgets[budgets["category"] != "Finance"] if not budgets.empty else budgets,
                                month, today, all_expenses=expenses, exclude_ids=anomaly_ids)
    try:
        fallback_income = float(settings.get("monthly_income", 0)) + float(settings.get("extra_income", 0))
    except (TypeError, ValueError):
        fallback_income = 0.0
    monthly = calc.monthly_series(expenses, incomes, fallback_income)
    daily = calc.daily_series(calc.split_consumption(calc.month_slice(expenses, month))[0], month, today)
    forecast = forecast_month(expenses, month, kpis["budget_consumption"], today, anomaly_ids)
    weekday = calc.weekday_analysis(expenses[expenses["month"] <= month] if not expenses.empty else expenses)
    score = calc.financial_score(kpis, bva, monthly, goals, daily, forecast)

    return {
        "month": month, "today": today, "settings": settings, "expenses": expenses,
        "incomes": incomes, "budgets": budgets, "goals": goals, "essential": essential,
        "kpis": kpis, "bva": bva, "monthly": monthly, "daily": daily, "forecast": forecast,
        "anomalies": anomalies, "anomaly_ids": anomaly_ids, "weekday": weekday, "score": score,
    }


def _complete_pivot(ctx: dict) -> pd.DataFrame:
    """Tableau mois x catégorie limité aux mois complets (un mois en cours fausserait les tendances)."""
    pivot = calc.category_monthly(ctx["expenses"])
    if pivot.empty:
        return pivot
    last = ctx["month"] if ctx["kpis"]["days_remaining"] == 0 else previous_month(ctx["month"])
    return pivot[pivot.index <= last]


def _item(level, title, message, action=None, category=None, priority=5) -> dict:
    return {"level": level, "title": title, "message": message, "action": action,
            "category": category, "priority": priority}


# ---------------------------------------------------------------------------
# Alertes
# ---------------------------------------------------------------------------
def generate_alerts(ctx: dict) -> list[dict]:
    k, bva, fc = ctx["kpis"], ctx["bva"], ctx["forecast"]
    month = ctx["month"]
    progress = k["month_progress"]
    alerts: list[dict] = []
    month_done = progress >= 100
    when = "sur le mois complet" if month_done else f"alors que le mois n'est réalisé qu'à {progress:.0f} %"
    try:
        warn_ratio = float(ctx["settings"].get("alert_warn_ratio", 0.8))
    except (TypeError, ValueError):
        warn_ratio = 0.8

    # 1. Catégories : dépassement ou consommation > 80 %
    for _, r in bva.iterrows():
        if r["budget"] <= 0:
            if r["spent"] > 0:
                alerts.append(_item("info", f"{r['category']} : pas de budget défini",
                                    f"Vous avez dépensé {fmt_money(r['spent'])} en {r['category']} sans budget "
                                    f"pour cette catégorie. Définissez-en un pour être alerté.",
                                    category=r["category"], priority=8))
            continue
        ratio = r["ratio"]
        if ratio >= 1.0:
            over = r["spent"] - r["budget"]
            alerts.append(_item(
                "danger", f"Budget {r['category']} dépassé",
                f"Le budget {r['category']} est dépassé de {fmt_money(over)} "
                f"({fmt_money(r['spent'])} dépensés pour {fmt_money(r['budget'])} prévus) {when}.",
                category=r["category"], priority=1))
        elif ratio >= warn_ratio:
            msg = (f"Vous avez {'consommé' if month_done else 'déjà consommé'} {ratio * 100:.0f} % "
                   f"de votre budget {r['category']} {when}.")
            if r["projected_gap"] > 0 and not month_done:
                msg += (f" Si votre rythme actuel continue, vous risquez de dépasser votre budget "
                        f"d'environ {fmt_money(r['projected_gap'])}.")
            alerts.append(_item("warning", f"Attention au budget {r['category']}", msg,
                                category=r["category"], priority=2))
        elif r["projected_gap"] > 0 and ratio >= 0.5 and progress < 90:
            alerts.append(_item(
                "warning", f"Rythme élevé en {r['category']}",
                f"{r['category']} est à {ratio * 100:.0f} % du budget pour {progress:.0f} % du mois. "
                f"À ce rythme, dépassement prévisible d'environ {fmt_money(r['projected_gap'])}.",
                category=r["category"], priority=3))

    # 2. Rythme global vs budget
    if k["budget_consumption"] > 0 and fc["days_remaining"] > 0:
        if fc["over_budget"]:
            alerts.append(_item(
                "danger" if fc["gap"] > 0.1 * k["budget_consumption"] else "warning",
                "Dépassement prévisionnel du budget global",
                f"Prévision de fin de mois : {fmt_money(fc['projected'])} pour un budget de "
                f"{fmt_money(k['budget_consumption'])}, soit un dépassement d'environ {fmt_money(fc['gap'])}. "
                f"Fourchette : {fmt_money(fc['projected_low'])} à {fmt_money(fc['projected_high'])}.",
                priority=1))
        elif k["budget_usage"] > progress + 10:
            alerts.append(_item(
                "warning", "Rythme de dépense supérieur au rythme recommandé",
                f"Budget consommé à {k['budget_usage']:.0f} % pour {progress:.0f} % du mois. "
                f"Le rythme recommandé est d'environ {fmt_money(fc['allowed_daily'])} par jour "
                f"sur les {fc['days_remaining']} jours restants.", priority=3))

    # 3. Dépenses quotidiennes trop élevées (7 derniers jours vs moyenne du mois)
    if fc["days_elapsed"] >= 10 and fc["avg_daily"] > 0 and fc["recent_daily"] > 1.5 * fc["avg_daily"]:
        alerts.append(_item(
            "warning", "Dépenses quotidiennes en forte hausse",
            f"Sur les 7 derniers jours vous dépensez en moyenne {fmt_money(fc['recent_daily'])} par jour, "
            f"contre {fmt_money(fc['avg_daily'])} sur l'ensemble du mois (+{(fc['recent_daily'] / fc['avg_daily'] - 1) * 100:.0f} %).",
            priority=3))

    # 4. Objectif d'épargne mensuel
    if k["savings_goal"] > 0 and k["income"] > 0:
        projected_savings = k["income"] - fc["projected"]
        if projected_savings < k["savings_goal"]:
            gap = k["savings_goal"] - projected_savings
            alerts.append(_item(
                "danger" if projected_savings < 0 else "warning",
                "Objectif d'épargne menacé",
                f"Objectif d'épargne : {fmt_money(k['savings_goal'])}. Avec la prévision actuelle, "
                f"l'épargne de fin de mois serait de {fmt_money(projected_savings)}, soit "
                f"{fmt_money(gap)} de moins que prévu.", priority=2))

    # 5. Anomalies
    for _, a in ctx["anomalies"].head(5).iterrows():
        alerts.append(_item(a["severity"], "Dépense inhabituelle détectée", a["message"],
                            category=a["category"], priority=4))

    # 6. Mois nettement au-dessus des précédents
    monthly = ctx["monthly"]
    hist = monthly[monthly["month"] < month].tail(3) if not monthly.empty else monthly
    if not hist.empty and hist["consumption"].mean() > 0 and fc["days_elapsed"] >= 7:
        ref = hist["consumption"].mean()
        if fc["projected"] > 1.2 * ref:
            alerts.append(_item(
                "warning", "Mois plus cher que d'habitude",
                f"La prévision du mois ({fmt_money(fc['projected'])}) dépasse de "
                f"{(fc['projected'] / ref - 1) * 100:.0f} % la moyenne des {len(hist)} mois précédents "
                f"({fmt_money(ref)}).", priority=4))

    # 7. Aucun budget du tout
    if k["budget_consumption"] <= 0:
        alerts.append(_item("info", "Aucun budget défini pour ce mois",
                            "Définissez un budget par catégorie dans Paramètres pour activer les alertes de dépassement.",
                            priority=9))

    if not [a for a in alerts if a["level"] in ("warning", "danger")]:
        alerts.insert(0, _item("ok", "Situation normale",
                               f"Aucun dépassement ni anomalie détectée pour {month_label(month)}. "
                               f"Budget consommé à {k['budget_usage']:.0f} % pour {progress:.0f} % du mois.",
                               priority=10))
    return sorted(alerts, key=lambda a: (a["priority"], -{"danger": 3, "warning": 2, "info": 1, "ok": 0}[a["level"]]))


# ---------------------------------------------------------------------------
# Recommandations
# ---------------------------------------------------------------------------
def generate_recommendations(ctx: dict) -> list[dict]:
    k, bva, fc, month = ctx["kpis"], ctx["bva"], ctx["forecast"], ctx["month"]
    expenses = ctx["expenses"]
    recs: list[dict] = []
    remaining_days = fc["days_remaining"]
    prev = previous_month(month)
    prev_df = calc.split_consumption(calc.month_slice(expenses, prev))[0]
    prev_totals = calc.category_totals(prev_df).set_index("category")["amount"] if not prev_df.empty else pd.Series(dtype=float)
    prev_kpis_income = ctx["monthly"].set_index("month")["income"].get(prev, np.nan) if not ctx["monthly"].empty else np.nan

    # A. Catégories dépassées ou en voie de l'être : consigne journalière concrète
    for _, r in bva.iterrows():
        if r["budget"] <= 0:
            continue
        share_now = safe_div(r["spent"], k["income"]) * 100 if k["income"] else np.nan
        share_prev = safe_div(prev_totals.get(r["category"], 0), prev_kpis_income) * 100 \
            if prev_kpis_income == prev_kpis_income and prev_kpis_income else np.nan
        comparison = ""
        if share_now == share_now and share_prev == share_prev:
            comparison = (f" Les dépenses {de_(r['category'].lower())} représentent {share_now:.0f} % de vos revenus "
                          f"contre {share_prev:.0f} % le mois précédent.")

        if r["ratio"] >= 1.0:
            over = r["spent"] - r["budget"]
            cat_fc = forecast_category(expenses, month, r["category"], r["budget"], ctx["today"], ctx["anomaly_ids"])
            excluded = float(r.get("excluded", 0.0) or 0.0)
            if excluded >= over * 0.8 and remaining_days > 0:
                # Le dépassement vient d'une dépense exceptionnelle, pas d'un rythme trop élevé
                action = (f"Ce dépassement s'explique par une dépense exceptionnelle de {fmt_money(excluded)} "
                          f"(voir Alertes). Ne l'ajoutez pas au rythme habituel : évitez simplement toute "
                          f"dépense {r['category'].lower()} non indispensable d'ici la fin du mois, et si "
                          f"ce type d'imprévu se répète, prévoyez une réserve « imprévus » d'environ "
                          f"{fmt_money(excluded / 3)} par mois.")
            elif remaining_days > 0 and cat_fc["recent_daily"] <= 0:
                action = (f"Aucune dépense {r['category'].lower()} ces 7 derniers jours : gardez ce cap "
                          f"jusqu'à la fin du mois pour ne pas creuser l'écart de {fmt_money(over)}.")
            elif remaining_days > 0:
                # Ramener la catégorie à un rythme qui limite la casse : moitié du rythme récent
                target_daily = max(cat_fc["recent_daily"] * 0.5, 0)
                action = (f"Limitez vos dépenses {de_(r['category'].lower())} à environ {fmt_money(target_daily)} "
                          f"par jour pendant les {remaining_days} prochains jours (rythme récent : "
                          f"{fmt_money(cat_fc['recent_daily'])}/jour). Le dépassement final resterait "
                          f"autour de {fmt_money(over + target_daily * remaining_days)} au lieu de "
                          f"{fmt_money(max(cat_fc['projected'] - r['budget'], over))}.")
            else:
                action = (f"Pour le mois prochain, prévoyez un budget {r['category']} plus réaliste "
                          f"(autour de {fmt_money(r['spent'])}) ou identifiez les postes à réduire.")
            recs.append(_item("danger", f"Budget {r['category']} dépassé de {fmt_money(over)}",
                              f"Votre budget {r['category'].lower()} est dépassé de {fmt_money(over)} ce mois-ci.{comparison}",
                              action, r["category"], priority=1))
        elif r["projected_gap"] > 0 and remaining_days > 0 and r["ratio"] >= 0.5:
            allowed_daily = safe_div(r["budget"] - r["spent"], remaining_days)
            recs.append(_item("warning", f"{r['category']} : ralentir pour rester dans le budget",
                              f"{r['category']} est à {r['ratio'] * 100:.0f} % du budget pour "
                              f"{k['month_progress']:.0f} % du mois ; dépassement prévisible de "
                              f"{fmt_money(r['projected_gap'])}.{comparison}",
                              f"Pour tenir le budget, ne dépassez pas {fmt_money(allowed_daily)} par jour "
                              f"en {r['category'].lower()} sur les {remaining_days} jours restants.",
                              r["category"], priority=2))
        elif r["ratio"] < 0.9 and r["projected_gap"] < 0 and r["spent"] > 0 and k["month_progress"] > 30:
            under = (1 - safe_div(r["projected"], r["budget"])) * 100
            if under >= 8:
                recs.append(_item("ok", f"{r['category']} : sous contrôle",
                                  f"Votre poste {r['category'].lower()} est actuellement {under:.0f} % sous "
                                  f"votre budget mensuel en projection. Vous pouvez maintenir votre rythme "
                                  f"actuel tout en conservant votre objectif d'épargne.",
                                  None, r["category"], priority=7))

    # B. Dépenses évitables
    avoidable = calc.avoidable_expenses(calc.month_slice(expenses, month), ctx["essential"])
    if not avoidable.empty and k["spent"] > 0:
        av_total = float(avoidable["amount"].sum())
        share = av_total / k["spent"] * 100
        top = avoidable.groupby(["category", "subcategory"])["amount"].sum().sort_values(ascending=False).head(3)
        detail = ", ".join(f"{s or c} {fmt_money(v)}" for (c, s), v in top.items())
        if share >= 20:
            recs.append(_item("warning", "Poids important des dépenses évitables",
                              f"{fmt_money(av_total)} ({share:.0f} % de vos dépenses du mois) sont non nécessaires "
                              f"ou dans des postes évitables. Principaux postes : {detail}.",
                              f"Réduire ces postes de moitié libérerait environ {fmt_money(av_total / 2)} "
                              f"par mois, soit {fmt_pct(safe_div(av_total / 2, k['income']) * 100)} de vos revenus.",
                              priority=3))

    # C. Épargne
    if k["income"] > 0:
        projected_savings = k["income"] - fc["projected"]
        if k["savings_goal"] > 0 and projected_savings < k["savings_goal"] and remaining_days > 0:
            gap = k["savings_goal"] - projected_savings
            recs.append(_item("warning", "Objectif d'épargne en danger",
                              f"Avec la prévision actuelle, votre épargne de fin de mois serait de "
                              f"{fmt_money(projected_savings)} pour un objectif de {fmt_money(k['savings_goal'])}.",
                              f"Il faudrait réduire les dépenses d'environ {fmt_money(gap)} d'ici la fin du mois, "
                              f"soit {fmt_money(safe_div(gap, remaining_days))} par jour de moins que le rythme actuel.",
                              priority=2))
        elif k["savings_rate"] >= 20 and k["month_progress"] > 50:
            recs.append(_item("ok", "Bon taux d'épargne",
                              f"Votre taux d'épargne est de {k['savings_rate']:.0f} % ce mois-ci.",
                              "Si cette marge se confirme en fin de mois, affectez le surplus à votre objectif "
                              "principal plutôt que de le laisser sur le compte courant.", priority=6))

    # D. Jour de la semaine le plus dépensier
    wd = ctx["weekday"]
    if not wd.empty and wd["n_days"].sum() >= 28:
        top = wd.sort_values("avg_per_day", ascending=False).iloc[0]
        if top["vs_others_pct"] >= 30:
            recs.append(_item("info", f"Le {top['weekday_name'].lower()} coûte cher",
                              f"Vous dépensez en moyenne {top['vs_others_pct']:.0f} % de plus le "
                              f"{top['weekday_name'].lower()} que les autres jours ({fmt_money(top['avg_per_day'])} contre "
                              f"{fmt_money(wd.attrs.get('overall_avg', 0))} en moyenne).",
                              f"Fixez-vous une enveloppe pour le {top['weekday_name'].lower()} et payez en espèces "
                              f"ce jour-là pour la rendre visible.", priority=5))

    # E. Catégorie qui monte le plus sur 3 mois
    pivot = _complete_pivot(ctx)
    if not pivot.empty and len(pivot) >= 3:
        recent = pivot.tail(3)
        if len(recent) == 3:
            growth = {}
            for cat in recent.columns:
                s = recent[cat]
                if s.iloc[0] > 0 and s.iloc[-1] > s.iloc[0] * 1.25 and s.iloc[-1] > 0.05 * max(k["spent"], 1):
                    growth[cat] = (s.iloc[-1] / s.iloc[0] - 1) * 100
            if growth:
                cat, pct = max(growth.items(), key=lambda kv: kv[1])
                recs.append(_item("warning", f"{cat} augmente régulièrement",
                                  f"Le poste {cat} a progressé de {pct:.0f} % sur les trois derniers mois complets "
                                  f"({fmt_money(recent[cat].iloc[0])} → {fmt_money(recent[cat].iloc[-1])}).",
                                  f"Vérifiez ce qui explique la hausse en {cat.lower()} (passez en revue les "
                                  f"sous-catégories dans Analyses) avant de fixer le budget du mois prochain.",
                                  cat, priority=4))

    # F. Fin de mois : restreindre les dépenses non essentielles
    if 0 < remaining_days <= 7 and (fc["over_budget"] or k["budget_usage"] > 85):
        recs.append(_item("warning", "Derniers jours du mois",
                          f"Il reste {remaining_days} jours et {fmt_money(max(k['budget_remaining'], 0))} de budget.",
                          "Évitez les dépenses non essentielles jusqu'à la fin du mois : "
                          "restaurants, sorties, achats non planifiés.", priority=2))

    if not recs:
        recs.append(_item("ok", "Rien à signaler",
                          "Vos dépenses sont dans les clous. Continuez à saisir vos dépenses chaque jour "
                          "pour garder une prévision fiable.", priority=9))
    return sorted(recs, key=lambda r: r["priority"])


# ---------------------------------------------------------------------------
# Réponses aux questions d'analyse (page Analyses)
# ---------------------------------------------------------------------------
def analysis_insights(ctx: dict) -> list[tuple[str, str]]:
    """Réponses courtes aux questions du cahier des charges (§ Analyse intelligente)."""
    k, fc, month, expenses = ctx["kpis"], ctx["forecast"], ctx["month"], ctx["expenses"]
    out = []
    em = calc.split_consumption(calc.month_slice(expenses, month))[0]
    cats = calc.category_totals(em)

    if not cats.empty:
        top = cats.iloc[0]
        out.append(("Où est-ce que je dépense le plus ?",
                    f"En {top['category']} : {fmt_money(top['amount'])}, soit {top['share']:.0f} % de vos dépenses de "
                    f"{month_label(month)}."))
    else:
        out.append(("Où est-ce que je dépense le plus ?", "Aucune dépense saisie ce mois-ci."))

    pivot = _complete_pivot(ctx)
    if not pivot.empty and len(pivot) >= 2:
        recent = pivot.tail(4)
        trends = {c: calc.trend(recent[c])["pct_per_period"] for c in recent.columns
                  if recent[c].sum() > 0 and recent[c].iloc[-1] >= 0.03 * recent.sum(axis=1).iloc[-1]}
        if trends:
            c, p = max(trends.items(), key=lambda kv: kv[1])
            out.append(("Quelle catégorie augmente le plus ?",
                        f"{c} : tendance de {p:+.0f} % par mois sur les {len(recent)} derniers mois complets "
                        f"({fmt_money(recent[c].iloc[0])} → {fmt_money(recent[c].iloc[-1])})."))
    # Dépassements réguliers
    all_budgets = db.get_budgets()
    if not all_budgets.empty:
        over_counts = {}
        for m in sorted(all_budgets["month"].unique()):
            if m > month:
                continue
            b = all_budgets[all_budgets["month"] == m]
            mdf = calc.split_consumption(calc.month_slice(expenses, m))[0]
            bva_m = calc.budget_vs_actual(mdf, b[b["category"] != "Finance"], m, ctx["today"], all_expenses=expenses)
            for _, r in bva_m.iterrows():
                if r["budget"] > 0 and r["ratio"] >= 1.0:
                    over_counts[r["category"]] = over_counts.get(r["category"], 0) + 1
        if over_counts:
            c, n = max(over_counts.items(), key=lambda kv: kv[1])
            out.append(("Quelle catégorie dépasse régulièrement son budget ?",
                        f"{c} : budget dépassé {n} mois sur {all_budgets['month'].nunique()}."))
        else:
            out.append(("Quelle catégorie dépasse régulièrement son budget ?", "Aucun dépassement sur l'historique budgété."))

    wd = ctx["weekday"]
    if not wd.empty and wd["total"].sum() > 0:
        top = wd.sort_values("avg_per_day", ascending=False).iloc[0]
        out.append(("Quel jour de la semaine je dépense le plus ?",
                    f"Le {top['weekday_name'].lower()} : {fmt_money(top['avg_per_day'])} par jour en moyenne, "
                    f"soit {top['vs_others_pct']:+.0f} % par rapport aux autres jours."))

    out.append(("Quelle est ma dépense moyenne quotidienne ?",
                f"{fmt_money(k['avg_daily'])} par jour sur {k['days_elapsed']} jours "
                f"(7 derniers jours : {fmt_money(fc['recent_daily'])})."))
    out.append(("Quel est mon taux d'épargne ?",
                f"{k['savings_rate']:.0f} % ({fmt_money(k['savings'])} sur {fmt_money(k['income'])} de revenus"
                + (" de référence" if k["income_is_reference"] else "") + ")."))

    if k["income"] > 0:
        proj_rate = (1 - fc["projected"] / k["income"]) * 100
        verdict = ("soutenable" if proj_rate >= 10 else
                   "fragile : l'épargne prévue est faible" if proj_rate >= 0 else
                   "non soutenable : les dépenses prévues dépassent les revenus")
        out.append(("Mon niveau de dépenses est-il soutenable ?",
                    f"Prévision de fin de mois {fmt_money(fc['projected'])} pour {fmt_money(k['income'])} de revenus, "
                    f"soit un taux d'épargne projeté de {proj_rate:.0f} % : {verdict}."))
    if k["budget_consumption"] > 0:
        out.append(("Est-ce que je risque de dépasser mon budget ?",
                    (f"Oui, dépassement prévisionnel de {fmt_money(fc['gap'])}." if fc["over_budget"] else
                     f"Non, marge prévisionnelle de {fmt_money(-fc['gap'])}.")
                    + f" Prévision : {fmt_money(fc['projected'])} pour {fmt_money(k['budget_consumption'])} de budget."))

    avoidable = calc.avoidable_expenses(calc.month_slice(expenses, month), ctx["essential"])
    if not avoidable.empty:
        top3 = avoidable.groupby(["category", "subcategory"])["amount"].sum().sort_values(ascending=False).head(3)
        out.append(("Quelles dépenses sont évitables ?",
                    f"{fmt_money(avoidable['amount'].sum())} ce mois-ci, principalement : "
                    + ", ".join(f"{s or c} ({fmt_money(v)})" for (c, s), v in top3.items()) + "."))
    rec = calc.recurring_summary(expenses)
    if not rec.empty:
        out.append(("Quelles dépenses sont récurrentes ?",
                    f"{len(rec)} charges récurrentes pour environ {fmt_money(rec['avg_monthly'].sum())} par mois : "
                    + ", ".join(f"{s or c} ({fmt_money(v)})" for c, s, v in
                                zip(rec['category'].head(4), rec['subcategory'].head(4), rec['avg_monthly'].head(4))) + "."))
    recs = [r for r in generate_recommendations(ctx) if r["action"]]
    if recs:
        out.append(("Comment réduire mes dépenses ?", " ".join(r["action"] for r in recs[:2])))
    return out


# ---------------------------------------------------------------------------
# Rapport mensuel
# ---------------------------------------------------------------------------
def monthly_report(ctx: dict) -> dict:
    """Rapport structuré d'un mois (résumé, analyse, alertes, recommandations)."""
    k, month, expenses = ctx["kpis"], ctx["month"], ctx["expenses"]
    prev = previous_month(month)
    cur = calc.category_totals(calc.split_consumption(calc.month_slice(expenses, month))[0])
    prv = calc.category_totals(calc.split_consumption(calc.month_slice(expenses, prev))[0])
    merged = pd.merge(cur[["category", "amount"]], prv[["category", "amount"]],
                      on="category", how="outer", suffixes=("_cur", "_prev")).fillna(0.0)
    merged["delta"] = merged["amount_cur"] - merged["amount_prev"]
    merged["delta_pct"] = merged.apply(lambda r: safe_div(r["delta"], r["amount_prev"], np.nan) * 100, axis=1)
    increased = merged[merged["delta"] > 0].sort_values("delta", ascending=False)
    decreased = merged[merged["delta"] < 0].sort_values("delta")
    overruns = ctx["bva"][(ctx["bva"]["budget"] > 0) & (ctx["bva"]["ratio"] >= 1.0)]

    alerts = [a for a in generate_alerts(ctx) if a["level"] in ("warning", "danger")]
    recs = generate_recommendations(ctx)

    # 3 à 5 recommandations concrètes pour le mois suivant
    next_actions: list[str] = []
    for _, r in overruns.head(2).iterrows():
        cut = r["spent"] - r["budget"]
        next_actions.append(f"Réduire les dépenses {de_(r['category'].lower())} de {fmt_money(cut)} "
                            f"(revenir à {fmt_money(r['budget'])}).")
    for _, r in ctx["bva"].iterrows():
        if r["budget"] > 0 and 0.9 <= r["ratio"] < 1.0 and len(next_actions) < 3:
            next_actions.append(f"Maintenir les dépenses {de_(r['category'].lower())} sous {fmt_money(r['budget'])}.")
    if k["savings_goal"] > 0 and k["savings"] < k["savings_goal"]:
        next_actions.append(f"Augmenter l'épargne mensuelle de {fmt_money(k['savings_goal'] - k['savings'])} "
                            f"pour atteindre l'objectif de {fmt_money(k['savings_goal'])}.")
    if k["unnecessary_share"] >= 15:
        next_actions.append("Éviter les dépenses non essentielles pendant les 5 derniers jours du mois.")
    for _, r in increased.head(1).iterrows():
        if r["delta_pct"] == r["delta_pct"] and r["delta_pct"] > 20 and len(next_actions) < 5:
            next_actions.append(f"Surveiller le poste {r['category'].lower()} qui a augmenté de "
                                f"{r['delta_pct']:.0f} % ce mois-ci.")
    if len(next_actions) < 3:
        next_actions.append("Saisir chaque dépense le jour même pour garder une prévision fiable.")
    if len(next_actions) < 3 and k["budget_consumption"] > 0:
        next_actions.append("Reconduire les budgets du mois et les ajuster aux catégories dépassées.")

    return {
        "month": month, "label": month_label(month), "kpis": k, "score": ctx["score"],
        "top_categories": cur.head(5), "increased": increased.head(5), "decreased": decreased.head(5),
        "overruns": overruns, "alerts": alerts[:6], "recommendations": recs[:5],
        "next_actions": next_actions[:5], "anomalies": ctx["anomalies"].head(5),
    }
