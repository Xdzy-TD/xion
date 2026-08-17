<div align="center">

# 📡 Xion

### Call Logs & Mobile Network Signal Analyzer

*Turn your own exported call logs and signal readings into clear, actionable insight — from the terminal or the browser.*

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://img.shields.io/badge/CI-passing-2ea44f?style=flat-square&logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![Interface](https://img.shields.io/badge/interface-CLI%20%2B%20Web-8A2BE2?style=flat-square)](#-usage)
[![License](https://img.shields.io/badge/license-MIT-informational?style=flat-square)](#-license)

[Features](#-features) • [Install](#-installation) • [Usage](#-usage) • [Configuration](#-configuration) • [Project Layout](#-project-layout)

</div>

<br>

## About

**Xion** imports your own call-log and mobile-signal exports (CSV/JSON), stores them locally in SQLite, and gives you both a rich terminal menu and a Streamlit web dashboard to explore them — call history, signal quality, coverage by cell, anomalies, and exportable reports.

> Xion only analyzes data you've already exported yourself. It doesn't collect anything from a device, and using it on someone else's data without permission isn't okay.

<br>

## ✨ Features

<table>
<tr>
<td width="50%" valign="top">

**📥 Import & Storage**
- Batch-import CSV/JSON exports, deduplicated automatically
- Multiple named profiles (e.g. per device or SIM)
- Column aliasing so exports from different tools just work

**📞 Call Insight**
- Filterable call log view (incoming / outgoing / missed)
- Search by phone number
- Contacts: label and annotate numbers

</td>
<td width="50%" valign="top">

**📶 Signal Analysis**
- RSRP quality banding (Excellent → Very Poor)
- Time-series signal trend (daily / weekly / monthly)
- Top cells by average signal
- Coverage map (via OpenCellID or a local coordinates CSV)

**🚨 Anomaly Alerts**
- Weak-signal spells
- Unusually long calls (outlier detection)
- Repeated missed calls in a time window

</td>
</tr>
</table>

**📤 Reports** — export any profile's data as CSV, Excel, or a charted PDF, on demand or on a schedule.

**🖥️ Two ways in** — a themed interactive terminal menu, *and* a full Streamlit web dashboard, launchable from the CLI itself.

<br>

## 🚀 Installation

```bash
git clone https://github.com/Xdzy-TD/XION-Call-Log-and-Signal-Analyzer.git
cd XION-Call-Log-and-Signal-Analyzer
pip install -r requirements.txt
```

Requires **Python 3.10+**.

<br>

## 🕹️ Usage

### Interactive menu (default)

```bash
python run.py
```

Walks you through profile selection, then drops you into a numbered menu — import data, browse call logs, run analysis, check coverage, export reports, launch the web GUI, and more. Type `h` at any prompt for the full command reference; `q` to quit.

### Web dashboard

```bash
python run.py gui
```

Opens the same data in a Streamlit dashboard — tabs for **Overview**, **Records**, **Trend**, **Alerts**, **Coverage**, and **Export** — in your browser. You can also launch it from inside the terminal menu (**Launch Web GUI**).

### Direct commands (scripting / cron)

```bash
# Import files straight into a profile, no menu
python run.py import export1.csv export2.json -p MyPhone

# Generate a report
python run.py report -p MyPhone --format pdf

# Only generate a report if one is due, per the configured interval
python run.py report --auto
```

<br>

## ⚙️ Configuration

Xion creates `config.json` on first run. Editable via the **Settings** menu, or by hand:

| Setting | Purpose |
|---|---|
| `poor_signal_threshold_dbm` / `very_poor_signal_threshold_dbm` | RSRP thresholds for weak-signal alerts |
| `long_call_seconds` | Flags calls longer than this |
| `duration_outlier_multiplier` | How far above average a call duration counts as an outlier |
| `missed_call_repeat_count` / `missed_call_window_hours` | Repeated missed-call alert sensitivity |
| `report_interval` | `manual`, or an auto-report cadence for `report --auto` |
| `default_export_format` | `csv`, `xlsx`, or `pdf` |
| `opencellid_api_key` / `cell_location_csv` | Either enables the coverage map — API lookup or a local lat/lon table |

<br>

## 📁 Project Layout

```
Xion/
├── run.py                 # Entry point
├── config.json             # Generated on first run
├── xion/
│   ├── cli.py              # Terminal menu + argparse commands
│   ├── webapp.py           # Streamlit web dashboard
│   ├── ui.py                # Terminal presentation layer (Rich)
│   ├── importer.py         # CSV/JSON loading & normalization
│   ├── db.py                 # SQLite storage layer
│   ├── analysis.py         # Signal analysis & anomaly detection
│   ├── coverage.py         # Cell coverage & map building
│   ├── reports.py          # CSV/Excel/PDF export
│   └── config.py           # Config load/save
├── tests/                  # pytest suite
└── .github/workflows/      # CI
```

<br>

## 🧪 Testing

```bash
pytest -v
```

<br>

## 📄 License

MIT — see [LICENSE](LICENSE).

<br>

<div align="center">

*Built for people who want to understand their own data — nothing more, nothing less.*

</div>
