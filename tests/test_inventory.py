from dataclasses import replace

from config.settings import Settings
from database.connection import connect
from scripts.seed_city import seed_city


def test_seeded_inventory_counts_capacity_and_relationships(tmp_path):
    settings = replace(Settings(), data_dir=tmp_path)
    summary = seed_city(settings)
    assert summary["ont_count"] == 5000
    assert summary["pon_port_count"] == 80
    assert summary["max_onts_per_port"] <= 64
    assert [z["actual_ont_count"] for z in summary["zones"]] == [2200, 1400, 600, 800]

    conn = connect(settings.database_path)
    try:
        assert conn.execute("SELECT COUNT(DISTINCT ont_id) FROM onts").fetchone()[0] == 5000
        assert conn.execute("SELECT COUNT(DISTINCT subscriber_number) FROM onts").fetchone()[0] == 5000
        assert conn.execute("SELECT COUNT(*) FROM onts o LEFT JOIN pon_ports p USING (pon_port_id) WHERE p.pon_port_id IS NULL").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM onts o LEFT JOIN splitters s USING (splitter_id) WHERE s.splitter_id IS NULL").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM onts o LEFT JOIN meters m USING (meter_id) WHERE m.meter_id IS NULL").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_seed_is_repeatable(tmp_path):
    settings = replace(Settings(), data_dir=tmp_path)
    seed_city(settings)
    conn = connect(settings.database_path)
    try:
        first = list(map(tuple, conn.execute("SELECT ont_id, pon_port_id, subscriber_number FROM onts ORDER BY ont_id")))
    finally:
        conn.close()
    seed_city(settings)
    conn = connect(settings.database_path)
    try:
        second = list(map(tuple, conn.execute("SELECT ont_id, pon_port_id, subscriber_number FROM onts ORDER BY ont_id")))
        assert first == second
    finally:
        conn.close()

