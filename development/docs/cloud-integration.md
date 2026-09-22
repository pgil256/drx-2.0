# KneeSpa cloud integration

The September 15, 2026 cloud handoff is implemented on top of the existing DRx
client. The handoff's older pinned DRx revision lacked this integration; the
current checkout already had its initial lookup and upload implementation.

## Provisioning

Register the device in the cloud dashboard under Devices → Register Device.
Set these environment variables on the Pi, or put them in
`devices/local/raspberry-pi/cloud.env` (process environment variables take precedence):

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

Lookup and treatment uploads use the device bearer token and `X-Device-Id`.
Patient and clinician sign-in uses phone approval through a QR code. Patient
registration opens the clinician web app. Profile edits use the approved
clinician machine session, or a separate staff login for legacy local operators.
Startup checks `/api/v1/device/ping` in the background.
All network operations have a 10-second timeout and run outside the Qt UI thread.

For desktop workflow testing, register a dedicated simulator device and use
`python development/tools/run_simulator.py --cloud`. Its credentials and durable
outbox are separate from Pi state. See the [simulator cloud setup](../simulator/README.md#connect-to-the-cloud-dashboard)
for the saved profile, launcher, and test-patient workflow. The default simulator
launcher continues using its local demo cloud.

## Operator and patient identification

The sign-in screen displays a short-lived QR code and matching display code.
Scan it, sign in on the phone (including MFA when required), choose **Patient**
or **Clinician**, and explicitly approve the matching machine. The complete
cloud `verification_url`, including its private fragment, is rendered locally.
No credentials are sent to a QR generation service.

The app creates `/api/v1/device/sign-in/requests`, polls at least every five
seconds, honors `Retry-After`, and exchanges an approval once. Denied, cancelled,
expired or consumed codes require a fresh request. Closing the overlay or choosing
local PIN cancels the abandoned request when the cloud connection allows it.
A lost exchange response is never replayed.

Patient approval loads identity and the resolved plan from
`/api/v1/device/session/patient`; no patient PIN or staff API is used. Patients
cannot open setup/service, edit patient records or change their treatment plan.
Changing patients signs out and requests another phone approval. A `409` plan
conflict blocks treatment and asks the care team to review the plan. The session
and plan are rechecked before Start; a changed plan is displayed for another
review before treatment can begin.

Clinician approval enables patient selection and the existing patient editor.
Only the role approved on the phone is granted, scoped to the registered
machine's clinic. Technician approval opens Device and cannot start treatment;
the existing service PIN remains required for service operations.

Machine calls use a separate cookie-free client with the device credentials
and `X-KneeSpa-Machine-Session`. Staff operations recheck
`/api/v1/device/session`, never `/api/v1/admin/me`, and use the same fixed clinic.
Human tokens stay in memory and are cleared on logout, user change, completion,
expiry and app exit. Logout is sent when possible. Restart begins signed out.
Idle sessions are rechecked every 15 seconds, and new privileged actions require
a fresh check. Expiry or cloud loss does not stop an existing treatment or gate
its stop, release or emergency controls. No approval is exchanged during treatment.

**Use local staff PIN** retains the existing local authentication and lockouts.
After staff login, select a patient on the Treatment screen and enter their four-digit cloud PIN,
including any leading zeros. Patient lookup calls `/api/v1/device/patients/lookup`.
The Treatment screen displays the confirmed patient name, external reference,
or UUID when neither name nor reference is available.

Starting a replacement PIN, opening the patient modal, canceling it, or logging
out clears the old cloud association. Start is disabled during lookup. Late
responses cannot replace a newer patient or alter an active session. The patient
identity and original plan are copied into the session at dispatch.

Manual treatment remains available through **Continue without patient**.
The screen and start confirmation explicitly show that no cloud patient is
linked. Existing operator, calibration, connection and start-confirmation checks
still apply. Unlinked sessions are never attributed to a previous patient or
uploaded as patient records.

## Add patients in the clinician app

**Add patient in clinician app**, above **Continue without patient**, displays a
locally generated QR code and the page address. Scan with a phone or tablet,
sign in to the web app, select this device's clinic, and create the patient and
treatment plan there. Complete any required plan approval in the web app.
Choose **Back to patient PIN** on the device and enter the new four-digit PIN,
including leading zeros. The existing device lookup validates the patient and
settings before linking them. Closing the QR dialog also returns to PIN entry;
opening it never creates or automatically selects a patient.

The default destination is `KNEESPA_CLOUD_URL` plus `/patients/new`. For the
current cloud deployment this is
`https://kneespa-cloud.onrender.com/patients/new` (verified to load the New Patient
page on September 21, 2026). To use another registration page, set the optional
`KNEESPA_PATIENT_PORTAL_URL` in `cloud.env`. Use a public HTTPS page URL without
credentials, query parameters, or fragments. No device tokens, patient data, or
local treatment settings are included in the code. The web app handles staff
authentication and registration; the device makes no registration API calls.

Install the updated runtime requirements for QR generation (`qrcode==7.4.2`).
If that dependency is unavailable or the address is too long for a legible code,
the dialog displays the address for manual entry. Missing or invalid addresses
show setup guidance. The local demo simulator has no public registration page;
use its existing demo PINs, or use cloud simulator mode for this workflow. Cloud
simulator profiles support the same optional URL override.

## Edit patients on the device

After clinician phone sign-in, **Edit patient** uses that approved machine session
and requires `patients.edit`. **Cloud sign in** changes the user by returning to
phone approval. Patient and technician sessions cannot use this editor.

For a legacy local staff PIN login, use **Cloud sign in** in the editor to enter an individual cloud staff
email/password, complete MFA if enabled (authenticator or recovery code), and
explicitly select the clinic this device is registered to. The app rechecks
`/api/v1/admin/me` and requires `patients.edit`. Local operator PINs and device
tokens do not grant staff access. Staff cookies live in memory only and are
discarded on operator login/logout and app exit. Credentials, cookies, PINs,
and patient API bodies are not logged.

**Edit patient** on the treatment screen loads the cloud profile and its version.
Names save through `PATCH /api/v1/admin/patients/{id}` with `expected_version`.
Treatment settings apply to the current treatment. Clinicians can explicitly
choose **Approve as saved cloud plan**, enter a reason, and save through the plan
endpoint with `expected_current_revision_id`. Profile and plan saves are separate
operations: a partial success is reported, and stale or uncertain writes require
reload and review. Cancel leaves the active patient and settings unchanged.
Patient editing is locked during treatment, including while paused.

This follows the cloud application's `DEVICE_PATIENT_INTEGRATION.md` handoff.
No device-token patient-write endpoints or cloud schema changes are required.

## Phone sign-in deployment and verification

Deploy the cloud implementation from `PATIENT_QR_SIGN_IN.md`, including migration
`0013_patient_machine_access`, and set its `PUBLIC_BASE_URL` to the public HTTPS
origin phones can reach. The GUI needs the registered device credentials above
and `qrcode==7.4.2` from the runtime requirements; no human account credentials
are stored on the machine. Invite patient accounts from their patient record in
the cloud app before testing. The GUI does not send invitations or run migrations.

Automated coverage is in `test_machine_sign_in.py` and `test_machine_sign_in_ui.py`.
Use cloud simulator mode with a dedicated registered device for a real phone
test; the local demo simulator continues to support its local staff/patient PINs.
Before rollout, verify on the physical touchscreen: scan and matching code,
patient and clinician roles, denial/expiry, revoked access, plan review errors,
logout and completion, plus loss of cloud access during an active treatment.

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
It uses an atomic replace and filesystem flushes at
`devices/local/raspberry-pi/data/pending_uploads.json`
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
and record-conflict failures remain saved. Treatment completion automatically
starts an upload; no upload button is needed. A failure opens a nonmodal
**Treatment upload failed** window explaining whether the record is saved and
whether retry is automatic. Repeated background failures do not reopen the same
message. **Upload issue** reopens the details after dismissal; blocked failures
offer **Retry upload** after the cause is corrected, preserving the original UUID,
body, and rate-limit deadline. A successful sync clears the failure window.
Disk-save failures explicitly say the record could not be saved for retry.

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
