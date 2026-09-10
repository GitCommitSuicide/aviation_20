"""
database/repositories/route_repository.py
==========================================
Data-access functions for the `route_searches` table.

A route search record logs that we called the SearchAPI for a given
origin→destination pair on a specific travel date. The actual flight rows
are stored in the `flights` table; this table lets us check whether we
already have a fresh API result for a route so we don't call the API again.
"""

import logging
import datetime
from typing import Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def create_route_search(conn: psycopg.Connection, data: dict) -> Optional[int]:
    """
    Insert a new route search record.

    `data` keys:
        origin_airport_id       int     required
        destination_airport_id  int     required
        search_date             str     "YYYY-MM-DD"
        travel_date             str     "YYYY-MM-DD"
        passengers              int
        cabin_class             str     e.g. "economy"
        trip_type               str     e.g. "one_way"
        currency                str     e.g. "INR"
        fetch_at                datetime (timezone-aware)

    Returns search_id or None on error.
    """
    origin_id = data.get("origin_airport_id")
    dest_id   = data.get("destination_airport_id")
    if not origin_id or not dest_id:
        logger.warning("create_route_search: missing airport IDs, skipping.")
        return None

    fetch_at = data.get("fetch_at") or datetime.datetime.now(tz=datetime.timezone.utc)

    def parse_date(val):
        if not val:
            return None
        if isinstance(val, datetime.date):
            return val
        try:
            return datetime.date.fromisoformat(val)
        except ValueError:
            return None

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO route_searches (
                    origin_airport_id, destination_airport_id,
                    search_date, travel_date,
                    passengers, cabin_class, trip_type, currency,
                    fetch_at, created_at
                )
                VALUES (
                    %(origin_id)s, %(dest_id)s,
                    %(search_date)s, %(travel_date)s,
                    %(passengers)s, %(cabin_class)s, %(trip_type)s, %(currency)s,
                    %(fetch_at)s, NOW()
                )
                RETURNING search_id
                """,
                {
                    "origin_id":   origin_id,
                    "dest_id":     dest_id,
                    "search_date": parse_date(data.get("search_date")),
                    "travel_date": parse_date(data.get("travel_date")),
                    "passengers":  data.get("passengers"),
                    "cabin_class": data.get("cabin_class"),
                    "trip_type":   data.get("trip_type"),
                    "currency":    data.get("currency"),
                    "fetch_at":    fetch_at,
                },
            )
            row = cur.fetchone()
            search_id = row["search_id"] if row else None
            logger.debug(
                "create_route_search: id=%s origin_id=%s dest_id=%s",
                search_id, origin_id, dest_id,
            )
            return search_id
    except psycopg.Error as exc:
        conn.rollback()
        logger.error("create_route_search error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_latest_route_search(
    conn: psycopg.Connection,
    origin_airport_id: int,
    destination_airport_id: int,
    travel_date: Optional[str] = None,
    currency: Optional[str] = None,
) -> Optional[dict]:
    """
    Return the most recent route search record for a given origin→destination,
    optionally filtered by travel_date and currency.
    Returns None if no record exists.
    """
    def parse_date(val):
        if not val:
            return None
        if isinstance(val, datetime.date):
            return val
        try:
            return datetime.date.fromisoformat(val)
        except ValueError:
            return None

    td = parse_date(travel_date)
    cur_upper = (currency or "").strip().upper() or None

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT *
            FROM route_searches
            WHERE origin_airport_id      = %(origin_id)s
              AND destination_airport_id = %(dest_id)s
              AND (%(travel_date)s::date    IS NULL OR travel_date = %(travel_date)s::date)
              AND (%(currency)s::varchar(3) IS NULL OR currency    = %(currency)s::varchar(3))
            ORDER BY fetch_at DESC
            LIMIT 1
            """,
            {
                "origin_id":   origin_airport_id,
                "dest_id":     destination_airport_id,
                "travel_date": td,
                "currency":    cur_upper,
            },
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Itinerary write — delete-and-replace for price freshness
# ---------------------------------------------------------------------------

def save_itineraries_to_db(
    conn: psycopg.Connection,
    dep_airport_id: int,
    arr_airport_id: int,
    travel_date,
    search_id: Optional[int],
    itineraries_raw: list[dict],
    currency: str = "INR",
    fetch_at=None,
) -> int:
    """
    Delete any existing cached itineraries for origin→destination+date, then
    insert the fresh set from the API along with their ordered legs.

    Each element of `itineraries_raw` is one Google Flights itinerary dict:
      {
        "price": 4500,
        "total_duration": 185,        # minutes
        "booking_token": "...",
        "flights": [                  # ordered list of legs
          {
            "flight_number": "6E 214",
            "airline": "IndiGo",
            "airplane": "Airbus A320",
            "duration": 110,
            "departure_airport": {"id": "BOM", "name": "...", "date": "2026-09-02", "time": "06:00"},
            "arrival_airport":   {"id": "DEL", "name": "...", "date": "2026-09-02", "time": "07:50"}
          }, ...
        ]
      }

    Returns the number of itineraries saved.
    """
    # Lazy import to avoid a circular import with chatbot.py
    from shared.db.repositories.flight_repository import upsert_flight
    from shared.db.repositories.airport_repository import upsert_airport, get_airport_by_iata

    now_utc = fetch_at or datetime.datetime.now(tz=datetime.timezone.utc)
    saved = 0

    def _parse_dt(date_str: str, time_str: str) -> Optional[datetime.datetime]:
        """Build a naive UTC datetime from SearchAPI date+time strings."""
        try:
            return datetime.datetime.strptime(
                f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
            )
        except Exception:
            return None

    try:
        with conn.cursor() as cur:
            # ── 1. Wipe stale itineraries for this route+date ─────────────────
            cur.execute(
                """
                DELETE FROM itineraries
                WHERE origin_airport_id      = %s
                  AND destination_airport_id = %s
                  AND travel_date            = %s
                """,
                (dep_airport_id, arr_airport_id, travel_date),
            )
            logger.debug(
                "save_itineraries_to_db: deleted stale itineraries for %s→%s %s",
                dep_airport_id, arr_airport_id, travel_date,
            )

            # ── 2. Insert fresh itineraries ───────────────────────────────────
            for raw_itin in itineraries_raw:
                legs_raw = raw_itin.get("flights", [])
                if not legs_raw:
                    continue

                # Upsert each leg's flight row and collect (flight_id, raw_leg)
                leg_flight_ids: list[tuple[int, dict]] = []
                for seg in legs_raw:
                    dep_ap = seg.get("departure_airport", {})
                    arr_ap = seg.get("arrival_airport", {})
                    seg_dep_iata = dep_ap.get("id", "")
                    seg_arr_iata = arr_ap.get("id", "")
                    seg_date = dep_ap.get("date", str(travel_date))

                    # Ensure minimal airport rows exist
                    for ap_iata, ap_name in [(seg_dep_iata, dep_ap.get("name", seg_dep_iata)),
                                             (seg_arr_iata, arr_ap.get("name", seg_arr_iata))]:
                        if ap_iata and not get_airport_by_iata(conn, ap_iata):
                            upsert_airport(conn, {
                                "iata_code": ap_iata,
                                "name":      ap_name or ap_iata,
                                "fetch_at":  now_utc,
                            })

                    flight_data = {
                        "flight_number": (seg.get("flight_number") or "").replace(" ", "").upper(),
                        "query_date":    seg_date,
                        "status":        None,
                        "fetch_at":      now_utc,
                        "departure_iata": seg_dep_iata,
                        "departure_name": dep_ap.get("name") or seg_dep_iata,
                        "departure_scheduled": f"{dep_ap.get('date', seg_date)} {dep_ap.get('time', '00:00')}",
                        "arrival_iata":   seg_arr_iata,
                        "arrival_name":   arr_ap.get("name") or seg_arr_iata,
                        "arrival_scheduled": f"{arr_ap.get('date', seg_date)} {arr_ap.get('time', '00:00')}",
                        "airline_name":  seg.get("airline"),
                        "aircraft_model": seg.get("airplane"),
                    }
                    if flight_data["flight_number"]:
                        fid = upsert_flight(conn, flight_data)
                        if fid:
                            leg_flight_ids.append((fid, seg))

                if not leg_flight_ids:
                    continue

                stop_count = max(0, len(leg_flight_ids) - 1)

                # Insert the itinerary header
                cur.execute(
                    """
                    INSERT INTO itineraries (
                        search_id,
                        origin_airport_id, destination_airport_id,
                        travel_date,
                        price, currency,
                        total_duration_minutes, stop_count,
                        booking_token, fetch_at, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING itinerary_id
                    """,
                    (
                        search_id,
                        dep_airport_id, arr_airport_id,
                        travel_date,
                        raw_itin.get("price"),
                        currency,
                        raw_itin.get("total_duration"),
                        stop_count,
                        raw_itin.get("booking_token"),
                        now_utc,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    continue
                itinerary_id = row[0]

                # Insert ordered legs with layover calculation
                for order, (flight_id, seg) in enumerate(leg_flight_ids, start=1):
                    layover_minutes = None
                    layover_airport_id = None

                    # Calculate layover between this leg's arrival and the next leg's departure
                    if order < len(leg_flight_ids):
                        this_arr_ap = seg.get("arrival_airport", {})
                        next_seg    = leg_flight_ids[order][1]   # order is 1-based; index is order
                        next_dep_ap = next_seg.get("departure_airport", {})

                        this_arr_dt = _parse_dt(
                            this_arr_ap.get("date", ""), this_arr_ap.get("time", "")
                        )
                        next_dep_dt = _parse_dt(
                            next_dep_ap.get("date", ""), next_dep_ap.get("time", "")
                        )
                        if this_arr_dt and next_dep_dt and next_dep_dt > this_arr_dt:
                            layover_minutes = int(
                                (next_dep_dt - this_arr_dt).total_seconds() / 60
                            )

                        # Layover airport is this leg's arrival airport
                        layover_iata = this_arr_ap.get("id", "")
                        if layover_iata:
                            ap_row = get_airport_by_iata(conn, layover_iata)
                            layover_airport_id = ap_row["airport_id"] if ap_row else None

                    cur.execute(
                        """
                        INSERT INTO itinerary_legs
                            (itinerary_id, flight_id, leg_order, layover_minutes, layover_airport_id)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (itinerary_id, flight_id, order, layover_minutes, layover_airport_id),
                    )

                saved += 1
                logger.debug("save_itineraries_to_db: saved itinerary_id=%s stops=%s", itinerary_id, stop_count)

        logger.info("save_itineraries_to_db: %s itineraries saved for %s→%s %s", saved, dep_airport_id, arr_airport_id, travel_date)
        return saved

    except psycopg.Error as exc:
        logger.error("save_itineraries_to_db error: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Itinerary read — reconstruct full multi-leg itineraries from cache
# ---------------------------------------------------------------------------

def get_cached_itineraries(
    conn: psycopg.Connection,
    dep_iata: str,
    arr_iata: str,
    travel_date,
) -> list[dict]:
    """
    Return a list of cached itineraries for dep_iata→arr_iata on travel_date.
    Each item in the list is a dict with keys:
        itinerary_id, price, currency, total_duration_minutes, stop_count,
        fetch_at, legs: [list of leg dicts]

    Each leg dict has:
        leg_order, flight_number, airline_name, aircraft_model,
        dep_iata, dep_airport_name, dep_city,
        arr_iata, arr_airport_name, arr_city,
        departure_scheduled, arrival_scheduled,
        departure_terminal, departure_gate,
        arrival_terminal, arrival_gate,
        layover_minutes, layover_iata

    Returns [] if no cached itineraries exist.
    """
    def parse_date(val):
        if not val:
            return None
        if isinstance(val, datetime.date):
            return val
        try:
            return datetime.date.fromisoformat(str(val))
        except ValueError:
            return None

    td = parse_date(travel_date)

    with conn.cursor(row_factory=dict_row) as cur:
        # Fetch itinerary headers
        cur.execute(
            """
            SELECT i.itinerary_id, i.price, i.currency,
                   i.total_duration_minutes, i.stop_count, i.fetch_at
            FROM itineraries i
            JOIN airports oa ON i.origin_airport_id      = oa.airport_id
            JOIN airports da ON i.destination_airport_id = da.airport_id
            WHERE oa.iata_code = %s
              AND da.iata_code = %s
              AND i.travel_date = %s
            ORDER BY i.price NULLS LAST, i.total_duration_minutes NULLS LAST
            """,
            (dep_iata, arr_iata, td),
        )
        itineraries = cur.fetchall()

        # For each itinerary, fetch its ordered legs
        for itin in itineraries:
            cur.execute(
                """
                SELECT
                    il.leg_order,
                    il.layover_minutes,
                    la.iata_code        AS layover_iata,

                    f.flight_number,
                    f.departure_scheduled,
                    f.arrival_scheduled,
                    f.departure_terminal,
                    f.departure_gate,
                    f.arrival_terminal,
                    f.arrival_gate,
                    f.status,

                    dep_ap.iata_code    AS dep_iata,
                    dep_ap.name         AS dep_airport_name,
                    dep_ap.city         AS dep_city,

                    arr_ap.iata_code    AS arr_iata,
                    arr_ap.name         AS arr_airport_name,
                    arr_ap.city         AS arr_city,

                    al.name             AS airline_name,
                    ac.model            AS aircraft_model

                FROM itinerary_legs il
                JOIN flights  f      ON il.flight_id            = f.flight_id
                JOIN airports dep_ap ON f.departure_airport_id  = dep_ap.airport_id
                JOIN airports arr_ap ON f.arrival_airport_id    = arr_ap.airport_id
                LEFT JOIN airlines al ON f.airline_id           = al.airline_id
                LEFT JOIN aircraft ac ON f.aircraft_id          = ac.aircraft_id
                LEFT JOIN airports la ON il.layover_airport_id  = la.airport_id
                WHERE il.itinerary_id = %s
                ORDER BY il.leg_order
                """,
                (itin["itinerary_id"],),
            )
            itin["legs"] = cur.fetchall()

    return list(itineraries)
