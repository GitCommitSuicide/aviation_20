-- =============================================================================
-- schema.sql  –  Aviation Chatbot PostgreSQL Schema
-- =============================================================================
-- Idempotent: safe to run multiple times (CREATE TABLE IF NOT EXISTS).
-- Run via:  python scripts/init_database.py
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;


-- ---------------------------------------------------------------------------
-- 1. AIRPORTS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS airports (
    airport_id      BIGSERIAL       PRIMARY KEY,

    iata_code       VARCHAR(3)      UNIQUE
                                    CHECK (iata_code = UPPER(iata_code)),

    icao_code       VARCHAR(4)      UNIQUE
                                    CHECK (icao_code = UPPER(icao_code)),

    name            TEXT            NOT NULL,
    city            TEXT,
    country         TEXT,
    country_code    VARCHAR(2)      CHECK (LENGTH(country_code) = 2),

    latitude        DOUBLE PRECISION
                                    CHECK (latitude  BETWEEN -90  AND  90),
    longitude       DOUBLE PRECISION
                                    CHECK (longitude BETWEEN -180 AND 180),

    timezone        TEXT,
    airport_type    TEXT,

    -- When this row was last fetched from an API (used for cache freshness)
    fetch_at        TIMESTAMPTZ,

    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_airports_iata     ON airports (iata_code);
CREATE INDEX IF NOT EXISTS idx_airports_icao     ON airports (icao_code);
CREATE INDEX IF NOT EXISTS idx_airports_city     ON airports (LOWER(city));
CREATE INDEX IF NOT EXISTS idx_airports_country  ON airports (LOWER(country));
CREATE INDEX IF NOT EXISTS idx_airports_name     ON airports USING gin (to_tsvector('english', name));


-- ---------------------------------------------------------------------------
-- 2. AIRLINES
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS airlines (
    airline_id      BIGSERIAL       PRIMARY KEY,

    iata_code       VARCHAR(3)      UNIQUE
                                    CHECK (iata_code = UPPER(iata_code)),

    icao_code       VARCHAR(4)      UNIQUE
                                    CHECK (icao_code = UPPER(icao_code)),

    name            TEXT            NOT NULL,
    country         TEXT,
    country_code    VARCHAR(2),

    -- Flexible JSON for onboard facilities (wifi, meals, entertainment, etc.)
    basic_facilities JSONB,

    rating          NUMERIC(3,2)    CHECK (rating BETWEEN 0 AND 10),
    fleet_size      INTEGER         CHECK (fleet_size >= 0),
    website         TEXT,

    fetch_at        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_airlines_iata    ON airlines (iata_code);
CREATE INDEX IF NOT EXISTS idx_airlines_icao    ON airlines (icao_code);
CREATE INDEX IF NOT EXISTS idx_airlines_name    ON airlines USING gin (to_tsvector('english', name));


-- ---------------------------------------------------------------------------
-- 3. AIRCRAFT
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aircraft (
    aircraft_id     BIGSERIAL       PRIMARY KEY,

    -- Registration number is the natural unique key (e.g. VT-ANR)
    registration    VARCHAR(20)     UNIQUE,

    model           TEXT,           -- e.g. "Airbus A320 NEO"
    manufacturer    TEXT,           -- e.g. "Airbus"
    aircraft_type   TEXT,           -- e.g. "narrow-body"
    iata_type_code  VARCHAR(10),    -- e.g. "32N"
    icao_type_code  VARCHAR(10),    -- e.g. "A20N"
    serial_number   TEXT,

    fetch_at        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aircraft_registration ON aircraft (registration);
CREATE INDEX IF NOT EXISTS idx_aircraft_model        ON aircraft (LOWER(model));


-- ---------------------------------------------------------------------------
-- 4. FLIGHTS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flights (
    flight_id               BIGSERIAL       PRIMARY KEY,

    flight_number           VARCHAR(20)     NOT NULL,

    -- The calendar date the flight operates (UTC date)
    query_date              DATE,

    -- Foreign keys to reference tables
    airline_id              BIGINT          REFERENCES airlines(airline_id)  ON DELETE SET NULL,
    aircraft_id             BIGINT          REFERENCES aircraft(aircraft_id) ON DELETE SET NULL,
    departure_airport_id    BIGINT          NOT NULL REFERENCES airports(airport_id),
    arrival_airport_id      BIGINT          NOT NULL REFERENCES airports(airport_id),

    status                  VARCHAR(50),

    -- Times are all stored as timezone-aware instants (UTC preferred)
    departure_scheduled     TIMESTAMPTZ,
    departure_actual        TIMESTAMPTZ,
    departure_estimated     TIMESTAMPTZ,
    departure_terminal      VARCHAR(20),
    departure_gate          VARCHAR(20),

    arrival_scheduled       TIMESTAMPTZ,
    arrival_actual          TIMESTAMPTZ,
    arrival_estimated       TIMESTAMPTZ,
    arrival_terminal        VARCHAR(20),
    arrival_gate            VARCHAR(20),
    arrival_baggage_belt    VARCHAR(20),

    delay_minutes           INTEGER,

    -- When this record was fetched from the API
    fetch_at                TIMESTAMPTZ     NOT NULL,

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Prevent exact duplicates for the same flight on the same route+date
    CONSTRAINT uq_flight_route_date
        UNIQUE (flight_number, query_date, departure_airport_id, arrival_airport_id)
);

CREATE INDEX IF NOT EXISTS idx_flights_number       ON flights (flight_number);
CREATE INDEX IF NOT EXISTS idx_flights_query_date   ON flights (query_date);
CREATE INDEX IF NOT EXISTS idx_flights_airline      ON flights (airline_id);
CREATE INDEX IF NOT EXISTS idx_flights_aircraft     ON flights (aircraft_id);
CREATE INDEX IF NOT EXISTS idx_flights_dep_airport  ON flights (departure_airport_id);
CREATE INDEX IF NOT EXISTS idx_flights_arr_airport  ON flights (arrival_airport_id);
CREATE INDEX IF NOT EXISTS idx_flights_status       ON flights (status);
CREATE INDEX IF NOT EXISTS idx_flights_fetch_at     ON flights (fetch_at);


-- ---------------------------------------------------------------------------
-- 5. ROUTE SEARCHES
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS route_searches (
    search_id               BIGSERIAL       PRIMARY KEY,

    origin_airport_id       BIGINT          NOT NULL REFERENCES airports(airport_id),
    destination_airport_id  BIGINT          NOT NULL REFERENCES airports(airport_id),

    -- The date the user searched (today's date at search time)
    search_date             DATE,

    -- The travel date the user is looking for flights on
    travel_date             DATE,

    -- Optional fields that may be available from the API/user
    passengers              SMALLINT        CHECK (passengers > 0),
    cabin_class             VARCHAR(20),    -- "economy", "business", "first"
    trip_type               VARCHAR(20),    -- "one_way", "round_trip"
    currency                VARCHAR(3),     -- ISO 4217, e.g. "INR"

    -- When this search result was fetched from the API
    fetch_at                TIMESTAMPTZ     NOT NULL,

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_route_origin       ON route_searches (origin_airport_id);
CREATE INDEX IF NOT EXISTS idx_route_destination  ON route_searches (destination_airport_id);
CREATE INDEX IF NOT EXISTS idx_route_search_date  ON route_searches (search_date);
CREATE INDEX IF NOT EXISTS idx_route_travel_date  ON route_searches (travel_date);
CREATE INDEX IF NOT EXISTS idx_route_fetch_at     ON route_searches (fetch_at);


-- ---------------------------------------------------------------------------
-- 6. ITINERARIES
--    One row per bookable option returned by the SearchAPI (Google Flights).
--    An itinerary owns its price, total travel time, and stop count.
--    Individual legs are stored in the flights table; itinerary_legs links them.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS itineraries (
    itinerary_id            BIGSERIAL       PRIMARY KEY,

    -- Which route search produced this itinerary
    search_id               BIGINT          REFERENCES route_searches(search_id) ON DELETE CASCADE,

    -- Convenience denormalisation — makes the cache query fast without a JOIN
    origin_airport_id       BIGINT          NOT NULL REFERENCES airports(airport_id),
    destination_airport_id  BIGINT          NOT NULL REFERENCES airports(airport_id),
    travel_date             DATE,

    -- Pricing & summary
    price                   NUMERIC(10,2),
    currency                VARCHAR(3),
    total_duration_minutes  INTEGER,
    stop_count              SMALLINT        NOT NULL DEFAULT 0,
    booking_token           TEXT,           -- Google Flights deep-link token

    fetch_at                TIMESTAMPTZ     NOT NULL,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_itin_route_date ON itineraries (origin_airport_id, destination_airport_id, travel_date);
CREATE INDEX IF NOT EXISTS idx_itin_fetch_at   ON itineraries (fetch_at);
CREATE INDEX IF NOT EXISTS idx_itin_search_id  ON itineraries (search_id);


-- ---------------------------------------------------------------------------
-- 7. ITINERARY LEGS
--    Ordered legs for one itinerary.  A single flights row may appear in
--    multiple itineraries (e.g. a shared hub leg), so this is a bridge table.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS itinerary_legs (
    itinerary_leg_id    BIGSERIAL   PRIMARY KEY,
    itinerary_id        BIGINT      NOT NULL REFERENCES itineraries(itinerary_id) ON DELETE CASCADE,
    flight_id           BIGINT      NOT NULL REFERENCES flights(flight_id)        ON DELETE CASCADE,
    leg_order           SMALLINT    NOT NULL,   -- 1-based: 1 = first leg, 2 = second, …

    -- Layover AFTER this leg (NULL on the last leg of an itinerary)
    layover_minutes     INTEGER,
    layover_airport_id  BIGINT      REFERENCES airports(airport_id),

    UNIQUE (itinerary_id, leg_order)
);

CREATE INDEX IF NOT EXISTS idx_itin_legs_itinerary ON itinerary_legs (itinerary_id);
CREATE INDEX IF NOT EXISTS idx_itin_legs_flight    ON itinerary_legs (flight_id);


-- ---------------------------------------------------------------------------
-- 8. FLIGHT SCHEDULES
--    Recurring weekly pattern for a flight/route.
--    Populated automatically by infer_and_update_schedule() as a side-effect
--    of normal API usage.  days_of_week uses the DEPARTURE airport's local
--    time — matching how airlines publish timetables ("flies on Mondays").
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flight_schedules (
    schedule_id                     BIGSERIAL    PRIMARY KEY,

    flight_number                   VARCHAR(20)  NOT NULL,
    airline_id                      BIGINT       REFERENCES airlines(airline_id),
    departure_airport_id            BIGINT       NOT NULL REFERENCES airports(airport_id),
    arrival_airport_id              BIGINT       NOT NULL REFERENCES airports(airport_id),

    -- ISO weekday numbers at departure-airport LOCAL time: 1=Mon ... 7=Sun
    days_of_week                    SMALLINT[]   NOT NULL,

    -- Clock time at the departure airport (local)
    scheduled_departure_local_time  TIME         NOT NULL,
    scheduled_arrival_local_time    TIME         NOT NULL,

    -- Validity window (NULL = open-ended)
    valid_from                      DATE,
    valid_to                        DATE,

    -- Inference quality
    confidence                      VARCHAR(20)  NOT NULL DEFAULT 'inferred',  -- 'inferred' | 'confirmed'
    observed_count                  SMALLINT     NOT NULL DEFAULT 1,

    fetch_at                        TIMESTAMPTZ  NOT NULL,
    created_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    UNIQUE (flight_number, departure_airport_id, arrival_airport_id, days_of_week)
);

CREATE INDEX IF NOT EXISTS idx_schedules_flight  ON flight_schedules (flight_number);
CREATE INDEX IF NOT EXISTS idx_schedules_route   ON flight_schedules (departure_airport_id, arrival_airport_id);
CREATE INDEX IF NOT EXISTS idx_schedules_fetchat ON flight_schedules (fetch_at);


-- ---------------------------------------------------------------------------
-- 9. FLIGHT ROUTES
--    Observed routes for a flight number
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flight_routes (
    route_id         BIGSERIAL PRIMARY KEY,
    flight_number    VARCHAR(20) NOT NULL,
    origin_iata      VARCHAR(3) NOT NULL,
    destination_iata VARCHAR(3) NOT NULL,
    first_seen       TIMESTAMPTZ DEFAULT NOW(),
    last_seen        TIMESTAMPTZ DEFAULT NOW(),
    observation_count INTEGER DEFAULT 1,
    UNIQUE(flight_number, origin_iata, destination_iata)
);


-- ---------------------------------------------------------------------------
-- 10. FLIGHT DELAY STATS
--     Aggregated reliability information
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flight_delay_stats (
    stat_id             BIGSERIAL PRIMARY KEY,
    flight_number       VARCHAR(20) NOT NULL,
    route_id            BIGINT REFERENCES flight_routes(route_id),
    total_observations  INTEGER DEFAULT 0,
    average_delay_mins  INTEGER DEFAULT 0,
    median_delay_mins   INTEGER DEFAULT 0,
    on_time_percentage  NUMERIC(5, 2) DEFAULT 100.00,
    last_calculated     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(flight_number, route_id)
);


-- ---------------------------------------------------------------------------
-- 8. SEMANTIC CACHE
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS semantic_cache (
    id              BIGSERIAL       PRIMARY KEY,
    query           TEXT            NOT NULL,
    response        TEXT            NOT NULL,
    embedding       VECTOR(384)     NOT NULL,
    query_type      VARCHAR(50),
    language        VARCHAR(10)     DEFAULT 'en',
    created_at      TIMESTAMPTZ     DEFAULT NOW(),
    expires_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS semantic_cache_embedding_idx ON semantic_cache USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS semantic_cache_type_idx ON semantic_cache(query_type);
CREATE INDEX IF NOT EXISTS semantic_cache_expiry_idx ON semantic_cache(expires_at);
