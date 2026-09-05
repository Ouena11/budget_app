"""Page Alertes : toutes les alertes du mois, classées par gravité, avec l'état de chaque budget."""
from __future__ import annotations

import streamlit as st

from analytics.recommendations import build_context, generate_alerts
from utils import ui
from utils.helpers import LEVEL_ICONS, fmt_money, month_label


def render(month: str) -> None:
    st.title(f"🚨 Alertes — {month_label(month)}")
    ctx = build_context(month)
    alerts = generate_alerts(ctx)
    counts = {lvl: sum(1 for a in alerts if a["level"] == lvl) for lvl in ("danger", "warning", "info", "ok")}
    overall = "danger" if counts["danger"] else "warning" if counts["warning"] else "ok"
    labels = {"danger": "Situation critique", "warning": "Attention", "ok": "Situation normale"}

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        ui.kpi_card("État général", f"{LEVEL_ICONS[overall]} {labels[overall]}", None, overall)
    with c2:
        ui.kpi_card("Alertes critiques", str(counts["danger"]), None, "danger" if counts["danger"] else None)
    with c3:
        ui.kpi_card("Avertissements", str(counts["warning"]), None, "warning" if counts["warning"] else None)
    with c4:
        ui.kpi_card("Informations", str(counts["info"]), None, "info" if counts["info"] else None)

    st.caption("Seuils : 🟡 à partir de 80 % du budget (réglable dans Paramètres) ou rythme menant à un "
               "dépassement ; 🔴 budget dépassé, dépassement prévisionnel important, dépense inhabituelle majeure.")

    filt = st.multiselect("Filtrer par niveau", ["danger", "warning", "info", "ok"],
                          default=["danger", "warning", "info", "ok"],
                          format_func=lambda l: f"{LEVEL_ICONS[l]} {l}", key="alert_filter")
    for a in alerts:
        if a["level"] in filt:
            ui.alert_box(a)

    st.divider()
    st.subheader("État des budgets par catégorie")
    bva = ctx["bva"]
    if bva.empty:
        ui.empty_state("Aucun budget ni dépense pour ce mois.")
        return
    show = bva[["category", "budget", "spent", "remaining", "ratio", "projected", "level"]].copy()
    show["ratio"] = (show["ratio"] * 100).round(0)
    show["level"] = show["level"].map(LEVEL_ICONS)
    show = show.rename(columns={"category": "Catégorie", "budget": "Budget", "spent": "Dépensé", "remaining": "Restant",
                                "ratio": "Consommé", "projected": "Prévision", "level": "État"})
    st.dataframe(
        ui.money_table(show, ["Budget", "Dépensé", "Restant", "Prévision"]),
        hide_index=True, width="stretch",
        column_config={
            "Consommé": st.column_config.ProgressColumn(format="%.0f %%", min_value=0, max_value=150),
        },
    )
    st.caption(f"Mois écoulé à {ctx['kpis']['month_progress']:.0f} %. La prévision par catégorie prolonge uniquement "
               f"la part variable des dépenses et ajoute les charges récurrentes attendues.")
