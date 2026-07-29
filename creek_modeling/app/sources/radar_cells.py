"""NEXRAD storm-cell tracks — inbound-cell early warning (slice 2g).

The gap this fills: storms here typically arrive from the W/NW, but the upstream PWS
corridor lies to the *SE* — geometrically behind the house for the dominant storm
motion. A convective cell on the usual track therefore reaches the house *before* any
upstream gauge sees rain, so every existing leading indicator (onsite gauge, upstream
PWS, even QPF between forecast cycles) is trailing for exactly the storms that matter
most. Radar cell tracks are the only input that leads regardless of approach bearing.

Data is the NWS Level 3 storm-attribute table from KBGM (the same SCIT product radar
apps render as cell markers with track vectors), served as CSV by the Iowa
Environmental Mesonet, which processes it in real time as each volume scan arrives
(~every 4-6 min in precip mode). Free, no key:

  GET mesonet.agron.iastate.edu/cgi-bin/request/gis/nexrad_storm_attrs.py
      ?fmt=csv&radar=BGM&sts=...&ets=...   (site code WITHOUT the ICAO K prefix)

Columns used: VALID (YYYYMMDDHHMM UTC), STORM_ID, DRCT, SKNT, MAX_DBZ, LAT, LON.

DRCT CONVENTION — VERIFIED EMPIRICALLY, DO NOT "FIX" TO THE OTHER SIGN. DRCT is the
direction the cell is coming FROM (wind convention): heading = (DRCT + 180) % 360.
Confirmed against live KBGM data on 2026-07-29 by regressing every storm's actual
centroid displacement over 30-135 min of track against its reported DRCT: the
from-convention matched all 45 storms with a usable track, the toward-convention
matched none. Getting this backwards silently inverts every threat call, which is why
`tests/test_radar_cells.py` pins the convention with a hand-computed case.

For each intense cell the threat test is a closest-point-of-approach (CPA) problem on
a flat local tangent plane (fine at these ranges): project the site onto the cell's
track line; the cell is a threat when that approach is close enough, genuinely inbound
(the along-track component is ahead of the cell, not behind it), and arriving soon.
The CPA radius covers the house *and* the short SE upstream corridor, so "headed at
me" and "working my upstream" are both caught without hardcoding a compass sector.

SCIT only tracks discrete cells — broad stratiform shields produce no attribute rows.
That is the accepted division of labour: QPF already handles the synoptic stuff well;
this exists for the convective gap between forecast cycles.
"""
from __future__ import annotations

import csv
import io
import logging
import math
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger("app.sources.radar_cells")

FEATURE_KEYS = (
    "radar_cells_tracked",
    "radar_threat_cells",
    "radar_threat_eta_min",
    "radar_threat_max_dbz",
)

# PLACEHOLDER THRESHOLDS — tune with observed storms, like everything else in tiers.py.
MIN_DBZ = 40.0            # below this a cell is tracked but not rain that matters
MIN_SPEED_KT = 5.0        # SCIT emits DRCT=0/SKNT=0 for unresolved motion; near-zero
                          # speed also makes the track bearing meaningless noise
CPA_RADIUS_MI = 4.0       # house + the SE upstream corridor
ETA_HORIZON_MIN = 90.0    # beyond this the cell will likely die/reform first

FETCH_WINDOW_MIN = 30     # how far back to ask IEM for rows
FRESH_MINUTES = 12.0      # a cell absent this long from the newest scan has dropped out

NM_PER_DEG_LAT = 60.0
MI_PER_NM = 1.15078


def _default_fetch(url: str, timeout: float = 15.0) -> str:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


class RadarCells:
    name = "radar"
    refresh_seconds = 5 * 60

    def __init__(self, lat: float, lon: float, radar_id: str = "KBGM",
                 fetch=_default_fetch, now_fn=None):
        self._lat = lat
        self._lon = lon
        # IEM's NEXRAD field is the 3-char site (BGM); accept the ICAO form too.
        self._radar = radar_id[-3:].upper() if len(radar_id) == 4 else radar_id.upper()
        self._fetch = fetch
        self._now = now_fn or (lambda: datetime.now(timezone.utc))

    def poll(self) -> dict:
        now = self._now()
        sts = (now - timedelta(minutes=FETCH_WINDOW_MIN)).strftime("%Y-%m-%dT%H:%MZ")
        ets = now.strftime("%Y-%m-%dT%H:%MZ")
        url = (
            "https://mesonet.agron.iastate.edu/cgi-bin/request/gis/nexrad_storm_attrs.py"
            f"?fmt=csv&radar={self._radar}&sts={sts}&ets={ets}"
        )
        cells = self._current_cells(self._fetch(url))

        out: dict[str, float | None] = {
            "radar_cells_tracked": float(len(cells)),
            "radar_threat_cells": 0.0,
            "radar_threat_eta_min": None,
            "radar_threat_max_dbz": None,
        }
        etas, dbzs = [], []
        for cell in cells:
            eta = self._intercept_eta_min(cell)
            if eta is not None:
                etas.append(eta)
                dbzs.append(cell["max_dbz"])
        if etas:
            out["radar_threat_cells"] = float(len(etas))
            out["radar_threat_eta_min"] = round(min(etas), 1)
            out["radar_threat_max_dbz"] = max(dbzs)
        return out

    @staticmethod
    def _current_cells(text: str) -> list[dict]:
        """Newest row per storm ID, dropping cells that fell out of tracking.

        Every volume scan re-lists every tracked cell, so the raw window holds each
        storm several times over; only its latest fix describes the present. A cell
        whose latest fix is much older than the newest scan was dropped by SCIT
        (dissipated or merged) and no longer exists to threaten anything.
        """
        newest: dict[str, dict] = {}
        latest_scan: datetime | None = None
        for row in csv.DictReader(io.StringIO(text)):
            try:
                cell = {
                    "valid": datetime.strptime(row["VALID"], "%Y%m%d%H%M"),
                    "id": row["STORM_ID"],
                    "lat": float(row["LAT"]),
                    "lon": float(row["LON"]),
                    "drct": float(row["DRCT"]),
                    "sknt": float(row["SKNT"]),
                    "max_dbz": float(row["MAX_DBZ"]),
                }
            except (KeyError, TypeError, ValueError):
                continue    # torn/malformed row — skip it, keep the rest
            prev = newest.get(cell["id"])
            if prev is None or cell["valid"] > prev["valid"]:
                newest[cell["id"]] = cell
            if latest_scan is None or cell["valid"] > latest_scan:
                latest_scan = cell["valid"]
        if latest_scan is None:
            return []
        cutoff = latest_scan - timedelta(minutes=FRESH_MINUTES)
        return [c for c in newest.values() if c["valid"] >= cutoff]

    def _intercept_eta_min(self, cell: dict) -> float | None:
        """Minutes until this cell's closest approach to the site, or None if it is
        no threat (weak, unresolved motion, outbound, passing wide, or too far out)."""
        if cell["max_dbz"] < MIN_DBZ or cell["sknt"] < MIN_SPEED_KT:
            return None

        # Site position relative to the cell, in nm on a local tangent plane.
        midlat = math.radians((self._lat + cell["lat"]) / 2)
        north = (self._lat - cell["lat"]) * NM_PER_DEG_LAT
        east = (self._lon - cell["lon"]) * NM_PER_DEG_LAT * math.cos(midlat)

        # DRCT is direction-FROM (verified above); the motion unit vector points toward.
        heading = math.radians((cell["drct"] + 180.0) % 360.0)
        ue, un = math.sin(heading), math.cos(heading)

        along_nm = east * ue + north * un          # site's distance ahead of the cell
        if along_nm <= 0:
            return None                            # already past us / moving away
        cross_nm = abs(east * un - north * ue)     # miss distance at closest approach
        if cross_nm * MI_PER_NM > CPA_RADIUS_MI:
            return None                            # passing wide

        eta_min = along_nm / cell["sknt"] * 60.0   # kt = nm/h, so this is minutes
        if eta_min > ETA_HORIZON_MIN:
            return None
        return eta_min
