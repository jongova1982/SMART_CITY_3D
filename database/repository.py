"""Small read-side repository helpers for the seeded inventory."""

from __future__ import annotations

import sqlite3
import json


def inventory_summary(conn: sqlite3.Connection) -> dict[str, object]:
    zones = [dict(row) for row in conn.execute(
        "SELECT zone_id, name, expected_ont_count, "
        "(SELECT COUNT(*) FROM onts WHERE onts.zone_id = zones.zone_id) AS actual_ont_count "
        "FROM zones ORDER BY zone_id"
    )]
    return {
        "zones": zones,
        "ont_count": conn.execute("SELECT COUNT(*) FROM onts").fetchone()[0],
        "pon_port_count": conn.execute("SELECT COUNT(*) FROM pon_ports").fetchone()[0],
        "max_onts_per_port": conn.execute(
            "SELECT COALESCE(MAX(n), 0) FROM "
            "(SELECT COUNT(*) AS n FROM onts GROUP BY pon_port_id)"
        ).fetchone()[0],
    }


def meters_for_zone(conn: sqlite3.Connection, zone_id: str):
    return conn.execute("SELECT meter_id, circuit_id FROM meters WHERE zone_id=? ORDER BY meter_id", (zone_id,)).fetchall()


def onts(conn: sqlite3.Connection):
    return conn.execute("SELECT ont_id, zone_id, pon_port_id, splitter_id, meter_id, subscriber_number FROM onts ORDER BY subscriber_number").fetchall()


def port_loads(conn: sqlite3.Connection):
    return {row["pon_port_id"]: row["n"] for row in conn.execute("SELECT pon_port_id, COUNT(*) n FROM onts GROUP BY pon_port_id")}


def save_telemetry(conn: sqlite3.Connection, timestamp_utc: str, simulation_time: float, records: list[dict]):
    with conn:
        conn.executemany("INSERT INTO telemetry(timestamp_utc, simulation_time, source, zone_id, asset_id, payload_json) VALUES (?,?,?,?,?,?)", [(timestamp_utc, simulation_time, r.get("source","simulation"), r.get("zone_id"), r["asset_id"], json.dumps(r.get("payload",{}),sort_keys=True)) for r in records])
        conn.execute("DELETE FROM telemetry WHERE id <= (SELECT MAX(id)-100000 FROM telemetry)")


def recent_telemetry(conn: sqlite3.Connection, limit: int=300):
    return [dict(r) for r in conn.execute("SELECT * FROM telemetry ORDER BY id DESC LIMIT ?", (limit,))]


def acknowledge_alarm(conn: sqlite3.Connection, event_id: str, status: str = "Reconocida"):
    from datetime import datetime, timezone
    if status not in ("Reconocida", "En investigación", "Resuelta"):
        raise ValueError("Estado de alarma no válido")
    conn.execute("INSERT INTO alarm_acknowledgements(event_id,status,updated_utc) VALUES(?,?,?) "
                 "ON CONFLICT(event_id) DO UPDATE SET status=excluded.status, updated_utc=excluded.updated_utc",
                 (event_id, status, datetime.now(timezone.utc).isoformat()))
    conn.commit()


def alarm_status(conn: sqlite3.Connection, event_id: str) -> str:
    row = conn.execute("SELECT status FROM alarm_acknowledgements WHERE event_id=?", (event_id,)).fetchone()
    return row[0] if row else "Nueva"

