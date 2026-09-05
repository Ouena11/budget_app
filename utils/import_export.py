"""
Import de dépenses depuis CSV / Excel et export (CSV, Excel, PDF).

Import : reconnaissance souple des colonnes (français/anglais, avec ou sans accents),
contrôle des dates et montants, normalisation des catégories vers celles de la base,
détection des doublons (dans le fichier et par rapport à la base). Rien n'est écrit
en base avant validation par l'utilisateur.
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd

from database.models import PAYMENT_METHODS
from utils.helpers import fmt_money, fmt_pct, normalize_text

# Synonymes acceptés pour chaque colonne cible (comparés après normalize_text)
COLUMN_ALIASES = {
    "date": ["date", "jour", "day", "date depense", "date de la depense"],
    "amount": ["montant", "amount", "somme", "prix", "total", "valeur", "value", "cout"],
    "category": ["categorie", "category", "cat", "poste", "type"],
    "subcategory": ["sous-categorie", "sous categorie", "souscategorie", "subcategory", "sub category", "sous_categorie"],
    "payment_method": ["moyen de paiement", "paiement", "payment", "payment method", "mode de paiement", "moyen"],
    "description": ["description", "libelle", "label", "commentaire", "note", "notes", "detail", "details"],
    "necessary": ["necessaire", "necessary", "essentiel", "essential", "indispensable"],
    "recurring": ["recurrente", "recurrent", "recurring", "fixe", "abonnement"],
}
YES_VALUES = {"oui", "yes", "o", "y", "1", "true", "vrai", "x"}
NO_VALUES = {"non", "no", "n", "0", "false", "faux", ""}


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
def read_uploaded_file(uploaded) -> pd.DataFrame:
    """Lit un fichier CSV (séparateur détecté) ou Excel (première feuille)."""
    name = getattr(uploaded, "name", "fichier").lower()
    data = uploaded.read() if hasattr(uploaded, "read") else uploaded
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(io.BytesIO(data))
    # CSV : essayer plusieurs encodages et laisser pandas deviner le séparateur
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return pd.read_csv(io.BytesIO(data), sep=None, engine="python", encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise ValueError("Impossible de lire le fichier : format ou encodage non reconnu.")


def detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """Associe chaque colonne cible à une colonne du fichier (ou None)."""
    normalized = {col: normalize_text(col) for col in df.columns}
    mapping: dict[str, str | None] = {}
    for target, aliases in COLUMN_ALIASES.items():
        found = None
        for col, norm in normalized.items():
            if norm in aliases or any(norm.startswith(a) for a in aliases if len(a) > 3):
                found = col
                break
        mapping[target] = found
    return mapping


# ---------------------------------------------------------------------------
# Nettoyage / validation
# ---------------------------------------------------------------------------
def _parse_amount(value) -> float | None:
    if value is None or (isinstance(value, float) and value != value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("FCFA", "").replace("XOF", "").replace(" ", "").replace("\xa0", "")
    text = text.replace(" ", "")
    # « 12 500,50 » -> 12500.50 ; « 12,500.50 » -> 12500.50
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".") if len(text.split(",")[-1]) <= 2 else text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value):
    """ISO (AAAA-MM-JJ) en priorité, sinon JJ/MM/AAAA ; datetime/Timestamp acceptés tels quels."""
    if value is None or (isinstance(value, float) and value != value):
        return pd.NaT
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value)
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return pd.to_datetime(text[:10], errors="coerce", format="%Y-%m-%d")
    return pd.to_datetime(text, errors="coerce", dayfirst=True)


def _parse_bool(value, default: bool) -> bool:
    if value is None or (isinstance(value, float) and value != value):
        return default
    if isinstance(value, bool):
        return value
    text = normalize_text(value)
    if text in YES_VALUES:
        return True
    if text in NO_VALUES:
        return default if text == "" else False
    return default


def _match_category(value, category_map: dict[str, list[str]]) -> tuple[str, str, bool]:
    """Retourne (catégorie, sous-catégorie déduite, reconnue ?)."""
    text = normalize_text(value)
    if not text:
        return "Autres", "", False
    for cat, subs in category_map.items():
        if normalize_text(cat) == text:
            return cat, "", True
    # Le fichier contient peut-être une sous-catégorie dans la colonne catégorie
    for cat, subs in category_map.items():
        for sub in subs:
            if normalize_text(sub) == text:
                return cat, sub, True
    # Correspondance partielle
    for cat, subs in category_map.items():
        if text in normalize_text(cat) or normalize_text(cat) in text:
            return cat, "", True
    return "Autres", "", False


def _match_subcategory(value, category: str, category_map: dict[str, list[str]]) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    text = normalize_text(value)
    if not text or text == "nan":
        return ""
    for sub in category_map.get(category, []):
        if normalize_text(sub) == text:
            return sub
    return str(value).strip()


def _match_payment(value) -> str:
    text = normalize_text(value)
    if not text:
        return "Espèces"
    for pm in PAYMENT_METHODS:
        if normalize_text(pm) == text or text in normalize_text(pm):
            return pm
    if "mobile" in text or "momo" in text or "orange" in text or "wave" in text or "mtn" in text:
        return "Mobile Money"
    if "carte" in text or "card" in text or "cb" == text:
        return "Carte bancaire"
    if "cash" in text or "espece" in text:
        return "Espèces"
    if "virement" in text or "transfer" in text:
        return "Virement"
    return "Autre"


def prepare_import(df: pd.DataFrame, mapping: dict, category_map: dict[str, list[str]],
                   existing: pd.DataFrame) -> pd.DataFrame:
    """
    Construit un tableau de prévisualisation avec, pour chaque ligne : les valeurs
    normalisées, un statut ('ok', 'doublon fichier', 'doublon base', 'erreur') et le détail.
    """
    if not mapping.get("date") or not mapping.get("amount") or not mapping.get("category"):
        raise ValueError("Les colonnes Date, Montant et Catégorie sont obligatoires.")
    rows = []
    key_cols = [mapping["date"], mapping["amount"], mapping["category"]]
    for i, r in df.iterrows():
        # Ligne vide (fréquent dans un modèle Excel pré-formaté) : ignorée
        if all(pd.isna(r[c]) or str(r[c]).strip() == "" for c in key_cols):
            continue
        problems = []
        d = _parse_date(r[mapping["date"]])
        if pd.isna(d):
            problems.append("date invalide")
        elif d.date() > date.today():
            problems.append("date dans le futur")
        amount = _parse_amount(r[mapping["amount"]])
        refund = False
        if amount is None:
            problems.append("montant invalide")
        elif amount == 0:
            problems.append("montant nul")
        elif amount < 0:
            refund = True   # accepté comme remboursement, signalé
        category, sub_from_cat, recognized = _match_category(r[mapping["category"]], category_map)
        if not recognized:
            problems.append(f"catégorie inconnue « {r[mapping['category']]} » → Autres")
        subcategory = _match_subcategory(r[mapping["subcategory"]], category, category_map) \
            if mapping.get("subcategory") else ""
        subcategory = subcategory or sub_from_cat
        payment = _match_payment(r[mapping["payment_method"]]) if mapping.get("payment_method") else "Espèces"
        description = str(r[mapping["description"]]).strip() if mapping.get("description") and pd.notna(r[mapping["description"]]) else ""
        necessary = _parse_bool(r[mapping["necessary"]], True) if mapping.get("necessary") else True
        recurring = _parse_bool(r[mapping["recurring"]], False) if mapping.get("recurring") else False
        rows.append({
            "ligne": i + 2, "date": d.date() if not pd.isna(d) else None, "amount": amount,
            "category": category, "subcategory": subcategory, "payment_method": payment,
            "description": description, "necessary": necessary, "recurring": recurring,
            "refund": refund, "problems": problems,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # Doublons dans le fichier
    key = out.apply(lambda r: (str(r["date"]), round(r["amount"] or 0, 2), r["category"], r["description"]), axis=1)
    dup_file = key.duplicated(keep="first")
    # Doublons par rapport à la base
    if existing is not None and not existing.empty:
        existing_keys = set(zip(existing["date"].dt.strftime("%Y-%m-%d"), existing["amount"].round(2),
                                existing["category"], existing["description"].fillna("")))
        dup_db = key.apply(lambda k: k in existing_keys)
    else:
        dup_db = pd.Series(False, index=out.index)

    def status(i):
        if out.loc[i, "problems"] and any(p in ("date invalide", "montant invalide", "montant nul") for p in out.loc[i, "problems"]):
            return "erreur"
        if dup_db[i]:
            return "doublon base"
        if dup_file[i]:
            return "doublon fichier"
        return "ok"

    out["status"] = [status(i) for i in out.index]
    out["detail"] = out["problems"].apply(lambda p: " ; ".join(p))
    return out


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def expenses_to_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Colonnes lisibles en français pour l'export."""
    if df.empty:
        return pd.DataFrame(columns=["Date", "Montant", "Catégorie", "Sous-catégorie", "Moyen de paiement",
                                     "Description", "Nécessaire", "Récurrente"])
    out = pd.DataFrame({
        "Date": df["date"].dt.strftime("%Y-%m-%d"),
        "Montant": df["amount"],
        "Catégorie": df["category"],
        "Sous-catégorie": df["subcategory"],
        "Moyen de paiement": df["payment_method"],
        "Description": df["description"],
        "Nécessaire": df["necessary"].map({True: "Oui", False: "Non"}),
        "Récurrente": df["recurring"].map({True: "Oui", False: "Non"}),
    })
    return out.sort_values("Date")


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")


def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name[:31], index=isinstance(df.index, pd.MultiIndex) or df.index.name is not None)
            ws = writer.sheets[name[:31]]
            for col in ws.columns:
                width = max((len(str(c.value)) if c.value is not None else 0) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(12, width + 2), 50)
    return buf.getvalue()


def _latin(text: str) -> str:
    """Les polices de base de fpdf2 sont limitées à latin-1 : on remplace le reste."""
    replacements = {"→": "->", "…": "...", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}
    for a, b in replacements.items():
        text = text.replace(a, b)
    return text.encode("latin-1", "replace").decode("latin-1")


def report_to_pdf_bytes(report: dict) -> bytes:
    """Rapport mensuel en PDF (fpdf2), sans dépendance réseau ni police externe."""
    from fpdf import FPDF

    k = report["kpis"]
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _latin(f"Rapport mensuel - {report['label']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _latin(f"Score financier : {report['score']['score']}/100 - {report['score']['label']}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    def section(title):
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _latin(title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)

    def line(text):
        pdf.multi_cell(0, 5.5, _latin(text), new_x="LMARGIN", new_y="NEXT")

    section("Résumé")
    line(f"Revenus : {fmt_money(k['income'])}" + (" (revenu de référence)" if k["income_is_reference"] else ""))
    line(f"Dépenses : {fmt_money(k['spent'])}  |  Budget : {fmt_money(k['budget_consumption'])}  |  "
         f"Consommation du budget : {fmt_pct(k['budget_usage'])}")
    line(f"Épargne : {fmt_money(k['savings'])}  |  Taux d'épargne : {fmt_pct(k['savings_rate'])}")
    line(f"Nombre de dépenses : {k['n_expenses']}  |  Dépense moyenne quotidienne : {fmt_money(k['avg_daily'])}")
    pdf.ln(2)

    section("Analyse")
    top = report["top_categories"]
    if not top.empty:
        line("Catégories les plus coûteuses : " + ", ".join(
            f"{r['category']} {fmt_money(r['amount'])} ({r['share']:.0f} %)" for _, r in top.iterrows()))
    inc = report["increased"]
    if not inc.empty:
        line("En hausse par rapport au mois précédent : " + ", ".join(
            f"{r['category']} {fmt_money(r['delta'])}" + (f" ({fmt_pct(r['delta_pct'], signed=True)})" if r['delta_pct'] == r['delta_pct'] else "")
            for _, r in inc.iterrows()))
    dec = report["decreased"]
    if not dec.empty:
        line("En baisse : " + ", ".join(
            f"{r['category']} {fmt_money(r['delta'])}" + (f" ({fmt_pct(r['delta_pct'], signed=True)})" if r['delta_pct'] == r['delta_pct'] else "")
            for _, r in dec.iterrows()))
    over = report["overruns"]
    if not over.empty:
        line("Dépassements : " + ", ".join(
            f"{r['category']} +{fmt_money(r['spent'] - r['budget'])} ({r['ratio'] * 100:.0f} % du budget)"
            for _, r in over.iterrows()))
    else:
        line("Aucun dépassement de budget par catégorie.")
    pdf.ln(2)

    section("Alertes")
    if report["alerts"]:
        for a in report["alerts"]:
            line(f"- [{a['level'].upper()}] {a['title']} : {a['message']}")
    else:
        line("Aucune alerte majeure ce mois-ci.")
    pdf.ln(2)

    section("Recommandations pour le mois suivant")
    for i, action in enumerate(report["next_actions"], 1):
        line(f"{i}. {action}")
    pdf.ln(2)

    section("Composantes du score")
    for name, pts, mx, expl in report["score"]["components"]:
        line(f"- {name} : {pts}/{mx}. {expl}")
    return bytes(pdf.output())


def import_template_csv() -> bytes:
    """Modèle de fichier CSV à remplir pour l'import."""
    sample = pd.DataFrame([
        {"Date": "2026-09-01", "Montant": 4500, "Catégorie": "Alimentation", "Sous-catégorie": "Courses",
         "Moyen de paiement": "Espèces", "Description": "Marché", "Nécessaire": "Oui", "Récurrente": "Non"},
        {"Date": "2026-09-03", "Montant": 100000, "Catégorie": "Logement", "Sous-catégorie": "Loyer",
         "Moyen de paiement": "Virement", "Description": "Loyer septembre", "Nécessaire": "Oui", "Récurrente": "Oui"},
    ])
    return to_csv_bytes(sample)
