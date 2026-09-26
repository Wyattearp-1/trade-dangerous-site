#!/usr/bin/env python3
"""
Rebuild data/trade-data.json from a public Elite: Dangerous data dump.

This is the piece that keeps the website "as close to live as possible":
run it on a schedule (see .github/workflows/update-data.yml) and it
downloads a fresh galaxy snapshot, keeps only the systems/stations/
commodities the trade optimizer actually needs, and writes a small JSON
file the static site can fetch.

Default data source: Spansh's public galaxy dumps (https://spansh.co.uk/dumps).
Spansh publishes several dump sizes; this script is written against the
"stations with market data, updated recently" style dump, because the full
galaxy dump is enormous (100+GB uncompressed) and total overkill for a
trading tool. IMPORTANT: dump filenames and the exact JSON field names on
Spansh's side can change — check https://spansh.co.uk/dumps before your
first real run and adjust SOURCE_URL / the field lookups below if needed.
The parsing below is written defensively (lots of .get() with fallbacks)
for exactly that reason.

Usage:
    pip install -r scripts/requirements.txt
    python scripts/build_data.py --out data/trade-data.json

Env vars (all optional):
    TD_SOURCE_URL       override the dump URL
    TD_MAX_STATIONS     cap station count (useful for local testing)
"""

import argparse
import gzip
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

import ijson  # streaming JSON parser -- the raw dump is far too big to load whole

DEFAULT_SOURCE_URL = os.environ.get(
    "TD_SOURCE_URL",
    # "Stations with markets, updated within the last day" style dump.
    # If Spansh renames this, grab the current link from https://spansh.co.uk/dumps
    "https://downloads.spansh.co.uk/galaxy_stations.json.gz",
)

MAX_STATIONS = int(os.environ.get("TD_MAX_STATIONS", "0")) or None  # 0/unset = no cap


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def open_source(url: str):
    """Return a file-like object of decompressed JSON bytes, streamed."""
    log(f"Downloading {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "trade-dangerous-web-builder/1.0"})
    resp = urllib.request.urlopen(req, timeout=120)
    if url.endswith(".gz"):
        return gzip.GzipFile(fileobj=resp)
    return resp


def pad_size_from_station(raw_station: dict) -> str:
    """Normalise whatever landing-pad info the dump gives us to 'L' or 'M'."""
    lp = raw_station.get("landingPads") or raw_station.get("landing_pads")
    if isinstance(lp, dict):
        if (lp.get("large") or 0) > 0:
            return "L"
        if (lp.get("medium") or 0) > 0:
            return "M"
    size = raw_station.get("maxLandingPadSize") or raw_station.get("max_landing_pad_size")
    if size:
        return "L" if str(size).upper().startswith("L") else "M"
    return "M"  # conservative default: assume can't fit a large ship


def extract_market(raw_station: dict):
    """
    Returns {commodityName: {buy, sell, supply, demand}} for a station,
    or None if it has no tradeable market at all (outposts with only
    ship/outfitting services, fleet carriers with market off, etc).
    """
    market = raw_station.get("market")
    commodities = None
    if isinstance(market, dict):
        commodities = market.get("commodities")
    elif isinstance(raw_station.get("commodities"), list):
        commodities = raw_station.get("commodities")

    if not commodities:
        return None

    out = {}
    for c in commodities:
        name = c.get("name") or c.get("symbol")
        if not name:
            continue
        buy = c.get("buyPrice") or c.get("buy_price") or 0
        sell = c.get("sellPrice") or c.get("sell_price") or 0
        if not buy and not sell:
            continue
        out[name.strip().upper()] = {
            "buy": int(buy or 0),
            "sell": int(sell or 0),
            "supply": int(c.get("supply") or 0),
            "demand": int(c.get("demand") or 0),
        }
    return out or None


def iter_systems(fh):
    """
    Streams top-level array items from the dump. Works whether the dump is
    "one big array of systems, each with a `stations` list" (Spansh's usual
    shape) or "one big array of stations, each with system info inline" --
    we sniff the first item's shape and branch.
    """
    parser = ijson.items(fh, "item")
    for obj in parser:
        yield obj


def build(source_url: str, out_path: str, max_stations):
    systems = {}
    stations = {}
    count = 0
    skipped_no_market = 0
    t0 = time.time()

    with open_source(source_url) as fh:
        for obj in iter_systems(fh):
            if max_stations and count >= max_stations:
                break

            # Shape A: system object containing a list of stations
            if "stations" in obj or "bodies" in obj:
                sys_name = obj.get("name")
                coords = obj.get("coords") or {}
                raw_stations = obj.get("stations") or []
            else:
                # Shape B: flat station object with system info inline
                sys_name = (obj.get("system") or {}).get("name") if isinstance(obj.get("system"), dict) else obj.get("systemName")
                coords = (obj.get("system") or {}).get("coords") or obj.get("systemCoords") or {}
                raw_stations = [obj]

            if not sys_name or "x" not in (coords or {}):
                continue
            sys_key = sys_name.strip().upper()

            for st in raw_stations:
                if max_stations and count >= max_stations:
                    break
                st_name = st.get("name")
                if not st_name:
                    continue
                mkt = extract_market(st)
                if not mkt:
                    skipped_no_market += 1
                    continue

                systems[sys_key] = {
                    "x": round(float(coords["x"]), 2),
                    "y": round(float(coords["y"]), 2),
                    "z": round(float(coords["z"]), 2),
                }
                key = f"{sys_key}/{st_name.strip().upper()}"
                stations[key] = {
                    "system": sys_key,
                    "pad": pad_size_from_station(st),
                    "distLs": int(st.get("distanceToArrival") or st.get("distance_to_arrival") or 0),
                    "planetary": bool(st.get("type", "").lower().find("surface") >= 0 or st.get("isPlanetary")),
                    "market": mkt,
                }
                count += 1
                if count % 5000 == 0:
                    log(f"  ...{count} stations so far ({time.time() - t0:.0f}s)")

    log(f"Kept {count} stations with markets ({skipped_no_market} skipped, no market data).")

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source_url,
        "systems": systems,
        "stations": stations,
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    size_mb = os.path.getsize(out_path) / 1e6
    log(f"Wrote {out_path} ({size_mb:.1f} MB).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/trade-data.json")
    ap.add_argument("--source", default=DEFAULT_SOURCE_URL)
    ap.add_argument("--max-stations", type=int, default=MAX_STATIONS)
    args = ap.parse_args()
    build(args.source, args.out, args.max_stations)


if __name__ == "__main__":
    main()
