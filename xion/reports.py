from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from . import analysis, db

INTERVAL_DELTAS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
}


def generate_charts(df: pd.DataFrame, out_dir: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    trend = analysis.time_series_trend(df, freq="D")
    if not trend.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(trend["period"], trend["avg_rsrp"], marker="o")
        ax.set_title("Average Signal Strength Over Time")
        ax.set_xlabel("Date")
        ax.set_ylabel("RSRP (dBm)")
        fig.autofmt_xdate()
        fig.tight_layout()
        p = out_dir / "signal_trend.png"
        fig.savefig(p)
        plt.close(fig)
        paths.append(p)

    dist = analysis.call_type_distribution(df)
    if not dist.empty:
        fig, ax = plt.subplots(figsize=(5, 5))
        ax.pie(dist.values, labels=dist.index, autopct="%1.0f%%")
        ax.set_title("Call Type Distribution")
        fig.tight_layout()
        p = out_dir / "call_type_distribution.png"
        fig.savefig(p)
        plt.close(fig)
        paths.append(p)

    net_dist = analysis.network_type_distribution(df)
    if not net_dist.empty:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(net_dist.index.astype(str), net_dist.values)
        ax.set_title("Network Type Distribution")
        ax.set_ylabel("Records")
        fig.tight_layout()
        p = out_dir / "network_type_distribution.png"
        fig.savefig(p)
        plt.close(fig)
        paths.append(p)

    durations = df["duration"].dropna()
    if not durations.empty:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.hist(durations, bins=20)
        ax.set_title("Call Duration Distribution")
        ax.set_xlabel("Seconds")
        ax.set_ylabel("Calls")
        fig.tight_layout()
        p = out_dir / "call_duration_histogram.png"
        fig.savefig(p)
        plt.close(fig)
        paths.append(p)

    return paths


def export_csv(df: pd.DataFrame, out_path: Path) -> Path:
    df.to_csv(out_path, index=False)
    return out_path


def export_excel(df: pd.DataFrame, out_path: Path) -> Path:
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Records")
        summary = analysis.analyze_signal_strength(df)
        summary_df = pd.DataFrame([summary.__dict__])
        summary_df.to_excel(writer, index=False, sheet_name="Summary")
        analysis.top_cells_by_signal(df).to_excel(writer, index=False, sheet_name="Top Cells")
    return out_path


def export_pdf(df: pd.DataFrame, out_path: Path, charts_dir: Path, title: str = "Xion Report") -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                     Table, TableStyle, Image)
    from reportlab.lib import colors

    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]),
             Paragraph(datetime.now().strftime("Generated %Y-%m-%d %H:%M"), styles["Normal"]),
             Spacer(1, 16)]

    summary = analysis.analyze_signal_strength(df)
    story.append(Paragraph("Signal Summary", styles["Heading2"]))
    summary_rows = [["Metric", "Value"]] + [
        [k.replace("_", " ").title(), str(v)] for k, v in summary.__dict__.items()
    ]
    t = Table(summary_rows, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3542")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(t)
    story.append(Spacer(1, 16))

    charts = generate_charts(df, charts_dir)
    for chart_path in charts:
        story.append(Paragraph(chart_path.stem.replace("_", " ").title(), styles["Heading3"]))
        story.append(Image(str(chart_path), width=420, height=230))
        story.append(Spacer(1, 12))

    doc = SimpleDocTemplate(str(out_path), pagesize=letter)
    doc.build(story)
    return out_path


def is_report_due(db_path: Path, interval: str) -> bool:
    if interval not in INTERVAL_DELTAS:
        return False
    last = db.get_meta(db_path, "last_scheduled_report")
    if not last:
        return True
    last_dt = datetime.fromisoformat(last)
    return datetime.now() - last_dt >= INTERVAL_DELTAS[interval]


def mark_report_run(db_path: Path) -> None:
    db.set_meta(db_path, "last_scheduled_report", datetime.now().isoformat())
