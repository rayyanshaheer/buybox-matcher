# Data Model

Four tables. Kept deliberately small — enough to drive the matching loop, no
more.

## Tables

### `buyers`
A cash buyer / investor.

| column     | type        | notes                    |
|------------|-------------|--------------------------|
| id         | uuid (pk)   | generated                |
| name       | text        | investor name            |
| company    | text        | nullable                 |
| email      | text        | nullable                 |
| phone      | text        | nullable                 |
| created_at | timestamptz | default now()            |

### `buy_boxes`
A buyer's purchase criteria. One active buy box per buyer (kept 1:1 for the
tryout; modelled as its own table so a buyer could have several later).

| column         | type        | notes                                            |
|----------------|-------------|--------------------------------------------------|
| id             | uuid (pk)   | generated                                        |
| buyer_id       | uuid (fk)   | → buyers.id                                      |
| markets        | text[]      | cities / metros, e.g. {"Tampa","Lakeland"}       |
| strategy       | text        | enum: fix_and_flip, buy_and_hold, brrrr, wholesale |
| property_type  | text        | enum: single_family, multi_family, condo, land   |
| price_min      | int         | nullable                                         |
| price_max      | int         | nullable                                         |
| arv_pct_max    | int         | max % of ARV they pay, e.g. 70                   |
| min_beds       | int         | nullable                                         |
| min_baths      | numeric     | nullable                                         |
| condition      | text        | enum: distressed, light_rehab, turnkey, any      |
| raw_text       | text        | original message the box was extracted from      |
| created_at     | timestamptz | default now()                                    |

### `properties`
A deal a wholesaler wants to place.

| column        | type        | notes                              |
|---------------|-------------|------------------------------------|
| id            | uuid (pk)   | generated                          |
| address       | text        |                                    |
| city          | text        |                                    |
| price         | int         | asking / contract price            |
| arv           | int         | after repair value                 |
| beds          | int         |                                    |
| baths         | numeric     |                                    |
| sqft          | int         | nullable                           |
| property_type | text        | same enum as buy_boxes             |
| condition     | text        | same enum as buy_boxes             |
| created_at    | timestamptz | default now()                      |

### `matches`
A computed score linking a property to a buyer. Cached so results are
inspectable and repeatable.

| column      | type        | notes                                         |
|-------------|-------------|-----------------------------------------------|
| id          | uuid (pk)   | generated                                     |
| property_id | uuid (fk)   | → properties.id                               |
| buyer_id    | uuid (fk)   | → buyers.id                                   |
| score       | int         | 0-100                                         |
| reasons     | jsonb       | { fit: [...], risk: [...] }                   |
| created_at  | timestamptz | default now()                                 |

## Relationships

```
buyers 1 ──── 1 buy_boxes
buyers 1 ──── * matches
properties 1 ── * matches
```

## Enums (kept as text + app-level validation)

- `strategy`: fix_and_flip | buy_and_hold | brrrr | wholesale
- `property_type`: single_family | multi_family | condo | land
- `condition`: distressed | light_rehab | turnkey | any

Stored as text for flexibility during a tryout; promote to Postgres enums or a
lookup table once the values stabilize.

## Derived value: ARV %

`property.price / property.arv * 100` is computed at match time and compared
against `buy_box.arv_pct_max`. Not stored on the property — it is a function of
price and ARV and should not drift out of sync.
