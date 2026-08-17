import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xion import db as xion_db
from xion.config import Config

SAMPLE_CSV = """timestamp,call_type,phone_number,duration,cell_id,lac,mcc,mnc,radio_type,signal_strength
2026-01-01 08:00:00,OUTGOING,+10000000001,120,101,20,310,260,LTE,-85
2026-01-01 09:00:00,INCOMING,+10000000002,45,102,20,310,260,LTE,-95
2026-01-01 10:00:00,MISSED,+10000000003,0,101,20,310,260,LTE,-130
2026-01-02 08:00:00,MISSED,+10000000003,0,101,20,310,260,LTE,-128
2026-01-02 08:30:00,MISSED,+10000000003,0,101,20,310,260,LTE,-129
2026-01-02 09:00:00,OUTGOING,+10000000004,2200,103,21,310,260,3G,-80
"""


@pytest.fixture
def sample_csv(tmp_path):
    p = tmp_path / "sample.csv"
    p.write_text(SAMPLE_CSV)
    return p


@pytest.fixture
def sample_df():
    from xion.importer import load_data
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(SAMPLE_CSV)
        path = f.name
    return load_data(path)


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "xion_test.db"
    xion_db.init_db(p)
    return p


@pytest.fixture
def test_config(tmp_path):
    cfg = Config()
    cfg.data_dir = str(tmp_path / "data")
    cfg.reports_dir = str(tmp_path / "reports")
    cfg.db_file = str(tmp_path / "data" / "xion.db")
    cfg.ensure_dirs()
    return cfg
