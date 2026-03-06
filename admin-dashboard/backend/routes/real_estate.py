from db import pools
from fastapi import APIRouter, HTTPException, Query

from routes.real_estate_common import normalize_town

router = APIRouter(prefix="/api/real-estate", tags=["real-estate"])


def _class_from_property_type(pt: str | None) -> str | None:
    if not pt:
        return None
    p = pt.lower()
    if "single" in p:
        return "single_family"
    if "multi" in p or "apartment" in p:
        return "multifamily"
    if "commercial" in p or "mixed" in p:
        return "mixed_use"
    if "residential" in p:
        return "single_family"
    return None


@router.get("/foreclosures")
async def list_foreclosures(limit: int = Query(500, ge=1, le=2000)):
    p = pools["real_estate"]
    rows = await p.fetch(
        """
        SELECT f.id, f.posting_id, f.town, f.address, f.sale_date,
               f.sale_type, f.property_type, f.check_amount,
               f.lat, f.lng, f.photo_url, f.status,
               EXISTS(
                 SELECT 1 FROM foreclosure_comp_rules r
                 WHERE r.foreclosure_id = f.id AND r.active
               ) AS has_rules
        FROM ct_foreclosures f
        WHERE f.address IS NOT NULL
          AND f.sale_date::date >= CURRENT_DATE
          AND COALESCE(f.status, '') != 'Cancelled'
        ORDER BY f.sale_date ASC, f.id
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


@router.get("/comp-rules")
async def comp_rules(foreclosure_id: int):
    p = pools["real_estate"]
    rows = await p.fetch(
        """
        SELECT id, foreclosure_id, rule_name, town, street_pattern,
               comp_class, min_sqft, max_sqft, active
        FROM foreclosure_comp_rules
        WHERE foreclosure_id = $1
        ORDER BY id
        """,
        foreclosure_id,
    )
    return [dict(r) for r in rows]


@router.get("/towns")
async def list_towns():
    """Return all towns that have geocoded parcels."""
    p = pools["real_estate"]
    rows = await p.fetch(
        """
        SELECT town, COUNT(*) as parcel_count
        FROM ct_vision_parcels
        WHERE lat IS NOT NULL AND lng IS NOT NULL
        GROUP BY town
        ORDER BY town
        """
    )
    return [{"town": r["town"], "parcel_count": r["parcel_count"]} for r in rows]


@router.get("/multifamily-points")
async def multifamily_points(
    town: str = Query(
        None, description="Filter by town (e.g. BridgeportCT). Required."
    ),
    bucket: str = Query("all"),
    sold_era: str = Query("all", description="Filter by last sale era"),
    limit: int = Query(20000, ge=1, le=100000),
):
    p = pools["real_estate"]
    town_normalized = normalize_town(town) if town and town != "all" else None

    # unit_count_expr: use actual count, fallback to use_code inference
    uc = (
        "COALESCE(p.unit_count, p.occupancy,"
        " CASE p.use_code"
        "   WHEN '102' THEN 2 WHEN '103' THEN 3 WHEN '104' THEN 4"
        " END)"
    )
    bucket_sql = f" AND {uc} >= 2 "
    if bucket == "2_fam":
        bucket_sql = f" AND {uc} = 2 "
    elif bucket == "3_fam":
        bucket_sql = f" AND {uc} = 3 "
    elif bucket == "4_fam":
        bucket_sql = f" AND {uc} = 4 "
    elif bucket == "5_10":
        bucket_sql = f" AND {uc} BETWEEN 5 AND 10 "
    elif bucket == "11_25":
        bucket_sql = f" AND {uc} BETWEEN 11 AND 25 "
    elif bucket == "25_plus":
        bucket_sql = f" AND {uc} > 25 "

    # Build a safe year expression: sales table → parcel last_sale_date → year_built
    sale_year_expr = (
        "COALESCE("
        "  EXTRACT(YEAR FROM s.sale_date)::int,"
        "  NULLIF(REGEXP_REPLACE("
        "    NULLIF(p.last_sale_date, ''), '[^0-9]', '', 'g'"
        "  ), '')::int,"
        "  p.year_built"
        ")"
    )

    era_sql = ""
    if sold_era == "pre2000":
        era_sql = f" AND {sale_year_expr} < 2000 "
    elif sold_era == "2000s":
        era_sql = f" AND {sale_year_expr} BETWEEN 2000 AND 2009 "
    elif sold_era == "2010s":
        era_sql = f" AND {sale_year_expr} BETWEEN 2010 AND 2019 "
    elif sold_era == "2020s":
        era_sql = f" AND {sale_year_expr} >= 2020 "

    rows = await p.fetch(
        f"""
        SELECT p.town, p.pid, p.address, p.use_desc,
               COALESCE(p.unit_count, p.occupancy,
                   CASE p.use_code
                     WHEN '102' THEN 2 WHEN '103' THEN 3
                     WHEN '104' THEN 4 WHEN '105' THEN 5
                     WHEN '106' THEN 6 WHEN '107' THEN 7
                     WHEN '108' THEN 8 WHEN '109' THEN 9
                     WHEN '110' THEN 10
                   END) AS unit_count,
               COALESCE(p.last_sale_price, s.sale_price)
                   AS last_sale_price,
               COALESCE(
                   NULLIF(p.last_sale_date, ''),
                   s.sale_date::text
               ) AS last_sale_date,
               p.living_area_sqft, p.year_built,
               p.lat, p.lng
        FROM ct_vision_parcels p
        LEFT JOIN LATERAL (
          SELECT sale_price, sale_date FROM ct_vision_sales
          WHERE town = p.town AND pid = p.pid
          ORDER BY sale_date DESC LIMIT 1
        ) s ON true
        WHERE p.lat IS NOT NULL AND p.lng IS NOT NULL
          {" AND p.town = $1 " if town_normalized else ""}
          AND (
            p.use_code IN (
              '102','103','104','105','106','107','108',
              '109','110','111','112','113',
              '208','800','800C','800R','801','802','805',
              '814','861','862',
              '946','947','948',
              '1040','1110','1111','1120','1250'
            )
            OR p.use_code LIKE '108C'
            OR p.use_code LIKE '111C'
            OR p.use_code LIKE '111J'
            OR p.use_code LIKE '112C'
            OR p.use_code LIKE '112R'
            OR p.use_desc ILIKE '%apartment%'
            OR p.use_desc ILIKE '%comm apt%'
            OR (p.use_desc ILIKE '%family%'
                AND p.use_desc NOT ILIKE '%single%')
          )
          {bucket_sql}
          {era_sql}
        LIMIT ${2 if town_normalized else 1}
        """,
        *([town_normalized, limit] if town_normalized else [limit]),
    )
    return [dict(r) for r in rows]


@router.get("/comps-legacy")
async def foreclosure_comps_legacy(foreclosure_id: int, limit: int = Query(2000, ge=1, le=10000)):
    p = pools["real_estate"]
    f = await p.fetchrow(
        "SELECT id, town, address, property_type FROM ct_foreclosures WHERE id = $1",
        foreclosure_id,
    )
    if not f:
        raise HTTPException(404, "Foreclosure not found")

    town = normalize_town(f["town"]) or ""
    prop_class = _class_from_property_type(f["property_type"])

    # Use explicit rules if present; otherwise fallback to same-street heuristic.
    rules = await p.fetch(
        """
        SELECT rule_name, town, street_pattern, comp_class, min_sqft, max_sqft
        FROM foreclosure_comp_rules
        WHERE foreclosure_id = $1 AND active
        ORDER BY id
        """,
        foreclosure_id,
    )

    if rules:
        rows = await p.fetch(
            """
            WITH r AS (
              SELECT rule_name, town, street_pattern, comp_class, min_sqft, max_sqft
              FROM foreclosure_comp_rules
              WHERE foreclosure_id = $1 AND active
            ),
            matched_parcels AS (
              SELECT DISTINCT r.rule_name, vp.town, vp.pid, vp.address, vp.use_code, vp.use_desc,
                     COALESCE(vs.living_area_sqft, vp.living_area_sqft) AS living_area_sqft
              FROM r
              JOIN ct_vision_parcels vp
                ON vp.town = r.town
               AND vp.address ILIKE r.street_pattern
              LEFT JOIN ct_vision_sales vs ON vs.town = vp.town AND vs.pid = vp.pid
              WHERE (r.min_sqft IS NULL OR vp.living_area_sqft >= r.min_sqft)
                AND (r.max_sqft IS NULL OR vp.living_area_sqft <= r.max_sqft)
                AND (
                  r.comp_class IS NULL OR
                  (
                    r.comp_class = 'single_family'
                    AND COALESCE(vp.unit_count, 1) <= 1
                    AND (
                      vp.use_desc ILIKE '%single%'
                      OR vp.use_code LIKE '20%'
                      OR vp.use_code LIKE '10%'
                    )
                  ) OR
                  (r.comp_class = 'small_multifamily' AND COALESCE(vp.unit_count, 1) BETWEEN 2 AND 4) OR
                  (r.comp_class = 'multifamily' AND COALESCE(vp.unit_count, 1) >= 5) OR
                  (r.comp_class = 'mixed_use' AND (vp.use_desc ILIKE '%mixed%' OR vp.use_desc ILIKE '%apt%'))
                )
            )
            SELECT mp.rule_name, mp.address, mp.use_desc, mp.living_area_sqft,
                   vs.sale_price, vs.sale_date, vs.owner, vs.book_page, vs.instrument,
                   mp.town, mp.pid
            FROM matched_parcels mp
            JOIN ct_vision_sales vs
              ON vs.town = mp.town AND vs.pid = mp.pid
            ORDER BY vs.sale_date DESC, vs.sale_price DESC
            LIMIT $2
            """,
            foreclosure_id,
            limit,
        )
    else:
        # Fallback: comps from same street + same inferred class.
        rows = await p.fetch(
            """
            WITH f AS (
              SELECT id, $2::text AS town,
                     UPPER(REGEXP_REPLACE(address, ',.*$', '')) AS raw_addr,
                     SPLIT_PART(UPPER(REGEXP_REPLACE(address, ',.*$', '')), ' ', 1) AS num,
                     REGEXP_REPLACE(
                       REGEXP_REPLACE(
                         UPPER(REGEXP_REPLACE(address, ',.*$', '')),
                         '^\\S+\\s+',
                         ''
                       ),
                       '[^A-Z0-9 ]',
                       '',
                       'g'
                     ) AS street_name,
                     $3::text AS prop_class
              FROM ct_foreclosures
              WHERE id = $1
            ),
            matched_parcels AS (
              SELECT DISTINCT vp.town, vp.pid, vp.address, vp.use_code, vp.use_desc,
                     COALESCE(vs.living_area_sqft, vp.living_area_sqft) AS living_area_sqft
              FROM f
              JOIN ct_vision_parcels vp
                ON vp.town = f.town
               AND UPPER(vp.address) ILIKE '%' || f.street_name || '%'
              LEFT JOIN ct_vision_sales vs ON vs.town = vp.town AND vs.pid = vp.pid
              WHERE (
                f.prop_class IS NULL OR
                (
                  f.prop_class = 'single_family'
                  AND COALESCE(vp.unit_count, 1) <= 1
                  AND (
                    vp.use_desc ILIKE '%single%'
                    OR vp.use_code LIKE '20%'
                    OR vp.use_code LIKE '10%'
                  )
                ) OR
                (f.prop_class = 'multifamily' AND COALESCE(vp.unit_count, 1) >= 5) OR
                (f.prop_class = 'mixed_use' AND (vp.use_desc ILIKE '%mixed%' OR vp.use_desc ILIKE '%apt%'))
              )
            )
            SELECT 'Auto (same street)' AS rule_name,
                   mp.address, mp.use_desc, mp.living_area_sqft,
                   vs.sale_price, vs.sale_date, vs.owner, vs.book_page, vs.instrument,
                   mp.town, mp.pid
            FROM matched_parcels mp
            JOIN ct_vision_sales vs
              ON vs.town = mp.town AND vs.pid = mp.pid
            ORDER BY vs.sale_date DESC, vs.sale_price DESC
            LIMIT $4
            """,
            foreclosure_id,
            town,
            prop_class,
            limit,
        )

    return {
        "foreclosure": dict(f),
        "rules_applied": [dict(r) for r in rules],
        "rows": [dict(r) for r in rows],
    }


@router.get("/photo/{foreclosure_id}")
async def foreclosure_photo(foreclosure_id: int):
    """Proxy and cache foreclosure photos from CT court site."""
    import os

    import httpx
    from fastapi.responses import FileResponse, Response

    cache_dir = "/tmp/nhc_photo_cache"
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{foreclosure_id}.jpg")

    # Serve from cache if available
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return FileResponse(cache_path, media_type="image/jpeg")

    # Fetch URL from DB
    p = pools["real_estate"]
    row = await p.fetchrow(
        "SELECT photo_url FROM ct_foreclosures WHERE id = $1",
        foreclosure_id,
    )
    if not row or not row["photo_url"]:
        return Response(status_code=404)

    # Download and cache
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(row["photo_url"])
            if resp.status_code == 200:
                with open(cache_path, "wb") as f:
                    f.write(resp.content)
                return FileResponse(
                    cache_path, media_type="image/jpeg"
                )
    except Exception:
        pass

    return Response(status_code=404)
