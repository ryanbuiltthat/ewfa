"""Persistent dataset writer (spec §4 nightly batch, §7 Phase 3 event log).

Fast loop appends feature rows to a Parquet dataset; the annotated storm event
log lives in SQLite. Both under /data so they survive add-on updates.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

from .features import FeatureRow

log = logging.getLogger("app.dataset")


class DatasetWriter:
    def __init__(self, data_dir: Path):
        self._parquet = data_dir / "datasets" / "dataset.parquet"
        self._sqlite = data_dir / "events.sqlite"
        self._parquet.parent.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()

    def _init_sqlite(self) -> None:
        with sqlite3.connect(self._sqlite) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS storm_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_ts REAL NOT NULL,
                    ended_ts REAL,
                    peak_stage_ft REAL,
                    notes TEXT
                )
                """
            )

    def append_row(self, row: FeatureRow) -> None:
        """Append a single feature row. Parquet has no cheap append, so we read +
        concat + rewrite; fine at fast-loop cadence (a few hundred rows/day)."""
        df_new = pd.DataFrame([row.as_dict()])
        if self._parquet.exists():
            df = pd.concat([pd.read_parquet(self._parquet), df_new], ignore_index=True)
        else:
            df = df_new
        df.to_parquet(self._parquet, index=False)
        log.debug("Dataset now %d rows", len(df))

    def row_count(self) -> int:
        if not self._parquet.exists():
            return 0
        return len(pd.read_parquet(self._parquet, columns=["ts"]))
