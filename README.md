# Pilotage budgétaire personnel

Application locale (Streamlit + SQLite) pour suivre son budget au jour le jour, comparer
les dépenses au budget prévu, prévoir la fin de mois, repérer les dépenses inhabituelles
et recevoir des recommandations chiffrées. Devise par défaut : FCFA. Fonctionne sans
connexion Internet ; les données restent dans `data/budget.db`.

## Installation (Windows)

1. Installer Python 3.10 ou plus récent depuis python.org (cocher « Add Python to PATH »).
2. Décompresser le dossier `budget_app` où vous voulez.
3. Double-cliquer sur `run.bat`. Au premier lancement, il crée un environnement virtuel
   et installe les dépendances (quelques minutes), puis ouvre l'application dans le navigateur.

À la main, dans un terminal ouvert dans le dossier :

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

macOS / Linux : `./run.sh` ou les mêmes commandes avec `source .venv/bin/activate`.

L'application s'ouvre sur http://localhost:8501. Pour l'arrêter : Ctrl+C dans le terminal.

## Premiers pas

- **Données de démonstration** : `python scripts/seed_data.py --reset` génère six mois
  d'historique fictif (ou : Paramètres › Données › « Charger des données fictives »).
  Utile pour découvrir les analyses avant d'avoir son propre historique.
- **Base vide** : `python scripts/init_db.py` (fait automatiquement au premier lancement).
- Ensuite : Paramètres › Profil (revenu, objectif d'épargne), Paramètres › Budgets
  (montant par catégorie pour le mois), puis saisie des dépenses dans 💸 Dépenses.
- Le mois analysé se choisit dans la barre latérale et s'applique à toutes les pages.

## Ce que fait l'application

| Page | Contenu |
| --- | --- |
| 🏠 Dashboard | KPI du mois (revenu, dépenses, épargne, restant, taux d'épargne, score), courbe quotidienne + moyenne mobile 7 j, dépenses par catégorie, budget vs réel, alertes et recommandations prioritaires |
| 💰 Revenus | Saisie, modification, suppression des revenus ; revenu de référence si rien n'est saisi |
| 💸 Dépenses | Saisie rapide (catégorie, sous-catégorie, paiement, nécessaire/récurrente, remboursement), liste filtrable et éditable, suppression avec confirmation, import CSV/Excel avec contrôle des doublons, export CSV/Excel |
| 📊 Analyses | Réponses aux questions clés, répartition (donut + sous-catégories), jour de la semaine, dépenses évitables et récurrentes, anomalies, comparaison de mois, rapport mensuel (PDF, Excel) |
| 📈 Évolution | Dépenses mois par mois avec tendance, évolution par catégorie, épargne mensuelle et cumulée, détail de la prévision |
| 🎯 Objectifs | Objectifs multiples, progression, mensualité recommandée, durée estimée |
| 🚨 Alertes | Toutes les alertes du mois (🟢 🟡 🔴) et l'état de chaque budget |
| 🤖 Recommandations | Score sur 100 expliqué, recommandations chiffrées, plan d'action pour le mois suivant |
| 📅 Calendrier | Grille du mois : montant, nombre d'opérations, catégorie dominante par jour |
| ⚙️ Paramètres | Profil, budgets, catégories (ajout/modification/suppression), seuils d'alerte, sauvegarde et réinitialisation |

## Comment sont faits les calculs (à savoir pour interpréter)

**Dépenses de consommation vs épargne.** Les lignes Finance › Épargne et Finance ›
Investissement sont de l'argent mis de côté, pas de la consommation. Elles n'entrent pas
dans « Dépenses » ni dans le taux d'épargne ; elles apparaissent à part (« mis de côté »).
Sans cette règle, faire un virement vers son épargne ferait baisser le taux d'épargne.

**Épargne du mois** = revenus du mois − dépenses de consommation. Si aucun revenu n'est
saisi pour un mois, le revenu de référence du profil est utilisé et signalé comme tel.

**Prévision de fin de mois** (`analytics/forecasting.py`) = dépensé à ce jour
+ rythme variable × jours restants + charges récurrentes attendues mais pas encore payées.
Le rythme variable exclut les charges récurrentes déjà payées (un loyer réglé le 3 ne se
répète pas) et les dépenses détectées comme inhabituelles (un examen médical exceptionnel
ne se prolonge pas). En début de mois, le rythme observé est lissé avec la moyenne des
trois mois précédents (poids équivalent à 15 jours d'observation) ; plus le mois avance,
plus les données réelles pèsent. Une fourchette basse/haute est affichée pour rappeler
qu'il s'agit d'une estimation. La même logique s'applique catégorie par catégorie.

**Anomalies** (`analytics/anomaly_detection.py`) : une dépense est signalée quand au
moins deux méthodes la retiennent parmi ratio à la médiane (> 3× par défaut), z-score
robuste (MAD > 3,5) et IQR (> Q3 + 1,5 IQR), sur au moins 5 dépenses de référence de la
même sous-catégorie (ou catégorie), ou quand une dépense non récurrente dépasse 25 % du
revenu mensuel. Les charges récurrentes ne sont pas testées.

**Score financier** (`analytics/calculations.py`, `financial_score`) sur 100 :
respect du budget 30 (prévision de fin de mois / budget, malus par catégorie déjà
dépassée), taux d'épargne projeté 25 (20 % = maximum), évolution vs 3 mois précédents 15,
régularité journalière 10, poids des dépenses non essentielles 10, progression des
objectifs 10. Chaque composante est affichée avec son explication : c'est une aide à la
lecture, pas un verdict.

**Alertes** : 🟡 à partir de 80 % du budget (réglable) ou quand le rythme mène à un
dépassement ; 🔴 budget dépassé, dépassement prévisionnel global supérieur à 10 % du
budget, dépense inhabituelle majeure, épargne prévue négative.

**Jour de la semaine** : total de chaque jour de semaine divisé par le nombre réel de ces
jours dans la période (les jours sans dépense comptent zéro), ce qui évite de surestimer
les jours rares.

Pas de machine learning dans cette version : statistiques descriptives, ratios, seuils et
comparaisons historiques suffisent et restent explicables. scikit-learn est dans les
dépendances pour une évolution ultérieure (par exemple un modèle de prévision entraîné sur
plusieurs mois de saisie réelle), une fois qu'il y aura assez de données pour qu'il
apporte quelque chose.

## Structure du projet

```text
budget_app/
├── app.py                    # point d'entrée, navigation, mois sélectionné
├── pages/                    # une fonction render(month) par page
│   ├── dashboard.py  incomes.py  expenses.py  analysis.py  evolution.py
│   ├── goals.py  alerts.py  recommendations.py  calendar.py  settings.py
├── database/
│   ├── models.py             # schéma SQL, catégories et paramètres par défaut
│   └── db.py                 # accès SQLite (CRUD, DataFrames typés)
├── analytics/
│   ├── calculations.py       # KPI, budget vs réel, séries, jour de semaine, score
│   ├── forecasting.py        # prévision de fin de mois
│   ├── anomaly_detection.py  # dépenses inhabituelles
│   └── recommendations.py    # contexte, alertes, recommandations, rapport mensuel
├── utils/
│   ├── helpers.py            # formatage FCFA, mois, texte
│   ├── charts.py             # graphiques Plotly
│   ├── ui.py                 # composants Streamlit (cartes, encadrés, sélecteur de mois)
│   └── import_export.py      # import CSV/Excel, export CSV/Excel/PDF
├── scripts/
│   ├── init_db.py            # création de la base
│   └── seed_data.py          # données fictives (--reset pour regénérer)
├── data/budget.db            # base SQLite (créée au premier lancement)
├── .streamlit/config.toml    # thème, navigation latérale désactivée
├── requirements.txt
├── run.bat / run.sh
└── README.md
```

Le moteur (`database/`, `analytics/`, `utils/helpers.py`, `utils/import_export.py`)
n'importe jamais Streamlit : il peut être réutilisé tel quel derrière une API (FastAPI)
ou une autre interface. Le chemin de la base se change avec la variable d'environnement
`BUDGET_DB_PATH`.

## Mise en ligne sur Streamlit Community Cloud

1. Créer un compte sur github.com et un dépôt **privé** (par exemple `budget_app`), y envoyer
   tout le dossier sauf `data/budget.db` et `.streamlit/secrets.toml` (déjà exclus par `.gitignore`).
   Avec GitHub Desktop : *Add local repository* › choisir le dossier › *Publish repository* (cocher « private »).
2. Sur share.streamlit.io, se connecter avec GitHub, *Create app* › *Deploy a public app from GitHub* :
   dépôt `budget_app`, branche `main`, fichier principal `app.py`.
3. Avant de cliquer sur *Deploy*, ouvrir *Advanced settings* › **Secrets** et coller :
   `APP_PASSWORD = "votre-mot-de-passe"`. Sans cette ligne, l'application est accessible à
   quiconque a l'adresse.
4. Déployer. L'adresse est du type `https://<nom>.streamlit.app`.

**Important : les données ne sont pas conservées durablement sur Streamlit Cloud.** Le fichier
`data/budget.db` est recréé vide à chaque redémarrage (mise à jour du code, inactivité de
plusieurs jours, maintenance). Après chaque session de saisie, téléchargez la sauvegarde
(Paramètres › Données › « Télécharger une sauvegarde ») ; au redémarrage, restaurez-la
(même onglet › « Restaurer une sauvegarde »). Pour un stockage réellement durable, il faut
une base en ligne (Postgres gratuit chez Supabase ou Neon) : `database/db.py` est le seul
module à adapter.

## Import de fichiers

Format attendu : une ligne par dépense, avec au minimum les colonnes Date, Montant et
Catégorie (les noms proches sont reconnus : « montant », « amount », « libellé »…).
Un modèle CSV est téléchargeable dans l'onglet Importer. L'application détecte les
doublons dans le fichier et par rapport à la base, normalise les catégories vers celles
existantes (inconnue → Autres, signalé) et n'écrit rien avant validation.

## Sauvegarde

Toute la donnée est dans `data/budget.db`. Copier ce fichier suffit (bouton de
téléchargement dans Paramètres › Données). Pour repartir de zéro : supprimer le fichier
ou utiliser « Effacer toutes les données ».

## Limites connues

- Mono-utilisateur, pas d'authentification : c'est une application locale.
- Les prévisions restent des projections simples ; avec moins d'un mois d'historique,
  elles s'appuient surtout sur le rythme observé et sont donc fragiles.
- Le PDF utilise les polices de base (latin-1) : les emojis n'y figurent pas.
