from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import streamlit as st

# `streamlit run xion/webapp.py` executes this file as a top-level script
# (no package context), so relative imports ("from . import ...") raise
# "ImportError: attempted relative import with no known parent package".
# Make sure the project root is importable, then use absolute imports so
# the app works both as `streamlit run xion/webapp.py` and as `python -m xion.webapp`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xion import analysis, coverage, db, importer, reports
from xion.config import load_config

st.set_page_config(page_title="Xion", layout="wide")

cfg = load_config()
db_path = cfg.abs_path(cfg.db_file)
db.init_db(db_path)

st.title("📡 Xion — Call & Signal Tracker")
st.caption("Analyze your own call logs & mobile network signals.")

st.info(
    "Xion only analyzes data you've already exported yourself. It does not "
    "collect data from any device, and using it on someone else's data "
    "without permission isn't okay."
)

profiles = db.list_profiles(db_path)
profile_names = [p["name"] for p in profiles] or ["default"]
selected_name = st.sidebar.selectbox("Profile", profile_names + ["+ New profile"])
if selected_name == "+ New profile":
    new_name = st.sidebar.text_input("New profile name")
    if new_name and st.sidebar.button("Create"):
        db.get_or_create_profile(db_path, new_name)
        st.rerun()
    st.stop()

profile_id = db.get_or_create_profile(db_path, selected_name)
selected_profile = next((p for p in profiles if p["name"] == selected_name), None)
selected_record_count = selected_profile["record_count"] if selected_profile else 0

with st.sidebar.expander("⚠️ Delete this profile"):
    st.warning(
        f"This permanently deletes **{selected_name}** and all "
        f"{selected_record_count} record(s). This cannot be undone."
    )
    confirm_name = st.text_input(
        f"Type \"{selected_name}\" to confirm", key=f"delete_confirm_{selected_name}"
    )
    if st.button("Delete profile", type="primary", key=f"delete_button_{selected_name}"):
        if confirm_name != selected_name:
            st.error("Name doesn't match — nothing deleted.")
        else:
            db.delete_profile(db_path, selected_name)
            st.success(f"Deleted profile '{selected_name}'.")
            st.rerun()

st.sidebar.header("Import data")
uploaded = st.sidebar.file_uploader("CSV or JSON export", accept_multiple_files=True)
if uploaded and st.sidebar.button("Import"):
    tmp_paths = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in uploaded:
            p = Path(tmpdir) / f.name
            p.write_bytes(f.read())
            tmp_paths.append(str(p))
        df, errors = importer.batch_load(tmp_paths)
        for e in errors:
            st.sidebar.warning(e)
        if not df.empty:
            inserted, skipped = db.insert_records(db_path, profile_id, df)
            st.sidebar.success(f"Imported {inserted} record(s), {skipped} duplicate(s) skipped.")

df = db.fetch_records(db_path, profile_id)

if df.empty:
    st.warning("No records yet — import a CSV/JSON export from the sidebar.")
    st.stop()

tab_overview, tab_records, tab_trend, tab_alerts, tab_coverage, tab_export = st.tabs(
    ["Overview", "Records", "Trend", "Alerts", "Coverage", "Export"]
)

with tab_overview:
    summary = analysis.analyze_signal_strength(df)
    col1, col2, col3 = st.columns(3)
    col1.metric("Total records", summary.total_records)
    col2.metric("Average RSRP", f"{summary.average_rsrp} dBm" if summary.average_rsrp is not None else "n/a")
    col3.metric("Weakest signal", f"{summary.weakest_rsrp} dBm" if summary.weakest_rsrp is not None else "n/a")

    st.subheader("Network type distribution")
    st.bar_chart(analysis.network_type_distribution(df))

    st.subheader("Top cells by average RSRP")
    st.dataframe(analysis.top_cells_by_signal(df))

with tab_records:
    search = st.text_input("Search phone number")
    view = df
    if search:
        view = view[view["phone_number"].astype(str).str.contains(search, na=False)]
    st.dataframe(view.sort_values("timestamp", ascending=False))

with tab_trend:
    freq = st.selectbox("Bucket by", ["D", "W", "M"], format_func=lambda x: {"D": "Daily", "W": "Weekly", "M": "Monthly"}[x])
    trend = analysis.time_series_trend(df, freq=freq)
    if trend.empty:
        st.info("Not enough data with timestamps + RSRP to chart a trend.")
    else:
        st.line_chart(trend.set_index("period")["avg_rsrp"])

with tab_alerts:
    anomalies = analysis.detect_anomalies(df, cfg)
    if not anomalies:
        st.success("No anomalies detected.")
    for a in anomalies:
        (st.error if a.severity == "critical" else st.warning if a.severity == "warning" else st.info)(
            f"[{a.kind}] {a.detail}"
        )

    kinds = {a.kind for a in anomalies}

    if "signal" in kinds:
        is_critical = any(a.kind == "signal" and a.severity == "critical" for a in anomalies)
        threshold = (cfg.very_poor_signal_threshold_dbm if is_critical
                     else cfg.poor_signal_threshold_dbm)
        weak = analysis.weak_signal_readings(df, threshold)
        if not weak.empty:
            with st.expander(f"Weak signal readings ({len(weak)})"):
                st.dataframe(analysis.display_columns(weak, analysis.WEAK_SIGNAL_DISPLAY_COLUMNS))

    if "duration_outlier" in kinds:
        outliers = analysis.detect_duration_outliers(df, cfg.duration_outlier_multiplier)
        if not outliers.empty:
            with st.expander(f"Unusually long calls ({len(outliers)})"):
                st.dataframe(analysis.display_columns(outliers, analysis.DURATION_OUTLIER_DISPLAY_COLUMNS))

with tab_coverage:
    table = coverage.cell_signal_table(df)
    st.dataframe(table)
    if not cfg.opencellid_api_key and not cfg.cell_location_csv:
        st.info("Add `opencellid_api_key` or `cell_location_csv` to config.json to plot these on a map.")
    else:
        out_path = cfg.abs_path(cfg.reports_dir) / "coverage_map.html"
        result = coverage.build_coverage_map(df, db_path, cfg, out_path)
        if result:
            st.components.v1.html(result.read_text(), height=500)
        else:
            st.warning("Could not resolve coordinates for any recorded cell towers.")

with tab_export:
    fmt = st.radio("Format", ["csv", "xlsx", "pdf"], horizontal=True)
    if st.button("Generate report"):
        reports_dir = cfg.abs_path(cfg.reports_dir)
        base = reports_dir / f"{selected_name}_webexport"
        if fmt == "csv":
            path = reports.export_csv(df, base.with_suffix(".csv"))
        elif fmt == "xlsx":
            path = reports.export_excel(df, base.with_suffix(".xlsx"))
        else:
            path = reports.export_pdf(df, base.with_suffix(".pdf"), reports_dir / "charts")
        st.success(f"Report saved to {path}")
        st.download_button("Download", data=Path(path).read_bytes(), file_name=Path(path).name)
