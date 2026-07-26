"""Storm event log (spec §7 Phase 3).

Phase 3's deliverable is an *annotated* record of storms: the unit of analysis for
"how long after the rain does the creek respond", and the count that gates the move from
threshold alerting to ML (`min_events_for_ml`, §5). Until now `events.sqlite` had a table
and nothing ever wrote to it, so that gate could never open.

Detection runs on the live feature stream rather than over the dataset nightly, because
the peaks matter and a 5-minute stream sees them; re-deriving from stored rows would work
too but would miss anything between samples. The open event lives in SQLite and is updated
in place, so a restart mid-storm resumes rather than splitting one storm into two.

An event is deliberately defined by *rainfall*, not by creek response: with no gauge yet
the response side is often empty, and defining events by rain means the record being built
now stays valid once the SEN0676 is mounted. Peak stage and rate-of-rise are recorded when
present and left null otherwise.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

log = logging.getLogger("app.storms")

# Where the log lives under /share. Namespaced so the add-on owns a directory rather
# than dropping a bare events.sqlite into a volume other add-ons share.
SHARE_SUBDIR = "creek_modeling"

# A human editing the DB by hand is now an expected concurrent writer, not an anomaly.
# The fast loop's writes are sub-millisecond, so any collision clears almost immediately
# — but the CLI's default is to fail instantly with "database is locked" rather than wait.
BUSY_TIMEOUT_MS = 5000

# PLACEHOLDER thresholds — a small flashy basin (§1), tune once storms are on record.
START_RAIN_1H_IN = 0.10        # on-site or upstream: rain is meaningfully falling
CONTINUE_RAIN_1H_IN = 0.02     # below this the storm is considered to have paused
END_QUIET_SECONDS = 6 * 3600   # ...and after this long paused, it has ended

# Columns tracked as running maxima over the event's life.
_PEAKS = {
    "peak_rain_1h_in": "rain_1h_in",
    "peak_upstream_rain_1h_in": "upstream_rain_1h_in",
    "peak_qpf_6h_in": "qpf_6h_in",
    "peak_stage_ft": "stage_ft",
    "peak_rate_of_rise_in_min": "rate_of_rise_in_min",
    "peak_leggetts_rise_3h_ft": "usgs_leggetts_rise_3h_ft",
    "peak_tunkhannock_rise_3h_ft": "usgs_tunkhannock_rise_3h_ft",
    "peak_alert_tier": None,       # supplied by the caller, not a feature-row field
}

_SCHEMA = {
    "started_ts": "REAL NOT NULL",
    "ended_ts": "REAL",
    "max_24h_rain_in": "REAL",
    "max_24h_upstream_rain_in": "REAL",
    "api_at_onset_in": "REAL",
    "soil_at_onset_pct": "REAL",
    "swe_at_onset_in": "REAL",
    "rain_on_snow": "INTEGER",
    "notes": "TEXT",
    **{k: "REAL" for k in _PEAKS},
}


def _resolve_db_path(data_dir: Path, share_dir: Path | None) -> Path:
    """Prefer /share so the file is reachable by hand; fall back to /data.

    The fallback is not decoration: `share:rw` can be dropped from the add-on's config,
    and outside Supervisor (local dev, the test suite) there is no /share at all. Losing
    the convenient path is acceptable; failing to record storms is not.

    An existing /data log is *moved*, never copied — a copy would leave the service
    writing one file while a human annotates another, and the annotations are the whole
    point of the log.
    """
    legacy = data_dir / "events.sqlite"
    if share_dir is None:
        return legacy

    target_dir = share_dir / SHARE_SUBDIR
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        probe = target_dir / ".write-test"
        probe.touch()
        probe.unlink()
    except OSError as exc:
        log.warning("%s not writable (%s) — storm log stays at %s", target_dir, exc, legacy)
        return legacy

    target = target_dir / "events.sqlite"
    if not target.exists() and legacy.exists():
        try:
            shutil.move(str(legacy), str(target))
            log.info("Migrated storm event log %s -> %s", legacy, target)
        except OSError as exc:
            log.warning("Could not migrate %s (%s) — staying put", legacy, exc)
            return legacy
    return target


class StormLog:
    """Detects storm events from the feature stream and records them in SQLite."""

    def __init__(self, data_dir: Path, share_dir: Path | None = None):
        self._path = _resolve_db_path(data_dir, share_dir)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._last_rain_ts: float | None = None   # last sample with meaningful rain
        log.info("Storm event log at %s", self._path)

    @property
    def path(self) -> Path:
        """Where the log actually landed — logged at startup and quoted in the docs, so
        the annotate command can name one real path instead of a guess."""
        return self._path

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path, timeout=BUSY_TIMEOUT_MS / 1000)
        con.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        con.row_factory = sqlite3.Row
        return con

    def _init_schema(self) -> None:
        with self._connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS storm_events ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, started_ts REAL NOT NULL)")
            # Additive migration: the original table had only a few columns, and any rows
            # a human already annotated must survive.
            existing = {r["name"] for r in con.execute("PRAGMA table_info(storm_events)")}
            for column, decl in _SCHEMA.items():
                if column not in existing:
                    con.execute(f"ALTER TABLE storm_events ADD COLUMN {column} "
                                f"{decl.replace(' NOT NULL', '')}")

    # --- detection ------------------------------------------------------------------
    @staticmethod
    def _rain_now(row) -> float:
        """Strongest 1 h rain signal available — on-site or upstream."""
        return max(row.rain_1h_in or 0.0, row.upstream_rain_1h_in or 0.0)

    def observe(self, row, alert_tier: int | None = None) -> str | None:
        """Feed one feature row. Returns "opened"/"closed" when the state changes."""
        rain = self._rain_now(row)
        open_event = self._open_event()

        if open_event is None:
            if rain >= START_RAIN_1H_IN:
                self._open(row)
                self._last_rain_ts = row.ts
                log.info("Storm event opened (rain %.2f in/h)", rain)
                return "opened"
            return None

        self._accumulate(open_event, row, alert_tier)
        if rain >= CONTINUE_RAIN_1H_IN:
            self._last_rain_ts = row.ts
            return None

        # Quiet: close only once it has been quiet long enough to be a separate storm.
        since = row.ts - (self._last_rain_ts or open_event["started_ts"])
        if since >= END_QUIET_SECONDS:
            self._close(open_event["id"], row.ts - since)
            self._last_rain_ts = None
            log.info("Storm event %d closed", open_event["id"])
            return "closed"
        return None

    def _open_event(self) -> sqlite3.Row | None:
        with self._connect() as con:
            return con.execute(
                "SELECT * FROM storm_events WHERE ended_ts IS NULL "
                "ORDER BY started_ts DESC LIMIT 1").fetchone()

    def _open(self, row) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO storm_events (started_ts, api_at_onset_in, soil_at_onset_pct,"
                " swe_at_onset_in, rain_on_snow, max_24h_rain_in, max_24h_upstream_rain_in)"
                " VALUES (?,?,?,?,?,0,0)",
                (row.ts, row.api_index_in, row.soil_moisture_mean_pct,
                 row.snow_water_equivalent_in, 1 if row.rain_on_snow_flag else 0),
            )

    def _accumulate(self, event: sqlite3.Row, row, alert_tier: int | None) -> None:
        """Update running peaks and storm totals."""
        updates: dict[str, float] = {}
        for column, feature in _PEAKS.items():
            value = alert_tier if feature is None else getattr(row, feature, None)
            if value is None:
                continue
            current = event[column]
            if current is None or value > current:
                updates[column] = float(value)

        # Peak 24 h accumulation during the event. NOT a true storm total: the 24 h window
        # is rolling, so back-to-back storms inflate the later one's figure with the
        # earlier one's rain. Taking the max is still wrong-but-bounded, whereas summing
        # the samples would count each one ~12 times over. A true per-event total needs
        # integrating rain_rate_in_hr across the event — worth doing once storms are on
        # record and the accumulation semantics can be checked against them.
        for column, feature in (("max_24h_rain_in", "rain_24h_in"),
                                ("max_24h_upstream_rain_in", "upstream_rain_24h_in")):
            value = getattr(row, feature, None)
            if value is not None and (event[column] is None or value > event[column]):
                updates[column] = float(value)

        if updates:
            assignments = ", ".join(f"{c} = ?" for c in updates)
            with self._connect() as con:
                con.execute(f"UPDATE storm_events SET {assignments} WHERE id = ?",
                            (*updates.values(), event["id"]))

    def _close(self, event_id: int, ended_ts: float) -> None:
        with self._connect() as con:
            con.execute("UPDATE storm_events SET ended_ts = ? WHERE id = ?",
                        (ended_ts, event_id))

    # --- reads ----------------------------------------------------------------------
    def count(self, completed_only: bool = True) -> int:
        """Completed storms — the number `min_events_for_ml` gates on (§5)."""
        sql = "SELECT COUNT(*) AS n FROM storm_events"
        if completed_only:
            sql += " WHERE ended_ts IS NOT NULL"
        with self._connect() as con:
            return int(con.execute(sql).fetchone()["n"])

    def events(self, limit: int = 20) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM storm_events ORDER BY started_ts DESC "
                               "LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def latest(self) -> dict | None:
        events = self.events(limit=1)
        return events[0] if events else None

    def annotate(self, event_id: int, notes: str) -> None:
        """Attach a human note — the "annotated" half of the Phase 3 deliverable."""
        with self._connect() as con:
            con.execute("UPDATE storm_events SET notes = ? WHERE id = ?", (notes, event_id))
