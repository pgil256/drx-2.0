# Device and Support pages

The rail contains Home, Setup, Treatment, Video, Support, and Device (wrench).
Device requires login. Profile shows identity, access level, available email,
current cloud clinic, login time, session duration and the automatic logout setting,
plus Log Out, Restart App, and Exit App. PIN enrollment and device information
are no longer profile actions. Session duration uses a monotonic clock.

## Device

The page has three tabs: **Overview**, **Settings**, and **Service**. Overview
contains versions, device ID, connectivity and power actions. Settings combines
network, Sync, date/time, sound, brightness, screen timeout and automatic logout.
Service contains tests, calibration, release installation, backups and history.
Settings and Service scroll vertically on the touchscreen.

- **Hardware Tests** starts supervised checks with preparation, fresh feedback,
  per-movement confirmation, stop handling, and result reporting. It has no
  calibration editing or save actions.
- **Service** requires the separate six-digit technician PIN, including for admins.
  Leaving the tab/page or changing operator locks it and clears release credentials.
  One unlock covers the current Service visit, including tests and calibration.
- **Calibration** covers actuator marks/travel factors and the load cell, with
  reviewed saving, backup, and deliberate unloaded reset afterward. See
  [hardware service](hardware-service.md) for credential provisioning and safeguards.
  Calibration omits the test result forms, leg-length tests, and bench inspections;
  connection checks and safe preparation are shared prerequisites.
- **System volume** uses the default PulseAudio output when available, with an
  ALSA Master/PCM/Speaker fallback. Applying a volume unmutes that output.
- **Brightness** uses an exposed Linux backlight. The application writes an
  already-writable brightness control or uses installed `brightnessctl` with
  its existing system permissions. The minimum selectable level is 10%.
- **Device information** shows application version, the connected controller's
  reported firmware version, and the configured cloud device ID (or the local
  persisted ID when cloud identity is absent). Disconnected or older controllers
  report that firmware information is unavailable rather than guessing a version.
- **Connections** shows Arduino connectivity, the active network and IP addresses.
  Test Connection probes public HTTPS and the authenticated cloud API separately.
  A blocked public probe is reported as a failed check, not proof that every
  network service is offline. Network/clock/local records refresh every ten seconds
  while the page is visible; internet/cloud probes require Test Connection.
- **Cloud synchronization** shows pending records, blocked records needing
  attention, and the last acknowledged upload time. Sync uses the existing
  durable outbox and still respects server retry timing. Checking status never
  quarantines or edits the queue. Unreadable or quarantined queues display unknown
  counts and ask for support; they do not silently display zero pending records.
- **Set Up Wi-Fi** scans nearby networks, offers masked touchscreen password entry,
  and joins personal/open networks. It supports installed NetworkManager (`nmcli`)
  or the older Pi `wpa_supplicant` service (`wpa_cli`). Passwords are passed on stdin,
  never in process arguments, logs, or diagnostic exports. The system network
  manager retains credentials to reconnect. Enterprise/WEP networks require
  separate provisioning. A failed wpa_supplicant attempt removes the new network
  and reselects the previous connection when one existed. Save permission failures
  are reported instead of promising persistence.
- **Test Sound** plays a short tone using the current default output and volume.
- **Idle screen dimming** offers Never, 1, 2, 5, 10, 15, and 30 minutes. The app dims
  a controllable backlight to 10% only while idle, with no service/reset/movement
  or modal interaction. The first touch/key wakes without activating a control.
  Treatment/service activity and app shutdown restore the selected brightness.
  This preference persists in device storage. OS screen locking and display power
  management remain independent; configure the appliance desktop to keep treatment
  controls visible. Displays without a backlight interface cannot use app dimming.
- **Service history** shows dated reports, operator, observations, and calibration
  saves/restores. Incomplete and skipped checks never appear as completed passes;
  bench failures remain visible even if calibration was saved. View Selected Report
  opens the full local record. These observations do not certify the device.
- **Automatic logout** offers Never, 1, 5, 10, 15, 30 and 60 minutes. It measures
  user inactivity separately from brightness restoration. Treatment, motion, reset,
  service workers and patient lookups defer logout and start a fresh idle interval
  on completion. Expiry clears the operator and service session and dismisses drafts.
- **Export Diagnostics** creates a ZIP with device/version/connection metadata and
  up to 200 categorized recent warnings/errors. It includes timestamps and fixed
  categories only, never raw error text, patient records, PINs, tokens, or passwords.
  The operator can copy the ZIP to USB or another chosen location. Nothing is sent
  automatically. Full service reports stay local and are not bundled.
- **Calibration backups** preserve calibration separately from credentials and
  other settings. Restore requires technician authentication even for an admin,
  validates the device ID and calibration values, presents the complete backup for
  review, saves the current values first, and writes the replacement atomically.
  It leaves unrelated configuration intact and puts the device in recovery until
  an explicit unloaded reset. Verify calibration afterward before treatment.
- **Date and time** shows local time, time zone, automatic-time state, and actual
  synchronization state. Operators with access can select an installed time zone
  and enable automatic synchronization; enabling NTP is not reported as already
  synchronized.
- **Power** offers Restart App, Restart Device, and Shut Down. Actions require
  administrator or technician access, an idle device, and confirmation. Profile's
  Restart App follows the same checks. OS power actions run only after the app's
  serial safety cleanup, workers, and cloud outbox close have finished.

Wi-Fi changes, calibration backup/restore, clock changes, and power operations
check the current user and idle state immediately before executing, including
after any review dialog or worker queue delay. Protected workers block treatment,
manual movement, reset, and calibration entry until completion. Calibration itself
requires the separate service PIN when entering Service.

Device data lives under the selected `devices/local/raspberry-pi/` state directory:
`device-settings.json`, `calibration-backups/`, `service-reports/`, and `exports/`.
The outbox's adjacent `sync-status.json` records only the last successful upload
timestamp. Routine software sync never replaces these files.

System operations run in a worker with command timeouts and read back the
actual setting. The app never requests sudo. Unsupported OS/display/audio
configurations leave the relevant slider disabled with an explanation and a
Refresh action. HDMI displays without a Linux backlight interface require their
physical brightness controls. Real Pi validation is required for the installed
audio route, backlight driver, Wi-Fi provider, clock/power permissions, and
unloaded calibration recovery. NetworkManager/wpa_supplicant, timedatectl, and
systemctl must already be provisioned with the appliance account's required
permissions; unavailable operations report a failure. No packages, privilege
rules, or OS permissions are installed or broadened by the app. Settings apply to the current
OS session; persistence across reboot depends on the OS configuration.

## Support

Four tabs provide Protocols, Controls (including safety and recovery),
Troubleshooting, and Contact Support. Opening a troubleshooting answer supplies
related-issue context and can prefill an empty ticket summary. Twenty issues cover
treatment, connection/sync, access, screen/sound, and updates/service.

Contact Support requires a name, valid reply email, summary, and description
(up to 4,000 characters). Tapping a field opens an on-screen keyboard with email
punctuation and multiline description entry; physical keyboard input also works.
Requests include a generated request reference,
timestamp, operator, device ID, software/firmware versions, connection state,
and device state. Patient records, credentials, and logs are not attached.

Delivery uses the existing `EMAIL_CONFIG` SMTP-over-SSL configuration and ticket
recipient. Reply-To is the supplied contact email. Submission is asynchronous;
the form locks during sending and displays confirmed delivery or a retryable
failure. Failed requests retain their contents and reference while the app
remains open. Success clears the issue fields and displays the request reference.
Changing operator clears the form. Drafts are in memory and do not survive app
restart. The reference identifies the outgoing request; this is email delivery,
not an integration that creates or tracks a remote help-desk ticket number.

Verification uses mocked SMTP; it does not send real support messages.
Network, clock, power, and calibration failure tests likewise use isolated device
files and mocked OS boundaries; they do not change the development computer's
network, clock, or power state.

## Cloud software and firmware releases

Service > Check Latest Releases uses the existing `KNEESPA_CLOUD_URL` origin.
The implemented cloud contract requires a **cloud staff account**, optional MFA,
and explicit clinic selection with `devices.view`. Local PINs and device bearer
credentials cannot authenticate this API. Session cookies are memory-only and
separate from the patient editor; they are discarded when Service locks.

The app calls `/api/v1/admin/releases`, uses its `latest` entries (newest upload,
not greatest version), and downloads the reviewed UUID from the same origin's
`/api/v1/admin/releases/{id}/download`. Redirects and foreign origins are rejected.
Downloads are capped at 256 MiB and five minutes, with per-read timeouts; size,
checksum header, and actual SHA-256 must match the selected metadata. Partial
files are deleted. A prepared download is explicitly distinguished from installation.

Flash Software / Flash Firmware reviews the version, notes and target, downloads,
validates and stages under device `updates/`, then asks to install on an unloaded
device with stable power. Only the production `kneespa.py` entry point on Linux
allows flashing. Before installation the app stops control workers, drains and
closes serial, stops cloud work, and releases GPIO. Installation runs in a progress
window after shutdown and asks **Restart App now?** on completion or failure.
No real flash or cloud publication is performed by the test suite.

Software ZIPs contain `runtime/raspberry-pi/`, `raspberry-pi/`, or its direct
contents (`main/` and `launch.sh`). They must contain the complete application.
Traversal, links, duplicate paths, device-state files and oversized expansions are
rejected. Python syntax is checked against the installed interpreter. The current
software is copied into the preparation folder before a same-filesystem rename
activates the new tree. Handled activation failures restore the old tree. Device
state, credentials, calibration, logs and uploads remain outside the replacement.
Dependencies must already be provisioned; installation does not install Python
packages or change OS permissions. Version metadata alone does not establish
compatibility with the installed OS or dependencies.

Firmware targets the repository's **Arduino Mega 2560**, through a selected
`/dev/ttyACM*` or `/dev/ttyUSB*` port, never the GPIO UART. HEX/BIN images must fit
the application region without the bootloader. HEX records and checksums are
validated. Firmware ZIPs use the `arduino/motor/` layout (optionally under
`runtime/`) or direct `motor/`; INO downloads use the locally provisioned
`hx711_sampler.h`. Source packages compile with a fixed Mega PlatformIO configuration,
ignoring uploaded PlatformIO configuration and rejecting executable build hooks.
PlatformIO, atmelavr dependencies and avrdude must be provisioned and the appliance
account must have USB access. Source builds may retrieve PlatformIO dependencies
if they are not cached; production appliances should pre-provision them.

avrdude reads a backup before writing and verifying; signature and verify checks
are never bypassed. A persistent `updates/firmware-recovery.json` record suppresses
automatic movement on restart. An interrupted/failed flash requires a successful
reflash before reset. A verified flash requires an explicit unloaded reset before
treatment is enabled. Validate the device physically before returning it to use.

`updates/installed.json` records the release UUID, version, checksum, installation
time and backup path after success. Preparation folders retain backups and build/
flash logs for service recovery. A power loss during the two software renames can
require manual restoration of `previous-software/` into `runtime/raspberry-pi/`
with the app stopped. The app does not claim power-loss atomicity or automatically
roll back a release that installs successfully but fails during its later startup.
Review and prune old update folders during maintenance after validating recovery.

The handoff document describes the current cloud implementation, which must be
deployed to the configured host. Live staff authentication, release compatibility,
USB flashing and post-flash reset still require testing on the provisioned Pi.
