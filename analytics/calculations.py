"""
Calculs descriptifs : KPI mensuels, budget vs réel, séries temporelles,
analyse par jour de semaine, comparaison de mois, score financier.

Convention importante : les lignes de la catégorie Finance en sous-catégorie
« Épargne » ou « Investissement » sont de l'argent mis de côté, pas de la
consommation. Elles sont donc exclues des « dépenses » au sens du pilotage et
ajoutées à l'épargne réalisée. Sans cette règle, épargner ferait baisser le
taux d'épargne, ce qui serait absurde.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from database.models import AVOIDABLE_SUBCATEGORIES
from utils.helpers import (WEEKDAYS_FR, days_elapsed, days_in_month, month_bounds,
                           previous_month, safe_div)

SAVINGS_SUBCATEGORIES = {"Épargne", "Investissement"}
PRIOR_WEIGHT_DAYS = 15  # poids de l'historique dans les projections, en « jours équivalents »


# ---------------------------------------------------------------------------
# Filtres de base
# ---------------------------------------------------------------------------
def month_slice(df: pd.DataFrame, month: str) -> pd.DataFrame:
    if df.empty:
        return df
    return df[df["month"] == month]


def split_consumption(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sépare consommation réelle et transferts d'épargne/investissement."""
    if df.empty:
        return df, df
    mask = df["subcategory"].isin(SAVINGS_SUBCATEGORIES)
    return df[~mask], df[mask]


def total(df: pd.DataFrame) -> float:
    return float(df["amount"].sum()) if not df.empty else 0.0


# ---------------------------------------------------------------------------
# Agrégations par catégorie
# ---------------------------------------------------------------------------
def category_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Total par catégorie, trié décroissant, avec la part en %."""
    if df.empty:
        return pd.DataFrame(columns=["category", "amount", "share"])
    out = df.groupby("category", as_index=False)["amount"].sum()
    out = out[out["amount"] > 0].sort_values("amount", ascending=False)
    out["share"] = out["amount"] / out["amount"].sum() * 100 if out["amount"].sum() else 0
    return out.reset_index(drop=True)


def subcategory_totals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["category", "subcategory", "amount"])
    out = df.groupby(["category", "subcategory"], as_index=False)["amount"].sum()
    return out.sort_values("amount", ascending=False).reset_index(drop=True)


def pending_recurring(expenses: pd.DataFrame, month: str, lookback: int = 3) -> pd.DataFrame:
    """
    Charges récurrentes observées dans au moins 2 des `lookback` mois précédents
    (même catégorie + sous-catégorie) et absentes du mois courant. Montant attendu = médiane.
    """
    cols = ["category", "subcategory", "expected_amount", "n_months"]
    if expenses.empty:
        return pd.DataFrame(columns=cols)
    rec = expenses[expenses["recurring"]]
    if rec.empty:
        return pd.DataFrame(columns=cols)
    prev_months = [previous_month(month, i) for i in range(1, lookback + 1)]
    hist = rec[rec["month"].isin(prev_months)]
    if hist.empty:
        return pd.DataFrame(columns=cols)
    g = hist.groupby(["category", "subcategory", "month"])["amount"].sum().reset_index()
    stats = g.groupby(["category", "subcategory"]).agg(expected_amount=("amount", "median"),
                                                       n_months=("month", "nunique")).reset_index()
    stats = stats[stats["n_months"] >= min(2, hist["month"].nunique())]
    current = rec[rec["month"] == month]
    paid = set(zip(current["category"], current["subcategory"]))
    stats = stats[[(c, s) not in paid for c, s in zip(stats["category"], stats["subcategory"])]]
    return stats.reset_index(drop=True)


def variable_daily_prior(expenses: pd.DataFrame, month: str, lookback: int = 3,
                         by_category: bool = False):
    """
    Dépense variable (non récurrente) moyenne par jour sur les `lookback` mois
    précédents. Sert de point de départ en début de mois, quand quelques jours
    d'observation ne suffisent pas à estimer un rythme.
    Renvoie un float (ou None), ou une Series par catégorie si by_category=True.
    """
    empty = pd.Series(dtype=float) if by_category else None
    if expenses.empty:
        return empty
    cons, _ = split_consumption(expenses)
    prev_months = [previous_month(month, i) for i in range(1, lookback + 1)]
    hist = cons[(cons["month"].isin(prev_months)) & (~cons["recurring"])]
    if hist.empty:
        return empty
    n_days = sum(days_in_month(m) for m in prev_months if m in set(hist["month"]))
    if by_category:
        return hist.groupby("category")["amount"].sum() / n_days
    return safe_div(float(hist["amount"].sum()), n_days) if n_days else None


def budget_vs_actual(month_df: pd.DataFrame, budgets: pd.DataFrame, month: str,
                     today: date | None = None, all_expenses: pd.DataFrame | None = None,
                     exclude_ids: set | None = None) -> pd.DataFrame:
    """
    Pour chaque catégorie budgétée ou dépensée : budget, dépensé, restant, taux de
    consommation et projection de fin de mois.

    La projection ne prolonge que la part variable des dépenses (le loyer payé le 3 ne se
    « répète » pas 10 fois dans le mois) ; on y ajoute les charges récurrentes attendues
    mais pas encore payées et, si `all_expenses` est fourni, on lisse le rythme observé
    avec l'historique des mois précédents (même logique que forecasting.forecast_month).
    """
    today = today or date.today()
    spent = category_totals(month_df)[["category", "amount"]].rename(columns={"amount": "spent"})
    bud = budgets[["category", "amount"]].rename(columns={"amount": "budget"}) if not budgets.empty \
        else pd.DataFrame(columns=["category", "budget"])
    out = pd.merge(bud, spent, on="category", how="outer").fillna(0.0)
    if out.empty:
        return pd.DataFrame(columns=["category", "budget", "spent", "remaining", "ratio",
                                     "projected", "projected_gap", "level", "month_progress"])
    elapsed = days_elapsed(month, today)
    n_days = days_in_month(month)
    remaining = max(n_days - elapsed, 0)
    progress = safe_div(elapsed, n_days, 1.0)

    if not month_df.empty:
        rec_spent = month_df[month_df["recurring"]].groupby("category")["amount"].sum()
    else:
        rec_spent = pd.Series(dtype=float)
    out["recurring_spent"] = out["category"].map(rec_spent).fillna(0.0)
    exclude_ids = exclude_ids or set()
    if exclude_ids and not month_df.empty:
        excl = month_df[month_df["id"].isin(exclude_ids)].groupby("category")["amount"].sum()
    else:
        excl = pd.Series(dtype=float)
    out["excluded"] = out["category"].map(excl).fillna(0.0)
    # Part variable servant au rythme : hors récurrent et hors dépenses inhabituelles
    out["variable_spent"] = out["spent"] - out["recurring_spent"] - out["excluded"]

    if all_expenses is not None and not all_expenses.empty:
        pend = pending_recurring(all_expenses, month)
        pend_by_cat = pend.groupby("category")["expected_amount"].sum() if not pend.empty else pd.Series(dtype=float)
        prior = variable_daily_prior(all_expenses, month, by_category=True)
    else:
        pend_by_cat, prior = pd.Series(dtype=float), pd.Series(dtype=float)
    out["pending_recurring"] = out["category"].map(pend_by_cat).fillna(0.0)

    def project(r):
        observed = safe_div(r["variable_spent"], elapsed)
        p = prior.get(r["category"], np.nan)
        if p == p and elapsed > 0:
            daily = (elapsed * observed + PRIOR_WEIGHT_DAYS * p) / (elapsed + PRIOR_WEIGHT_DAYS)
        elif p == p:
            daily = p
        else:
            daily = observed
        return r["spent"] + daily * remaining + r["pending_recurring"]

    out["remaining"] = out["budget"] - out["spent"]
    out["ratio"] = out.apply(lambda r: safe_div(r["spent"], r["budget"], np.nan), axis=1)
    out["projected"] = out.apply(project, axis=1)
    out["projected_gap"] = out["projected"] - out["budget"]

    def level(r):
        if r["budget"] <= 0:
            return "info" if r["spent"] > 0 else "ok"
        if r["ratio"] >= 1.0:
            return "danger"
        if r["ratio"] >= 0.8 or (r["projected_gap"] > 0 and r["ratio"] >= 0.5):
            return "warning"
        return "ok"

    out["level"] = out.apply(level, axis=1)
    out["month_progress"] = progress
    return out.sort_values("spent", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Séries temporelles
# ---------------------------------------------------------------------------
def daily_series(df: pd.DataFrame, month: str, today: date | None = None) -> pd.DataFrame:
    """Dépense par jour du mois (jours sans dépense = 0), moyenne mobile 7 j et cumul.
    S'arrête au jour courant pour le mois en cours."""
    today = today or date.today()
    first, last = month_bounds(month)
    end = min(last, today) if today >= first else first
    idx = pd.date_range(first, end, freq="D")
    m = month_slice(df, month)
    daily = m.groupby(m["date"].dt.normalize())["amount"].sum() if not m.empty else pd.Series(dtype=float)
    out = pd.DataFrame({"date": idx})
    out["amount"] = out["date"].map(daily).fillna(0.0)
    out["count"] = out["date"].map(m.groupby(m["date"].dt.normalize()).size()).fillna(0).astype(int) \
        if not m.empty else 0
    out["rolling7"] = out["amount"].rolling(7, min_periods=1).mean()
    out["cumulative"] = out["amount"].cumsum()
    return out


def all_days_series(df: pd.DataFrame) -> pd.DataFrame:
    """Série journalière sur tout l'historique (pour la moyenne mobile longue)."""
    if df.empty:
        return pd.DataFrame(columns=["date", "amount", "rolling7"])
    idx = pd.date_range(df["date"].min().normalize(), df["date"].max().normalize(), freq="D")
    daily = df.groupby(df["date"].dt.normalize())["amount"].sum()
    out = pd.DataFrame({"date": idx})
    out["amount"] = out["date"].map(daily).fillna(0.0)
    out["rolling7"] = out["amount"].rolling(7, min_periods=1).mean()
    return out


def monthly_series(expenses: pd.DataFrame, incomes: pd.DataFrame,
                   fallback_income: float = 0.0) -> pd.DataFrame:
    """
    Par mois : revenus, consommation, transferts d'épargne, épargne réalisée, taux,
    cumul d'épargne. Si un mois n'a aucun revenu saisi, on utilise le revenu de référence
    du profil (fallback) et on le signale dans la colonne income_is_reference.
    """
    months = set()
    if not expenses.empty:
        months |= set(expenses["month"])
    if not incomes.empty:
        months |= set(incomes["month"])
    if not months:
        return pd.DataFrame(columns=["month", "income", "consumption", "savings_transfers",
                                     "savings", "savings_rate", "cumulative_savings",
                                     "income_is_reference", "n_expenses"])
    rows = []
    for m in sorted(months):
        em = month_slice(expenses, m)
        cons, sav = split_consumption(em)
        inc = float(incomes.loc[incomes["month"] == m, "amount"].sum()) if not incomes.empty else 0.0
        is_ref = inc == 0 and fallback_income > 0
        if is_ref:
            inc = fallback_income
        consumption = total(cons)
        savings = inc - consumption
        rows.append({
            "month": m, "income": inc, "consumption": consumption,
            "savings_transfers": total(sav), "savings": savings,
            "savings_rate": safe_div(savings, inc) * 100,
            "income_is_reference": is_ref, "n_expenses": len(em),
        })
    out = pd.DataFrame(rows)
    out["cumulative_savings"] = out["savings"].cumsum()
    return out


def category_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Tableau croisé mois x catégorie (montants)."""
    if df.empty:
        return pd.DataFrame()
    cons, _ = split_consumption(df)
    pivot = cons.pivot_table(index="month", columns="category", values="amount",
                             aggfunc="sum", fill_value=0.0)
    return pivot.sort_index()


def trend(series: pd.Series) -> dict:
    """Tendance linéaire d'une série (pente par période et variation relative)."""
    s = pd.Series(series).dropna().astype(float)
    if len(s) < 2:
        return {"slope": 0.0, "pct_per_period": 0.0, "direction": "stable", "n": len(s)}
    x = np.arange(len(s))
    slope = float(np.polyfit(x, s.values, 1)[0])
    mean = float(s.mean()) if s.mean() else 1.0
    pct = slope / mean * 100
    direction = "hausse" if pct > 5 else "baisse" if pct < -5 else "stable"
    return {"slope": slope, "pct_per_period": pct, "direction": direction, "n": len(s)}


# ---------------------------------------------------------------------------
# Jour de la semaine
# ---------------------------------------------------------------------------
def weekday_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Dépense moyenne par jour de semaine. On divise le total de chaque jour de semaine
    par le nombre réel de ces jours dans la période observée (les jours sans dépense
    comptent donc pour zéro, ce qui évite de surestimer les jours rares).
    """
    cols = ["weekday", "weekday_name", "total", "n_days", "avg_per_day", "n_tx", "vs_others_pct"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    cons, _ = split_consumption(df)
    if cons.empty:
        return pd.DataFrame(columns=cols)
    span = pd.date_range(cons["date"].min().normalize(), cons["date"].max().normalize(), freq="D")
    n_days = pd.Series(span.weekday).value_counts().reindex(range(7), fill_value=0)
    totals = cons.groupby("weekday")["amount"].sum().reindex(range(7), fill_value=0.0)
    counts = cons.groupby("weekday").size().reindex(range(7), fill_value=0)
    out = pd.DataFrame({
        "weekday": range(7),
        "weekday_name": WEEKDAYS_FR,
        "total": totals.values,
        "n_days": n_days.values,
        "n_tx": counts.values,
    })
    out["avg_per_day"] = out.apply(lambda r: safe_div(r["total"], r["n_days"]), axis=1)
    overall = out["avg_per_day"].mean()

    def vs_others(r):
        others = out.loc[out["weekday"] != r["weekday"], "avg_per_day"].mean()
        return safe_div(r["avg_per_day"] - others, others) * 100

    out["vs_others_pct"] = out.apply(vs_others, axis=1)
    out.attrs["overall_avg"] = overall
    return out


# ---------------------------------------------------------------------------
# Comparaison de mois
# ---------------------------------------------------------------------------
def compare_months(df: pd.DataFrame, months: list[str]) -> pd.DataFrame:
    """Tableau catégorie x mois, avec variation entre le premier et le dernier mois."""
    if df.empty or not months:
        return pd.DataFrame()
    pivot = category_monthly(df)
    pivot = pivot.reindex(months, fill_value=0.0).T
    pivot = pivot.loc[(pivot != 0).any(axis=1)]
    if len(months) >= 2:
        a, b = months[0], months[-1]
        pivot["Variation"] = pivot[b] - pivot[a]
        pivot["Variation %"] = pivot.apply(
            lambda r: safe_div(r[b] - r[a], r[a], np.nan) * 100, axis=1)
    pivot.index.name = "Catégorie"
    total_row = pivot.sum(numeric_only=True)
    if len(months) >= 2:
        total_row["Variation %"] = safe_div(total_row[months[-1]] - total_row[months[0]],
                                            total_row[months[0]], np.nan) * 100
    pivot.loc["TOTAL"] = total_row
    return pivot


# ---------------------------------------------------------------------------
# KPI mensuels
# ---------------------------------------------------------------------------
def month_kpis(expenses: pd.DataFrame, incomes: pd.DataFrame, budgets: pd.DataFrame,
               settings: dict, month: str, today: date | None = None) -> dict:
    today = today or date.today()
    em = month_slice(expenses, month)
    cons, sav = split_consumption(em)

    income = float(incomes.loc[incomes["month"] == month, "amount"].sum()) if not incomes.empty else 0.0
    income_is_reference = False
    if income == 0:
        try:
            income = float(settings.get("monthly_income", 0)) + float(settings.get("extra_income", 0))
        except (TypeError, ValueError):
            income = 0.0
        income_is_reference = income > 0

    spent = total(cons)
    savings_transfers = total(sav)
    budget_total = float(budgets["amount"].sum()) if not budgets.empty else 0.0
    # Le budget de la catégorie Finance (épargne) n'est pas un budget de consommation
    if not budgets.empty and "Finance" in set(budgets["category"]):
        budget_consumption = budget_total - float(budgets.loc[budgets["category"] == "Finance", "amount"].sum())
    else:
        budget_consumption = budget_total

    elapsed = days_elapsed(month, today)
    n_days = days_in_month(month)
    savings = income - spent
    # Mois précédent : à date comparable si le mois en cours n'est pas terminé
    prev = month_slice(expenses, previous_month(month))
    prev_cons, _ = split_consumption(prev)
    prev_is_partial = elapsed < n_days and not prev_cons.empty
    if prev_is_partial:
        prev_cons = prev_cons[prev_cons["day"] <= elapsed]
    prev_spent = total(prev_cons)

    try:
        savings_goal = float(settings.get("savings_goal_monthly", 0))
    except (TypeError, ValueError):
        savings_goal = 0.0

    return {
        "month": month,
        "income": income,
        "income_is_reference": income_is_reference,
        "spent": spent,
        "savings_transfers": savings_transfers,
        "budget_total": budget_total,
        "budget_consumption": budget_consumption,
        "budget_remaining": budget_consumption - spent,
        "budget_usage": safe_div(spent, budget_consumption) * 100,
        "available": income - spent - savings_transfers,   # ce qui reste réellement disponible
        "savings": savings,
        "savings_rate": safe_div(savings, income) * 100,
        "savings_goal": savings_goal,
        "n_expenses": int(len(cons)),
        "avg_daily": safe_div(spent, elapsed),
        "days_elapsed": elapsed,
        "days_in_month": n_days,
        "days_remaining": max(n_days - elapsed, 0),
        "month_progress": safe_div(elapsed, n_days) * 100,
        "prev_spent": prev_spent,
        "prev_is_partial": prev_is_partial,
        "vs_prev_pct": safe_div(spent - prev_spent, prev_spent, np.nan) * 100,
        "unnecessary": total(cons[~cons["necessary"]]) if not cons.empty else 0.0,
        "unnecessary_share": safe_div(total(cons[~cons["necessary"]]) if not cons.empty else 0.0, spent) * 100,
        "recurring": total(cons[cons["recurring"]]) if not cons.empty else 0.0,
    }


# ---------------------------------------------------------------------------
# Dépenses évitables / récurrentes
# ---------------------------------------------------------------------------
def avoidable_expenses(df: pd.DataFrame, essential_categories: set[str]) -> pd.DataFrame:
    """Dépenses non nécessaires, ou dans une sous-catégorie considérée comme évitable."""
    if df.empty:
        return df
    cons, _ = split_consumption(df)
    mask = (~cons["necessary"]) | cons["subcategory"].isin(AVOIDABLE_SUBCATEGORIES) \
        | (~cons["category"].isin(essential_categories))
    return cons[mask].sort_values("amount", ascending=False)


def recurring_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Charges récurrentes : par catégorie/sous-catégorie, montant moyen par mois."""
    if df.empty:
        return pd.DataFrame(columns=["category", "subcategory", "avg_monthly", "n_months"])
    rec = df[df["recurring"]]
    if rec.empty:
        return pd.DataFrame(columns=["category", "subcategory", "avg_monthly", "n_months"])
    g = rec.groupby(["category", "subcategory", "month"])["amount"].sum().reset_index()
    out = g.groupby(["category", "subcategory"]).agg(avg_monthly=("amount", "mean"),
                                                     n_months=("month", "nunique")).reset_index()
    return out.sort_values("avg_monthly", ascending=False)


# ---------------------------------------------------------------------------
# Score financier
# ---------------------------------------------------------------------------
def financial_score(kpis: dict, bva: pd.DataFrame, monthly: pd.DataFrame,
                    goals: pd.DataFrame, daily: pd.DataFrame, forecast: dict | None = None) -> dict:
    """
    Score sur 100, décomposé en six volets explicités. C'est un indicateur de lecture,
    pas une vérité : chaque composante est renvoyée avec sa justification.
    Pour un mois en cours, on juge la prévision de fin de mois plutôt que le dépensé brut,
    sinon un loyer payé le 3 ferait chuter le score à chaque début de mois.
    """
    comps = []
    projected = forecast["projected"] if forecast else kpis["spent"] / max(kpis["month_progress"] / 100, 0.05)

    # 1. Respect du budget (30 pts) : prévision de fin de mois / budget, et dépassements déjà constatés
    if kpis["budget_consumption"] > 0:
        pace = safe_div(projected, kpis["budget_consumption"], 1.0)   # 1.0 = budget exactement tenu
        pts = 30 * float(np.clip(1.5 - pace, 0, 1)) if pace > 0.5 else 30   # 100 % → 15 pts, 150 % → 0
        n_over = int(((bva["budget"] > 0) & (bva["ratio"] >= 1.0)).sum()) if not bva.empty else 0
        pts = max(pts - 3 * n_over, 0)
        expl = (f"Prévision de fin de mois à {pace * 100:.0f} % du budget "
                f"({kpis['budget_usage']:.0f} % consommés pour {kpis['month_progress']:.0f} % du mois)"
                + (f", {n_over} catégorie(s) déjà dépassée(s) (-{3 * n_over})." if n_over else "."))
    else:
        pts, expl = 15, "Aucun budget défini : la moitié des points est attribuée par défaut."
    comps.append(("Respect du budget", round(pts, 1), 30, expl))

    # 2. Taux d'épargne (25 pts) : 20 % de taux d'épargne projeté = score plein
    if kpis["income"] > 0 and kpis["days_remaining"] > 0:
        rate = (1 - safe_div(projected, kpis["income"])) * 100
        note = "projeté en fin de mois"
    else:
        rate = kpis["savings_rate"]
        note = "réalisé"
    pts = 25 * float(np.clip(rate / 20, 0, 1))
    comps.append(("Taux d'épargne", round(pts, 1), 25,
                  f"Taux d'épargne {note} : {rate:.0f} % (objectif implicite : 20 %)."))

    # 3. Évolution des dépenses (15 pts) : comparaison avec la moyenne des 3 mois précédents
    if monthly is not None and len(monthly) >= 2:
        hist = monthly[monthly["month"] < kpis["month"]].tail(3)
        if not hist.empty and hist["consumption"].mean() > 0:
            delta = (projected - hist["consumption"].mean()) / hist["consumption"].mean()
            pts = 15 * float(np.clip(1 - delta * 2, 0, 1)) if delta > 0 else 15
            expl = f"Rythme du mois {delta * 100:+.0f} % par rapport à la moyenne des {len(hist)} mois précédents."
        else:
            pts, expl = 10, "Pas assez d'historique pour juger l'évolution."
    else:
        pts, expl = 10, "Pas assez d'historique pour juger l'évolution."
    comps.append(("Évolution des dépenses", round(pts, 1), 15, expl))

    # 4. Régularité (10 pts) : coefficient de variation des dépenses journalières
    if daily is not None and len(daily) >= 5 and daily["amount"].mean() > 0:
        cv = daily["amount"].std() / daily["amount"].mean()
        pts = 10 * float(np.clip(1 - (cv - 0.8) / 1.5, 0, 1))
        expl = f"Coefficient de variation journalier : {cv:.2f} (plus il est bas, plus les dépenses sont régulières)."
    else:
        pts, expl = 6, "Trop peu de jours pour mesurer la régularité."
    comps.append(("Régularité", round(pts, 1), 10, expl))

    # 5. Poids des dépenses non essentielles (10 pts) : 30 % ou plus = 0 pt
    share = kpis["unnecessary_share"]
    pts = 10 * float(np.clip(1 - share / 30, 0, 1))
    comps.append(("Dépenses non essentielles", round(pts, 1), 10,
                  f"{share:.0f} % des dépenses sont déclarées non nécessaires."))

    # 6. Progression vers les objectifs (10 pts)
    if goals is not None and not goals.empty:
        prog = (goals["current_amount"] / goals["target_amount"]).clip(0, 1)
        goal_on_track = float(prog.mean())
        pts = 10 * goal_on_track
        expl = f"Progression moyenne des objectifs : {goal_on_track * 100:.0f} %."
        # Bonus si l'objectif d'épargne mensuel est atteint
        if kpis["savings_goal"] > 0 and kpis["savings"] >= kpis["savings_goal"]:
            pts = min(10, pts + 3)
            expl += " Objectif d'épargne mensuel atteint (+3)."
    else:
        pts, expl = 5, "Aucun objectif défini : points neutres."
    comps.append(("Objectifs", round(pts, 1), 10, expl))

    score = int(round(sum(c[1] for c in comps)))
    score = max(0, min(100, score))
    if score >= 80:
        label, level = "Excellente maîtrise", "ok"
    elif score >= 60:
        label, level = "Situation correcte", "warning"
    elif score >= 40:
        label, level = "Vigilance", "warning"
    else:
        label, level = "Situation préoccupante", "danger"
    return {"score": score, "label": label, "level": level, "components": comps}
