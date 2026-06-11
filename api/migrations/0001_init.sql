-- BuyBox Matcher — initial schema (migration 0001)
-- Creates the four core tables (buyers, buy_boxes, properties, matches),
-- their constraints, and supporting indexes.
-- Requirements: 9.1-9.8

-- buyers (Req 9.1)
create table buyers (
    id         uuid primary key default gen_random_uuid(),
    name       text not null,
    company    text,
    email      text,
    phone      text,
    created_at timestamptz not null default now()
);

-- buy_boxes (Req 9.2, 9.7) — 1:1 with buyer enforced by unique(buyer_id)
create table buy_boxes (
    id            uuid primary key default gen_random_uuid(),
    buyer_id      uuid not null references buyers(id) on delete cascade,
    markets       text[] not null default '{}',
    strategy      text,
    property_type text,
    price_min     int,
    price_max     int,
    arv_pct_max   int check (arv_pct_max between 0 and 100),
    min_beds      int,
    min_baths     numeric,
    condition     text,
    raw_text      text not null,
    created_at    timestamptz not null default now(),
    constraint uq_buy_box_buyer unique (buyer_id),                 -- enforces 1:1 (9.7)
    constraint ck_price_range check (
        price_min is null or price_max is null or price_min <= price_max
    ),
    constraint ck_strategy check (
        strategy is null or strategy in
        ('fix_and_flip','buy_and_hold','brrrr','wholesale')        -- (9.5)
    ),
    constraint ck_property_type check (
        property_type is null or property_type in
        ('single_family','multi_family','condo','land')
    ),
    constraint ck_condition check (
        condition is null or condition in
        ('distressed','light_rehab','turnkey','any')
    )
);

-- properties (Req 9.3, 9.6 — no Deal_ARV_Pct column)
create table properties (
    id            uuid primary key default gen_random_uuid(),
    address       text not null,
    city          text not null,
    price         int  not null,
    arv           int  not null,
    beds          int,
    baths         numeric,
    sqft          int,
    property_type text not null check (property_type in
                  ('single_family','multi_family','condo','land')),
    condition     text not null check (condition in
                  ('distressed','light_rehab','turnkey','any')),
    created_at    timestamptz not null default now()
);

-- matches (Req 9.4, 9.8)
create table matches (
    id          uuid primary key default gen_random_uuid(),
    property_id uuid not null references properties(id) on delete cascade,
    buyer_id    uuid not null references buyers(id) on delete cascade,
    score       int  not null check (score between 0 and 100),
    reasons     jsonb not null,            -- { "fit": [...], "risk": [...] }
    created_at  timestamptz not null default now()
);

create index idx_matches_property on matches(property_id);
create index idx_buy_boxes_buyer  on buy_boxes(buyer_id);
