from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import analysis, coverage, db, importer, reports, ui
from .config import load_config, save_config, Config
from .ui import QuitRequested


# ── Display formatting helpers ──────────────────────────────────────────
# The raw records table carries DB bookkeeping columns (id, profile_id,
# import_hash, source_file, profile_name, mcc/mnc, ...) that just add noise
# to a table someone's actually trying to read. These curate + format the
# handful of columns that matter for the interactive views.
CALL_TYPE_ICONS = {
    "OUTGOING": ("↑", "info"),
    "INCOMING": ("↓", "success"),
    "MISSED": ("✗", "error"),
}
RSRP_STYLES = {
    "Excellent": "success", "Good": "success", "Fair": "warning",
    "Poor": "error", "Very Poor": "error",
}


def _fmt_call_type(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v in ("", "None"):
        return "[subtle]—[/subtle]"
    icon, style = CALL_TYPE_ICONS.get(v, ("•", "value"))
    return f"[{style}]{icon} {str(v).title()}[/{style}]"


def _fmt_duration(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "[subtle]—[/subtle]"
    seconds = int(v)
    if seconds <= 0:
        return "[subtle]—[/subtle]"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def _fmt_rsrp(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "[subtle]—[/subtle]"
    quality = analysis.rsrp_quality(float(v))
    style = RSRP_STYLES.get(quality, "value")
    return f"[{style}]{float(v):.0f} dBm[/{style}] [subtle]({quality})[/subtle]"


def _fmt_plain(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v in ("", "None"):
        return "[subtle]—[/subtle]"
    return str(v)


RECORD_COLUMNS = ["timestamp", "call_type", "phone_number", "duration", "radio_type", "rsrp", "cell_id"]
RECORD_HEADERS = {
    "timestamp": "When", "call_type": "Type", "phone_number": "Number",
    "duration": "Duration", "radio_type": "Network", "rsrp": "Signal", "cell_id": "Cell",
}
RECORD_FORMATTERS = {
    "call_type": _fmt_call_type, "duration": _fmt_duration,
    "rsrp": _fmt_rsrp, "timestamp": _fmt_plain, "cell_id": _fmt_plain,
}


def _current_profile_records(cfg: Config, profile_id: int | None) -> pd.DataFrame:
    return db.fetch_records(cfg.abs_path(cfg.db_file), profile_id)


def _select_profile(cfg: Config) -> tuple[int, str]:
    db_path = cfg.abs_path(cfg.db_file)
    profiles = db.list_profiles(db_path)
    if not profiles:
        ui.info("No profiles yet — let's create one (e.g. 'MyPhone').")
        name = ui.ask("Profile name", default="default")
        pid = db.get_or_create_profile(db_path, name)
        return pid, name

    ui.console.print("\n[header]Profiles[/header]")
    for i, p in enumerate(profiles, 1):
        ui.console.print(f"  [index]{i}[/index]  {p['name']} [subtle]({p['record_count']} records)[/subtle]")
    ui.console.print(f"  [index]{len(profiles) + 1}[/index]  [muted]+ Create new profile[/muted]")

    choice = ui.ask("Select profile")
    try:
        idx = int(choice)
        if idx == len(profiles) + 1:
            name = ui.ask("New profile name", default="default")
            pid = db.get_or_create_profile(db_path, name)
            return pid, name
        if idx < 1:
            raise IndexError
        row = profiles[idx - 1]
        return row["id"], row["name"]
    except (ValueError, IndexError):
        ui.warn("Invalid choice, using first profile.")
        row = profiles[0]
        return row["id"], row["name"]


def do_delete_profile(cfg: Config, current_profile_id: int,
                       current_profile_name: str) -> tuple[int, str]:
    """Delete a profile (and all its records). Returns the profile that
    should now be active — unchanged unless the deleted one was active,
    in which case the caller is walked through picking/creating another."""
    db_path = cfg.abs_path(cfg.db_file)
    profiles = db.list_profiles(db_path)
    if not profiles:
        ui.warn("No profiles to delete.")
        return current_profile_id, current_profile_name

    ui.console.print("\n[header]Profiles[/header]")
    for i, p in enumerate(profiles, 1):
        ui.console.print(f"  [index]{i}[/index]  {p['name']} [subtle]({p['record_count']} records)[/subtle]")

    choice = ui.ask("Profile number to delete (blank to cancel)").strip()
    if not choice:
        ui.info("Cancelled — nothing deleted.")
        return current_profile_id, current_profile_name

    try:
        idx = int(choice)
        if not (1 <= idx <= len(profiles)):
            raise IndexError
    except ValueError:
        ui.error(f"'{choice}' isn't a number.")
        return current_profile_id, current_profile_name
    except IndexError:
        ui.error(f"Choose a number between 1 and {len(profiles)}.")
        return current_profile_id, current_profile_name

    target = profiles[idx - 1]
    confirmed = ui.confirm(
        f"Delete profile '{target['name']}' and all {target['record_count']} "
        f"record(s)? This cannot be undone.",
        default=False,
    )
    if not confirmed:
        ui.info("Cancelled — nothing deleted.")
        return current_profile_id, current_profile_name

    if not db.delete_profile(db_path, target["name"]):
        ui.error(f"Couldn't find profile '{target['name']}' — it may have already been deleted.")
        return current_profile_id, current_profile_name

    ui.success(f"Deleted profile '{target['name']}'.")

    if target["id"] == current_profile_id:
        ui.info("That was your active profile — pick another.")
        return _select_profile(cfg)

    return current_profile_id, current_profile_name


def do_import(cfg: Config, profile_id: int, profile_name: str) -> None:
    raw = ui.ask("Enter file path(s), comma-separated for batch import")
    paths = [p.strip() for p in raw.split(",") if p.strip()]
    if not paths:
        ui.warn("No file paths given.")
        return
    with ui.status("Reading file(s)"):
        df, errors = importer.batch_load(paths)
    for e in errors:
        (ui.warn if e.startswith("[info]") else ui.error)(e)
    if df.empty:
        ui.warn("Nothing to import.")
        return
    inserted, skipped = db.insert_records(cfg.abs_path(cfg.db_file), profile_id, df,
                                           source_file=", ".join(paths))
    ui.success(f"Imported {inserted} new record(s) into '{profile_name}' "
               f"({skipped} duplicate(s) skipped).")


def do_view_call_logs(cfg: Config, profile_id: int) -> None:
    df = _current_profile_records(cfg, profile_id)
    calls = df[df["call_type"].isin(["INCOMING", "OUTGOING", "MISSED"])]
    ui.show_dataframe(calls.sort_values("timestamp", ascending=False), "Call Logs",
                       columns=RECORD_COLUMNS, headers=RECORD_HEADERS, formatters=RECORD_FORMATTERS)


def do_view_all_records(cfg: Config, profile_id: int) -> None:
    df = _current_profile_records(cfg, profile_id)
    ui.show_dataframe(df.sort_values("timestamp", ascending=False), "All Records",
                       columns=RECORD_COLUMNS, headers=RECORD_HEADERS, formatters=RECORD_FORMATTERS)


def do_search_by_number(cfg: Config, profile_id: int) -> None:
    number = ui.ask("Enter phone number (or part of it) to search")
    df = _current_profile_records(cfg, profile_id)
    res = df[df["phone_number"].astype(str).str.contains(number, na=False, regex=False)]
    ui.show_dataframe(res.sort_values("timestamp", ascending=False), f"Results for '{number}'",
                       columns=RECORD_COLUMNS, headers=RECORD_HEADERS, formatters=RECORD_FORMATTERS)


def do_contacts(cfg: Config, profile_id: int) -> None:
    db_path = cfg.abs_path(cfg.db_file)
    ui.console.print("[index]1[/index] List contacts   [index]2[/index] Add/update label")
    choice = ui.ask("Choose")
    if choice.strip() == "2":
        number = ui.ask("Phone number")
        if not number.strip():
            ui.warn("No phone number given — nothing saved.")
            return
        label = ui.ask("Label (name/tag)")
        notes = ui.ask("Notes (optional)")
        db.upsert_contact(db_path, number.strip(), label, notes)
        ui.success(f"Saved contact info for {number}.")
    else:
        ui.show_dataframe(db.get_contacts(db_path), "Contacts")


def do_analyze_signal(cfg: Config, profile_id: int) -> None:
    df = _current_profile_records(cfg, profile_id)
    summary = analysis.analyze_signal_strength(df)
    ui.console.print(_signal_summary_panel(summary))
    ui.console.print()

    dist = analysis.network_type_distribution(df)
    if not dist.empty:
        ui.console.print(ui.key_value_table(
            [(k, str(v)) for k, v in dist.items()], title="Network Type Distribution"
        ))
        ui.console.print()

    top = analysis.top_cells_by_signal(df)
    ui.show_dataframe(top, "Top Cells by Avg RSRP",
                       headers={"cell_id": "Cell", "avg_rsrp": "Avg Signal", "samples": "Samples"},
                       formatters={"avg_rsrp": _fmt_rsrp})


def _signal_summary_panel(summary: analysis.SignalSummary):
    quality = analysis.rsrp_quality(summary.average_rsrp) if summary.average_rsrp is not None else None
    quality_style = RSRP_STYLES.get(quality, "value") if quality else "value"

    rows = [
        ("Total records", str(summary.total_records)),
        ("Analyzed (has signal)", str(summary.analyzed_records)),
        ("Average signal", f"[{quality_style}]{summary.average_rsrp} dBm ({quality})[/{quality_style}]"
                             if summary.average_rsrp is not None else "[subtle]n/a[/subtle]"),
        ("Strongest", f"{summary.strongest_rsrp} dBm — cell {summary.strongest_cell}"
                       if summary.strongest_rsrp is not None else "[subtle]n/a[/subtle]"),
        ("Weakest", f"{summary.weakest_rsrp} dBm — cell {summary.weakest_cell}"
                     if summary.weakest_rsrp is not None else "[subtle]n/a[/subtle]"),
    ]
    lines = "\n".join(f"[muted]{label}:[/muted]  {value}" for label, value in rows)
    return ui.panel(lines, title="Signal Strength Analysis")


def do_trend(cfg: Config, profile_id: int) -> None:
    df = _current_profile_records(cfg, profile_id)
    freq = ui.ask("Bucket by (D)aily, (W)eekly, (M)onthly?", default="D").strip().upper()
    if freq not in ("D", "W", "M"):
        ui.warn(f"Didn't recognize '{freq}' — defaulting to Daily.")
        freq = "D"
    trend = analysis.time_series_trend(df, freq=freq)
    ui.show_dataframe(trend, "Signal Trend Over Time",
                       headers={"period": "Period", "avg_rsrp": "Avg Signal", "samples": "Samples"},
                       formatters={"avg_rsrp": _fmt_rsrp})


def do_anomalies(cfg: Config, profile_id: int) -> None:
    df = _current_profile_records(cfg, profile_id)
    found = analysis.detect_anomalies(df, cfg)
    if not found:
        ui.success("No anomalies detected.")
        return
    for a in found:
        style = {"critical": ui.error, "warning": ui.warn, "info": ui.info}[a.severity]
        style(f"[{a.kind}] {a.detail}")
    ui.console.print()

    kinds = {a.kind for a in found}

    if "signal" in kinds:
        is_critical = any(a.kind == "signal" and a.severity == "critical" for a in found)
        threshold = (cfg.very_poor_signal_threshold_dbm if is_critical
                     else cfg.poor_signal_threshold_dbm)
        weak = analysis.weak_signal_readings(df, threshold)
        if not weak.empty:
            weak = analysis.display_columns(weak, analysis.WEAK_SIGNAL_DISPLAY_COLUMNS)
            ui.show_dataframe(weak, "Weak Signal Readings (weakest first)",
                               headers=RECORD_HEADERS, formatters=RECORD_FORMATTERS)

    if "duration_outlier" in kinds:
        outliers = analysis.detect_duration_outliers(df, cfg.duration_outlier_multiplier)
        if not outliers.empty:
            outliers = analysis.display_columns(outliers, analysis.DURATION_OUTLIER_DISPLAY_COLUMNS)
            ui.show_dataframe(outliers, "Unusually Long Calls (outliers)",
                               headers=RECORD_HEADERS, formatters=RECORD_FORMATTERS)


def do_coverage(cfg: Config, profile_id: int) -> None:
    df = _current_profile_records(cfg, profile_id)
    table = coverage.cell_signal_table(df)
    if table.empty:
        ui.warn("No cell/signal data available.")
        return
    ui.show_dataframe(table, "Cell Signal Quality",
                       headers={"cell_key": "Cell Key", "cell_id": "Cell", "avg_rsrp": "Avg Signal", "samples": "Samples"},
                       formatters={"avg_rsrp": _fmt_rsrp})

    if not cfg.opencellid_api_key and not cfg.cell_location_csv:
        ui.info("No coordinate source configured (opencellid_api_key or "
                 "cell_location_csv in config.json) — showing table only, no map.")
        return

    out_path = cfg.abs_path(cfg.reports_dir) / "coverage_map.html"
    with ui.status("Building coverage map"):
        result = coverage.build_coverage_map(df, cfg.abs_path(cfg.db_file), cfg, out_path)
    if result:
        ui.success(f"Coverage map written to {result}")
    else:
        ui.warn("Could not resolve any cell coordinates — map not generated.")


def do_export(cfg: Config, profile_id: int, profile_name: str, fmt: str | None = None) -> None:
    df = _current_profile_records(cfg, profile_id)
    if df.empty:
        ui.warn("No data to export.")
        return
    fmt = (fmt or ui.ask("Format (csv/xlsx/pdf)", default=cfg.default_export_format)).strip().lower()
    if fmt not in ("csv", "xlsx", "pdf"):
        ui.error(f"Unknown format '{fmt}'. Choose csv, xlsx, or pdf.")
        return

    reports_dir = cfg.abs_path(cfg.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = reports_dir / f"{profile_name}_{stamp}"

    with ui.status(f"Generating {fmt.upper()} report"):
        if fmt == "csv":
            path = reports.export_csv(df, base.with_suffix(".csv"))
        elif fmt == "xlsx":
            path = reports.export_excel(df, base.with_suffix(".xlsx"))
        else:
            path = reports.export_pdf(df, base.with_suffix(".pdf"), reports_dir / "charts",
                                       title=f"Xion Report — {profile_name}")
    ui.success(f"Report exported: {path}")


def do_settings(cfg: Config) -> None:
    fields = [
        ("poor_signal_threshold_dbm", "Poor signal threshold (dBm)"),
        ("very_poor_signal_threshold_dbm", "Very poor signal threshold (dBm)"),
        ("long_call_seconds", "Long call threshold (s)"),
        ("duration_outlier_multiplier", "Duration outlier multiplier"),
        ("missed_call_repeat_count", "Missed call repeat count"),
        ("missed_call_window_hours", "Missed call window (hours)"),
        ("report_interval", "Report interval"),
        ("default_export_format", "Default export format"),
        ("opencellid_api_key", "OpenCellID API key set?"),
        ("cell_location_csv", "Cell location CSV"),
    ]
    rows = []
    for i, (attr, label) in enumerate(fields, 1):
        value = getattr(cfg, attr)
        if attr == "opencellid_api_key":
            value = "yes" if value else "no"
        display = "[subtle]—[/subtle]" if value in (None, "") else str(value)
        rows.append((str(i), label, display))
    ui.console.print(ui.indexed_table(rows, title="Current Settings"))
    ui.console.print("[subtle]Tip: enter the number of a setting to change it. "
                      "For anything else, edit config.json directly.[/subtle]\n")

    choice = ui.ask("Setting number to change (blank to cancel)").strip()
    if not choice:
        return

    attr = None
    if choice.isdigit() and 1 <= int(choice) <= len(fields):
        attr = fields[int(choice) - 1][0]
    elif hasattr(cfg, choice):
        attr = choice  # still accept the raw field name for scripting/power users

    if attr is None:
        ui.warn(f"'{choice}' isn't one of the settings above — "
                f"enter a number from 1-{len(fields)}.")
        return

    new_val = ui.ask("New value (blank to leave unchanged)").strip()
    if not new_val:
        ui.info("No change made.")
        return

    current = getattr(cfg, attr)
    try:
        if isinstance(current, bool):
            new_val = new_val.lower() in ("1", "true", "yes")
        elif isinstance(current, float):
            new_val = float(new_val)
        elif isinstance(current, int):
            new_val = int(new_val)
        setattr(cfg, attr, new_val)
        save_config(cfg)
        ui.success("Settings saved.")
    except ValueError:
        ui.error(f"Couldn't parse '{new_val}' for this setting.")


def do_launch_gui() -> None:
    webapp_path = Path(__file__).resolve().parent / "webapp.py"
    ui.info("Launching the web GUI — your browser should open shortly.")
    ui.info("Leave this window open while you use it; press Ctrl+C here to stop the server.")
    try:
        subprocess.run([sys.executable, "-m", "streamlit", "run", str(webapp_path)])
    except FileNotFoundError:
        ui.error("Streamlit isn't installed. Run: pip install -r requirements.txt")
    except KeyboardInterrupt:
        pass
    ui.info("Web GUI closed — back to the menu.")


MENU_OPTIONS = [
    "Import Data (CSV/JSON)",
    "Switch Profile",
    "Delete Profile",
    "View Call Logs",
    "View All Records",
    "Search by Phone Number",
    "Contacts",
    "Analyze Signal Strength",
    "Time-Series Trend",
    "Anomaly Alerts",
    "Coverage Map",
    "Export Report (CSV/Excel/PDF)",
    "Launch Web GUI",
    "Settings",
    "Help",
    "Exit",
]

# One line per menu option, shown on the Help screen — kept next to
# MENU_OPTIONS so the two stay in sync as options are added or reworded.
HELP_DESCRIPTIONS = {
    "Import Data (CSV/JSON)": "Load one or more exported files into the current profile.",
    "Switch Profile": "Choose a different saved profile, or create a new one.",
    "Delete Profile": "Permanently delete a profile and all of its records.",
    "View Call Logs": "Show incoming, outgoing, and missed calls — most recent first.",
    "View All Records": "Show every imported record for this profile — most recent first.",
    "Search by Phone Number": "Filter records by a phone number, or part of one.",
    "Contacts": "List saved contacts, or add/update a label and notes for a number.",
    "Analyze Signal Strength": "Summarize signal quality: averages, strongest/weakest cell, network mix.",
    "Time-Series Trend": "Bucket signal strength by day, week, or month to see it change over time.",
    "Anomaly Alerts": "Flag weak-signal spells, unusually long calls, and repeated missed calls.",
    "Coverage Map": "Show per-cell signal quality, and build a map if coordinates are configured.",
    "Export Report (CSV/Excel/PDF)": "Write the current profile's records out as a report.",
    "Launch Web GUI": "Open the Streamlit-based browser dashboard in a new tab.",
    "Settings": "View and edit thresholds, formats, and other config values.",
    "Help": "Show this screen.",
    "Exit": "Leave Xion. Nothing is deleted on the way out.",
}


def do_help() -> None:
    ui.console.print()
    rows = [(str(i), opt, HELP_DESCRIPTIONS.get(opt, "")) for i, opt in enumerate(MENU_OPTIONS, 1)]
    ui.console.print(ui.indexed_table(
        rows, title="Menu Commands", headers=("#", "Option", "What it does"),
    ))
    ui.console.print()

    cli_lines = "\n".join([
        "◆ [prompt]python run.py[/prompt] [muted]— open this interactive menu[/muted]",
        "◆ [prompt]python run.py import FILE [FILE ...] -p PROFILE[/prompt] "
        "[muted]— import without opening the menu[/muted]",
        "◆ [prompt]python run.py report -p PROFILE --format csv|xlsx|pdf[/prompt] "
        "[muted]— generate a report[/muted]",
        "◆ [prompt]python run.py report --auto[/prompt] "
        "[muted]— only runs if a report is due, per Settings[/muted]",
        "◆ [prompt]python run.py gui[/prompt] "
        "[muted]— launch the web GUI directly, skipping the menu[/muted]",
    ])
    ui.console.print(ui.panel(
        cli_lines, title="Command-Line Mode", border_style="accent2", badge_style="badge.accent",
    ))
    ui.console.print()

    shortcut_lines = "\n".join([
        "◆ [prompt]q[/prompt], [prompt]quit[/prompt], [prompt]exit[/prompt], or [prompt]:q[/prompt] "
        "[muted]— leave, from any prompt[/muted]",
        "◆ [prompt]h[/prompt], [prompt]help[/prompt], or [prompt]?[/prompt] "
        "[muted]— show this screen again[/muted]",
        "◆ [prompt]Ctrl+C[/prompt] / [prompt]Ctrl+D[/prompt] "
        "[muted]— exit cleanly, nothing is lost[/muted]",
    ])
    ui.console.print(ui.panel(
        shortcut_lines, title="Shortcuts", border_style="accent3", badge_style="badge.gold",
    ))
    ui.console.print()


def run_menu() -> None:
    cfg = load_config()
    db.init_db(cfg.abs_path(cfg.db_file))

    ui.banner()
    ui.notice()
    profile_id, profile_name = _select_profile(cfg)

    if reports.is_report_due(cfg.abs_path(cfg.db_file), cfg.report_interval):
        ui.info(f"A scheduled ({cfg.report_interval}) summary report is due — "
                "run it from the Export menu, or `python run.py report --auto`.")

    while True:
        ui.section_header(profile_name)
        choice = ui.menu(MENU_OPTIONS)
        if choice.strip().lower() in ("h", "help", "?"):
            do_help()
            continue
        try:
            choice_num = int(choice)
        except ValueError:
            ui.error("Please enter a number, or 'h' for help.")
            continue

        if choice_num == 1:
            do_import(cfg, profile_id, profile_name)
        elif choice_num == 2:
            profile_id, profile_name = _select_profile(cfg)
        elif choice_num == 3:
            profile_id, profile_name = do_delete_profile(cfg, profile_id, profile_name)
        elif choice_num == 4:
            do_view_call_logs(cfg, profile_id)
        elif choice_num == 5:
            do_view_all_records(cfg, profile_id)
        elif choice_num == 6:
            do_search_by_number(cfg, profile_id)
        elif choice_num == 7:
            do_contacts(cfg, profile_id)
        elif choice_num == 8:
            do_analyze_signal(cfg, profile_id)
        elif choice_num == 9:
            do_trend(cfg, profile_id)
        elif choice_num == 10:
            do_anomalies(cfg, profile_id)
        elif choice_num == 11:
            do_coverage(cfg, profile_id)
        elif choice_num == 12:
            do_export(cfg, profile_id, profile_name)
        elif choice_num == 13:
            do_launch_gui()
        elif choice_num == 14:
            do_settings(cfg)
            cfg = load_config()
        elif choice_num == 15:
            do_help()
        elif choice_num == 16:
            raise QuitRequested("exit")
        else:
            ui.error("Invalid option. Please choose 1-16.")


def cmd_import(args: argparse.Namespace) -> None:
    cfg = load_config()
    db.init_db(cfg.abs_path(cfg.db_file))
    profile_id = db.get_or_create_profile(cfg.abs_path(cfg.db_file), args.profile)
    df, errors = importer.batch_load(args.files)
    for e in errors:
        print(e)
    if df.empty:
        print("Nothing to import.")
        return
    inserted, skipped = db.insert_records(cfg.abs_path(cfg.db_file), profile_id, df,
                                           source_file=", ".join(args.files))
    print(f"Imported {inserted} new record(s) into '{args.profile}' ({skipped} duplicates skipped).")


def cmd_report(args: argparse.Namespace) -> None:
    cfg = load_config()
    db_path = cfg.abs_path(cfg.db_file)
    db.init_db(db_path)

    if args.auto and not reports.is_report_due(db_path, cfg.report_interval):
        print("No scheduled report due yet.")
        return

    profile_id = None
    profile_name = "all_profiles"
    if args.profile:
        profile_id = db.get_or_create_profile(db_path, args.profile)
        profile_name = args.profile

    df = db.fetch_records(db_path, profile_id)
    if df.empty:
        print("No data to report on.")
        return

    reports_dir = cfg.abs_path(cfg.reports_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = reports_dir / f"{profile_name}_{stamp}"
    fmt = args.format or cfg.default_export_format

    if fmt == "csv":
        path = reports.export_csv(df, base.with_suffix(".csv"))
    elif fmt == "xlsx":
        path = reports.export_excel(df, base.with_suffix(".xlsx"))
    else:
        path = reports.export_pdf(df, base.with_suffix(".pdf"), reports_dir / "charts")

    reports.mark_report_run(db_path)
    print(f"Report written to {path}")


def cmd_gui(args: argparse.Namespace) -> None:
    do_launch_gui()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xion", description=ui.APP_TAGLINE)
    sub = parser.add_subparsers(dest="command")

    p_gui = sub.add_parser("gui", help="Launch the web GUI (Streamlit dashboard)")
    p_gui.set_defaults(func=cmd_gui)

    p_import = sub.add_parser("import", help="Import one or more CSV/JSON files")
    p_import.add_argument("files", nargs="+")
    p_import.add_argument("-p", "--profile", default="default")
    p_import.set_defaults(func=cmd_import)

    p_report = sub.add_parser("report", help="Generate a report (for cron/Task Scheduler use --auto)")
    p_report.add_argument("-p", "--profile", default=None)
    p_report.add_argument("--format", choices=["csv", "xlsx", "pdf"], default=None)
    p_report.add_argument("--auto", action="store_true",
                           help="Only run if due per config's report_interval")
    p_report.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        if getattr(args, "command", None):
            args.func(args)
        else:
            run_menu()
    except QuitRequested as e:
        ui.goodbye(e.reason)
    except KeyboardInterrupt:
        ui.goodbye("interrupt")
    except EOFError:
        ui.goodbye("interrupt")


if __name__ == "__main__":
    main()
