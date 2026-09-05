"""
Prévision de fin de mois.

Trois estimateurs simples, combinés :
  1. rythme moyen depuis le début du mois (dépensé / jours écoulés) ;
  2. rythme récent (moyenne des 7 derniers jours), plus réactif ;
  3. charges récurrentes attendues mais pas encore payées ce mois-ci (loyer, abonnements…),
     déduites de l'historique des mois précédents.

La prévision retenue = dépensé + rythme pondéré x jours restants + récurrent en attente.
Le rythme pondéré donne plus de poids au rythme récent quand le mois est bien avancé,
et plus de poids à la moyenne du mois quand on a peu de jours d'observation.
On renvoie aussi une fourchette (basse / haute) pour rappeler que c'est une estimation.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from analytics.calculations import (PRIOR_WEIGHT_DAYS, daily_series, month_slice,
                                    pending_recurring, split_consumption, variable_daily_prior)
from utils.helpers import days_elapsed, days_in_month, previous_month, safe_div


def forecast_month(expenses: pd.DataFrame, month: str, budget: float,
                   today: date | None = None, exclude_ids: set | None = None) -> dict:
    """
    `exclude_ids` : identifiants de dépenses jugées inhabituelles (voir anomaly_detection).
    Elles restent comptées dans le dépensé, mais pas dans le rythme projeté : un examen
    médical exceptionnel ne doit pas se « répéter » chaque jour jusqu'à la fin du mois.
    """
    today = today or date.today()
    exclude_ids = exclude_ids or set()
    em = month_slice(expenses, month)
    cons, _ = split_consumption(em)
    elapsed = days_elapsed(month, today)
    n_days = days_in_month(month)
    remaining = max(n_days - elapsed, 0)
    spent = float(cons["amount"].sum()) if not cons.empty else 0.0
    excluded = float(cons.loc[cons["id"].isin(exclude_ids), "amount"].sum()) if not cons.empty else 0.0

    # Rythmes observés (hors dépenses inhabituelles)
    daily = daily_series(cons[~cons["id"].isin(exclude_ids)] if not cons.empty else cons, month, today)
    avg_daily = safe_div(spent, elapsed)
    recent = daily["amount"].tail(7)
    recent_daily = float(recent.mean()) if len(recent) else avg_daily

    # Tendance sur la série journalière (pente de la régression linéaire)
    slope = 0.0
    if len(daily) >= 7 and daily["amount"].std() > 0:
        x = np.arange(len(daily))
        slope = float(np.polyfit(x, daily["amount"].values, 1)[0])

    # Charges récurrentes attendues mais pas encore payées (loyer, abonnements…)
    pending = pending_recurring(expenses, month)
    pending_total = float(pending["expected_amount"].sum()) if not pending.empty else 0.0

    # Rythme hors récurrent : on retire le récurrent déjà payé pour projeter la dépense courante
    paid_recurring = float(cons.loc[cons["recurring"], "amount"].sum()) if not cons.empty else 0.0
    variable_spent = spent - paid_recurring - excluded
    variable_daily = safe_div(variable_spent, elapsed)
    recent_recurring = float(cons.loc[cons["recurring"] & (cons["date"] >= daily["date"].iloc[-7:].min()), "amount"].sum()) \
        if not cons.empty and len(daily) else 0.0
    variable_recent = max(recent_daily - safe_div(recent_recurring, min(7, len(daily))), 0) if elapsed else 0.0

    # Pondération : plus le mois avance, plus le rythme récent compte
    w_recent = float(np.clip(elapsed / n_days, 0.2, 0.7)) if elapsed >= 7 else 0.2
    observed_daily = (1 - w_recent) * variable_daily + w_recent * variable_recent

    # Lissage avec l'historique : en début de mois, quelques jours (et une grosse dépense
    # isolée) ne font pas un rythme. L'historique pèse PRIOR_WEIGHT_DAYS jours équivalents.
    prior = variable_daily_prior(expenses, month)
    if prior is not None and elapsed > 0:
        blended_daily = (elapsed * observed_daily + PRIOR_WEIGHT_DAYS * prior) / (elapsed + PRIOR_WEIGHT_DAYS)
    elif prior is not None:
        blended_daily = prior
    else:
        blended_daily = observed_daily

    projected_variable = blended_daily * remaining
    projected = spent + projected_variable + pending_total
    # Fourchette : entre le rythme historique et le rythme observé ce mois-ci
    candidates = [c for c in (observed_daily, prior, blended_daily) if c is not None]
    low = spent + min(candidates) * remaining + pending_total
    high = spent + max(candidates) * remaining + pending_total

    if elapsed == 0:
        projected = low = high = pending_total + (prior or 0) * n_days

    gap = projected - budget if budget > 0 else np.nan
    # Rythme journalier à respecter pour tenir le budget sur les jours restants
    allowed_daily = safe_div(budget - spent - pending_total, remaining) if remaining else 0.0

    return {
        "month": month,
        "spent": spent,
        "days_elapsed": elapsed,
        "days_remaining": remaining,
        "avg_daily": avg_daily,
        "recent_daily": recent_daily,
        "blended_daily": blended_daily,
        "observed_daily": observed_daily,
        "prior_daily": prior,
        "paid_recurring": paid_recurring,
        "excluded_anomalies": excluded,
        "slope_per_day": slope,
        "pending_recurring": pending,
        "pending_recurring_total": pending_total,
        "projected": projected,
        "projected_low": low,
        "projected_high": high,
        "budget": budget,
        "gap": gap,
        "allowed_daily": allowed_daily,
        "over_budget": bool(budget > 0 and projected > budget),
    }


def forecast_category(expenses: pd.DataFrame, month: str, category: str, budget: float,
                      today: date | None = None, exclude_ids: set | None = None) -> dict:
    """Même logique, restreinte à une catégorie (utile pour les recommandations ciblées)."""
    sub = expenses[expenses["category"] == category] if not expenses.empty else expenses
    return forecast_month(sub, month, budget, today, exclude_ids)
