#!/usr/bin/env python3
"""
Run the VGSI parcel scraper across all remaining Vision towns.

Usage:
    python scrape_all_vision_towns.py [--dry-run] [--max-pid 50000] [--delay 0.3]
    python scrape_all_vision_towns.py --town FairfieldCT   # single town
    python scrape_all_vision_towns.py --resume              # skip already-scraped towns
"""

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.scrape_vgsi_parcels import fetch_parcel, parse_parcel, scrape_town

# All 89 Vision towns (from memory/real-estate-data.md)
ALL_VISION_TOWNS = [
    "AndoverCT", "BerlinCT", "BethlehemCT", "BoltonCT", "BranfordCT",
    "BridgeportCT", "BridgewaterCT", "BristolCT", "BrookfieldCT", "BrooklynCT",
    "BurlingtonCT", "CanterburyCT", "CantonCT", "ChaplinCT", "ClintonCT",
    "CornwallCT", "CoventryCT", "DeepRiverCT", "EastGranbyCT", "EastHaddamCT",
    "EastLymeCT", "EastWindsorCT", "EnfieldCT", "EssexCT", "FairfieldCT",
    "GlastonburyCT", "GranbyCT", "GriswoldCT", "HamdenCT", "HamptonCT",
    "HarwintonCT", "KentCT", "LebanonCT", "LedyardCT", "LisbonCT",
    "LymeCT", "MadisonCT", "ManchesterCT", "MansfieldCT", "MeridenCT",
    "MiddleburyCT", "MiddlefieldCT", "MiddletownCT", "MilfordCT", "MonroeCT",
    "NewBritainCT", "NewFairfieldCT", "NewHartfordCT", "NewHavenCT", "NewLondonCT",
    "NewMilfordCT", "NewtownCT", "NorthBranfordCT", "NorwichCT", "OldLymeCT",
    "OldSaybrookCT", "OrangeCT", "PlainfieldCT", "PomfretCT", "PrestonCT",
    "ReddingCT", "SalemCT", "SalisburyCT", "SharonCT", "SomersCT",
    "SouthWindsorCT", "SouthburyCT", "SouthingtonCT", "SpragueCT", "StaffordCT",
    "StamfordCT", "SterlingCT", "StoningtonCT", "StratfordCT", "ThompsonCT",
    "TollandCT", "TrumbullCT", "UnionCT", "WallingfordCT", "WaterfordCT",
    "WestHartfordCT", "WestHavenCT", "WestbrookCT", "WestportCT", "WillingtonCT",
    "WinchesterCT", "WindhamCT", "WolcottCT", "WoodstockCT",
]

# Towns already scraped (as of Feb 19, 2026)
ALREADY_SCRAPED = {"AndoverCT", "BridgeportCT", "NewHavenCT", "StamfordCT", "WestportCT"}

PROGRESS_FILE = os.path.join(ROOT, "scripts", ".scrape_progress.json")


def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": list(ALREADY_SCRAPED), "failed": [], "results": {}}


def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def probe_town(town: str) -> bool:
    """Quick check if a town's VGSI site works by trying multiple PIDs."""
    for pid in [100, 500, 1000, 5000, 10000]:
        html = fetch_parcel(town, pid)
        if html:
            p = parse_parcel(html, town, pid)
            if p is not None:
                return True
    return False


def estimate_max_pid(town: str) -> int:
    """Binary search for approximate max PID in a town."""
    _low, _high = 1, 80000
    last_valid = 0

    # Quick probes at geometric intervals
    for probe in [100, 500, 1000, 5000, 10000, 20000, 30000, 40000, 50000, 60000]:
        html = fetch_parcel(town, probe)
        if html and parse_parcel(html, town, probe):
            last_valid = probe
            time.sleep(0.2)
        else:
            break

    if last_valid == 0:
        return 5000  # default for small towns

    # Add 20% buffer
    return int(last_valid * 1.3)


def main():
    parser = argparse.ArgumentParser(description="Scrape all Vision towns")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-pid", type=int, default=0, help="Override max PID (0=auto-detect)")
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--town", type=str, help="Scrape single town")
    parser.add_argument("--resume", action="store_true", help="Skip already-completed towns")
    parser.add_argument("--probe-only", action="store_true", help="Just test which towns work")
    args = parser.parse_args()

    progress = load_progress()

    if args.town:
        towns = [args.town]
    else:
        towns = [t for t in ALL_VISION_TOWNS if t not in ALREADY_SCRAPED]

    if args.resume:
        towns = [t for t in towns if t not in progress["completed"]]

    print("=== VGSI Multi-Town Scraper ===", flush=True)
    print(f"Towns to process: {len(towns)}", flush=True)
    print(f"Already completed: {len(progress['completed'])}", flush=True)
    print(flush=True)

    if args.probe_only:
        working = []
        broken = []
        for town in towns:
            ok = probe_town(town)
            status = "✅" if ok else "❌"
            print(f"  {status} {town}", flush=True)
            (working if ok else broken).append(town)
            time.sleep(0.3)
        print(f"\nWorking: {len(working)}, Broken: {len(broken)}")
        if broken:
            print(f"Broken towns: {broken}")
        return

    for i, town in enumerate(towns):
        print(f"\n{'='*60}", flush=True)
        print(f"[{i+1}/{len(towns)}] {town}", flush=True)
        print(f"{'='*60}", flush=True)

        # Probe first
        if not probe_town(town):
            print(f"  ❌ {town} VGSI site not responding or redirecting. Skipping.", flush=True)
            progress["failed"].append(town)
            save_progress(progress)
            continue

        # Auto-detect max PID
        max_pid = args.max_pid
        if max_pid == 0:
            print("  Estimating max PID...", flush=True)
            max_pid = estimate_max_pid(town)
            print(f"  Estimated max PID: {max_pid}", flush=True)

        try:
            result = scrape_town(
                town=town,
                min_units=0,
                max_pid=max_pid,
                dry_run=args.dry_run,
                delay=args.delay,
                batch_size=args.batch_size,
            )
            progress["completed"].append(town)
            progress["results"][town] = result
            save_progress(progress)
            print(f"\n  ✅ {town}: {result['total_found']} found, {result['total_saved']} saved", flush=True)

        except Exception as e:
            print(f"\n  ❌ {town} ERROR: {e}", flush=True)
            progress["failed"].append(town)
            save_progress(progress)

        # Brief pause between towns
        time.sleep(2)

    # Final summary
    print(f"\n{'='*60}", flush=True)
    print("COMPLETE", flush=True)
    print(f"  Scraped: {len(progress['completed'])}", flush=True)
    print(f"  Failed: {len(progress['failed'])}", flush=True)
    total_parcels = sum(r.get("total_saved", 0) for r in progress["results"].values())
    print(f"  Total parcels: {total_parcels}", flush=True)
    if progress["failed"]:
        print(f"  Failed towns: {progress['failed']}", flush=True)


if __name__ == "__main__":
    main()
