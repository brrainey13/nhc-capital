"""
Sales Comp Engine v2 — radius + property class + size band + outlier detection + scoring.

Replaces the old street-name matching with a proper comp methodology:
1. Find candidate parcels (radius when coords available, else same-town)
2. Filter by property class and size band
3. Join to sales history
4. Detect and flag outliers
5. Score each comp by similarity to subject
6. Return ranked results
"""

from db import pools
from fastapi import APIRouter, HTTPException, Query

from routes.real_estate_common import normalize_town

router = APIRouter(prefix="/api/real-estate", tags=["comps-v2"])

# ── Constants ──

DEFAULT_RADIUS_MI = 0.5
MAX_RADIUS_MI = 2.0
SQFT_BAND_PCT = 0.25  # ±25% of subject sqft
BED_BAND = 1  # ±1 bedroom
YEAR_BUILT_BAND = 20  # ±20 years
RECENCY_YEARS = 5  # prefer sales within last N years
OUTLIER_FLOOR_PCT = 0.35  # flag if sale < 35% of median $/sqft
OUTLIER_CEILING_PCT = 5.0  # flag if sale > 500% of median $/sqft (generous for high-variance towns)
MIN_SALE_PRICE = 10000  # ignore sales under $10K (likely transfers)


def _haversine_sql(lat1: str, lng1: str, lat2: str, lng2: str) -> str:
    """SQL expression for haversine distance in miles between two lat/lng pairs."""
    return f"""
    (3959 * acos(
        LEAST(1.0, GREATEST(-1.0,
            cos(radians({lat1})) * cos(radians({lat2})) *
            cos(radians({lng2}) - radians({lng1})) +
            sin(radians({lat1})) * sin(radians({lat2}))
        ))
    ))
    """


def _property_class(use_code: str | None, use_desc: str | None, unit_count: int | None) -> str:
    """Classify a property into a comp class."""
    units = unit_count or 1
    desc = (use_desc or "").lower()
    code = use_code or ""

    if units >= 5:
        return "multifamily_5plus"
    if units >= 2 or "two family" in desc or "three family" in desc or "four family" in desc:
        return "small_multi_2_4"
    if "condo" in desc:
        return "condo"
    if "commercial" in desc or "mixed" in desc:
        return "commercial"
    if "single" in desc or code.startswith("10") or code.startswith("20"):
        return "single_family"
    # Default to single family for residential
    if "res" in desc:
        return "single_family"
    return "other"


def _infer_subject_class(property_type: str | None) -> str | None:
    """Infer comp class from foreclosure property_type field."""
    if not property_type:
        return None
    p = property_type.lower()
    if "single" in p or "residential" in p:
        return "single_family"
    if "multi" in p or "apartment" in p:
        return "small_multi_2_4"
    if "condo" in p:
        return "condo"
    if "commercial" in p or "mixed" in p:
        return "commercial"
    return "single_family"  # default for residential


@router.get("/comps")
async def foreclosure_comps(
    foreclosure_id: int,
    radius_mi: float = Query(DEFAULT_RADIUS_MI, ge=0.1, le=MAX_RADIUS_MI),
    sqft_band: float = Query(SQFT_BAND_PCT, ge=0.1, le=1.0),
    recency_years: int = Query(RECENCY_YEARS, ge=1, le=30),
    limit: int = Query(500, ge=1, le=5000),
    include_outliers: bool = Query(True),
):
    """
    Find sales comps for a foreclosure listing.

    Strategy:
    - If subject has coords: radius search on parcels with coords + town fallback for rest
    - If no coords: town-wide search filtered by property class + size
    - All results scored by similarity and outliers flagged
    """
    p = pools["real_estate"]

    # ── 1. Get subject property ──
    f = await p.fetchrow(
        """
        SELECT id, town, address, property_type, lat, lng, check_amount, sale_date
        FROM ct_foreclosures WHERE id = $1
        """,
        foreclosure_id,
    )
    if not f:
        raise HTTPException(404, "Foreclosure not found")

    town = normalize_town(f["town"]) or ""
    subject_class = _infer_subject_class(f["property_type"])
    has_coords = f["lat"] is not None and f["lng"] is not None

    # Try to get subject property details from parcels (sqft, beds, year_built)
    subject_details = None
    if has_coords:
        subject_details = await p.fetchrow(
            f"""
            SELECT
                pid,
                living_area_sqft,
                total_bedrooms,
                total_bathrooms,
                year_built,
                unit_count,
                use_code,
                use_desc
            FROM ct_vision_parcels
            WHERE town = $1 AND lat IS NOT NULL
            ORDER BY {_haversine_sql('$2', '$3', 'lat', 'lng')}
            LIMIT 1
            """,
            town, f["lat"], f["lng"],
        )
        # Only use if very close (within 0.02 miles ~ 100ft)
        if subject_details:
            dist_check = await p.fetchval(
                f"""
                SELECT {_haversine_sql('$1', '$2', 'lat', 'lng')}
                FROM ct_vision_parcels WHERE town = $3 AND pid = $4
                """,
                f["lat"], f["lng"], town, subject_details["pid"],
            )
            if dist_check and dist_check > 0.02:
                subject_details = None

    if not subject_details:
        # Try address match — normalize punctuation and common abbreviations
        import re
        addr_clean = (f["address"] or "").split(",")[0].strip().upper()
        addr_clean = re.sub(r'[^A-Z0-9 ]', '', addr_clean).strip()
        if addr_clean:
            subject_details = await p.fetchrow(
                """
                SELECT
                    pid,
                    living_area_sqft,
                    total_bedrooms,
                    total_bathrooms,
                    year_built,
                    unit_count,
                    use_code,
                    use_desc
                FROM ct_vision_parcels
                WHERE town = $1
                  AND REGEXP_REPLACE(UPPER(address), '[^A-Z0-9 ]', '', 'g') = $2
                LIMIT 1
                """,
                town, addr_clean,
            )

    subject_sqft = subject_details["living_area_sqft"] if subject_details else None
    subject_beds = subject_details["total_bedrooms"] if subject_details else None
    subject_year = subject_details["year_built"] if subject_details else None

    # Refine class from actual parcel data if available
    if subject_details:
        subject_class = _property_class(
            subject_details["use_code"], subject_details["use_desc"], subject_details["unit_count"]
        )

    # ── 2. Build property class filter SQL ──
    class_filter = ""
    if subject_class == "single_family":
        class_filter = """
        AND COALESCE(vp.unit_count, 1) <= 1
        AND (vp.use_desc ILIKE '%single%' OR vp.use_desc ILIKE '%res%'
             OR vp.use_code LIKE '10%' OR vp.use_code LIKE '20%')
        AND vp.use_desc NOT ILIKE '%condo%'
        AND vp.use_desc NOT ILIKE '%multi%'
        AND vp.use_desc NOT ILIKE '%two fam%'
        AND vp.use_desc NOT ILIKE '%three fam%'
        AND vp.use_desc NOT ILIKE '%four fam%'
        """
    elif subject_class == "small_multi_2_4":
        class_filter = """
        AND (COALESCE(vp.unit_count, 1) BETWEEN 2 AND 4
             OR vp.use_desc ILIKE '%two fam%'
             OR vp.use_desc ILIKE '%three fam%'
             OR vp.use_desc ILIKE '%four fam%')
        """
    elif subject_class == "multifamily_5plus":
        class_filter = "AND COALESCE(vp.unit_count, 1) >= 5"
    elif subject_class == "condo":
        class_filter = "AND vp.use_desc ILIKE '%condo%'"
    elif subject_class == "commercial":
        class_filter = "AND (vp.use_desc ILIKE '%commercial%' OR vp.use_desc ILIKE '%mixed%')"

    # ── 3. Build size band + bedroom filter ──
    sqft_filter = ""
    if subject_sqft and subject_sqft > 0:
        min_sqft = int(subject_sqft * (1 - sqft_band))
        max_sqft = int(subject_sqft * (1 + sqft_band))
        sqft_filter = f"AND vp.living_area_sqft BETWEEN {min_sqft} AND {max_sqft}"

    bed_filter = ""
    if subject_beds and subject_beds > 0:
        bed_filter = f"AND vp.total_bedrooms BETWEEN {subject_beds - BED_BAND} AND {subject_beds + BED_BAND}"

    # ── 4. Find comp candidates + sales ──
    # Hybrid: radius for parcels with coords, town-wide for the rest
    distance_col = "'no_coords'"
    if has_coords:
        distance_col = f"""
        CASE WHEN vp.lat IS NOT NULL THEN
            {_haversine_sql(str(f['lat']), str(f['lng']), 'vp.lat', 'vp.lng')}
        ELSE NULL END
        """

    query = f"""
    WITH comp_sales AS (
        SELECT
            vp.pid,
            vp.town,
            vp.address AS parcel_address,
            vp.use_code,
            vp.use_desc,
            vp.living_area_sqft,
            vp.total_bedrooms,
            vp.total_bathrooms,
            vp.year_built,
            vp.unit_count,
            vp.lat AS parcel_lat,
            vp.lng AS parcel_lng,
            vs.sale_price,
            vs.sale_date,
            vs.owner,
            vs.book_page,
            vs.instrument,
            vs.living_area_sqft AS sale_sqft,
            {distance_col} AS distance_mi
        FROM ct_vision_parcels vp
        JOIN ct_vision_sales vs ON vs.town = vp.town AND vs.pid = vp.pid
        WHERE vp.town = $1
          AND vs.sale_price >= {MIN_SALE_PRICE}
          AND vs.sale_date >= (CURRENT_DATE - INTERVAL '{recency_years} years')
          {class_filter}
          {sqft_filter}
          {bed_filter}
    )
    SELECT *,
        CASE WHEN living_area_sqft > 0 THEN
            ROUND((sale_price / living_area_sqft)::numeric, 2)
        ELSE NULL END AS price_per_sqft
    FROM comp_sales
    ORDER BY sale_date DESC
    """

    rows = await p.fetch(query, town)

    # ── 5. Filter by radius if coords available ──
    results = []
    for r in rows:
        d = dict(r)
        if has_coords and d["distance_mi"] is not None:
            if float(d["distance_mi"]) > radius_mi:
                continue
            d["distance_mi"] = round(float(d["distance_mi"]), 3)
        else:
            d["distance_mi"] = None
        results.append(d)

    # ── 6. Outlier detection ──
    # Calculate median $/sqft
    ppsf_values = [float(r["price_per_sqft"]) for r in results if r["price_per_sqft"] and r["price_per_sqft"] > 0]
    median_ppsf = None
    if ppsf_values:
        sorted_ppsf = sorted(ppsf_values)
        mid = len(sorted_ppsf) // 2
        if len(sorted_ppsf) % 2:
            median_ppsf = float(sorted_ppsf[mid])
        else:
            median_ppsf = float((sorted_ppsf[mid - 1] + sorted_ppsf[mid]) / 2)

    for r in results:
        r["is_outlier"] = False
        r["outlier_reason"] = None

        ppsf = r["price_per_sqft"]
        if ppsf and median_ppsf and median_ppsf > 0:
            ratio = float(ppsf) / median_ppsf
            if ratio < OUTLIER_FLOOR_PCT:
                r["is_outlier"] = True
                r["outlier_reason"] = (
                    f"Price/sqft ${ppsf} is {ratio:.0%} of "
                    f"median ${median_ppsf:.0f}/sqft; likely non-arm's-length"
                )
            elif ratio > OUTLIER_CEILING_PCT:
                r["is_outlier"] = True
                r["outlier_reason"] = f"Price/sqft ${ppsf} is {ratio:.1f}x median — extreme outlier"

        # Same-PID same-date anomaly
        if r["sale_date"]:
            same_pid_same_date = [
                x for x in results
                if x["pid"] == r["pid"] and x["sale_date"] == r["sale_date"] and x["sale_price"] != r["sale_price"]
            ]
            if same_pid_same_date:
                other_price = same_pid_same_date[0]["sale_price"]
                if float(r["sale_price"]) < float(other_price) * 0.3:
                    r["is_outlier"] = True
                    r["outlier_reason"] = (
                        f"Same property sold for ${float(other_price):,.0f} "
                        "on the same date; likely a partial interest or correction"
                    )

    # ── 7. Similarity scoring ──
    for r in results:
        score = 100.0

        # Distance penalty (if available): -10 per 0.1 mile
        if r["distance_mi"] is not None:
            score -= float(r["distance_mi"]) * 100  # -10 per 0.1mi

        # Sqft similarity: -1 per 1% difference
        if subject_sqft and r["living_area_sqft"] and subject_sqft > 0:
            sqft_diff_pct = abs(r["living_area_sqft"] - subject_sqft) / subject_sqft
            score -= sqft_diff_pct * 100

        # Bedroom match: -10 per bedroom difference
        if subject_beds and r["total_bedrooms"]:
            score -= abs(r["total_bedrooms"] - subject_beds) * 10

        # Year built: -2 per decade difference
        if subject_year and r["year_built"]:
            score -= abs(r["year_built"] - subject_year) / 5

        # Recency bonus: -5 per year old
        if r["sale_date"]:
            from datetime import date
            days_old = (date.today() - r["sale_date"]).days
            years_old = days_old / 365.25
            score -= years_old * 5

        # Outlier penalty
        if r["is_outlier"]:
            score -= 50

        r["comp_score"] = round(max(0, score), 1)

    # Sort by score (best first), outliers last
    results.sort(key=lambda r: (-1 if r["is_outlier"] else 0, -r["comp_score"]))

    if not include_outliers:
        results = [r for r in results if not r["is_outlier"]]

    results = results[:limit]

    # ── 8. Summary stats (excluding outliers) ──
    clean = [r for r in results if not r["is_outlier"] and r["price_per_sqft"] and r["price_per_sqft"] > 0]
    clean_prices = [float(r["sale_price"]) for r in clean if r["sale_price"]]
    clean_ppsf = [float(r["price_per_sqft"]) for r in clean if r["price_per_sqft"]]

    summary = {
        "total_comps": len(results),
        "clean_comps": len(clean),
        "outliers": sum(1 for r in results if r["is_outlier"]),
        "median_ppsf": round(median_ppsf, 2) if median_ppsf else None,
        "min_price": min(clean_prices) if clean_prices else None,
        "max_price": max(clean_prices) if clean_prices else None,
        "median_price": round(sorted(clean_prices)[len(clean_prices) // 2], 2) if clean_prices else None,
        "avg_ppsf": round(sum(clean_ppsf) / len(clean_ppsf), 2) if clean_ppsf else None,
        "min_ppsf": round(min(clean_ppsf), 2) if clean_ppsf else None,
        "max_ppsf": round(max(clean_ppsf), 2) if clean_ppsf else None,
    }

    # Subject property info
    subject = {
        "id": f["id"],
        "town": f["town"],
        "address": f["address"],
        "property_type": f["property_type"],
        "check_amount": f["check_amount"],
        "sale_date": f["sale_date"],
        "lat": f["lat"],
        "lng": f["lng"],
        "inferred_class": subject_class,
        "sqft": subject_sqft,
        "bedrooms": subject_beds,
        "year_built": subject_year,
        "has_coords": has_coords,
    }

    return {
        "subject": subject,
        "summary": summary,
        "config": {
            "radius_mi": radius_mi if has_coords else None,
            "sqft_band_pct": sqft_band,
            "recency_years": recency_years,
            "min_sale_price": MIN_SALE_PRICE,
            "outlier_floor_pct": OUTLIER_FLOOR_PCT,
            "outlier_ceiling_pct": OUTLIER_CEILING_PCT,
        },
        "comps": [
            {
                "pid": r["pid"],
                "address": r["parcel_address"],
                "town": r["town"],
                "use_desc": r["use_desc"],
                "sqft": r["living_area_sqft"],
                "bedrooms": r["total_bedrooms"],
                "bathrooms": r["total_bathrooms"],
                "year_built": r["year_built"],
                "units": r["unit_count"],
                "sale_price": float(r["sale_price"]) if r["sale_price"] else None,
                "sale_date": str(r["sale_date"]) if r["sale_date"] else None,
                "price_per_sqft": float(r["price_per_sqft"]) if r["price_per_sqft"] else None,
                "owner": r["owner"],
                "book_page": r["book_page"],
                "distance_mi": r["distance_mi"],
                "comp_score": r["comp_score"],
                "is_outlier": r["is_outlier"],
                "outlier_reason": r["outlier_reason"],
            }
            for r in results
        ],
    }
