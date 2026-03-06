#!/usr/bin/env python3
"""
Parallel VGSI scraper — runs multiple towns concurrently.

Usage:
    python scrape_parallel.py --workers 4 --delay 0.1 [--resume]
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.scrape_vgsi_parcels import scrape_town, fetch_parcel, parse_parcel

# 72 confirmed working towns (excludes 12 redirect failures + 5 already scraped)
WORKING_TOWNS = [
    "BethlehemCT", "BoltonCT", "BranfordCT", "BridgewaterCT",
    "BrookfieldCT", "BrooklynCT", "BurlingtonCT", "CantonCT", "ChaplinCT",
    "ClintonCT", "CornwallCT", "CoventryCT", "DeepRiverCT", "EastHaddamCT",
    "EastLymeCT", "EastWindsorCT", "EnfieldCT", "EssexCT", "FairfieldCT",
    "GlastonburyCT", "GranbyCT", "HamdenCT", "HamptonCT", "HarwintonCT",
    "KentCT", "LebanonCT", "LedyardCT", "LisbonCT", "MadisonCT",
    "ManchesterCT", "MansfieldCT", "MeridenCT", "MiddlefieldCT", "MiddletownCT",
    "MilfordCT", "NewBritainCT", "NewFairfieldCT", "NewLondonCT", "NewMilfordCT",
    "NewtownCT", "NorthBranfordCT", "NorwichCT", "OldLymeCT", "OldSaybrookCT",
    "OrangeCT", "PlainfieldCT", "PrestonCT", "ReddingCT", "SalemCT",
    "SalisburyCT", "SharonCT", "SomersCT", "SouthWindsorCT", "SouthburyCT",
    "SouthingtonCT", "SpragueCT", "StaffordCT", "SterlingCT", "StoningtonCT",
    "StratfordCT", "ThompsonCT", "TollandCT", "TrumbullCT", "WallingfordCT",
    "WaterfordCT", "WestHartfordCT", "WestHavenCT", "WestbrookCT",
    "WinchesterCT", "WindhamCT", "WolcottCT", "WoodstockCT",
]

PROGRESS_FILE = os.path.join(ROOT, "scripts", ".scrape_progress.json")


def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": [], "failed": [], "results": {}}


def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def estimate_max_pid(town: str) -> int:
    """Quick probe for max PID."""
    last_valid = 0
    for probe in [100, 500, 1000, 2000, 5000, 10000, 15000, 20000, 25000, 30000, 40000, 50000]:
        html = fetch_parcel(town, probe)
        if html and parse_parcel(html, town, probe):
            last_valid = probe
            time.sleep(0.1)
        else:
            break
    return max(int(last_valid * 1.3), 2000)


def scrape_one_town(town: str, delay: float, batch_size: int) -> dict:
    """Scrape a single town. Returns result dict."""
    max_pid = estimate_max_pid(town)
    print(f"  [{town}] max_pid={max_pid}, starting...", flush=True)
    result = scrape_town(
        town=town, min_units=0, max_pid=max_pid,
        dry_run=False, delay=delay, batch_size=batch_size,
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay between requests per worker")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    progress = load_progress()
    already_done = set(progress.get("completed", []))
    # Include the 5 originally scraped towns
    already_done.update({"AndoverCT", "BridgeportCT", "NewHavenCT", "StamfordCT", "WestportCT"})

    towns = WORKING_TOWNS
    if args.resume:
        towns = [t for t in towns if t not in already_done]

    print(f"=== Parallel VGSI Scraper ===", flush=True)
    print(f"Workers: {args.workers} | Delay: {args.delay}s | Towns: {len(towns)}", flush=True)
    print(f"Already done: {len(already_done)}", flush=True)
    print(flush=True)

    start_time = time.time()
    completed = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(scrape_one_town, town, args.delay, args.batch_size): town
            for town in towns
        }

        for future in as_completed(futures):
            town = futures[future]
            try:
                result = future.result()
                completed += 1
                progress["completed"].append(town)
                progress["results"][town] = result
                elapsed = time.time() - start_time
                print(f"\n✅ [{completed}/{len(towns)}] {town}: {result['total_found']} found, {result['total_saved']} saved ({elapsed/60:.1f}min elapsed)", flush=True)
            except Exception as e:
                failed += 1
                progress["failed"].append(town)
                print(f"\n❌ {town}: {e}", flush=True)

            save_progress(progress)

    elapsed = time.time() - start_time
    print(f"\n{'='*60}", flush=True)
    print(f"DONE in {elapsed/3600:.1f} hours", flush=True)
    print(f"Completed: {completed} | Failed: {failed}", flush=True)
    total = sum(r.get("total_saved", 0) for r in progress["results"].values())
    print(f"Total parcels saved: {total}", flush=True)


if __name__ == "__main__":
    main()
