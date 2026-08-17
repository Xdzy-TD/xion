import pytest

from xion import importer


def test_load_data_normalizes_columns(sample_csv):
    df = importer.load_data(str(sample_csv))
    assert list(df.columns) == importer.KNOWN_COLUMNS
    assert len(df) == 6
    assert df["rsrp"].iloc[0] == -85


def test_load_data_missing_file():
    with pytest.raises(importer.ImportError_):
        importer.load_data("does_not_exist.csv")


def test_load_data_unsupported_format(tmp_path):
    p = tmp_path / "file.txt"
    p.write_text("hello")
    with pytest.raises(importer.ImportError_):
        importer.load_data(str(p))


def test_load_data_missing_required_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("duration,cell_id\n10,101\n")
    with pytest.raises(importer.ImportError_):
        importer.load_data(str(p))


def test_batch_load_dedups_across_files(sample_csv, tmp_path):
    dup = tmp_path / "dup.csv"
    dup.write_text(sample_csv.read_text())

    combined, errors = importer.batch_load([str(sample_csv), str(dup)])
    assert len(combined) == 6
    assert any("Dropped" in e for e in errors)


def test_batch_load_reports_bad_file_but_continues(sample_csv, tmp_path):
    missing = tmp_path / "missing.csv"
    combined, errors = importer.batch_load([str(sample_csv), str(missing)])
    assert len(combined) == 6
    assert any("not found" in e.lower() for e in errors)
