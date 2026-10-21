"""Central settings for the JONGOX Smart City simulation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = PROJECT_ROOT / "data"
    database_name: str = "jongox_city.sqlite3"
    random_seed: int = 20261020
    pon_port_count: int = 80
    max_onts_per_port: int = 64
    zone_subscriber_counts: tuple[tuple[str, int], ...] = (
        ("A", 2200),
        ("B", 1400),
        ("C", 600),
        ("D", 800),
    )

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_name


def load_settings() -> Settings:
    """Load supported environment overrides while retaining safe defaults."""
    defaults = Settings()
    data_dir = Path(os.environ.get("JONGOX_DATA_DIR", str(defaults.data_dir)))
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    seed = int(os.environ.get("JONGOX_RANDOM_SEED", defaults.random_seed))
    return Settings(data_dir=data_dir, random_seed=seed)

