"""Page Dépenses : saisie rapide, liste filtrable, modification/suppression, import et export."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from database import db
from database.models import PAYMENT_METHODS
from utils import import_export as ie
from utils import ui
from utils.helpers import fmt_money, month_bounds, month_label


def _entry_form(month: str, category_map: dict) -> None:
    st.subheader("➕ Saisie rapide")
    first, last = month_bounds(month)
    today = date.today()
    default_date = today if first <= today <= last else last
    categories = list(category_map.keys())

    c1, c2 = st.columns([1, 1])
    category = c1.selectbox("Catégorie", categories, key="exp_category")
    subs = category_map.get(category, [])
    subcategory = c2.selectbox("Sous-catégorie", subs + ["(autre)"] if subs else ["(autre)"], key="exp_subcategory")
    if subcategory == "(autre)":
        subcategory = c2.text_input("Précisez la sous-catégorie", key="exp_subcategory_free")

    with st.form("expense_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        d = c1.date_input("Date", value=default_date, min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))
        amount = c2.number_input("Montant (FCFA)", min_value=0.0, step=500.0, format="%.0f")
        payment = c3.selectbox("Moyen de paiement", PAYMENT_METHODS)
        description = st.text_input("Description (facultatif)")
        c1, c2, c3 = st.columns(3)
        necessary = c1.radio("Dépense nécessaire ?", ["Oui", "Non"], horizontal=True) == "Oui"
        recurring = c2.radio("Dépense récurrente ?", ["Non", "Oui"], horizontal=True) == "Oui"
        refund = c3.checkbox("Remboursement (montant déduit)")
        force = st.checkbox("Enregistrer même si une dépense semblable existe déjà (ce n'est pas un doublon)")
        submitted = st.form_submit_button("💾 Enregistrer la dépense", type="primary")
        if submitted:
            if amount <= 0:
                st.error("Le montant doit être supérieur à zéro.")
                return
            signed = -abs(amount) if refund else amount
            if not refund and not force and db.expense_exists(d, signed, category):
                st.warning("Une dépense semblable (même jour, même montant, même catégorie) existe déjà : elle n'a "
                           "pas été enregistrée une seconde fois. Si c'est bien une nouvelle dépense, cochez "
                           "« Enregistrer même si… » et validez à nouveau.")
                return
            try:
                db.add_expense(d, signed, category, subcategory, payment, description, necessary, recurring, refund)
            except ValueError as e:
                st.error(str(e))
                return
            st.success(f"{'Remboursement' if refund else 'Dépense'} de {fmt_money(abs(amount))} en {category}"
                       f"{' › ' + subcategory if subcategory else ''} enregistré{'' if refund else 'e'}.")
            st.rerun()


def _list_and_edit(month: str, category_map: dict) -> None:
    st.subheader("📋 Dépenses enregistrées")
    all_exp = db.get_expenses()
    show_all = st.checkbox("Afficher tous les mois", value=False, key="exp_show_all")
    table = all_exp if show_all else (all_exp[all_exp["month"] == month] if not all_exp.empty else all_exp)

    c1, c2, c3 = st.columns(3)
    cat_filter = c1.multiselect("Filtrer par catégorie", list(category_map.keys()), key="exp_filter_cat")
    pay_filter = c2.multiselect("Moyen de paiement", PAYMENT_METHODS, key="exp_filter_pay")
    search = c3.text_input("Rechercher dans la description", key="exp_search")
    if cat_filter:
        table = table[table["category"].isin(cat_filter)]
    if pay_filter:
        table = table[table["payment_method"].isin(pay_filter)]
    if search:
        table = table[table["description"].str.contains(search, case=False, na=False)]

    if table.empty:
        ui.empty_state("Aucune dépense ne correspond.")
        return
    st.caption(f"{len(table)} opérations · total {fmt_money(table['amount'].sum())}")

    display = table[["id", "date", "amount", "category", "subcategory", "payment_method",
                     "description", "necessary", "recurring"]].copy()
    display["date"] = display["date"].dt.date
    all_subs = sorted({s for subs in category_map.values() for s in subs} | set(display["subcategory"]) - {""})
    edited = st.data_editor(
        display, hide_index=True, width="stretch", key="expense_editor", height=420,
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
            "amount": st.column_config.NumberColumn("Montant", step=100, format="%d"),
            "category": st.column_config.SelectboxColumn("Catégorie", options=list(category_map.keys())),
            "subcategory": st.column_config.SelectboxColumn("Sous-catégorie", options=[""] + all_subs),
            "payment_method": st.column_config.SelectboxColumn("Paiement", options=PAYMENT_METHODS),
            "description": st.column_config.TextColumn("Description"),
            "necessary": st.column_config.CheckboxColumn("Nécessaire"),
            "recurring": st.column_config.CheckboxColumn("Récurrente"),
        },
    )
    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button("💾 Enregistrer les modifications", key="save_expenses"):
            changed, errors = 0, []
            for _, row in edited.iterrows():
                orig = display[display["id"] == row["id"]].iloc[0]
                if orig.equals(row):
                    continue
                try:
                    db.update_expense(int(row["id"]), date=row["date"], amount=float(row["amount"]),
                                      category=row["category"], subcategory=row["subcategory"] or "",
                                      payment_method=row["payment_method"], description=row["description"] or "",
                                      necessary=bool(row["necessary"]), recurring=bool(row["recurring"]),
                                      refund=float(row["amount"]) < 0)
                    changed += 1
                except ValueError as e:
                    errors.append(f"#{row['id']} : {e}")
            if errors:
                st.error("\n".join(errors))
            st.success(f"{changed} dépense(s) mise(s) à jour.")
            if not errors:
                st.rerun()
    with c2:
        to_delete = st.selectbox(
            "Supprimer une dépense", options=[None] + list(display["id"]),
            format_func=lambda i: "—" if i is None else
            f"#{i} · {display.loc[display['id'] == i, 'date'].iloc[0]:%d/%m} · "
            f"{display.loc[display['id'] == i, 'category'].iloc[0]} · "
            f"{fmt_money(display.loc[display['id'] == i, 'amount'].iloc[0])}",
            key="exp_delete_select")
        if to_delete is not None and ui.confirm_delete(f"expense_{to_delete}"):
            db.delete_expense(int(to_delete))
            ui.flash("Dépense supprimée.")
            st.rerun()


def _import_section(category_map: dict) -> None:
    st.subheader("📥 Importer un historique (CSV / Excel)")
    st.caption("Colonnes reconnues : Date, Montant, Catégorie (obligatoires) ; Sous-catégorie, Moyen de paiement, "
               "Description, Nécessaire, Récurrente (facultatives). Les noms proches sont acceptés.")
    st.download_button("Télécharger un modèle CSV", ie.import_template_csv(), "modele_import_depenses.csv", "text/csv")
    uploaded = st.file_uploader("Fichier à importer", type=["csv", "xlsx", "xls"], key="import_file")
    if not uploaded:
        return
    try:
        raw = ie.read_uploaded_file(uploaded)
    except Exception as e:  # noqa: BLE001
        st.error(f"Lecture impossible : {e}")
        return
    st.write(f"{len(raw)} lignes lues. Aperçu :")
    st.dataframe(raw.head(5), width="stretch")

    detected = ie.detect_columns(raw)
    st.markdown("**Correspondance des colonnes** (corrigez si besoin)")
    cols = [None] + list(raw.columns)
    mapping = {}
    labels = {"date": "Date *", "amount": "Montant *", "category": "Catégorie *", "subcategory": "Sous-catégorie",
              "payment_method": "Moyen de paiement", "description": "Description", "necessary": "Nécessaire",
              "recurring": "Récurrente"}
    grid = st.columns(4)
    for i, (target, label) in enumerate(labels.items()):
        default = detected.get(target)
        mapping[target] = grid[i % 4].selectbox(label, cols, index=cols.index(default) if default in cols else 0,
                                                key=f"map_{target}")
    try:
        preview = ie.prepare_import(raw, mapping, category_map, db.get_expenses())
    except ValueError as e:
        st.error(str(e))
        return
    counts = preview["status"].value_counts().to_dict()
    st.markdown(f"✅ Prêtes : **{counts.get('ok', 0)}** · 🔁 Doublons dans le fichier : **{counts.get('doublon fichier', 0)}** · "
                f"🗄️ Déjà en base : **{counts.get('doublon base', 0)}** · ❌ Erreurs : **{counts.get('erreur', 0)}**")
    st.dataframe(preview[["ligne", "date", "amount", "category", "subcategory", "payment_method", "description",
                          "necessary", "recurring", "status", "detail"]], width="stretch", height=300)
    include_dups = st.checkbox("Importer aussi les doublons du fichier", value=False)
    to_import = preview[preview["status"].isin(["ok"] + (["doublon fichier"] if include_dups else []))]
    if st.button(f"📥 Importer {len(to_import)} dépense(s)", type="primary", disabled=to_import.empty):
        rows = to_import.drop(columns=["ligne", "problems", "status", "detail"]).to_dict("records")
        n = db.bulk_insert_expenses(rows)
        ui.flash(f"{n} dépense(s) importée(s).")
        st.rerun()


def _export_section(month: str) -> None:
    st.subheader("📤 Exporter")
    all_exp = db.get_expenses()
    scope = st.radio("Périmètre", [f"Mois ({month_label(month)})", "Tout l'historique"], horizontal=True, key="export_scope")
    data = all_exp if scope.startswith("Tout") else (all_exp[all_exp["month"] == month] if not all_exp.empty else all_exp)
    frame = ie.expenses_to_export_frame(data)
    suffix = "tout" if scope.startswith("Tout") else month
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ CSV", ie.to_csv_bytes(frame), f"depenses_{suffix}.csv", "text/csv", disabled=frame.empty)
    c2.download_button("⬇️ Excel", ie.to_excel_bytes({"Dépenses": frame}), f"depenses_{suffix}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", disabled=frame.empty)


def render(month: str) -> None:
    st.title(f"💸 Dépenses — {month_label(month)}")
    category_map = db.get_category_map()
    tab1, tab2, tab3 = st.tabs(["Saisie et liste", "Importer", "Exporter"])
    with tab1:
        _entry_form(month, category_map)
        st.divider()
        _list_and_edit(month, category_map)
    with tab2:
        _import_section(category_map)
    with tab3:
        _export_section(month)
