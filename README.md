# Trade Dangerous — Web

A browser port of the core idea behind [Trade Dangerous](https://github.com/eyeonus/Trade-Dangerous):
a multi-hop trade route optimizer for Elite: Dangerous. This is **not** the
original TD codebase — TD is a Python CLI/GUI app with its own SQLite
database and EDDN listener, and none of that can run on GitHub Pages, which
only serves static files. This project re-implements the *routing idea* as
a self-contained static site, and uses GitHub Actions to keep its trade
data as fresh as a static site can be.

## How it stays "live"

- `data/trade-data.json` is a compact snapshot of systems, stations, and
  commodity markets.
- `.github/workflows/update-data.yml` runs on a schedule (every 3 hours by
  default), re-downloads a public galaxy data dump, rebuilds
  `trade-data.json`, and commits it if anything changed.
- `.github/workflows/pages.yml` redeploys the site to GitHub Pages any time
  `main` changes — including those automated data commits.
- The **route optimizer itself runs entirely in the visitor's browser**
  (`js/optimizer.js`) against whatever `trade-data.json` currently says. No
  backend, no per-request server cost.

This is the closest a static GitHub Pages site can get to "live": the data
is at most one refresh cycle old, and you control that cycle by editing the
cron schedule in `update-data.yml`.

## Setup

1. **Push this repo to GitHub** (create a new repo, or use this folder as
   the root of an existing one).
2. **Enable Pages**: repo Settings → Pages → Source → "GitHub Actions".
3. **Enable Actions** if prompted (Settings → Actions → General → allow
   workflows to run).
4. That's it. `pages.yml` deploys on every push to `main`; `update-data.yml`
   refreshes the data and pushes to `main` on its own schedule, which
   triggers a redeploy automatically.

You can also trigger either workflow manually from the **Actions** tab
(`workflow_dispatch`) instead of waiting for the schedule — handy for
verifying everything works right after you push.

## Data source — please read before your first real run

`scripts/build_data.py` downloads a public galaxy dump (currently pointed
at one of [Spansh](https://spansh.co.uk/dumps)'s station-market dumps) and
compacts it. Two things worth knowing:

- **Dump filenames and field names can change upstream.** The script parses
  defensively (falls back across a few likely field names), but you should
  still check <https://spansh.co.uk/dumps> and skim the first few objects
  of whatever dump you point at before trusting it in production. Adjust
  `SOURCE_URL` / the field lookups in `build_data.py` if the shape has
  moved on.
- **The full galaxy dump is enormous** (100+ GB uncompressed) — don't point
  this at it. Use one of the smaller "stations with markets" or
  "recently updated" dumps; that's what keeps the Action fast and
  `trade-data.json` small enough to serve.

If you'd rather source data from somewhere else entirely (Trade Dangerous'
own `eddblink` server, EDSM, your own EDMC export, etc.), swap out
`build_data.py`'s download/parse logic — the only contract the rest of the
site relies on is the output shape:

```json
{
  "generated_at": "2026-09-26T00:00:00Z",
  "systems":  { "SYSTEM NAME": { "x": 0, "y": 0, "z": 0 } },
  "stations": {
    "SYSTEM NAME/STATION NAME": {
      "system": "SYSTEM NAME",
      "pad": "L",
      "distLs": 490,
      "planetary": false,
      "market": {
        "COMMODITY NAME": { "buy": 9250, "sell": 8900, "supply": 3400, "demand": 0 }
      }
    }
  }
}
```

A small hand-written sample dataset ships in `data/trade-data.json` so the
site works immediately, before you've run the build script for real.

## Local development

```bash
python -m http.server 8000    # from this folder
# open http://localhost:8000
```

To test a real data rebuild locally:

```bash
pip install -r scripts/requirements.txt
python scripts/build_data.py --out data/trade-data.json --max-stations 20000
```

(`--max-stations` caps the run so you're not downloading and parsing the
full dump just to sanity-check it.)

## What the optimizer does and doesn't do

It plans multi-hop trade runs (`js/optimizer.js`): starting station, credits,
insurance reserve, cargo capacity, jump range, max jumps per hop, number of
hops, avoid-lists for systems/stations/commodities, an optional "head
toward" system, an optional loop-back-to-start, and a minimum profit
threshold. At each hop it evaluates nearby stations, works out the best
cargo load for that leg, and keeps a beam of the best partial routes going
into the next hop.

It's a genuine re-implementation of TD's *approach*, not a guarantee of
identical output to the real TD — the real tool has years of edge-case
handling (station bans, fleet carriers, odyssey settlements, exact
jump-graph pathing rather than straight-line distance, etc.) that this
does not attempt to fully replicate.

## License

MIT for this code. Not affiliated with Frontier Developments, Elite
Dangerous, or the Trade Dangerous project — just inspired by it.
