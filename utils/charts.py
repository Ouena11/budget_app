"""
Graphiques Plotly. Chaque fonction renvoie une figure prête pour st.plotly_chart.
Palette sobre et cohérente ; les montants sont affichés avec séparateur de milliers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from utils.helpers import LEVEL_COLORS, month_short

PALETTE = ["#1f5f8b", "#2e8b57", "#d17a22", "#7b4ea3", "#c0392b", "#16a085",
           "#8e6c3a", "#5d6d7e", "#b7950b", "#884ea0"]
TEMPLATE = "plotly_white"
MONEY_FMT = ",.0f"


def _layout(fig: go.Figure, title: str = "", height: int = 380, **kwargs) -> go.Figure:
    fig.update_layout(
        template=TEMPLATE, title=title, height=height, margin=dict(l=10, r=10, t=50 if title else 20, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        separators=". ",  # séparateur décimal « . », milliers « espace »
        **kwargs,
    )
    fig.update_yaxes(tickformat=MONEY_FMT, ticksuffix=" F")
    return fig


# 1. Évolution quotidienne + moyenne mobile 7 j
def daily_chart(daily: pd.DataFrame, budget_daily: float | None = None) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=daily["date"], y=daily["amount"], name="Dépense du jour", marker_color="#9ec5e8",
                hovertemplate="%{x|%d/%m}<br>%{y:,.0f} FCFA<extra></extra>")
    fig.add_scatter(x=daily["date"], y=daily["rolling7"], name="Moyenne mobile 7 j", mode="lines",
                    line=dict(color="#1f5f8b", width=3),
                    hovertemplate="%{x|%d/%m}<br>Moy. 7 j : %{y:,.0f} FCFA<extra></extra>")
    if budget_daily:
        fig.add_hline(y=budget_daily, line_dash="dot", line_color=LEVEL_COLORS["warning"],
                      annotation_text="Rythme budget/jour", annotation_position="top left")
    fig.update_xaxes(tickformat="%d/%m")
    return _layout(fig, "Évolution quotidienne des dépenses")


# Cumul du mois vs cumul budget (utile pour voir le rythme)
def cumulative_chart(daily: pd.DataFrame, budget: float, n_days: int) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=daily["date"], y=daily["cumulative"], name="Dépenses cumulées", mode="lines",
                    fill="tozeroy", line=dict(color="#1f5f8b", width=3),
                    hovertemplate="%{x|%d/%m}<br>Cumul : %{y:,.0f} FCFA<extra></extra>")
    if budget > 0 and len(daily):
        start = daily["date"].iloc[0]
        end = start + pd.Timedelta(days=n_days - 1)
        fig.add_scatter(x=[start, end], y=[budget / n_days, budget], name="Rythme budget", mode="lines",
                        line=dict(color=LEVEL_COLORS["warning"], dash="dot"))
    fig.update_xaxes(tickformat="%d/%m")
    return _layout(fig, "Dépenses cumulées vs rythme du budget", height=320)


# 2. Évolution mensuelle
def monthly_chart(monthly: pd.DataFrame) -> go.Figure:
    labels = [month_short(m) for m in monthly["month"]]
    fig = go.Figure()
    fig.add_bar(x=labels, y=monthly["consumption"], name="Dépenses", marker_color="#1f5f8b",
                hovertemplate="%{x}<br>Dépenses : %{y:,.0f} FCFA<extra></extra>")
    fig.add_scatter(x=labels, y=monthly["income"], name="Revenus", mode="lines+markers",
                    line=dict(color="#2e8b57", width=2),
                    hovertemplate="%{x}<br>Revenus : %{y:,.0f} FCFA<extra></extra>")
    if len(monthly) >= 3:
        x = np.arange(len(monthly))
        coef = np.polyfit(x, monthly["consumption"].values, 1)
        fig.add_scatter(x=labels, y=np.polyval(coef, x), name="Tendance dépenses", mode="lines",
                        line=dict(color="#d17a22", dash="dash"))
    return _layout(fig, "Évolution mensuelle des dépenses")


# 3. Dépenses par catégorie (barres)
def category_bar(cats: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=cats["amount"], y=cats["category"], orientation="h",
        marker_color=PALETTE[: len(cats)] if len(cats) <= len(PALETTE) else "#1f5f8b",
        text=[f"{v:,.0f}".replace(",", " ") for v in cats["amount"]], textposition="outside",
        hovertemplate="%{y}<br>%{x:,.0f} FCFA<extra></extra>",
    ))
    fig = _layout(fig, "Dépenses par catégorie", height=max(300, 40 * len(cats) + 80))
    fig.update_yaxes(autorange="reversed", tickformat=None, ticksuffix="")
    fig.update_xaxes(tickformat=MONEY_FMT, ticksuffix=" F", range=[0, float(cats["amount"].max()) * 1.3])
    return fig


# 4. Évolution d'une catégorie dans le temps
def category_trend_chart(pivot: pd.DataFrame, category: str) -> go.Figure:
    s = pivot[category] if category in pivot.columns else pd.Series(dtype=float)
    labels = [month_short(m) for m in s.index]
    fig = go.Figure()
    fig.add_scatter(x=labels, y=s.values, mode="lines+markers", name=category,
                    line=dict(color="#1f5f8b", width=3),
                    hovertemplate="%{x}<br>%{y:,.0f} FCFA<extra></extra>")
    if len(s) >= 3:
        x = np.arange(len(s))
        coef = np.polyfit(x, s.values, 1)
        fig.add_scatter(x=labels, y=np.polyval(coef, x), name="Tendance", mode="lines",
                        line=dict(color="#d17a22", dash="dash"))
    return _layout(fig, f"Évolution : {category}", height=340)


# Toutes les catégories empilées par mois
def stacked_monthly_chart(pivot: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    labels = [month_short(m) for m in pivot.index]
    for i, cat in enumerate(pivot.columns):
        fig.add_bar(x=labels, y=pivot[cat], name=cat, marker_color=PALETTE[i % len(PALETTE)],
                    hovertemplate="%{x}<br>" + cat + " : %{y:,.0f} FCFA<extra></extra>")
    fig.update_layout(barmode="stack")
    return _layout(fig, "Répartition mensuelle par catégorie", height=400)


# 5. Budget prévu vs réel
def budget_vs_actual_chart(bva: pd.DataFrame) -> go.Figure:
    data = bva[(bva["budget"] > 0) | (bva["spent"] > 0)]
    colors = [LEVEL_COLORS.get(lv, "#1f5f8b") for lv in data["level"]]
    fig = go.Figure()
    fig.add_bar(x=data["category"], y=data["budget"], name="Budget prévu", marker_color="#cfd8dc",
                hovertemplate="%{x}<br>Budget : %{y:,.0f} FCFA<extra></extra>")
    fig.add_bar(x=data["category"], y=data["spent"], name="Dépenses réelles", marker_color=colors,
                hovertemplate="%{x}<br>Réel : %{y:,.0f} FCFA<extra></extra>")
    if "projected" in data:
        fig.add_scatter(x=data["category"], y=data["projected"], name="Prévision fin de mois", mode="markers",
                        marker=dict(symbol="line-ew-open", size=22, color="#333", line=dict(width=2)),
                        hovertemplate="%{x}<br>Prévision : %{y:,.0f} FCFA<extra></extra>")
    fig.update_layout(barmode="group")
    return _layout(fig, "Budget prévu vs dépenses réelles", height=400)


# 6. Répartition (donut)
def donut_chart(cats: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Pie(labels=cats["category"], values=cats["amount"], hole=0.55,
                           marker=dict(colors=PALETTE), textinfo="label+percent",
                           hovertemplate="%{label}<br>%{value:,.0f} FCFA (%{percent})<extra></extra>"))
    fig.update_layout(template=TEMPLATE, title="Répartition des dépenses", height=380,
                      margin=dict(l=10, r=10, t=50, b=10), showlegend=False)
    return fig


# 7. Évolution de l'épargne
def savings_chart(monthly: pd.DataFrame, goal_monthly: float = 0.0) -> go.Figure:
    labels = [month_short(m) for m in monthly["month"]]
    fig = go.Figure()
    colors = [LEVEL_COLORS["ok"] if v >= 0 else LEVEL_COLORS["danger"] for v in monthly["savings"]]
    fig.add_bar(x=labels, y=monthly["savings"], name="Épargne mensuelle", marker_color=colors,
                hovertemplate="%{x}<br>Épargne : %{y:,.0f} FCFA<extra></extra>")
    fig.add_scatter(x=labels, y=monthly["cumulative_savings"], name="Épargne cumulée", mode="lines+markers",
                    line=dict(color="#1f5f8b", width=3), yaxis="y2",
                    hovertemplate="%{x}<br>Cumul : %{y:,.0f} FCFA<extra></extra>")
    if goal_monthly > 0:
        fig.add_hline(y=goal_monthly, line_dash="dot", line_color=LEVEL_COLORS["warning"],
                      annotation_text="Objectif mensuel", annotation_position="top left")
    fig = _layout(fig, "Évolution de l'épargne", height=400)
    fig.update_layout(yaxis2=dict(title="Cumul", overlaying="y", side="right", tickformat=MONEY_FMT, ticksuffix=" F",
                                  showgrid=False))
    return fig


# Jour de la semaine
def weekday_chart(wd: pd.DataFrame) -> go.Figure:
    overall = wd.attrs.get("overall_avg", wd["avg_per_day"].mean() if len(wd) else 0)
    colors = [LEVEL_COLORS["danger"] if v > overall * 1.2 else "#1f5f8b" for v in wd["avg_per_day"]]
    fig = go.Figure(go.Bar(x=wd["weekday_name"], y=wd["avg_per_day"], marker_color=colors,
                           hovertemplate="%{x}<br>Moyenne : %{y:,.0f} FCFA/jour<extra></extra>"))
    if overall:
        fig.add_hline(y=overall, line_dash="dot", line_color="#666", annotation_text="Moyenne")
    return _layout(fig, "Dépense moyenne par jour de la semaine", height=340)


# Jauge du score
def score_gauge(score: int) -> go.Figure:
    color = LEVEL_COLORS["ok"] if score >= 80 else "#f9a825" if score >= 60 else "#ef6c00" if score >= 40 else LEVEL_COLORS["danger"]
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score, number=dict(suffix=" / 100", font=dict(size=34)),
        gauge=dict(axis=dict(range=[0, 100]), bar=dict(color=color, thickness=0.3),
                   steps=[dict(range=[0, 40], color="#fde0dc"), dict(range=[40, 60], color="#ffe8cc"),
                          dict(range=[60, 80], color="#fff6c2"), dict(range=[80, 100], color="#dcf2df")]),
    ))
    fig.update_layout(height=220, margin=dict(l=20, r=20, t=20, b=10), template=TEMPLATE)
    return fig


# Objectif : barre de progression
def goal_progress_chart(name: str, current: float, target: float) -> go.Figure:
    pct = min(current / target * 100, 100) if target else 0
    fig = go.Figure(go.Bar(x=[pct], y=[name], orientation="h", marker_color=LEVEL_COLORS["ok"] if pct >= 100 else "#1f5f8b",
                           text=f"{pct:.0f} %", textposition="inside" if pct > 15 else "outside",
                           hovertemplate=f"{current:,.0f} / {target:,.0f} FCFA<extra></extra>"))
    fig.update_xaxes(range=[0, 100], showticklabels=False, showgrid=False)
    fig.update_yaxes(showticklabels=False)
    fig.update_layout(height=70, margin=dict(l=5, r=5, t=5, b=5), template=TEMPLATE, showlegend=False)
    return fig


# Calendrier (heatmap mensuelle)
def calendar_heatmap(daily: pd.DataFrame, month_label: str) -> go.Figure:
    """Grille lundi→dimanche x semaines, couleur = montant du jour."""
    if daily.empty:
        return go.Figure()
    df = daily.copy()
    df["weekday"] = df["date"].dt.weekday
    first_wd = df["date"].iloc[0].weekday()
    df["week"] = ((df["date"].dt.day - 1 + first_wd) // 7)
    n_weeks = int(df["week"].max()) + 1
    z = np.full((n_weeks, 7), np.nan)
    text = np.full((n_weeks, 7), "", dtype=object)
    for _, r in df.iterrows():
        z[int(r["week"]), int(r["weekday"])] = r["amount"]
        dom = r.get("dominant", "")
        text[int(r["week"]), int(r["weekday"])] = (
            f"<b>{r['date'].day}</b><br>{r['amount']:,.0f} F<br>{int(r['count'])} op." + (f"<br>{dom}" if dom else "")
        ).replace(",", " ")
    fig = go.Figure(go.Heatmap(
        z=z, x=["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"], y=[f"S{i + 1}" for i in range(n_weeks)],
        text=text, texttemplate="%{text}", colorscale=[[0, "#f1f8e9"], [0.5, "#ffe082"], [1, "#e53935"]],
        showscale=True, colorbar=dict(title="FCFA", tickformat=MONEY_FMT), xgap=3, ygap=3,
        hovertemplate="%{text}<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(template=TEMPLATE, title=f"Calendrier des dépenses — {month_label}", separators=". ",
                      height=120 + 90 * n_weeks, margin=dict(l=10, r=10, t=50, b=10))
    return fig
