from xion import db


def test_profile_creation_is_idempotent(db_path):
    id1 = db.get_or_create_profile(db_path, "PhoneA")
    id2 = db.get_or_create_profile(db_path, "PhoneA")
    assert id1 == id2


def test_insert_records_and_dedup(db_path, sample_df):
    profile_id = db.get_or_create_profile(db_path, "PhoneA")

    inserted, skipped = db.insert_records(db_path, profile_id, sample_df, source_file="a.csv")
    assert inserted == 6
    assert skipped == 0

    inserted2, skipped2 = db.insert_records(db_path, profile_id, sample_df, source_file="a.csv")
    assert inserted2 == 0
    assert skipped2 == 6


def test_records_scoped_by_profile(db_path, sample_df):
    p1 = db.get_or_create_profile(db_path, "PhoneA")
    p2 = db.get_or_create_profile(db_path, "PhoneB")

    db.insert_records(db_path, p1, sample_df)
    db.insert_records(db_path, p2, sample_df)

    assert len(db.fetch_records(db_path, p1)) == 6
    assert len(db.fetch_records(db_path, p2)) == 6
    assert len(db.fetch_records(db_path, None)) == 12


def test_contacts_upsert(db_path):
    db.upsert_contact(db_path, "+10000000001", "Alice", "coworker")
    db.upsert_contact(db_path, "+10000000001", "Alice W.", "updated notes")
    contacts = db.get_contacts(db_path)
    assert len(contacts) == 1
    assert contacts.iloc[0]["label"] == "Alice W."


def test_meta_roundtrip(db_path):
    assert db.get_meta(db_path, "missing_key") is None
    db.set_meta(db_path, "last_scheduled_report", "2026-01-01T00:00:00")
    assert db.get_meta(db_path, "last_scheduled_report") == "2026-01-01T00:00:00"
