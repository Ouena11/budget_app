"""Page Revenus : saisie, liste et modification des revenus."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from database import db
from database.models import INCOME_SOURCES
from utils import ui
from utils.helpers import fmt_money, month_bounds, month_label


def render(month: str) -> None:
    st.title(f"💰 Revenus — {month_label(month)}")
    first, last = month_bounds(month)
    incomes = db.get_incomes()
    month_inc = incomes[incomes["month"] == month] if not incomes.empty else incomes
    ref = db.get_setting_float("monthly_income") + db.get_setting_float("extra_income")

    c1, c2, c3 = st.columns(3)
    with c1:
        ui.kpi_card("Revenus du mois", fmt_money(month_inc["amount"].sum() if not month_inc.empty else 0),
                    f"{len(month_inc)} entrée(s)", "info")
    with c2:
        ui.kpi_card("Revenu de référence (profil)", fmt_money(ref), "utilisé si aucun revenu saisi")
    with c3:
        avg = incomes.groupby("month")["amount"].sum().mean() if not incomes.empty else 0
        ui.kpi_card("Moyenne mensuelle", fmt_money(avg), f"sur {incomes['month'].nunique() if not incomes.empty else 0} mois")

    st.subheader("Ajouter un revenu")
    with st.form("income_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        d = c1.date_input("Date", value=min(max(first, date.today()), last) if first <= date.today() <= last else first,
                          min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))
        amount = c2.number_input("Montant (FCFA)", min_value=0.0, step=1000.0, format="%.0f")
        source = c3.selectbox("Source", INCOME_SOURCES)
        note = st.text_input("Note (facultatif)")
        if st.form_submit_button("💾 Enregistrer", type="primary"):
            if amount <= 0:
                st.error("Le montant doit être supérieur à zéro.")
            else:
                db.add_income(d, amount, source, note)
                ui.flash(f"Revenu de {fmt_money(amount)} enregistré.")
                st.rerun()

    if month_inc.empty:
        st.caption("Astuce : si votre salaire est stable, renseignez-le une fois dans ⚙️ Paramètres ; "
                   "il servira de revenu de référence pour les mois sans saisie.")
        if ref > 0 and st.button(f"Reporter le revenu de référence ({fmt_money(ref)}) sur ce mois"):
            db.add_income(first, db.get_setting_float("monthly_income"), "Salaire", "Revenu de référence")
            extra = db.get_setting_float("extra_income")
            if extra > 0:
                db.add_income(first, extra, "Revenu supplémentaire", "Revenu de référence")
            st.rerun()

    st.subheader("Revenus enregistrés")
    show_all = st.checkbox("Afficher tous les mois", value=False)
    table = incomes if show_all else month_inc
    if table.empty:
        ui.empty_state("Aucun revenu enregistré.")
        return
    display = table[["id", "date", "amount", "source", "note"]].copy()
    display["date"] = display["date"].dt.date
    edited = st.data_editor(
        display, hide_index=True, width="stretch", key="income_editor",
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
            "amount": st.column_config.NumberColumn("Montant (FCFA)", min_value=0, step=1000, format="%d"),
            "source": st.column_config.SelectboxColumn("Source", options=INCOME_SOURCES),
            "note": st.column_config.TextColumn("Note"),
        },
    )
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("💾 Enregistrer les modifications", key="save_incomes"):
            changed = 0
            for _, row in edited.iterrows():
                orig = display[display["id"] == row["id"]].iloc[0]
                if not orig.equals(row):
                    db.update_income(int(row["id"]), row["date"], float(row["amount"]), row["source"], row["note"] or "")
                    changed += 1
            ui.flash(f"{changed} revenu(s) mis à jour.")
            st.rerun()
    with c2:
        to_delete = st.selectbox("Supprimer un revenu", options=[None] + list(display["id"]),
                                 format_func=lambda i: "—" if i is None else
                                 f"#{i} · {display.loc[display['id'] == i, 'date'].iloc[0]:%d/%m} · "
                                 f"{fmt_money(display.loc[display['id'] == i, 'amount'].iloc[0])}")
        if to_delete is not None and ui.confirm_delete(f"income_{to_delete}"):
            db.delete_income(int(to_delete))
            ui.flash("Revenu supprimé.")
            st.rerun()
