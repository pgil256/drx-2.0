# KneeSpa Admin Dashboard — Proof-of-Concept Plan

**Date:** 2026-09-01
**Repositories:** new `kneespa-cloud` (dashboard + API) and `drx-2.0` (device client)
**Scope:** A separately hosted web application that (a) receives protocol-completion records from the device, (b) returns a patient's settings to the device on PIN lookup, and (c) gives an administrator login plus patient CRUD.
**Out of scope this phase:** 21 CFR Part 11 audit trails, HIPAA controls, e-signatures, multi-tenant billing. The design below leaves room for all of them (§10).

---

## 1. Goals and constraints

1. Every patient gets the same treatment settings visit to visit, regardless of which device or operator runs the session.
2. Every completed protocol is recorded once, durably, with enough fidelity to support an eventual FDA submission.
3. The device is a **client only**: it initiates every request over HTTPS on the clinic Wi-Fi. The dashboard never connects into the clinic network, so no port-forwarding, VPN, or inbound firewall rule is needed.
4. A lost connection must never affect a running treatment and must never lose a record.
5. Nothing here may touch the firmware safety path. All device-side work is Python in `main/`, isolated behind one new module, and the app must behave exactly as today when the cloud is unconfigured.

### Facts from the current device code that shape the design

| Fact | Where | Consequence |
|---|---|---|
| The 4-digit PIN entered at login identifies the **operator** (`admin`/`user` rows in `user_pins.csv`), not a patient. | `controllers/auth_controller.py`, `helpers/csv.py` | Patient PIN is a **second, separate** keypad step on the Treatment screen, after operator login and before Start. Operator login is unchanged. |
| The device already generates and persists a per-device UUID (`[Device] id` in `kneespa.cfg`). | `config/config.py` `ensure_device_id()` | Reused as the device identity sent to the server. |
| Treatment settings are a five-value tuple: `max_pressure`, `max_left`, `max_right`, `pulse_rate` (pulses/s, 0 = off), `duration` (min). | `config/config.py` `protocol_defaults()` | The server's "patient settings" object is exactly this tuple plus `protocol_number`. |
| Settings can change mid-session via sliders, and the worker holds the live values. | `helpers/protocols.py` `request_live_*` | "Settings at end of session" = the worker's `max_pressure`, `max_left`, `max_right`, `pulse_rate` at completion, not the values the session started with. |
| `protocol_completed(success)` fires on natural completion, operator stop, and fault. | `controllers/protocol_controller.py` | One hook point produces the treatment record; the record carries an `outcome` so stopped/faulted sessions are also captured. |
| Protocol numbers are `"1"`–`"4"`; pressure is capped at 80 lb; lateral limits come from `LATERAL_MAX_DEGREES`; pulse interval 100–5000 ms. | `config/constants.py` | Server-side validation ranges mirror these. |
| The Pi has no HTTP client dependency today; PyQt5 comes from apt. | `main/requirements.txt` | Device client uses the standard library (`urllib.request`, `json`, `sqlite3`) so no new packages are needed on the Pi. |

---

## 2. Hosting

**Recommendation: Render (web service + managed Postgres), US region, packaged as a single Docker image.**

Why:
- Zero-ops TLS, custom domain, and health checks. The device only needs a public HTTPS hostname.
- Managed Postgres with automatic daily backups and point-in-time recovery on paid tiers.
- Docker-based deploys mean the same image runs on AWS App Runner/ECS + RDS later. Moving hosts when a HIPAA BAA becomes necessary is a config change, not a rewrite. Confirm BAA availability with the chosen provider before Phase 2; if it is not available, AWS (App Runner + RDS, both HIPAA-eligible) is the fallback and the Dockerfile already targets it.
- Cost for PoC is on the order of tens of dollars per month.

Equivalent alternatives: Fly.io, Railway. Rejected for PoC: raw VPS (you own patching and TLS renewal), serverless (cold starts complicate the device's short timeouts, and a long-lived process is simpler to reason about).

Environment layout: one `staging` and one `production` service from day one. The bench Pi points at staging; nothing points at production until §12 M5.

---

## 3. Backend stack

**Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL 16, Jinja2 + HTMX for the admin UI, pytest.**

Why Python: the device is Python, the team already tests with pytest and fakes (`tests/fixtures/fake_arduino.py`), and the PIN-hashing helper (`helpers/secure_auth.py`, PBKDF2) can be lifted directly. One language, one test style.

Why FastAPI: automatic OpenAPI schema. The device client and the server tests are validated against the same contract file (§6), which is what makes the API safe to evolve.

Why server-rendered HTMX rather than a React SPA: the admin UI is forms and tables. HTMX gives inline edits and live search without a second build pipeline. The JSON API underneath is the same one a SPA would use, so a richer front end can replace the templates later without touching the backend.

Project layout (`kneespa-cloud`):

```
app/
  main.py            # FastAPI app factory, middleware, routers
  settings.py        # pydantic-settings; everything from env vars
  db.py              # engine/session
  models/            # SQLAlchemy models (one file per table)
  schemas/           # pydantic request/response models
  api/device_v1.py   # /api/v1/device/*   (device token auth)
  api/admin_v1.py    # /api/v1/admin/*    (session auth)  — JSON, used by HTMX
  web/               # Jinja2 templates + HTMX views
  services/          # settings resolution, PIN hashing, token issuance
  auth/              # admin sessions, device token verification, rate limiting
alembic/             # migrations
tests/
Dockerfile
docker-compose.yml   # local Postgres for dev
openapi/device-v1.json   # frozen contract, checked in
```

---

## 4. Database schema

All timestamps are `timestamptz` in UTC. All primary keys are UUIDs. Nothing is hard-deleted; rows carry `deleted_at`. Treatment records and settings history are append-only. These four rules cost nothing now and are the foundation for Part 11 later.

```sql
-- Clinics / trial sites. PoC has one row; a trial has several.
create table sites (
  id           uuid primary key,
  name         text not null,
  created_at   timestamptz not null default now()
);

-- Dashboard logins.
create table admin_users (
  id             uuid primary key,
  email          citext unique not null,
  password_hash  text not null,          -- argon2id
  role           text not null default 'admin',   -- 'admin' | 'viewer'
  created_at     timestamptz not null default now(),
  last_login_at  timestamptz,
  disabled_at    timestamptz
);

-- Registered devices. device_id is the UUID from kneespa.cfg [Device] id.
create table devices (
  id            uuid primary key,
  site_id       uuid not null references sites(id),
  device_id     text unique not null,     -- from the Pi's kneespa.cfg
  name          text not null,            -- "Left bench unit"
  token_hash    text not null,            -- sha256 of the bearer token
  app_version   text,
  fw_version    text,
  last_seen_at  timestamptz,
  created_at    timestamptz not null default now(),
  revoked_at    timestamptz
);

create table patients (
  id            uuid primary key,
  site_id       uuid not null references sites(id),
  external_ref  text not null,            -- clinic chart # or study ID (see §9 PHI note)
  display_name  text,                     -- optional; initials recommended for PoC
  notes         text,
  pin_hmac      text not null,            -- HMAC-SHA256(server pepper, pin)
  status        text not null default 'active',   -- 'active' | 'inactive'
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz,
  unique (site_id, pin_hmac)              -- PIN unique per site; lookup is O(1)
);

-- Append-only settings history. The device receives the newest row.
create table patient_settings (
  id               uuid primary key,
  patient_id       uuid not null references patients(id),
  protocol_number  smallint not null check (protocol_number between 1 and 4),
  max_pressure_lb  numeric(5,1) not null check (max_pressure_lb between 0 and 80),
  max_left_deg     numeric(4,1) not null check (max_left_deg >= 0),
  max_right_deg    numeric(4,1) not null check (max_right_deg >= 0),
  pulse_rate_hz    numeric(4,2) not null check (pulse_rate_hz between 0 and 10),
  duration_min     smallint not null check (duration_min between 1 and 60),
  source           text not null,         -- 'admin' | 'device'
  source_id        uuid,                  -- admin_users.id or treatment_records.id
  effective_at     timestamptz not null default now(),
  created_at       timestamptz not null default now()
);
create index on patient_settings (patient_id, effective_at desc);

-- One row per protocol run. Written once; never updated.
create table treatment_records (
  id                  uuid primary key,
  client_record_id    uuid unique not null,   -- generated on the Pi; idempotency key
  patient_id          uuid not null references patients(id),
  device_id           uuid not null references devices(id),
  protocol_number     smallint not null,
  outcome             text not null,          -- 'completed' | 'stopped' | 'fault'
  planned_duration_s  integer not null,
  actual_duration_s   integer not null,
  max_pressure_lb     numeric(5,1) not null,  -- setting at end of session
  pulse_rate_hz       numeric(4,2) not null,
  max_left_deg        numeric(4,1) not null,
  max_right_deg       numeric(4,1) not null,
  started_at          timestamptz not null,   -- device clock
  ended_at            timestamptz not null,   -- device clock
  received_at         timestamptz not null default now(),   -- server clock
  clock_skew_s        integer,                -- server_now - device ended_at at receipt
  app_version         text,
  fw_version          text,
  raw_payload         jsonb not null          -- exact body as received
);
create index on treatment_records (patient_id, ended_at desc);

-- Cheap now, required later. Written by a 3-line helper on every mutating
-- admin action and every device registration/revocation.
create table events (
  id          bigserial primary key,
  at          timestamptz not null default now(),
  actor_type  text not null,     -- 'admin' | 'device' | 'system'
  actor_id    uuid,
  action      text not null,     -- 'patient.create', 'device.revoke', ...
  target_type text,
  target_id   uuid,
  detail      jsonb
);
```

### Settings resolution ("settings at the end of the most recent session")

The lookup returns the newest `patient_settings` row for the patient. Two things write that table:

- **Device**, when it posts a treatment record: the server inserts a `source='device'` row from the record's end-of-session values, `effective_at = ended_at`.
- **Admin**, when they save the settings form: a `source='admin'` row with `effective_at = now()`.

So a clinician who lowers a patient's pressure in the dashboard after a session wins over that session's ending values, and the next session's ending values win over that. Creating a patient requires an initial settings row, so a first visit never falls back to device defaults. The history is visible in the patient view and is never edited.

**Why HMAC rather than salted PBKDF2 for the patient PIN:** the device sends a PIN and the server must find the patient in one indexed read. A per-row salt would force scanning every patient (what the device does today over a handful of operators). A 4-digit space is 10,000 values, so no hash makes it strong; the real protection is the device token, per-device rate limiting, and the server-side pepper kept in the secret store. This also enforces PIN uniqueness per site at insert time. Trade-off accepted for PoC; `pin_hmac` can be re-keyed with a pepper rotation job.

---

## 5. Device-to-server API contract

Base URL: `https://<host>/api/v1/device`. JSON only. Every request carries:

```
Authorization: Bearer <device token>
X-Device-Id: <uuid from kneespa.cfg>
User-Agent: kneespa-device/<app_version>
```

The server rejects a token whose `device_id` does not match the header. This binds the token to one physical unit and makes a cloned SD card obvious in the device list.

### `GET /ping`
Connectivity and clock check. Called at app start and by the uploader before draining the queue.

Response `200`:
```json
{ "server_time": "2026-09-01T14:03:11Z", "device_name": "Left bench unit", "min_app_version": "2.3.0" }
```

### `POST /patients/lookup`
PIN → settings. POST, not GET, so the PIN never appears in a URL, proxy log, or browser history.

Request:
```json
{ "pin": "4821" }
```

Response `200`:
```json
{
  "patient_id": "0f4c...",
  "display_name": "J.D.",
  "external_ref": "STUDY-0117",
  "settings": {
    "protocol_number": 2,
    "max_pressure_lb": 45.0,
    "max_left_deg": 15.0,
    "max_right_deg": 10.0,
    "pulse_rate_hz": 2.0,
    "duration_min": 12
  },
  "settings_source": "device",
  "settings_effective_at": "2026-08-28T16:42:09Z",
  "last_session_at": "2026-08-28T16:42:09Z",
  "session_count": 7
}
```

Response `404 { "error": "unknown_pin" }` for no match or inactive patient (the same response for both, so the device cannot enumerate). Response `429 { "error": "rate_limited", "retry_after_s": 60 }` after 10 failed lookups from one device in 5 minutes.

### `POST /treatments`
Idempotent on `client_record_id`. The device generates the UUID when the record is created, before the first send attempt. A retry after a timeout therefore cannot create a duplicate.

Request:
```json
{
  "schema_version": 1,
  "client_record_id": "9d1e...",
  "patient_id": "0f4c...",
  "protocol_number": 2,
  "outcome": "completed",
  "planned_duration_s": 720,
  "actual_duration_s": 721,
  "settings_at_end": {
    "max_pressure_lb": 45.0,
    "pulse_rate_hz": 2.0,
    "max_left_deg": 15.0,
    "max_right_deg": 10.0
  },
  "started_at": "2026-09-01T14:00:02Z",
  "ended_at":   "2026-09-01T14:12:03Z",
  "app_version": "2.3.0",
  "fw_version": "FAILSAFE-5"
}
```

Responses: `201` created, `200` already existed (body identical to 201, includes `id`). Both mean "done, remove from queue". `422` validation failure with a field-level `detail` list: the device moves the record to a dead-letter file and raises an operator-visible warning, because retrying will never succeed. `401`/`403`: token invalid or revoked, the uploader pauses and the status bar shows an auth error. `5xx`/timeout: retry per §7.

### Versioning and evolution
- Path version (`/v1`) changes only for breaking changes. Additive fields are always allowed; the device ignores unknown fields and the server tolerates missing optional ones.
- `schema_version` inside the treatment body lets the server store and later migrate records posted by older app versions.
- `openapi/device-v1.json` is checked into both repos. The server's test suite asserts the generated schema matches it; the device test suite validates its outgoing payloads against it.

### Device registration and the token
1. Admin creates the device in the dashboard (§8). The server generates 32 random bytes, stores `sha256(token)`, and shows the base64url token **once**.
2. On the Pi, the token goes into `/etc/kneespa/cloud.env` (mode 0600, owner `pi`):
   ```
   KNEESPA_CLOUD_URL=https://staging.kneespa.example/api/v1/device
   KNEESPA_CLOUD_TOKEN=...
   ```
   The unit in `rpi/startup_version.txt` has no environment file today; add `EnvironmentFile=-/etc/kneespa/cloud.env` (the leading `-` makes a missing file non-fatal) and have `rpi/desktop_executable.sh` source the same file so the desktop launcher and the service agree. `rpi/sync_pis.sh` never touches this file, in line with how it treats `kneespa.cfg` and `user_pins.csv`.
3. If either variable is absent, the cloud client is disabled and the app behaves exactly as today. This is also the escape hatch for bench work.
4. Rotation: admin clicks **Rotate token**, gets a new one, updates the env file, restarts the service. The old token is rejected immediately. Revocation is the same without a replacement.

---

## 6. Device-side design (`drx-2.0`)

One new package, three new UI touches, no firmware or safety-path changes.

```
main/helpers/cloud/
  __init__.py
  client.py     # CloudClient: ping(), lookup_pin(pin), post_treatment(record)  (urllib, timeouts 3s connect / 5s read)
  outbox.py     # Outbox: sqlite-backed durable queue of treatment records
  uploader.py   # UploaderThread (QThread): drains Outbox with backoff; emits status signals
  cache.py      # last-known settings per patient for offline PIN lookups
main/controllers/patient_controller.py   # patient PIN step, holds current_patient
```

### Where it hooks into the existing flow

| Event | Today | With the cloud client |
|---|---|---|
| App start | connect Arduino, show login | also start `UploaderThread`; it pings, then drains any queued records |
| Operator logs in | Treatment screen | unchanged |
| Operator presses **Patient** (new button, Treatment screen header) | – | 4-digit keypad modal reusing `DSKeypad(length=4)`; on submit, `PatientController.lookup(pin)` runs `CloudClient.lookup_pin` on a worker thread |
| Lookup success | – | sliders and protocol selector are set from `settings` via the existing `shell.treatment.set_settings(...)` path; banner shows `display_name` and "last session <date>"; `window.current_patient` set |
| Operator presses **Start** | `start_protocol()` checks `current_user` and `config.calibrated` | additionally checks `current_patient`; if none, timed error "Enter patient PIN before starting" and no start. When the cloud is unconfigured this check is skipped so bench/testing behaviour is unchanged. |
| Session ends (`protocol_completed`) | UI reset | build the record from the worker's live `max_pressure`/`max_left`/`max_right`/`pulse_rate`, `protocol_start_time`, `success`/`protocol_stop_requested`/fault state; `Outbox.enqueue(record)` **before** anything else; then nudge the uploader. `current_patient` is cleared so the next session must re-enter a PIN. |
| Operator logs out / app closes | – | `current_patient` cleared; uploader thread is joined with the same deterministic-shutdown pattern the serial threads use |

The record is assembled on the UI thread from values the worker already holds; the worker itself is untouched.

### Status surface
A small cloud indicator in the existing status area with four states: **Synced**, **N pending** (offline, queued), **Offline: PIN lookup unavailable**, **Cloud auth error: see admin**. No modal dialogs for transient outages; treatment is never interrupted by cloud state.

---

## 7. Lost-connection handling (queue and retry)

Principle: the cloud is consulted at exactly two moments, immediately before a session (PIN lookup) and immediately after (record post). During the session nothing touches the network, so a Wi-Fi drop mid-treatment has no effect on the protocol.

### Record posting: durable outbox
1. `protocol_completed` writes the full JSON body plus `client_record_id`, `created_at`, `attempts=0` into `data/cloud_outbox.sqlite` in one transaction. Only after the commit does the UI proceed. A power cut after this point cannot lose the record.
2. `UploaderThread` loop: if the outbox is non-empty, `ping`; if that fails, sleep with backoff and retry. Otherwise take the oldest record, POST it, and on `200`/`201` delete it. Records are sent strictly in order so history stays chronological even after a long outage.
3. Backoff: 5 s, 10 s, 20 s, ... capped at 5 min, with ±20 % jitter. A successful call resets it. Wake-ups also come from `protocol_completed` (new record) and from a 60 s periodic timer so a restored network is noticed quickly.
4. Terminal failures: `422` → move to `data/cloud_deadletter/<client_record_id>.json`, log at ERROR, set the status indicator to the warning state, continue with the next record. `401`/`403` → stop draining, show the auth-error state, retry a `ping` every 5 min so a rotated token recovers without a restart.
5. Nothing is ever deleted from the outbox except on server acknowledgement. The outbox survives reboots and app upgrades (`sync_pis.sh` excludes `data/`).

### PIN lookup when offline
1. Every successful lookup is cached in `data/cloud_cache.sqlite` keyed by `HMAC(device_token, pin)` → `{patient_id, display_name, settings, effective_at, cached_at}`.
2. If the lookup times out or errors and a cache entry younger than 30 days exists, the device proceeds with the cached settings and the banner reads "Offline: using settings from <date>". The record posted afterwards is what brings the server up to date.
3. If offline with no cache entry, Start is blocked with "Cannot verify patient PIN while offline". This is the one case that halts treatment, and it only affects a patient's first visit on a given device during an outage. Alternative if the clinic prefers: allow a "no patient" session that records `patient_id: null`. Decide during M4 with the clinic.
4. If a PIN lookup succeeds online but the *post* later reveals the patient was deleted (`422 unknown patient`), the record goes to dead-letter and is visible in the admin UI's dead-letter report (M5), never silently dropped.

### Clocks
The Pi's clock may be wrong after a long power-off without network. The device sends its own `started_at`/`ended_at`; the server stores `received_at` and `clock_skew_s`. Records with skew over 5 minutes are flagged in the history view. `ping` returns `server_time` so the app can log a warning at start if the skew is large. The Pi should run `systemd-timesyncd` (standard on Raspberry Pi OS); this plan does not depend on it but benefits from it.

### Mid-session app crash or power loss
`protocol_completed` runs on stop and fault as well as completion, so an operator stop or firmware fault still produces a record. A hard power cut mid-session produces no record. Closing that gap (a "session started" marker written at Start and reconciled on next boot as `outcome='incomplete'`) is a Phase 2 item; it is listed so the schema's `outcome` column already has room for it.

---

## 8. Admin UI

Server-rendered pages, mobile-usable, no JS build. Login is email + password (argon2id), HTTP-only secure session cookie, CSRF tokens on every form, 5 failed logins → 15 min lockout (same shape as the device's lockout).

| Page | Contents |
|---|---|
| **Login** | email, password |
| **Patients** | table: external ref, display name, status, last session, session count; live search (HTMX); **New patient** |
| **Patient — new/edit** | external ref, display name, notes, status; **PIN** (auto-generated unique 4-digit, shown once, **Regenerate**); initial/current settings form (protocol 1–4, pressure 0–80, left/right 0–max, pulse 0–10 Hz, duration 1–60 min) with the same ranges the device enforces |
| **Patient — detail** | current settings with source ("from session on 28 Aug" / "set by admin on 30 Aug"); settings history; treatment history table (date, device, protocol, outcome, duration, pressure, pulse, left, right, skew flag); **Export CSV** |
| **Devices** | list with site, name, last seen, app/fw version, status; **Register device** (enter the Pi's `device_id`, get a one-time token); **Rotate token**; **Revoke** |
| **Admin users** | list, invite, disable (admin role only) |

Deletion is soft: a deleted patient disappears from lists and returns `unknown_pin` to devices, but their treatment history is retained. The UI labels it "Deactivate" to match.

---

## 9. Security baseline for the PoC

- TLS everywhere; HSTS on the dashboard host. The device client refuses plain `http://` URLs outside `--testing` mode.
- Device tokens: 256-bit random, stored hashed, bound to `device_id`, revocable, rotated from the UI.
- Admin passwords: argon2id. Sessions expire after 12 h idle.
- Rate limits: PIN lookups per device (above), admin login per IP.
- The PIN and the bearer token are never logged on either side. Device-side logging already redacts the operator PIN; extend the same filter.
- Secrets (DB URL, session key, PIN pepper) come from the host's secret store, never from the repo.
- Postgres reachable only from the web service (private network), not from the internet.
- **PHI minimisation:** for the PoC, identify patients by a clinic chart number or study ID plus optional initials. Do not store names, dates of birth, or contact details. This keeps the PoC outside HIPAA's practical reach while a BAA is arranged, and it is the identification scheme a trial will want anyway. The schema has `display_name` and `notes` for the clinic's convenience; the onboarding note tells admins what not to put there.
- Daily automated DB backups (provider feature), restore tested once in M5.

---

## 10. Keeping the compliance path open

Nothing in this phase implements Part 11 or HIPAA, but each of these choices is what those phases will build on, and reversing any of them later would be expensive:

| Later requirement | Decision made now that supports it |
|---|---|
| Audit trail of who changed what, when | `events` table written from day one; append-only `patient_settings` and `treatment_records`; soft delete everywhere |
| Data integrity / non-repudiation | `raw_payload` kept verbatim; `client_record_id` idempotency; device identity bound to token; server `received_at` alongside device timestamps |
| Access control and unique user IDs | separate `admin_users` with roles; per-device tokens (no shared credential) |
| HIPAA technical safeguards | TLS, hashed secrets, private DB, US region, backups, PHI minimisation; Docker image portable to a BAA-covered host |
| Multi-site trials | `sites` scoping on patients and devices from the first migration |
| Electronic signatures | admin actions already recorded with actor and timestamp; adding a re-authentication step is UI-only |
| Data export for submission | CSV export exists; schema is flat enough for CDISC-style mapping later |

Explicitly deferred: MFA for admins, field-level encryption, tamper-evident (hash-chained) audit log, retention policies, `outcome='incomplete'` reconciliation, per-site admin roles.

---

## 11. Testing strategy

**Server (`kneespa-cloud`):** pytest against a real Postgres in `docker-compose`. Contract tests for every endpoint including the 404/422/429/401 paths and idempotent re-posts. A schema-drift test asserts the live OpenAPI output equals `openapi/device-v1.json`. Migrations run forward and back in CI.

**Device (`drx-2.0`):** `tests/fixtures/fake_cloud.py`, a tiny in-process HTTP server mirroring `fake_arduino.py`'s role, scriptable for timeouts, 5xx, 422, and 401. Unit tests for `Outbox` (durability across "reboot" = re-open the sqlite file, ordering, dead-letter), `UploaderThread` backoff, `cache` TTL, and `PatientController`. Existing suites must stay green with the cloud unconfigured; `test_run_local.py` gains a case that the app runs with no `KNEESPA_CLOUD_*` set.

**End-to-end (M4):** bench Pi on Wi-Fi against staging: PIN lookup, run a protocol with no patient attached to the mechanism, confirm the record appears; pull the Wi-Fi dongle, run again, confirm "1 pending", reconnect, confirm delivery and ordering; revoke the token, confirm the auth-error state and recovery after rotation.

---

## 12. Milestones

| # | Deliverable | Acceptance |
|---|---|---|
| **M0** | `kneespa-cloud` repo scaffold: FastAPI app, Alembic, Dockerfile, compose, CI running tests, staging deploy on Render with TLS | `GET /api/v1/device/ping` returns 401 without a token from the public URL |
| **M1** | Schema (§4), device API (§5), token issuance, rate limiting, frozen `openapi/device-v1.json` | contract tests green; a `curl` with a real token completes lookup → post → lookup and the returned settings reflect the post |
| **M2** | Admin UI (§8): login, patients CRUD with PIN + settings, devices with token issue/rotate/revoke, patient history + CSV | an admin can create a patient and a device from a clean DB with no CLI access |
| **M3** | Device client (§6–7) on a `feat/cloud-client` branch of `drx-2.0`: `helpers/cloud/`, `PatientController`, Patient button + keypad, Start gate, outbox + uploader, status indicator, `fake_cloud` tests | all existing suites green with cloud unconfigured; new tests green; `run_local.py` demo against a local server |
| **M4** | Bench validation on the left-rpi unit against staging (§11 E2E), clinic decision on the offline-first-visit policy | E2E checklist signed off; no firmware change required |
| **M5** | Hardening: production service, backup restore drill, dead-letter report page, README for admins and for device provisioning, PR to `main` | production URL live with one registered device |

Rough effort: M0–M2 about two weeks, M3 about one week, M4–M5 about one week, for one developer with the bench unit available for M4.

---

## 13. Open decisions for the owner

1. **Hosting provider:** Render as recommended, or straight to AWS now if a BAA is expected within months.
2. **Offline first-visit policy** (§7): block Start, or allow an unattributed session.
3. **Patient identifier:** confirm the clinic can supply a chart number or study ID so no names are stored in the PoC.
4. **Pulse rate on the record:** the spec says "pulse rate"; the device has both an on/off flag and a Hz value. The plan records Hz with 0 meaning off. Confirm that is sufficient for the trial data set.
5. **Duration on the record:** the plan records both planned and actual seconds. Confirm which the trial protocol considers "duration".
