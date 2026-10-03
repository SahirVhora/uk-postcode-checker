"""Run the Area Pack pipeline.

    python -m pipeline.run --sources all
    python -m pipeline.run --sources onspd,catchments --refresh
    python -m pipeline.run --sources all --offline
"""

import argparse
import importlib
import logging
import sys
import traceback

from . import ManualInputNeeded, SourceFormatChanged
from .context import Context
from .db import count, record_run

# Build priority order: backbone, schools, prices, neighbourhood, community.
SOURCES = [
    "onspd", "catchments", "gias", "ofsted", "performance", "gates", "admissions",
    "ppd", "epc",
    "census", "imd", "lsoa_boundaries", "police",
    "osm",
]

# Main table populated by each source, used for row counts.
TABLES = {
    "onspd": "postcodes", "catchments": "postcode_catchments", "gias": "schools", "ofsted": "ofsted",
    "performance": "performance", "gates": "school_gates", "admissions": "admissions_history",
    "ppd": "ppd", "epc": "epc", "census": "census", "imd": "imd", "lsoa_boundaries": "lsoa_boundaries",
    "police": "crimes", "osm": "osm_pois",
}

log = logging.getLogger("pipeline")


def run_source(ctx: Context, name: str) -> tuple[str, int | None, str]:
    mod = importlib.import_module(f"pipeline.sources.{name}")
    ctx.reset_run_state()
    log.info("=== %s (%s)", name, ctx.mode)
    try:
        raw = mod.fetch(ctx)
        rows = mod.parse(ctx, raw)
        mod.load(ctx, rows)
        problems = mod.validate(ctx) or []
        n = count(ctx.conn, TABLES[name])
        status = "ok" if not problems else "ok_with_warnings"
        note = "; ".join(ctx.notes + problems) or None
        for p in problems:
            log.warning("[%s] %s", name, p)
    except ManualInputNeeded as exc:
        n, status, note = None, "skipped_manual_input_needed", str(exc)
        log.error("[%s] MANUAL INPUT NEEDED: %s", name, exc)
    except SourceFormatChanged as exc:
        n, status, note = None, "failed_format_changed", str(exc)
        log.error("[%s] FORMAT CHANGED: %s", name, exc)
    except Exception as exc:  # keep going so one broken source does not block the others
        n, status, note = None, "failed", f"{exc.__class__.__name__}: {exc}"
        log.error("[%s] FAILED: %s\n%s", name, exc, traceback.format_exc())
    record_run(ctx.conn, name, ctx.mode, status, url=ctx.source_url, licence=getattr(mod, "LICENCE", None),
               fetched_at=ctx.latest_fetch(), row_count=n, note=note)
    log.info("[%s] %s, rows=%s", name, status, n)
    return status, n, note


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", default="all", help="all, or a comma-separated list of: " + ",".join(SOURCES))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--refresh", action="store_true", help="ignore the cache and download again")
    mode.add_argument("--offline", action="store_true", help="rebuild only from pipeline/cache, no network")
    parser.add_argument("--no-derive", action="store_true", help="skip distances, metrics and scores")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    names = SOURCES if args.sources == "all" else [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        parser.error(f"unknown sources: {unknown}")

    ctx = Context.create(offline=args.offline, refresh=args.refresh)
    results = {name: run_source(ctx, name) for name in names}

    if not args.no_derive:
        from . import derive
        derive.run_all(ctx)

    print("\nSummary")
    print(f"{'source':<16}{'status':<30}{'rows':>10}")
    for name, (status, n, note) in results.items():
        print(f"{name:<16}{status:<30}{'' if n is None else n:>10}")
    failed = [n for n, (s, _, _) in results.items() if s.startswith("failed")]
    manual = [n for n, (s, _, _) in results.items() if s.startswith("skipped")]
    if manual:
        print(f"\nManual input needed: {', '.join(manual)} (see notes in source_runs / docs/MANUAL_CHECKS.md)")
    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
