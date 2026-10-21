"""SQLite connection and schema management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS zones (
    zone_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    profile TEXT NOT NULL,
    expected_ont_count INTEGER NOT NULL CHECK (expected_ont_count >= 0)
);
CREATE TABLE IF NOT EXISTS olt_devices (
    olt_id TEXT PRIMARY KEY,
    zone_id TEXT NOT NULL REFERENCES zones(zone_id),
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pon_ports (
    pon_port_id TEXT PRIMARY KEY,
    olt_id TEXT NOT NULL REFERENCES olt_devices(olt_id),
    port_number INTEGER NOT NULL CHECK (port_number > 0),
    capacity INTEGER NOT NULL CHECK (capacity BETWEEN 1 AND 64),
    UNIQUE (olt_id, port_number)
);
CREATE TABLE IF NOT EXISTS splitters (
    splitter_id TEXT PRIMARY KEY,
    pon_port_id TEXT NOT NULL REFERENCES pon_ports(pon_port_id),
    split_ratio INTEGER NOT NULL CHECK (split_ratio > 0)
);
CREATE TABLE IF NOT EXISTS transformers (
    transformer_id TEXT PRIMARY KEY,
    zone_id TEXT NOT NULL REFERENCES zones(zone_id),
    rated_kva REAL NOT NULL CHECK (rated_kva > 0)
);
CREATE TABLE IF NOT EXISTS circuits (
    circuit_id TEXT PRIMARY KEY,
    transformer_id TEXT NOT NULL REFERENCES transformers(transformer_id),
    zone_id TEXT NOT NULL REFERENCES zones(zone_id)
);
CREATE TABLE IF NOT EXISTS meters (
    meter_id TEXT PRIMARY KEY,
    circuit_id TEXT NOT NULL REFERENCES circuits(circuit_id),
    zone_id TEXT NOT NULL REFERENCES zones(zone_id)
);
CREATE TABLE IF NOT EXISTS onts (
    ont_id TEXT PRIMARY KEY,
    zone_id TEXT NOT NULL REFERENCES zones(zone_id),
    pon_port_id TEXT NOT NULL REFERENCES pon_ports(pon_port_id),
    splitter_id TEXT NOT NULL REFERENCES splitters(splitter_id),
    meter_id TEXT NOT NULL UNIQUE REFERENCES meters(meter_id),
    subscriber_number INTEGER NOT NULL UNIQUE CHECK (subscriber_number > 0)
);
CREATE INDEX IF NOT EXISTS idx_onts_zone ON onts(zone_id);
CREATE INDEX IF NOT EXISTS idx_onts_pon ON onts(pon_port_id);
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    simulation_time REAL NOT NULL,
    source TEXT NOT NULL,
    zone_id TEXT,
    asset_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processed_events (event_id TEXT PRIMARY KEY, received_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alarm_acknowledgements (
    event_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('Reconocida','En investigación','Resuelta')),
    updated_utc TEXT NOT NULL
);
"""


def connect(database_path: Path | str) -> sqlite3.Connection:
    """Open a foreign-key enforcing SQLite connection in WAL mode."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()

