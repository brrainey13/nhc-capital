#!/usr/bin/env python3
"""
ETL: Commercial Valuations from CSV into PostgreSQL.
Source: Assessor_-_Commercial_Valuation_Data_*.csv (flat file).
Schema: schema/cook_county.md — commercial_valuations.
"""

import glob
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd
from utils.csv_normalize import normalize_commercial_valuation_csv
from utils.db import ensure_schema, get_connection, log_refresh

# Table columns (excluding id, created_at) for INSERT. Match schema/cook_county.md.
CV_COLS = [
    "keypin", "keypin_normalized", "pins", "year", "township", "modelgroup", "class_es",
    "studiounits", "_1brunits", "_2brunits", "_3brunits", "_4brunits", "tot_units",
    "address", "adj_rent_sf", "aprx_comm_sf", "apt", "avgdailyrate", "bldgsf",
    "gross_building_area", "caprate", "carwash", "category", "ceilingheight",
    "cost_day_bed", "costapproach_sf", "covidadjvacancy", "ebitda_pct", "egi",
    "excesslandarea", "excesslandval", "exp", "f_r", "finalmarketvalue",
    "finalmarketvalue_bed", "finalmarketvalue_key", "finalmarketvalue_sf", "finalmarketvalue_unit",
    "idphlicense", "incomemarketvalue", "incomemarketvalue_sf", "investmentrating",
    "land_bldg", "landsf", "model", "nbhd", "netrentablesf", "noi",
    "oiltankvalue_atypicaloby", "owner", "parking", "parkingsf", "pctownerinterest",
    "permit_partial_demovalue", "permit_partial_demovalue_reason", "pgi",
    "property_name_description", "property_type_use", "reportedoccupancy",
    "revenuebed_day", "revpar", "roomrev_pct", "salecompmarketvalue_sf",
    "sap", "sapdeduction", "saptier", "stories", "subclass2", "taxdist",
    "taxpayer", "totalrevreported", "totalexp", "totallandval", "totalrev",
    "townregion", "vacancy", "yearbuilt",
]


def find_csv(data_dir: str = None) -> str:
    """Locate Commercial Valuation CSV. data_dir defaults to project root."""
    data_dir = data_dir or ROOT
    pattern = os.path.join(data_dir, "Assessor_-_Commercial_Valuation_Data_*.csv")
    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError(f"No CSV found: {pattern}")
    return matches[0]


def run(csv_path: str = None, dry_run: bool = False) -> dict:
    csv_path = csv_path or find_csv()
    start = time.perf_counter()
    df = pd.read_csv(csv_path)
    df = normalize_commercial_valuation_csv(df)
    # Align to table columns (only columns that exist in DataFrame)
    cols = [c for c in CV_COLS if c in df.columns]
    missing = [c for c in CV_COLS if c not in df.columns and c != "keypin_normalized"]
    if missing:
        print(f"Note: CSV has no column for: {missing}")
    df = df[cols].copy()
    df = df.where(pd.notnull(df), None)
    rows = [tuple(r) for r in df.to_numpy()]
    fetched = len(rows)

    if dry_run:
        print(f"[dry run] Would upsert {fetched} rows into commercial_valuations from {csv_path}")
        return {"rows_fetched": fetched, "rows_inserted": 0, "duration_sec": 0, "data": df}

    with get_connection() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            from psycopg2.extras import execute_values
            cols_sql = ", ".join(cols)
            execute_values(
                cur,
                f"""
                INSERT INTO commercial_valuations ({cols_sql})
                VALUES %s
                ON CONFLICT (keypin_normalized, year) DO UPDATE SET
                    keypin = EXCLUDED.keypin, pins = EXCLUDED.pins, township = EXCLUDED.township,
                    modelgroup = EXCLUDED.modelgroup, class_es = EXCLUDED.class_es,
                    studiounits = EXCLUDED.studiounits, _1brunits = EXCLUDED._1brunits,
                    _2brunits = EXCLUDED._2brunits, _3brunits = EXCLUDED._3brunits, _4brunits = EXCLUDED._4brunits,
                    tot_units = EXCLUDED.tot_units, address = EXCLUDED.address, adj_rent_sf = EXCLUDED.adj_rent_sf,
                    aprx_comm_sf = EXCLUDED.aprx_comm_sf, apt = EXCLUDED.apt, avgdailyrate = EXCLUDED.avgdailyrate,
                    bldgsf = EXCLUDED.bldgsf, gross_building_area = EXCLUDED.gross_building_area,
                    caprate = EXCLUDED.caprate, carwash = EXCLUDED.carwash, category = EXCLUDED.category,
                    ceilingheight = EXCLUDED.ceilingheight, cost_day_bed = EXCLUDED.cost_day_bed,
                    costapproach_sf = EXCLUDED.costapproach_sf, covidadjvacancy = EXCLUDED.covidadjvacancy,
                    ebitda_pct = EXCLUDED.ebitda_pct, egi = EXCLUDED.egi,
                    excesslandarea = EXCLUDED.excesslandarea, excesslandval = EXCLUDED.excesslandval,
                    exp = EXCLUDED.exp, f_r = EXCLUDED.f_r, finalmarketvalue = EXCLUDED.finalmarketvalue,
                    finalmarketvalue_bed = EXCLUDED.finalmarketvalue_bed,
                    finalmarketvalue_key = EXCLUDED.finalmarketvalue_key,
                    finalmarketvalue_sf = EXCLUDED.finalmarketvalue_sf,
                    finalmarketvalue_unit = EXCLUDED.finalmarketvalue_unit,
                    idphlicense = EXCLUDED.idphlicense, incomemarketvalue = EXCLUDED.incomemarketvalue,
                    incomemarketvalue_sf = EXCLUDED.incomemarketvalue_sf,
                    investmentrating = EXCLUDED.investmentrating, land_bldg = EXCLUDED.land_bldg,
                    landsf = EXCLUDED.landsf, model = EXCLUDED.model, nbhd = EXCLUDED.nbhd,
                    netrentablesf = EXCLUDED.netrentablesf, noi = EXCLUDED.noi,
                    oiltankvalue_atypicaloby = EXCLUDED.oiltankvalue_atypicaloby, owner = EXCLUDED.owner,
                    parking = EXCLUDED.parking, parkingsf = EXCLUDED.parkingsf,
                    pctownerinterest = EXCLUDED.pctownerinterest,
                    permit_partial_demovalue = EXCLUDED.permit_partial_demovalue,
                    permit_partial_demovalue_reason = EXCLUDED.permit_partial_demovalue_reason,
                    pgi = EXCLUDED.pgi, property_name_description = EXCLUDED.property_name_description,
                    property_type_use = EXCLUDED.property_type_use,
                    reportedoccupancy = EXCLUDED.reportedoccupancy, revenuebed_day = EXCLUDED.revenuebed_day,
                    revpar = EXCLUDED.revpar, roomrev_pct = EXCLUDED.roomrev_pct,
                    salecompmarketvalue_sf = EXCLUDED.salecompmarketvalue_sf,
                    sap = EXCLUDED.sap, sapdeduction = EXCLUDED.sapdeduction, saptier = EXCLUDED.saptier,
                    stories = EXCLUDED.stories, subclass2 = EXCLUDED.subclass2, taxdist = EXCLUDED.taxdist,
                    taxpayer = EXCLUDED.taxpayer, totalrevreported = EXCLUDED.totalrevreported,
                    totalexp = EXCLUDED.totalexp, totallandval = EXCLUDED.totallandval,
                    totalrev = EXCLUDED.totalrev, townregion = EXCLUDED.townregion,
                    vacancy = EXCLUDED.vacancy, yearbuilt = EXCLUDED.yearbuilt
                """,
                rows,
                page_size=1000,
            )
            inserted = cur.rowcount

    duration = time.perf_counter() - start
    return {"rows_fetched": fetched, "rows_inserted": inserted, "duration_sec": duration}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="ETL Commercial Valuations CSV → PostgreSQL")
    p.add_argument("--csv-path", type=str, default=None, help="Path to CSV (default: auto-detect in project root)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    try:
        stats = run(csv_path=args.csv_path, dry_run=args.dry_run)
        if not args.dry_run and stats.get("rows_fetched"):
            with get_connection() as conn:
                log_refresh(
                    conn, "commercial_valuations", "full",
                    stats["rows_fetched"], stats.get("rows_inserted", 0), 0,
                    stats.get("duration_sec", 0), "success",
                )
        print("Done:", stats)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)
