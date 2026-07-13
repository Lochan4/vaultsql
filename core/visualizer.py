"""
visualizer.py

Auto-selects chart type based on data shape and generates a matplotlib
figure returned as a base64 PNG string for rendering in the chat UI.

Chart selection logic:
  - 1 numeric col, no grouping     → single metric (big number display)
  - 1 categorical + 1 numeric      → horizontal bar chart
  - 1 date/time + 1 numeric        → line chart
  - 1 categorical + multiple nums  → grouped bar chart
  - 2+ numeric cols                → scatter plot (first two)
  - All text / unrecognised        → table only (no chart)
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from enum import Enum

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use("Agg")   # non-interactive backend — no display needed


class ChartType(str, Enum):
    BAR         = "bar"
    LINE        = "line"
    GROUPED_BAR = "grouped_bar"
    SCATTER     = "scatter"
    METRIC      = "metric"       # single KPI number
    NONE        = "none"         # table only


@dataclass
class VisualizationResult:
    chart_type: ChartType
    image_b64: str      # base64 PNG, empty if chart_type == NONE
    title: str


_FIG_SIZE = (8, 4)
_STYLE = "seaborn-v0_8-whitegrid"

# Column name patterns that suggest date/time
_DATE_PATTERNS = ("date", "time", "at", "day", "week", "month", "year", "period")


def visualize(df: pd.DataFrame, question: str) -> VisualizationResult:
    """
    Auto-select chart type and generate a base64 PNG.

    Args:
        df:       DataFrame from executor.py
        question: Original NL question (used for chart title)

    Returns:
        VisualizationResult with chart type and base64 image.
        Returns chart_type=NONE with empty image if no chart is appropriate.
    """
    if df.empty or len(df.columns) == 0:
        return VisualizationResult(ChartType.NONE, "", question)

    chart_type = _select_chart_type(df)

    if chart_type == ChartType.NONE:
        return VisualizationResult(ChartType.NONE, "", question)

    try:
        image_b64 = _render(df, chart_type, question)
        return VisualizationResult(chart_type, image_b64, question)
    except Exception:
        # Chart generation is best-effort — never block the response
        return VisualizationResult(ChartType.NONE, "", question)


# ------------------------------------------------------------------
# Chart type selection
# ------------------------------------------------------------------

def _select_chart_type(df: pd.DataFrame) -> ChartType:
    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(include=["object", "category", "bool"]).columns.tolist()
    date_cols = [c for c in df.columns if _is_date_col(df, c)]

    n_rows = len(df)

    # Single numeric value — KPI metric
    if len(df.columns) == 1 and len(num_cols) == 1 and n_rows == 1:
        return ChartType.METRIC

    # Date + numeric → line chart
    if date_cols and num_cols:
        return ChartType.LINE

    # Categorical + multiple numerics → grouped bar
    if cat_cols and len(num_cols) > 1:
        return ChartType.GROUPED_BAR

    # Categorical + single numeric → horizontal bar
    if cat_cols and len(num_cols) == 1:
        return ChartType.BAR

    # Two+ numerics → scatter
    if len(num_cols) >= 2:
        return ChartType.SCATTER

    return ChartType.NONE


def _is_date_col(df: pd.DataFrame, col: str) -> bool:
    """Heuristic: column is date-like if its name contains a date keyword
    or if it can be parsed as datetime."""
    col_lower = col.lower()
    if any(p in col_lower for p in _DATE_PATTERNS):
        return True
    try:
        pd.to_datetime(df[col], errors="raise")
        return True
    except Exception:
        return False


# ------------------------------------------------------------------
# Chart rendering
# ------------------------------------------------------------------

def _render(df: pd.DataFrame, chart_type: ChartType, title: str) -> str:
    """Render chart to base64 PNG string."""
    plt.style.use(_STYLE)
    fig, ax = plt.subplots(figsize=_FIG_SIZE)
    fig.patch.set_facecolor("#FAFAFA")
    ax.set_facecolor("#FAFAFA")

    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(include=["object", "category", "bool"]).columns.tolist()
    date_cols = [c for c in df.columns if _is_date_col(df, c)]

    if chart_type == ChartType.METRIC:
        val = df.iloc[0, 0]
        ax.text(
            0.5, 0.5, f"{val:,}" if isinstance(val, (int, float)) else str(val),
            ha="center", va="center", fontsize=36, fontweight="bold",
            transform=ax.transAxes,
        )
        ax.axis("off")

    elif chart_type == ChartType.BAR:
        x_col = cat_cols[0]
        y_col = num_cols[0]
        plot_df = df[[x_col, y_col]].head(20)  # cap at 20 bars
        ax.barh(plot_df[x_col].astype(str), plot_df[y_col], color="#4C72B0")
        ax.set_xlabel(y_col.replace("_", " ").title())
        ax.set_ylabel(x_col.replace("_", " ").title())

    elif chart_type == ChartType.LINE:
        x_col = date_cols[0]
        y_col = num_cols[0]
        plot_df = df[[x_col, y_col]].sort_values(x_col)
        ax.plot(plot_df[x_col].astype(str), plot_df[y_col],
                marker="o", color="#4C72B0", linewidth=2)
        ax.set_xlabel(x_col.replace("_", " ").title())
        ax.set_ylabel(y_col.replace("_", " ").title())
        plt.xticks(rotation=30, ha="right")

    elif chart_type == ChartType.GROUPED_BAR:
        x_col = cat_cols[0]
        plot_df = df[[x_col] + num_cols[:4]].head(15).set_index(x_col)
        plot_df.plot(kind="bar", ax=ax, colormap="tab10")
        ax.set_xlabel(x_col.replace("_", " ").title())
        plt.xticks(rotation=30, ha="right")
        ax.legend(loc="upper right", fontsize=8)

    elif chart_type == ChartType.SCATTER:
        x_col, y_col = num_cols[0], num_cols[1]
        ax.scatter(df[x_col], df[y_col], alpha=0.6, color="#4C72B0")
        ax.set_xlabel(x_col.replace("_", " ").title())
        ax.set_ylabel(y_col.replace("_", " ").title())

    # Truncate title to avoid overflow
    display_title = title[:80] + "..." if len(title) > 80 else title
    ax.set_title(display_title, fontsize=10, pad=10)

    plt.tight_layout()
    return _fig_to_b64(fig)


def _fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")
