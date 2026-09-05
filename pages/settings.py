"""Page Paramètres : profil financier, budgets par catégorie, catégories, seuils, données."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from database import db
from database.models import GOAL_TYPES
from utils import ui
from utils.helpers import fmt_money, month_label, previous_month


def _profile() -> None:
    st.subheader("👤 Profil financier")
    s = db.get_settings()
    goals = db.get_goals()
    with st.form("profile_form"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Nom", s.get("user_name", ""))
        currency = c2.text_input("Devise", s.get("currency", "FCFA"), disabled=True,
                                 help="Le FCFA est la devise par défaut ; le libellé est fixe dans cette version.")
        c1, c2, c3 = st.columns(3)
        income = c1.number_input("Revenu mensuel (FCFA)", min_value=0.0, value=float(s.get("monthly_income") or 0), step=10000.0, format="%.0f")
        extra = c2.number_input("Revenus supplémentaires habituels", min_value=0.0, value=float(s.get("extra_income") or 0), step=5000.0, format="%.0f")
        savings_start = c3.number_input("Épargne disponible en début de mois", min_value=0.0, value=float(s.get("savings_start") or 0), step=10000.0, format="%.0f")
        c1, c2 = st.columns(2)
        savings_goal = c1.number_input("Objectif d'épargne mensuel", min_value=0.0, value=float(s.get("savings_goal_monthly") or 0), step=5000.0, format="%.0f")
        goal_names = list(goals["name"]) if not goals.empty else []
        options = goal_names + [g for g in GOAL_TYPES if g not in goal_names]
        current_main = s.get("main_goal") or (options[0] if options else "")
        main_goal = c2.selectbox("Objectif financier principal", options,
                                 index=options.index(current_main) if current_main in options else 0)
        st.caption("Le montant nécessaire et la date cible de l'objectif principal se gèrent dans la page 🎯 Objectifs.")
        if st.form_submit_button("💾 Enregistrer le profil", type="primary"):
            db.set_setting("user_name", name.strip())
            db.set_setting("monthly_income", income)
            db.set_setting("extra_income", extra)
            db.set_setting("savings_start", savings_start)
            db.set_setting("savings_goal_monthly", savings_goal)
            db.set_setting("main_goal", main_goal)
            if not goals.empty and main_goal in goal_names:
                row = goals[goals["name"] == main_goal].iloc[0]
                db.update_goal(int(row["id"]), row["name"], row["target_amount"], row["current_amount"],
                               row["target_date"].date() if row["target_date"] == row["target_date"] else None, True)
            ui.flash("Profil enregistré.")
            st.rerun()
    goal, inc = float(s.get("savings_goal_monthly") or 0), float(s.get("monthly_income") or 0)
    if inc and goal:
        st.caption(f"Objectif d'épargne = {goal / inc * 100:.0f} % du revenu mensuel.")


def _budgets(month: str) -> None:
    st.subheader(f"💼 Budgets par catégorie — {month_label(month)}")
    cats = db.get_categories()
    budgets = db.get_budgets(month)
    prev = previous_month(month)
    prev_budgets = db.get_budgets(prev)
    if budgets.empty and not prev_budgets.empty:
        if st.button(f"Reprendre les budgets de {month_label(prev)} ({fmt_money(prev_budgets['amount'].sum())})"):
            db.copy_budgets(prev, month)
            st.rerun()
    existing = dict(zip(budgets["category"], budgets["amount"])) if not budgets.empty else {}
    table = pd.DataFrame({"Catégorie": cats["name"], "Budget": [float(existing.get(c, 0.0)) for c in cats["name"]]})
    edited = st.data_editor(table, hide_index=True, width="stretch", key="budget_editor",
                            column_config={"Catégorie": st.column_config.TextColumn(disabled=True),
                                           "Budget": st.column_config.NumberColumn("Budget mensuel (FCFA)", min_value=0, step=5000, format="%d")})
    total = float(edited["Budget"].sum())
    finance = float(edited.loc[edited["Catégorie"] == "Finance", "Budget"].sum())
    income = db.get_setting_float("monthly_income") + db.get_setting_float("extra_income")
    st.markdown(f"Total : **{fmt_money(total)}** (dont Finance/épargne {fmt_money(finance)}, consommation "
                f"{fmt_money(total - finance)})" + (f" — soit {total / income * 100:.0f} % du revenu de référence." if income else "."))
    if income and total > income:
        st.warning("Le total des budgets dépasse le revenu de référence.")
    c1, c2 = st.columns(2)
    if c1.button("💾 Enregistrer les budgets", type="primary", key="save_budgets"):
        for _, r in edited.iterrows():
            db.set_budget(month, r["Catégorie"], float(r["Budget"] or 0))
        ui.flash("Budgets enregistrés.")
        st.rerun()
    if c2.button("Appliquer aussi aux 3 mois suivants", key="copy_budgets_forward"):
        from utils.helpers import next_month
        m = month
        for _ in range(3):
            m = next_month(m)
            for _, r in edited.iterrows():
                db.set_budget(m, r["Catégorie"], float(r["Budget"] or 0))
        st.success("Budgets copiés sur les trois mois suivants.")


def _categories() -> None:
    st.subheader("🗂️ Catégories et sous-catégories")
    cats = db.get_categories()
    st.caption("Renommer une catégorie met à jour les dépenses et budgets existants. Supprimer une catégorie "
               "réaffecte ses dépenses à « Autres ».")
    for _, c in cats.iterrows():
        with st.expander(f"{c['name']}  ·  {', '.join(c['subcategories']) or 'aucune sous-catégorie'}"):
            with st.form(f"cat_{c['id']}"):
                name = st.text_input("Nom", c["name"])
                subs = st.text_input("Sous-catégories (séparées par des virgules)", ", ".join(c["subcategories"]))
                essential = st.checkbox("Catégorie essentielle", value=bool(c["essential"]),
                                        help="Les dépenses d'une catégorie non essentielle sont considérées comme évitables.")
                if st.form_submit_button("💾 Enregistrer"):
                    try:
                        db.update_category(int(c["id"]), name, [s.strip() for s in subs.split(",")], essential)
                        ui.flash("Catégorie mise à jour.")
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Impossible : {e}")
            if c["name"] != "Autres" and ui.confirm_delete(f"cat_{c['id']}", "Supprimer cette catégorie"):
                db.delete_category(int(c["id"]))
                st.rerun()
    with st.form("new_cat"):
        st.markdown("**Ajouter une catégorie**")
        c1, c2 = st.columns(2)
        name = c1.text_input("Nom de la catégorie")
        subs = c2.text_input("Sous-catégories (virgules)")
        essential = st.checkbox("Catégorie essentielle", value=False, key="new_cat_essential")
        if st.form_submit_button("➕ Ajouter"):
            try:
                db.add_category(name, [s for s in subs.split(",")], essential)
                ui.flash("Catégorie ajoutée.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Impossible : {e}")


def _thresholds() -> None:
    st.subheader("🎚️ Seuils d'alerte et d'anomalie")
    s = db.get_settings()
    with st.form("thresholds"):
        c1, c2 = st.columns(2)
        warn = c1.slider("Alerte 🟡 à partir de … % du budget", 50, 95, int(float(s.get("alert_warn_ratio", 0.8)) * 100), 5)
        ratio = c2.slider("Dépense inhabituelle si > … × la médiane habituelle", 2.0, 6.0, float(s.get("anomaly_ratio", 3.0)), 0.5)
        if st.form_submit_button("💾 Enregistrer les seuils"):
            db.set_setting("alert_warn_ratio", warn / 100)
            db.set_setting("anomaly_ratio", ratio)
            ui.flash("Seuils enregistrés.")
            st.rerun()


def _data() -> None:
    st.subheader("🗄️ Données")
    st.markdown(f"Base SQLite : `{db.DB_PATH}`")
    n = len(db.get_expenses())
    st.caption(f"{n} dépenses enregistrées. Sauvegardez régulièrement le fichier de base (copie du fichier .db).")
    if db.DB_PATH.exists():
        st.download_button("⬇️ Télécharger une sauvegarde de la base", db.DB_PATH.read_bytes(),
                           f"budget_backup_{date.today():%Y%m%d}.db", "application/octet-stream")
    st.markdown("**Restaurer une sauvegarde**")
    up = st.file_uploader("Fichier .db téléchargé précédemment", type=["db", "sqlite", "sqlite3"], key="restore_db")
    if up is not None:
        st.warning("La restauration remplace toutes les données actuelles par celles de la sauvegarde.")
        if st.button("✅ Restaurer cette sauvegarde", type="primary"):
            data_bytes = up.read()
            if not data_bytes.startswith(b"SQLite format 3"):
                st.error("Ce fichier n'est pas une base SQLite valide.")
            else:
                db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                db.DB_PATH.write_bytes(data_bytes)
                db.init_db()   # ajoute les tables/paramètres manquants si la sauvegarde est ancienne
                ui.flash(f"Sauvegarde restaurée : {len(db.get_expenses())} dépenses.")
                st.rerun()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Charger des données fictives de démonstration", help="Remplace toutes les données actuelles."):
            st.session_state["confirm_seed"] = True
        if st.session_state.get("confirm_seed"):
            st.warning("Cette action efface toutes les données existantes.")
            if st.button("✅ Oui, remplacer par les données de démonstration", type="primary"):
                from scripts.seed_data import generate
                db.reset_db()
                generate()
                st.session_state["confirm_seed"] = False
                ui.flash("Données de démonstration chargées.")
                st.rerun()
    with c2:
        if ui.confirm_delete("reset_all", "Effacer toutes les données"):
            db.reset_db()
            ui.flash("Base réinitialisée.")
            st.rerun()


def render(month: str) -> None:
    st.title("⚙️ Paramètres")
    tabs = st.tabs(["Profil", "Budgets", "Catégories", "Seuils", "Données"])
    with tabs[0]:
        _profile()
    with tabs[1]:
        _budgets(month)
    with tabs[2]:
        _categories()
    with tabs[3]:
        _thresholds()
    with tabs[4]:
        _data()
