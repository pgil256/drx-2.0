# Handoff: Connect drx-2.0 to kneespa-cloud

This document tells you how to add cloud connectivity to the KneeSpa DRx 2.0 app so it can look up patients by PIN from the cloud dashboard and upload treatment records after each session.

## What exists today

**drx-2.0** is a PyQt5 kiosk app on Raspberry Pi that controls a knee decompression device. It currently has:

- **Local PIN auth only** — PINs are verified against `data/user_pins.csv` and env vars via PBKDF2-HMAC-SHA256 (`main/helpers/secure_auth.py`, `main/helpers/csv.py`). The auth controller is at `main/controllers/auth_controller.py`.
- **No network API calls** — the only outbound network is SMTP email for support tickets.
- **No treatment history** — protocols run and complete, but nothing is recorded or uploaded.

**kneespa-cloud** is a FastAPI server with two API surfaces:
1. Admin dashboard (web UI for clinic staff) — not relevant here
2. **Device API** (`/api/v1/device/*`) — this is what drx-2.0 needs to call

## The cloud Device API

**Base URL:** configured via env var (e.g. `KNEESPA_CLOUD_URL=https://cloud.kneespa.com`)

**Auth:** every request needs two headers:
```
Authorization: Bearer <device_token>
X-Device-Id: <device_id>
```
The token and device_id are provisioned by a clinic admin through the dashboard. Store them as env vars `KNEESPA_DEVICE_TOKEN` and `KNEESPA_DEVICE_ID`.

### Endpoints to integrate

#### 1. `GET /api/v1/device/ping`

Health check. Call on startup to verify connectivity.

**Response:**
```json
{
  "server_time": "2026-09-02T12:00:00Z",
  "device_name": "Clinic Room 1",
  "min_app_version": "2.0"
}
```

#### 2. `POST /api/v1/device/patients/lookup`

Looks up a patient by their 4-digit PIN. This replaces/augments the local CSV PIN check.

**Request:**
```json
{"pin": "1234"}
```

**Response (200):**
```json
{
  "patient_id": "uuid",
  "display_name": "Maria G.",
  "external_ref": "KS-2024-001",
  "settings": {
    "protocol_number": 1,
    "max_pressure_lb": 45.0,
    "max_left_deg": 10.0,
    "max_right_deg": 10.0,
    "pulse_rate_hz": 2.0,
    "duration_min": 12
  },
  "settings_source": "admin",
  "settings_effective_at": "2026-08-15T10:00:00Z",
  "last_session_at": "2026-08-28T14:30:00Z",
  "session_count": 5
}
```

**Error responses:**
- `404` with `{"error": "unknown_pin"}` — PIN not found
- `429` with `{"error": "rate_limited", "retry_after_s": 30}` — too many lookups (10 per 5 min per device)

#### 3. `POST /api/v1/device/treatments`

Upload a treatment record after a session completes. Call this from the protocol completion handler.

**Request:**
```json
{
  "schema_version": 1,
  "client_record_id": "uuid-generated-locally",
  "patient_id": "uuid-from-lookup",
  "protocol_number": 1,
  "outcome": "completed",
  "planned_duration_s": 720,
  "actual_duration_s": 715,
  "settings_at_end": {
    "max_pressure_lb": 45.0,
    "pulse_rate_hz": 2.0,
    "max_left_deg": 10.0,
    "max_right_deg": 10.0
  },
  "started_at": "2026-09-02T14:00:00Z",
  "ended_at": "2026-09-02T14:12:15Z",
  "app_version": "2.3",
  "fw_version": null
}
```

- `outcome`: one of `"completed"`, `"stopped"`, `"fault"`
- `client_record_id`: a UUID you generate locally — makes the upload idempotent (retries return 200 instead of creating duplicates)

**Response (201):**
```json
{
  "id": "server-uuid",
  "client_record_id": "your-uuid",
  "received_at": "2026-09-02T14:12:20Z"
}
```

## Where to integrate in drx-2.0

### New file: `main/helpers/cloud_client.py`

Create a cloud API client class. Use `urllib.request` (stdlib, no new dependencies) or add `requests` to the Pi's packages. The client should:

- Be initialized with `cloud_url`, `device_token`, `device_id` from env vars
- Have methods: `ping()`, `lookup_pin(pin: str)`, `post_treatment(record: dict)`
- Handle network errors gracefully — the device must work offline
- Run API calls in a `QThread` or `QRunnable` to avoid freezing the UI

### Modify: `main/controllers/auth_controller.py`

Change `handle_login()` to try cloud lookup first, fall back to local CSV:

```
Current flow:
  1. Check lockout
  2. Iterate window.users, verify PIN locally
  3. Set window.current_user = matched user dict

New flow:
  1. Check lockout
  2. Try cloud_client.lookup_pin(pin)
     - On success: build user dict from cloud response, store patient_id and
       cloud settings on the window (e.g. window.cloud_patient)
     - On 404: fall through to local CSV check
     - On network error / timeout: fall through to local CSV check
  3. If cloud failed, iterate window.users, verify PIN locally (existing logic)
  4. Set window.current_user = matched user dict
```

The cloud lookup response includes treatment settings (`protocol_number`, `max_pressure_lb`, etc.). After a successful cloud login, apply these to the Treatment screen's sliders via `treatment_screen.set_settings(values)` so the device starts with the clinic-prescribed settings.

**Important:** The cloud PIN lookup uses HMAC-SHA256 with a server-side pepper — the raw PIN is sent to the server over HTTPS, not a hash. This is different from the local PBKDF2 flow. The server handles the hashing.

### Modify: `main/controllers/protocol_controller.py`

In `protocol_completed(self, success)`, after the existing completion logic, post the treatment record to the cloud:

```python
# After existing completion handling...
if window.cloud_patient is not None:
    record = {
        "schema_version": 1,
        "client_record_id": str(uuid.uuid4()),
        "patient_id": str(window.cloud_patient["patient_id"]),
        "protocol_number": window.protocol_value,
        "outcome": "completed" if success else "stopped",
        "planned_duration_s": window.duration_value * 60,
        "actual_duration_s": elapsed_seconds,
        "settings_at_end": {
            "max_pressure_lb": float(window.max_pressure_value),
            "pulse_rate_hz": float(window.pulse_rate_value),
            "max_left_deg": float(window.max_left_value),
            "max_right_deg": float(window.max_right_value),
        },
        "started_at": protocol_start_time.isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "app_version": APP_VERSION,
        "fw_version": None,
    }
    # Fire and forget in background thread — don't block UI
    cloud_client.post_treatment_async(record)
```

For the `"fault"` outcome, also capture it — use the `signals.error` or `emergency_stop_clicked` path.

### Modify: `main/kneespa.py`

1. Initialize the cloud client in `__init__`:
   ```python
   from helpers.cloud_client import CloudClient
   self.cloud_client = CloudClient()  # reads env vars
   self.cloud_patient = None  # set on cloud login, cleared on logout
   ```

2. Pass `self.cloud_client` to `AuthController` and `ProtocolController`.

3. In `_on_logout()`, clear `self.cloud_patient = None`.

4. In `update_ui_after_login()`, if `self.cloud_patient` is set, apply its settings to the treatment screen.

### Offline resilience

The device must never brick if the cloud is unreachable:

- **PIN lookup:** try cloud first, fall back to local CSV. If the cloud is down, local users still work.
- **Treatment upload:** queue failed uploads to a local JSON file (e.g. `data/pending_uploads.json`). Retry on next successful `ping()` or on next app startup. The `client_record_id` UUID makes retries idempotent.
- **Startup ping:** if ping fails, log a warning and continue. Show a small "offline" indicator in the UI if desired.

### New env vars to add

Add these to the Pi's environment (systemd unit file or `.env`):

```
KNEESPA_CLOUD_URL=https://cloud.kneespa.com
KNEESPA_DEVICE_TOKEN=<base64url token from admin dashboard>
KNEESPA_DEVICE_ID=DRX-PI-001
```

## Data mapping reference

| drx-2.0 (current) | Cloud API field | Source in drx-2.0 |
|---|---|---|
| `window.protocol_value` | `protocol_number` | Treatment screen protocol picker (1-4) |
| `window.max_pressure_value` | `max_pressure_lb` | Treatment screen slider, `settings_values()["max_pressure"]` |
| `window.max_left_value` | `max_left_deg` | Treatment screen slider, `settings_values()["max_left"]` |
| `window.max_right_value` | `max_right_deg` | Treatment screen slider, `settings_values()["max_right"]` |
| `window.pulse_rate_value` | `pulse_rate_hz` | Treatment screen slider, `settings_values()["pulse_rate"]` |
| `window.duration_value * 60` | `planned_duration_s` | Treatment screen slider, `settings_values()["duration"]` (minutes → seconds) |
| Protocol elapsed time | `actual_duration_s` | `protocol_timer` elapsed, or `Protocols.duration - Protocols.remaining` |
| `APP_VERSION` ("2.3") | `app_version` | `main/config/constants.py` |
| Protocol success bool | `outcome` | `signals.finished(True)` → "completed", `signals.stopped` → "stopped", `signals.error` / e-stop → "fault" |

## Testing

For local development, run kneespa-cloud on the same machine or network:
```
KNEESPA_CLOUD_URL=http://localhost:8000
```

The device API test fixtures are in `kneespa-cloud/tests/test_device_api.py` — reference those for expected request/response shapes.

Test PINs are generated when patients are created through the admin dashboard. The PIN is shown once at creation time. For dev, seed patients via the admin API or use the seeded test data.
