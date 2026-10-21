"""Create a deterministic logical city inventory in SQLite."""

from __future__ import annotations

import argparse
import random

from config.settings import Settings, load_settings
from database.connection import connect, initialize_schema
from database.repository import inventory_summary

ZONE_META = {
    "A": ("Residencial", "viviendas, medidores y luminarias"),
    "B": ("Comercial", "locales, edificios y cruces"),
    "C": ("Industrial", "fábricas, cargas y transformadores"),
    "D": ("Tecnológica", "hospital, NOC, OLT y centro de datos"),
}
ZONE_PORT_COUNTS = {"A": 35, "B": 22, "C": 10, "D": 13}


def seed_city(settings: Settings | None = None) -> dict[str, object]:
    settings = settings or load_settings()
    total = sum(count for _, count in settings.zone_subscriber_counts)
    if total > settings.pon_port_count * settings.max_onts_per_port:
        raise ValueError("ONT inventory exceeds configured PON capacity")
    rng = random.Random(settings.random_seed)
    conn = connect(settings.database_path)
    try:
        initialize_schema(conn)
        with conn:
            # Reseeding deliberately replaces this generated inventory atomically.
            for table in ("onts", "meters", "circuits", "transformers", "splitters",
                          "pon_ports", "olt_devices", "zones"):
                conn.execute(f"DELETE FROM {table}")

            for zone_id, count in settings.zone_subscriber_counts:
                name, profile = ZONE_META[zone_id]
                conn.execute("INSERT INTO zones VALUES (?, ?, ?, ?)",
                             (zone_id, name, profile, count))
                olt_id = f"OLT-{zone_id}-01"
                transformer_id = f"TX-{zone_id}-01"
                circuit_id = f"CIR-{zone_id}-01"
                conn.execute("INSERT INTO olt_devices VALUES (?, ?, ?)",
                             (olt_id, zone_id, f"OLT Zona {zone_id}"))
                conn.execute("INSERT INTO transformers VALUES (?, ?, ?)",
                             (transformer_id, zone_id, 1000.0))
                conn.execute("INSERT INTO circuits VALUES (?, ?, ?)",
                             (circuit_id, transformer_id, zone_id))

            if sum(ZONE_PORT_COUNTS.values()) != settings.pon_port_count:
                raise ValueError("Configured PON port count must match zone allocation")
            ports_by_zone: dict[str, list[str]] = {}
            global_port_index = 0
            for zone_id, port_count in ZONE_PORT_COUNTS.items():
                ports_by_zone[zone_id] = []
                for port_number in range(1, port_count + 1):
                    global_port_index += 1
                    port_id = f"PON-{global_port_index:03d}"
                    splitter_id = f"SPL-{global_port_index:03d}"
                    ports_by_zone[zone_id].append(port_id)
                    conn.execute("INSERT INTO pon_ports VALUES (?, ?, ?, ?)",
                                 (port_id, f"OLT-{zone_id}-01", port_number,
                                  settings.max_onts_per_port))
                    conn.execute("INSERT INTO splitters VALUES (?, ?, ?)",
                                 (splitter_id, port_id, settings.max_onts_per_port))

            assigned_by_port = {
                port_id: 0 for ports in ports_by_zone.values() for port_id in ports
            }
            subscriber_no = 0
            for zone_id, zone_count in settings.zone_subscriber_counts:
                candidates = ports_by_zone[zone_id]
                for offset in range(zone_count):
                    subscriber_no += 1
                    # Spread assignments reproducibly across each zone's ports.
                    choices = [p for p in candidates if assigned_by_port[p] < settings.max_onts_per_port]
                    if not choices:
                        raise ValueError(f"Insufficient PON capacity in zone {zone_id}")
                    port_id = choices[rng.randrange(len(choices))]
                    assigned_by_port[port_id] += 1
                    local_id = f"{zone_id}-{offset + 1:04d}"
                    meter_id = f"MTR-{local_id}"
                    conn.execute("INSERT INTO meters VALUES (?, ?, ?)",
                                 (meter_id, f"CIR-{zone_id}-01", zone_id))
                    splitter_id = conn.execute(
                        "SELECT splitter_id FROM splitters WHERE pon_port_id = ?", (port_id,)
                    ).fetchone()[0]
                    conn.execute("INSERT INTO onts VALUES (?, ?, ?, ?, ?, ?)",
                                 (f"ONT-{local_id}", zone_id, port_id, splitter_id,
                                  meter_id, subscriber_no))
        return inventory_summary(conn)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", help="Override the configured SQLite path")
    args = parser.parse_args()
    settings = load_settings()
    if args.database:
        from dataclasses import replace
        from pathlib import Path
        settings = replace(settings, data_dir=Path(args.database).resolve().parent,
                           database_name=Path(args.database).name)
    print(seed_city(settings))


if __name__ == "__main__":
    main()

