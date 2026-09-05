"""
Point d'entrée de l'application « Pilotage budgétaire personnel ».

Lancement :  streamlit run app.py

La navigation est gérée ici (menu latéral) plutôt que par le mécanisme multi-pages
automatique de Streamlit, afin de contrôler l'ordre, les icônes et le mois sélectionné
partagé entre toutes les pages. Chaque page expose une fonction render().
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Permet d'importer les modules du projet quel que soit le répertoire de lancement
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402
from utils import ui  # noqa: E402
from utils.helpers import month_label  # noqa: E402

st.set_page_config(
    page_title="Pilotage budgétaire",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Crée la base et les valeurs par défaut au premier lancement (idempotent)
db.init_db()
ui.inject_css()


def check_password() -> bool:
    """Protection par mot de passe, active seulement si APP_PASSWORD est défini dans
    les secrets Streamlit (.streamlit/secrets.toml en local, onglet Secrets sur
    Streamlit Cloud). Sans secret, l'application reste ouverte : usage local."""
    try:
        expected = st.secrets.get("APP_PASSWORD", "")
    except Exception:  # noqa: BLE001 — pas de fichier secrets.toml
        expected = ""
    if not expected:
        return True
    if st.session_state.get("authenticated"):
        return True
    st.markdown("## 💰 Pilotage budgétaire")
    pwd = st.text_input("Mot de passe", type="password")
    if st.button("Entrer", type="primary") or pwd:
        if pwd == expected:
            st.session_state["authenticated"] = True
            st.rerun()
        elif pwd:
            st.error("Mot de passe incorrect.")
    return False


if not check_password():
    st.stop()

PAGES = {
    "🏠 Dashboard": "dashboard",
    "💰 Revenus": "incomes",
    "💸 Dépenses": "expenses",
    "📊 Analyses": "analysis",
    "📈 Évolution": "evolution",
    "🎯 Objectifs": "goals",
    "🚨 Alertes": "alerts",
    "🤖 Recommandations": "recommendations",
    "📅 Calendrier": "calendar",
    "⚙️ Paramètres": "settings",
}

with st.sidebar:
    name = db.get_setting("user_name") or "Bienvenue"
    st.markdown(f"## 💰 Pilotage budgétaire")
    st.caption(f"Profil : **{name}**")
    choice = st.radio("Navigation", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()
    month = ui.month_selector("Mois analysé")
    st.caption(f"Toutes les pages analysent **{month_label(month)}**.")
    st.divider()
    if st.session_state.get("authenticated"):
        st.caption("⚠️ Hébergé en ligne : pensez à télécharger une sauvegarde (Paramètres › Données) "
                   "après vos saisies, le serveur peut être réinitialisé.")
        if st.button("Se déconnecter"):
            st.session_state["authenticated"] = False
            st.rerun()
    else:
        st.caption("Données stockées localement dans `data/budget.db`. Aucune connexion Internet requise.")

module_name = PAGES[choice]
page = __import__(f"pages.{module_name}", fromlist=["render"])
ui.show_flash()
page.render(month)
