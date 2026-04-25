# Database Schema Documentation

> **Generated**: 2026-04-25 19:18:26 UTC  
> **Database**: `ledger_db_test` @ `localhost`  
> **Tables**: 14

---

## Table of Contents

- [alembic_version](#alembic_version) (0 rows)
- [booking_history](#booking_history) (0 rows)
- [booking_id_seq](#booking_id_seq) (0 rows)
- [booking_items](#booking_items) (0 rows)
- [bookings](#bookings) (0 rows)
- [generators](#generators) (0 rows)
- [rental_vendor_id_seq](#rental_vendor_id_seq) (0 rows)
- [rental_vendors](#rental_vendors) (0 rows)
- [revoked_tokens](#revoked_tokens) (0 rows)
- [sessions](#sessions) (0 rows)
- [user_permission_overrides](#user_permission_overrides) (0 rows)
- [users](#users) (0 rows)
- [vendor_id_seq](#vendor_id_seq) (0 rows)
- [vendors](#vendors) (0 rows)

---

## alembic_version

**Rows (approx)**: 0
**Primary Key**: `version_num`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `version_num` | `character varying(32)` | ✗ | — | 🔑 |

---

## booking_history

**Rows (approx)**: 0
**Primary Key**: `id`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `id` | `integer` | ✗ | — | 🔑 |
| `event_time` | `text` | ✗ | — |  |
| `event_type` | `text` | ✗ | — |  |
| `booking_id` | `text` | ✓ | — |  |
| `vendor_id` | `text` | ✓ | — |  |
| `user` | `text` | ✓ | — |  |
| `summary` | `text` | ✓ | — |  |
| `details` | `text` | ✓ | — |  |

**Indexes**:

- `idx_booking_history_booking`: (booking_id)
- `idx_booking_history_time`: (event_time)
- `idx_booking_history_vendor`: (vendor_id)

---

## booking_id_seq

**Rows (approx)**: 0
**Primary Key**: `booking_date`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `booking_date` | `text` | ✗ | — | 🔑 |
| `next_val` | `integer` | ✗ | — |  |

---

## booking_items

**Rows (approx)**: 0
**Primary Key**: `id`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `id` | `integer` | ✗ | — | 🔑 |
| `booking_id` | `text` | ✗ | — |  |
| `generator_id` | `text` | ✗ | — |  |
| `start_dt` | `text` | ✗ | — |  |
| `end_dt` | `text` | ✗ | — |  |
| `item_status` | `text` | ✓ | `'Confirmed'::text` |  |
| `remarks` | `text` | ✓ | — |  |

**Foreign Keys**:

- `booking_id` → `bookings.booking_id` (`booking_items_booking_id_fkey`)
- `generator_id` → `generators.generator_id` (`booking_items_generator_id_fkey`)

**Indexes**:

- `idx_booking_items_booking`: (booking_id)
- `idx_booking_items_generator`: (generator_id, item_status)

---

## bookings

**Rows (approx)**: 0
**Primary Key**: `booking_id`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `booking_id` | `text` | ✗ | — | 🔑 |
| `vendor_id` | `text` | ✗ | — |  |
| `created_at` | `text` | ✗ | — |  |
| `status` | `text` | ✓ | `'Confirmed'::text` |  |

**Foreign Keys**:

- `vendor_id` → `vendors.vendor_id` (`bookings_vendor_id_fkey`)

---

## generators

**Rows (approx)**: 0
**Primary Key**: `generator_id`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `generator_id` | `text` | ✗ | — | 🔑 |
| `capacity_kva` | `integer` | ✗ | — |  |
| `identification` | `text` | ✓ | — |  |
| `type` | `text` | ✓ | — |  |
| `status` | `text` | ✓ | `'Active'::text` |  |
| `notes` | `text` | ✓ | — |  |
| `inventory_type` | `text` | ✓ | `'retailer'::text` |  |
| `rental_vendor_id` | `text` | ✓ | — |  |

**Indexes**:

- `idx_generators_inventory_rental_vendor`: (inventory_type, rental_vendor_id, generator_id)
- `idx_generators_inventory_type`: (inventory_type, generator_id)

---

## rental_vendor_id_seq

**Rows (approx)**: 0
**Primary Key**: `id`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `id` | `integer` | ✗ | `nextval('rental_vendor_id_seq_id_seq'::regclass)` | 🔑 |
| `next_val` | `integer` | ✗ | — |  |

---

## rental_vendors

**Rows (approx)**: 0
**Primary Key**: `rental_vendor_id`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `rental_vendor_id` | `text` | ✗ | — | 🔑 |
| `vendor_name` | `text` | ✗ | — |  |
| `vendor_place` | `text` | ✓ | — |  |
| `phone` | `text` | ✓ | — |  |

---

## revoked_tokens

**Rows (approx)**: 0
**Primary Key**: `jti`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `jti` | `text` | ✗ | — | 🔑 |
| `expires_at` | `bigint` | ✗ | — |  |

**Indexes**:

- `idx_revoked_tokens_expires_at`: (expires_at)

---

## sessions

**Rows (approx)**: 0
**Primary Key**: `session_id`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `session_id` | `text` | ✗ | — | 🔑 |
| `user_id` | `integer` | ✗ | — |  |
| `csrf_token` | `text` | ✗ | — |  |
| `created_at` | `bigint` | ✗ | — |  |
| `expires_at` | `bigint` | ✗ | — |  |
| `last_seen` | `bigint` | ✓ | — |  |
| `ip_address` | `text` | ✓ | — |  |
| `user_agent` | `text` | ✓ | — |  |

**Foreign Keys**:

- `user_id` → `users.id` (`sessions_user_id_fkey`)

**Indexes**:

- `idx_sessions_expires_at`: (expires_at)
- `idx_sessions_user_id`: (user_id)

---

## user_permission_overrides

**Rows (approx)**: 0
**Primary Key**: `user_id`, `capability_key`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `user_id` | `integer` | ✗ | — | 🔑 |
| `capability_key` | `text` | ✗ | — | 🔑 |
| `is_allowed` | `integer` | ✗ | — |  |

**Foreign Keys**:

- `user_id` → `users.id` (`user_permission_overrides_user_id_fkey`)

**Indexes**:

- `idx_user_permission_overrides_user_id`: (user_id)

---

## users

**Rows (approx)**: 0
**Primary Key**: `id`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `id` | `integer` | ✗ | — | 🔑 |
| `username` | `text` | ✗ | — |  |
| `password_hash` | `text` | ✗ | — |  |
| `role` | `text` | ✗ | — |  |
| `is_active` | `integer` | ✗ | `1` |  |
| `created_at` | `text` | ✗ | — |  |
| `last_login` | `text` | ✓ | — |  |

**Indexes**:

- `users_username_key` (UNIQUE): (username)

---

## vendor_id_seq

**Rows (approx)**: 0
**Primary Key**: `id`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `id` | `integer` | ✗ | `nextval('vendor_id_seq_id_seq'::regclass)` | 🔑 |
| `next_val` | `integer` | ✗ | — |  |

---

## vendors

**Rows (approx)**: 0
**Primary Key**: `vendor_id`

| Column | Type | Nullable | Default | PK |
|--------|------|----------|---------|:--:|
| `vendor_id` | `text` | ✗ | — | 🔑 |
| `vendor_name` | `text` | ✗ | — |  |
| `vendor_place` | `text` | ✓ | — |  |
| `phone` | `text` | ✓ | — |  |

---
