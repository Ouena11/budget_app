"""
Schéma de la base SQLite et valeurs par défaut (catégories, moyens de paiement, objectifs).
Les tables sont créées par database/db.py à partir de SCHEMA.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'FCFA',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Paramètres du profil financier (clé/valeur pour rester souple)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    subcategories TEXT NOT NULL DEFAULT '',   -- séparées par '|'
    essential INTEGER NOT NULL DEFAULT 0,     -- 1 = catégorie essentielle par défaut
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS incomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                       -- AAAA-MM-JJ
    amount REAL NOT NULL CHECK (amount >= 0),
    source TEXT NOT NULL DEFAULT 'Salaire',
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                       -- AAAA-MM-JJ
    amount REAL NOT NULL,                     -- négatif autorisé uniquement pour un remboursement
    category TEXT NOT NULL,
    subcategory TEXT DEFAULT '',
    payment_method TEXT DEFAULT 'Espèces',
    description TEXT DEFAULT '',
    necessary INTEGER NOT NULL DEFAULT 1,     -- 1 = nécessaire
    recurring INTEGER NOT NULL DEFAULT 0,     -- 1 = récurrente
    refund INTEGER NOT NULL DEFAULT 0,        -- 1 = remboursement (montant négatif accepté)
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date);
CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month TEXT NOT NULL,                      -- AAAA-MM
    category TEXT NOT NULL,
    amount REAL NOT NULL CHECK (amount >= 0),
    UNIQUE (month, category)
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_amount REAL NOT NULL CHECK (target_amount > 0),
    current_amount REAL NOT NULL DEFAULT 0,
    target_date TEXT,                         -- AAAA-MM-JJ, optionnel
    is_main INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Catégories par défaut : (nom, sous-catégories, essentielle)
DEFAULT_CATEGORIES = [
    ("Logement", ["Loyer", "Eau", "Électricité", "Internet", "Entretien"], 1),
    ("Alimentation", ["Courses", "Restaurant", "Livraison", "Snacks"], 1),
    ("Transport", ["Carburant", "Taxi", "Transport en commun", "Entretien véhicule"], 1),
    ("Famille", ["Aide familiale", "Cadeaux", "Dépenses familiales"], 0),
    ("Santé", ["Médicaments", "Consultations", "Soins"], 1),
    ("Loisirs", ["Sorties", "Divertissement", "Abonnements"], 0),
    ("Communication", ["Téléphone", "Internet"], 1),
    ("Éducation", ["Formation", "Livres", "Frais scolaires"], 1),
    ("Finance", ["Épargne", "Investissement", "Remboursement de dette"], 1),
    ("Autres", ["Divers"], 0),
]

# Les sous-catégories dont le montant est considéré comme évitable, même dans une
# catégorie essentielle (ex. : restaurant dans Alimentation). Sert à l'analyse "dépenses évitables".
AVOIDABLE_SUBCATEGORIES = {"Restaurant", "Livraison", "Snacks", "Taxi", "Sorties",
                           "Divertissement", "Abonnements", "Cadeaux"}

PAYMENT_METHODS = ["Espèces", "Mobile Money", "Carte bancaire", "Virement", "Autre"]

INCOME_SOURCES = ["Salaire", "Revenu supplémentaire", "Prime", "Activité secondaire",
                  "Remboursement reçu", "Autre"]

GOAL_TYPES = ["Épargne de sécurité", "Achat d'une maison", "Mariage", "Investissement",
              "Voiture", "Voyage", "Création d'entreprise", "Autre"]

# Clés de la table settings avec leurs valeurs par défaut
DEFAULT_SETTINGS = {
    "user_name": "",
    "currency": "FCFA",
    "monthly_income": "0",         # revenu mensuel de référence (salaire)
    "extra_income": "0",           # revenus supplémentaires habituels
    "savings_start": "0",          # épargne disponible en début de mois
    "savings_goal_monthly": "0",   # objectif d'épargne mensuel
    "main_goal": "",               # objectif financier principal (nom)
    "alert_warn_ratio": "0.8",     # seuil d'alerte jaune (80 % du budget)
    "anomaly_ratio": "3.0",        # une dépense > 3x la médiane est inhabituelle
}
