"""
Détection des dépenses inhabituelles.

Quatre méthodes complémentaires, appliquées par (catégorie, sous-catégorie) puis par
catégorie seule quand la sous-catégorie manque d'historique :

  - ratio à la médiane : montant > k x médiane habituelle (k = 3 par défaut, paramétrable) ;
  - z-score robuste : (x - médiane) / (1,4826 x MAD) > 3,5 ;
  - IQR : x > Q3 + 1,5 x IQR ;
  - règle métier : une dépense non récurrente qui dépasse 25 % du revenu mensuel.

Une dépense est signalée si au moins deux méthodes la retiennent (ou la règle métier
seule), ce qui limite les faux positifs sur des séries courtes. On exige au minimum
5 observations de référence pour les méthodes statistiques.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.calculations import split_consumption
from utils.helpers import fmt_money

MIN_HISTORY = 5


def _stats(reference: pd.Series) -> dict:
    ref = reference.astype(float)
    median = float(ref.median())
    mad = float((ref - median).abs().median())
    q1, q3 = float(ref.quantile(0.25)), float(ref.quantile(0.75))
    return {"median": median, "mad": mad, "q1": q1, "q3": q3, "iqr": q3 - q1,
            "mean": float(ref.mean()), "n": int(len(ref))}


def _score_row(amount: float, st: dict, ratio_threshold: float) -> tuple[list[str], float]:
    """Retourne la liste des méthodes déclenchées et le ratio à la médiane."""
    methods = []
    ratio = amount / st["median"] if st["median"] > 0 else np.inf
    if st["median"] > 0 and ratio >= ratio_threshold:
        methods.append("ratio médiane")
    if st["mad"] > 0:
        z = (amount - st["median"]) / (1.4826 * st["mad"])
        if z > 3.5:
            methods.append("z-score robuste")
    if st["iqr"] > 0 and amount > st["q3"] + 1.5 * st["iqr"]:
        methods.append("IQR")
    return methods, ratio


def detect_anomalies(expenses: pd.DataFrame, month: str | None = None,
                     ratio_threshold: float = 3.0, monthly_income: float = 0.0,
                     lookback_months: int = 6) -> pd.DataFrame:
    """
    Analyse les dépenses du mois `month` (ou toutes si None) par rapport à l'historique.
    Renvoie un DataFrame : id, date, amount, category, subcategory, description,
    reference_median, ratio, methods, severity, message.
    """
    cols = ["id", "date", "amount", "category", "subcategory", "description",
            "reference_median", "ratio", "methods", "severity", "message"]
    if expenses.empty:
        return pd.DataFrame(columns=cols)
    cons, _ = split_consumption(expenses)
    cons = cons[cons["amount"] > 0]
    if cons.empty:
        return pd.DataFrame(columns=cols)

    if month:
        target = cons[cons["month"] == month]
        months = sorted(cons["month"].unique())
        keep = [m for m in months if m <= month][-(lookback_months + 1):]
        reference_pool = cons[cons["month"].isin(keep)]
    else:
        target = cons
        reference_pool = cons

    results = []
    for _, row in target.iterrows():
        amount = float(row["amount"])
        # Référence : même sous-catégorie, en excluant la ligne elle-même
        same_sub = reference_pool[(reference_pool["category"] == row["category"]) &
                                  (reference_pool["subcategory"] == row["subcategory"]) &
                                  (reference_pool["id"] != row["id"])]
        same_cat = reference_pool[(reference_pool["category"] == row["category"]) &
                                  (reference_pool["id"] != row["id"])]
        methods: list[str] = []
        ratio = np.nan
        st = None
        if len(same_sub) >= MIN_HISTORY:
            st = _stats(same_sub["amount"])
            methods, ratio = _score_row(amount, st, ratio_threshold)
            scope = row["subcategory"] or row["category"]
        elif len(same_cat) >= MIN_HISTORY:
            st = _stats(same_cat["amount"])
            methods, ratio = _score_row(amount, st, ratio_threshold)
            scope = row["category"]
        else:
            scope = row["category"]

        business_rule = (monthly_income > 0 and not row["recurring"] and amount > 0.25 * monthly_income)
        if business_rule:
            methods.append("règle métier (> 25 % du revenu)")

        # Une dépense récurrente (loyer, école...) est rarement une anomalie, sauf règle métier
        if row["recurring"] and not business_rule:
            continue

        flagged = len([m for m in methods if not m.startswith("règle")]) >= 2 or business_rule
        if not flagged:
            continue

        severity = "danger" if (business_rule or (ratio == ratio and ratio >= 2 * ratio_threshold)) else "warning"
        median = st["median"] if st else np.nan
        if st and median > 0:
            msg = (f"Dépense inhabituelle : {fmt_money(amount)} en {scope} le {row['date']:%d/%m/%Y}. "
                   f"C'est environ {ratio:.1f} fois votre montant habituel ({fmt_money(median)}, "
                   f"médiane de {st['n']} dépenses de référence).")
        else:
            msg = (f"Dépense très élevée : {fmt_money(amount)} en {scope} le {row['date']:%d/%m/%Y}, "
                   f"soit plus de 25 % de votre revenu mensuel.")
        if row["description"]:
            msg += f" Libellé : « {row['description']} »."
        results.append({
            "id": row["id"], "date": row["date"], "amount": amount,
            "category": row["category"], "subcategory": row["subcategory"],
            "description": row["description"], "reference_median": median,
            "ratio": ratio, "methods": ", ".join(methods), "severity": severity, "message": msg,
        })
    out = pd.DataFrame(results, columns=cols)
    return out.sort_values("amount", ascending=False).reset_index(drop=True)


def unusual_daily_totals(daily: pd.DataFrame, factor: float = 2.5) -> pd.DataFrame:
    """Jours dont le total dépasse `factor` x la médiane des jours avec dépense."""
    if daily.empty:
        return daily
    active = daily[daily["amount"] > 0]
    if len(active) < MIN_HISTORY:
        return daily.iloc[0:0]
    median = active["amount"].median()
    return active[active["amount"] > factor * median].assign(median=median)
