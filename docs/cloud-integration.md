# KneeSpa cloud integration

The September 15, 2026 cloud handoff is implemented on top of the existing DRx
client. The handoff's older pinned DRx revision lacked this integration; the
current checkout already had its initial lookup and upload implementation.

## Provisioning

Register the device in the cloud dashboard under Devices → Register Device.
Set these environment variables on the Pi, or put them in `cloud.env` at the
repository root (process environment variables take precedence):

```text
KNEESPA_CLOUD_URL=https://your-cloud-host
KNEESPA_DEVICE_ID=DRX-PI-001
KNEESPA_DEVICE_TOKEN=<device token shown by the dashboard>
```

Use the registered device ID string, not its database UUID. Do not commit the
token. `python-dotenv` from the application requirements loads `cloud.env`.
Production URLs require HTTPS. HTTP is accepted only for localhost/loopback
development servers. Redirects are refused so device credentials stay at the
configured origin. Incomplete configuration disables cloud operations.

Requests use the device bearer token and `X-Device-Id`; operator/admin cookies
are not involved. Startup checks `/api/v1/device/ping` in the background.
All network operations have a 10-second timeout and run outside the Qt UI thread.

## Operator and patient identification

Operator login still uses the existing local PIN authentication and lockouts.
After login, a separate patient PIN modal opens. Enter the four-digit cloud PIN,
including any leading zeros. Patient lookup calls `/api/v1/device/patients/lookup`.
The Treatment screen displays the confirmed patient name, external reference,
or UUID when neither name nor reference is available.

Starting a replacement PIN, opening the patient modal, canceling it, or logging
out clears the old cloud association. Start is disabled during lookup. Late
responses cannot replace a newer patient or alter an active session. The patient
identity and original plan are copied into the session at dispatch.

Manual treatment remains available through **Continue without cloud patient**.
The screen and start confirmation explicitly show that no cloud patient is
linked. Existing operator, calibration, connection and start-confirmation checks
still apply. Unlinked sessions are never attributed to a previous patient or
uploaded as patient records.

## Supported cloud settings

| Field | Device range and increment |
|---|---|
| `protocol_number` | 1–4 |
| `duration_min` | 5–30 minutes, step 1 |
| `max_pressure_lb` | 10–80 lb, step 1 |
| `max_left_deg`, `max_right_deg` | 0–20 degrees, step 1; positive magnitudes |
| `pulse_rate_hz` | 0–5 pulses per second, step 0.2 |

The API's historical `pulse_rate_hz` name is retained; values mean **pulses per
second**, matching the `/sec` control. Zero disables pulsing. No unit conversion
is performed. Decimal strings are accepted. All settings and the patient UUID
are validated before changing any control. Unsupported, missing, nonfinite or
off-increment values reject the entire response instead of being clamped or
rounded. In particular, 2.5 pulses/sec is rejected; 2.4 and 2.6 are supported.

A `409 settings_not_supported` response tells staff to correct the saved values
in the cloud dashboard. Unknown/inactive patients, revoked credentials and rate
limits have separate messages. Lookup retries honor the server's delay.

The selected protocol updates the checked picker, title and controller value.
The normal start path still reads controls to synchronize the worker's pulse
enable/rate. Motor speed controls remain local; they are not part of this cloud
contract. Requested pulse cadence is not evidence of delivered cadence when
the firmware falls back to legacy pulse on/off commands.

## Session records and offline uploads

Every dispatched session gets its own UUID, patient association, protocol,
original planned duration and UTC start time. Active elapsed time uses a
monotonic clock and excludes pauses, including a session stopped while paused.
Start/end timestamps remain wall-clock UTC timestamps. A failed dispatch does
not create a session record.

One guarded finalizer captures ending control values before cleanup changes
them. Normal completion is `completed`; operator STOP/RESET is `stopped`;
physical/banner emergency stop, command faults and unrequested worker failure
are `fault`. A repeated or late worker signal cannot create a second record or
finish/reset a newer session. Firmware version remains null when unknown.

The outbox persists the exact body before posting to `/api/v1/device/treatments`.
It uses an atomic replace and filesystem flushes at `data/pending_uploads.json`
(override with `KNEESPA_PENDING_UPLOADS_PATH`). A background executor performs
disk and network work after stop commands have been issued. Normal application
exit lets submitted background writes finish; abrupt power loss before a
submitted write reaches disk cannot be recovered from the queue.
Shutdown stops further upload attempts after the current bounded request;
pending bodies remain available on the next launch.

Each queue entry contains `record` plus optional retry/error metadata. Old queues
containing raw record dictionaries are read without changing their IDs or bodies.
Unreadable queue files are preserved under `.corrupt-<id>` for support. Keep
these files protected with the same local access controls as patient records.

An entry is removed only on HTTP 200/201 with a valid receipt for that record's
UUID. Temporary errors back off automatically; retries run every five seconds
when due, and `Retry-After` delays survive restarts. Authentication, validation
and record-conflict failures remain saved and appear under the Patient panel.
After addressing the cause, use **Retry uploads** to retry those blocked entries
with their original UUID and body. This button also honors rate-limit delays.

The server appends treatment/settings history; an older delayed upload does not
replace a newer effective admin update. Records describe settings and session
outcomes, not continuous telemetry or measured delivery of a prescribed pulse rate.

## Verification

```text
python -m pytest
```

Focused checks cover the cloud client/contract, session capture and the real
window wiring with mocked hardware/network boundaries. They use synthetic IDs,
PINs and responses; they do not modify clinic data. Full Pi/Arduino verification
and an end-to-end test against an isolated cloud instance are still required
before relying on a deployed device's patient history. Provision a dedicated test
device and test patient; do not assume that a seeded PIN or token exists.
