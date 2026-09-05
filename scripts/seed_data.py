"""
Génère des données fictives réalistes pour tester l'application (6 mois d'historique,
le mois courant partiellement rempli), avec quelques dépenses volontairement
inhabituelles pour vérifier la détection d'anomalies.

Usage :  python scripts/seed_data.py            (conserve la base si elle contient déjà des dépenses)
         python scripts/seed_data.py --reset    (efface et regénère)
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import db  # noqa: E402
from utils.helpers import month_key, previous_month, month_bounds  # noqa: E402

random.seed(42)

MONTHLY_INCOME = 450_000
EXTRA_INCOME = 50_000

BUDGETS = {
    "Logement": 135_000, "Alimentation": 100_000, "Transport": 45_000, "Famille": 30_000,
    "Santé": 15_000, "Loisirs": 25_000, "Communication": 15_000, "Éducation": 10_000,
    "Finance": 60_000, "Autres": 10_000,
}

# Charges fixes mensuelles : (jour, catégorie, sous-catégorie, montant, moyen, libellé)
FIXED = [
    (3, "Logement", "Loyer", 100_000, "Virement", "Loyer appartement"),
    (6, "Logement", "Électricité", 14_000, "Mobile Money", "Facture CIE"),
    (8, "Logement", "Eau", 6_000, "Mobile Money", "Facture SODECI"),
    (10, "Logement", "Internet", 12_000, "Mobile Money", "Abonnement fibre"),
    (5, "Communication", "Téléphone", 10_000, "Mobile Money", "Forfait mobile"),
    (12, "Loisirs", "Abonnements", 6_500, "Carte bancaire", "Netflix + Spotify"),
    (2, "Finance", "Épargne", 50_000, "Virement", "Virement épargne"),
    (15, "Famille", "Aide familiale", 20_000, "Mobile Money", "Aide parents"),
]

# Dépenses variables : (catégorie, sous-catégorie, prob/jour, min, max, nécessaire)
VARIABLE = [
    ("Alimentation", "Courses", 0.35, 2_000, 9_000, True),
    ("Alimentation", "Restaurant", 0.12, 2_500, 6_000, False),
    ("Alimentation", "Livraison", 0.05, 3_000, 7_000, False),
    ("Alimentation", "Snacks", 0.30, 300, 1_500, False),
    ("Transport", "Taxi", 0.22, 800, 3_000, True),
    ("Transport", "Transport en commun", 0.40, 200, 800, True),
    ("Transport", "Carburant", 0.05, 8_000, 15_000, True),
    ("Loisirs", "Sorties", 0.06, 3_000, 12_000, False),
    ("Santé", "Médicaments", 0.05, 1_500, 8_000, True),
    ("Famille", "Cadeaux", 0.03, 5_000, 15_000, False),
    ("Éducation", "Livres", 0.03, 3_000, 9_000, True),
    ("Autres", "Divers", 0.06, 500, 4_000, False),
]

PAYMENTS = ["Espèces", "Mobile Money", "Mobile Money", "Carte bancaire"]


def generate(today: date | None = None) -> None:
    today = today or date.today()
    current = month_key(today)
    months = [previous_month(current, i) for i in range(6, 0, -1)] + [current]

    for i, m in enumerate(months):
        first, last = month_bounds(m)
        end = min(last, today)
        # Revenus
        db.add_income(first, MONTHLY_INCOME, "Salaire", "Salaire mensuel")
        if random.random() < 0.6 and first <= today:
            db.add_income(first + timedelta(days=random.randint(5, 20)),
                          random.choice([30_000, 50_000, 75_000]), "Activité secondaire", "Mission freelance")
        # Budgets
        for cat, amount in BUDGETS.items():
            db.set_budget(m, cat, amount)
        # Charges fixes
        for day, cat, sub, amount, pay, label in FIXED:
            d = first.replace(day=day)
            if d <= end:
                db.add_expense(d, amount, cat, sub, pay, label, necessary=(cat != "Loisirs"), recurring=True)
        # Dérive progressive des dépenses de transport et loisirs (pour voir une tendance)
        drift = 1 + 0.05 * i
        d = first
        while d <= end:
            weekend = d.weekday() >= 5
            for cat, sub, prob, lo, hi, necessary in VARIABLE:
                p = prob * (1.5 if weekend and cat in ("Alimentation", "Loisirs") else 1.0)
                if random.random() < p:
                    amount = random.randint(lo, hi)
                    if cat in ("Transport", "Loisirs"):
                        amount = int(amount * drift)
                    amount = round(amount / 100) * 100
                    db.add_expense(d, amount, cat, sub, random.choice(PAYMENTS), "", necessary, False)
            d += timedelta(days=1)

    # Anomalies volontaires
    m_prev = previous_month(current)
    first_prev, _ = month_bounds(m_prev)
    db.add_expense(first_prev.replace(day=18), 25_000, "Alimentation", "Restaurant", "Carte bancaire",
                   "Dîner d'anniversaire", necessary=False, recurring=False)
    cur_first, _ = month_bounds(current)
    if today.day >= 2:
        db.add_expense(cur_first.replace(day=2), 45_000, "Santé", "Consultations", "Espèces",
                       "Consultation spécialiste + examens", necessary=True, recurring=False)
    if today.day >= 3:
        db.add_expense(cur_first.replace(day=3), 18_000, "Transport", "Taxi", "Espèces",
                       "Taxi aéroport aller-retour", necessary=True, recurring=False)
    # Un remboursement (montant négatif autorisé)
    db.add_expense(first_prev.replace(day=20), -4_000, "Alimentation", "Livraison", "Mobile Money",
                   "Remboursement commande annulée", necessary=False, recurring=False, refund=True)

    # Profil et objectifs
    db.set_setting("user_name", "Edouard")
    db.set_setting("monthly_income", MONTHLY_INCOME)
    db.set_setting("extra_income", EXTRA_INCOME)
    db.set_setting("savings_start", 350_000)
    db.set_setting("savings_goal_monthly", 80_000)
    db.set_setting("main_goal", "Épargne de sécurité")
    db.add_goal("Épargne de sécurité", 1_000_000, 350_000, str(today.replace(year=today.year + 1)), True)
    db.add_goal("Voyage", 400_000, 120_000, str((today + timedelta(days=240))), False)
    db.add_goal("Voiture", 3_500_000, 500_000, str(today.replace(year=today.year + 3)), False)


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    if reset:
        db.reset_db()
    else:
        db.init_db()
    if not reset and not db.get_expenses().empty:
        print("La base contient déjà des dépenses. Utilisez --reset pour la regénérer.")
        sys.exit(0)
    generate()
    n = len(db.get_expenses())
    print(f"Données fictives générées : {n} dépenses dans {db.DB_PATH}")
