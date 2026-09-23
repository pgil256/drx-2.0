# KneeSpa DRx GUI — visual audit and polish plan (2026-09-21)

Scope: every screen, modal and dialog in `runtime/raspberry-pi/main/ui/`, rendered
offscreen at the device resolution (1366×768) with
`development/tools/screen_gallery.py` plus four extra states (PIN-mode login,
idle warning/fault banner, native alert boxes). Code audited at commit `54346b8`
on `branch/ui-device-simulator-updates`. The backend, controllers and safety
paths are out of scope; everything below is view-layer only.

Verdict: the bones are good (real design tokens, a small component library, a
consistent 108px rail + 84px top bar, IBM Plex, ≥48px touch targets almost
everywhere). What makes it look unfinished is a handful of *systemic* choices
that repeat on every page: a flat type scale, heavy 2px outlines on every
secondary control, scrambled colour semantics (Stop is blue, Start is black),
three different tab styles, and stock Qt widgets (combos, tables, scrollbars,
dialogs) leaking through untouched. Fix those once in the theme and most pages
improve without being redesigned. Then four pages need real touch-ups: Home,
Setup, Device, and the dialog/banner family.

Regenerate the screenshots referenced below with:

```bash
QT_QPA_PLATFORM=offscreen python development/tools/screen_gallery.py --outdir .cache/gallery
```

---

## 1. Systemic issues (fix once, improves everything)

### 1.1 Colour no longer means anything
* `app.qss` styles `variant="danger"` **identically to `primary`** (blue) — see the
  comment "The legacy danger variant also uses blue" in
  [app.qss](../../../runtime/raspberry-pi/main/ui/theme/app.qss). Result: Stop
  (Treatment, Setup, editor, pressure notice), Log Out, Shut Down and "Restore
  This Calibration" all render as the primary call-to-action, while START, Save
  defaults, Restart App and "Observed pass" are black (`dark`).
* On the Treatment page that inverts every industrial convention: black START,
  blue Stop. The `--green-500` / `--red-500` tokens exist and are unused by any
  button.
* Casing is mixed inside the same row: `START` / `PAUSE` / `Stop`.

Recommendation: START/RESUME = `success`, STOP = `danger` mapped to `--red-600`
with white text, PAUSE = `secondary`. Add a `destructive` variant (white fill,
`--red-400` border + text) for Log Out / Shut Down / Restore / Exit so red fill
is reserved for stopping motion. Keep `dark` only for the rail/top bar. If the
owner prefers no red outside the physical e-stop, the fallback is START green +
STOP `--ink-900` black, but never blue.

### 1.2 Flat type scale
[tokens.py](../../../runtime/raspberry-pi/main/ui/theme/tokens.py) sets
`--text-2xs`, `--text-xs` and `--text-sm` all to **16px**, base 18, md 20. Captions,
helper copy, body and labels differ only by weight and grey, and almost every
button/label is weight 700/600. Everything shouts at the same volume, which is
why Device and Profile read as walls of text.

Recommendation: 2xs 13 / xs 14 / sm 16 / base 18 / md 20 / lg 24 / xl 30 /
2xl 40 / 3xl 56, with a rule that anything the operator reads at arm's length
stays ≥16px (readouts, labels, buttons) and only captions/eyebrows/units go
below. Default button weight 600, semibold labels 600, bold 700 reserved for
page titles and readouts. Remove raw `sans_font(size=16)` literals
(setup.py, treatment.py, support.py, treatment_editor.py, patient_*.py) in
favour of tokens.

### 1.3 Heavy outlines everywhere
`QPushButton` default and `secondary` use a **2px `#78858e` border + bold text**.
Setup shows 55 of these boxes at once; Device/Support tab rows and every
dialog footer repeat it. Recommendation: secondary = 1px `--gray-400` border,
white fill, weight 600; the 2px treatment only for the *checked* state of tab
buttons and for focus. Jog clusters become one segmented group (see §3.2).

### 1.4 Three tab styles for one pattern
* Support / Troubleshooting topics: filled primary when active, outline otherwise
  ([help.py:153](../../../runtime/raspberry-pi/main/ui/screens/help.py),
  [support.py:156](../../../runtime/raspberry-pi/main/ui/screens/support.py)).
* Device: fixed **black / white / blue** fills for Overview / Settings / Service
  with a 3px cyan ring on the checked one
  ([device.py:44](../../../runtime/raspberry-pi/main/ui/screens/device.py),
  `sectionTab` rule in app.qss). It reads as three unrelated buttons; "Service"
  is always blue whether or not it is selected.
* Calibration dialog uses a stock `QTabWidget`.

Recommendation: one `DSSegmentedTabs` widget (48–56px tall, white group with 1px
border, active segment filled primary) used by Support, Troubleshooting, Device
and the calibration tabs.

### 1.5 Stock Qt widgets leak through
No global rules exist for: `QComboBox` (Fusion gradient + tiny arrow on Device
Settings/Service, Wi-Fi, time zone, staff login, patient editor, video output),
`QTableWidget` (Service history and calibration tables: bright Fusion selection,
grid lines, bold header, empty trailing row), `QCheckBox` in the hardware wizard,
`QDoubleSpinBox`, `QListWidget` (wizard step list, video list), `QTabWidget`.
Each dialog patches its own copy inline
([hardware_service_dialog.py:93](../../../runtime/raspberry-pi/main/ui/modals/hardware_service_dialog.py),
[video_modal.py:591](../../../runtime/raspberry-pi/main/ui/modals/video_modal.py)).
The global scrollbar is a 48px gutter with a dark pill; the video list overrides
it to a **blue** 48px thumb that looks like a button.

Recommendation: add app.qss sections for all of the above (combo with a drawn
chevron and 48px popup rows; table with tinted header strip, no grid, row hover,
`--blue-100` selection, hidden empty rows; 14px scrollbar thumb inside a 48px
transparent hit area) and delete the per-dialog overrides.

### 1.6 Token drift
81 hard-coded hex colours outside tokens.py (43 in video_modal.py, 7 top_bar.py,
6 nav_rail_button.py, 5 hardware_service_dialog.py) and raw px sizes.
[treatment_status_panel.py](../../../runtime/raspberry-pi/main/ui/widgets/treatment_status_panel.py)
has its own `rgb()` palette and 22/26/30px sizes. Add the missing tokens
(`--surface-chrome-hover`, `--overlay-scrim`, `--banner-warning`,
`--banner-fault`, `--table-selection`) and sweep to `resolve()`.

### 1.7 Focus rings fire on touch
`QPushButton:focus { border: 3px solid ink-900 }` stays lit after every tap
(visible on "Done" in the editor, "STOP" in the wizard, "Back to settings" in the
review). On a touch kiosk show focus only for keyboard navigation: give
`DSButton` `Qt.TabFocus` and style `:focus` only when a `keyboardFocus` property is
set by an app-level event filter.

### 1.8 Glyph substitutes
`« ‹ › » ↺ × ←` come from Plex and read as punctuation, not controls
([icons.py:25](../../../runtime/raspberry-pi/main/ui/theme/icons.py)). The
banner's dismiss `×` renders as a tiny tick (28-setup-warning-banner.png).
`icons.py` already draws play/pause/nav icons with QPainter — add chevron,
double-chevron, rotate, close and backspace icons the same way and use them in
the jog buttons, steppers, keypad and banner.

---

## 2. Chrome

* **Rail**: items use `fill_height`, so five pages + Video stretch to ~114px each
  and the rail reads as a stack of dark slabs; "Treatment" at 19px bold runs
  edge to edge ([nav_rail_button.py:28](../../../runtime/raspberry-pi/main/ui/widgets/ds/nav_rail_button.py)).
  Fix: fixed 88px items, top-aligned, 17px weight 600 labels, a hairline above
  Video (it is a launcher, not a page), Device pinned to the bottom.
* **Colour**: chrome is `#1e1e1e`; the brand slate `--surface-dark` (#172f42) is a
  token and already used by the video header. Using it for rail + top bar ties
  the chrome to the blue palette instead of looking like a dark-mode leftover.
* **Top bar**: "Device · Ready" is plain white text
  ([top_bar.py:69](../../../runtime/raspberry-pi/main/ui/chrome/top_bar.py)).
  Make it a status pill with a dot (green Ready, blue Preparing, amber
  Stopping/Resetting, red Recovery/Offline) — cheapest high-value change in the
  app. The avatar's black 2px ring is invisible on the black bar; use a cyan ring
  when logged in and a plain white disc when logged out. Wordmark 34px bold is
  heavier than the 60px mark next to it; 28px semibold.

## 3. Screens

### 3.1 Home (01, 03) — biggest aesthetic problem
A 1080×540 marketing raster ("rapid, reliable, KNEE PAIN, relief™ … .com") on
pure white, plus a lone Login button; logged in it is only the logo
([home.py:30](../../../runtime/raspberry-pi/main/ui/screens/home.py)). It looks
like a website splash, not a device home, and gives a logged-in clinician nothing
to do.

Recommendation (still flat and compact, no hero imagery): `--surface-page` wash;
knee mark + wordmark at 48px top-left of the content; a device status card
(status pill, controller/cloud/last sync lines, calibration state); three
launch tiles (Set up patient → Setup, Start treatment → Treatment, Watch videos)
at ~200px tall; a "last treatment" line. Logged out: same layout with tiles
dimmed and a single prominent "Sign in" tile. Keep the full kneespa.com logo
only on the video poster and the login card.

### 3.2 Setup (04)
Five rows × 12 controls. Per row: name/range, four jog boxes, reset, −, a 210px
slider, +, an unlabelled mono target, a captioned mono measured value, Go, Stop.
Problems: the target has no caption while "Measured" does, so `2 in` / `1.2 in`
look like a typo; the slider covers 8 steps in 210px so the thumb jumps and the
−/+ already cover it (owner prefers steppers); per-row "Stop" text buttons
compete with the global STOP; the action row gives the rare "Save treatment
defaults" black hero weight and Stop blue.

Recommendation per row: `Name / range` │ jog segmented group (« ‹ › » drawn
chevrons, one rounded container) │ reset icon │ target stepper `− 2.0 in +` with
a "Target" caption │ "Measured 1.2 in" │ **Go** │ quiet square stop icon. Under
the controls, a thin non-interactive track (min…max) with a target ring and a
measured fill replaces the slider as a position indicator. Action row:
`[Reset and home]  [Save defaults]  …  [STOP]` with STOP red and wider.

### 3.3 Treatment (05–20) — structure is owner-approved, needs polish
* Run controls: apply §1.1 (START green / PAUSE outline / STOP red, all
  uppercase, icons 22px) — [treatment.py:430](../../../runtime/raspberry-pi/main/ui/screens/treatment.py).
* Layout jitter between states: the readiness line appears/disappears (numbers
  move 15px) [treatment.py:507](../../../runtime/raspberry-pi/main/ui/screens/treatment.py);
  readouts shrink 56→30px on outcome [treatment.py:551](../../../runtime/raspberry-pi/main/ui/screens/treatment.py);
  "Prepare next treatment" is injected into the limit/angle row
  [treatment.py:425](../../../runtime/raspberry-pi/main/ui/screens/treatment.py).
  Fix: reserve the helper line's height, keep one readout size, move "Prepare
  next treatment" into the action row (it takes START's slot while an outcome is
  showing), put the outcome text next to the phase badge.
* Monitor composition: two big numbers float in a large empty band with the
  limit/angle stats far below. Compose as two columns — pressure with "limit 40
  lbs" directly beneath, time with the phase beneath — then the progress bar.
* Settings strip: a 3×2 grid whose mono values right-align per column, so
  `12 min / 40 lbs / 2/sec` sit at different x and a lone "Motor speed" wraps
  under an empty row when angles are hidden (05-treatment.png)
  [treatment.py:273](../../../runtime/raspberry-pi/main/ui/screens/treatment.py).
  Use one row of equal-width `label-over-value` chips (the "Limits" tile pattern
  from Support), hiding angle chips per protocol without retaining space.
* Patient strip: "Upload failed · record retained for retry" is muted grey —
  give failures amber text and show the existing "Upload issue" button.
* Protocol tiles: 1px border when unselected (2px slate is heavy); fine
  otherwise.
* Editor dialog (05b): opens as a native window (frame on the Pi, no scrim).
  Make it an in-shell overlay sheet; add range hints ("5–30 min") under labels.
* Review dialog (12): native window, no title bar styling; migrate to the
  DSDialog base (§4).

### 3.4 Support (07, 07b, 08, 08b, 24) — the best page today
Nits only: three stacked rows of buttons (tabs, topics, accordion) before content
— shrink topic chips to 44px `sm`; accordion `+`/`×` indicators become drawn
chevrons; number circles 48px radius 12 fine. Keep the Limits tiles pattern and
reuse it on Treatment.

### 3.5 Device (08c, 08c1, 08c2)
* Overview: three centred stacked power buttons with Shut Down as primary blue.
  Use a left-aligned horizontal row; Shut Down / Restart Device `destructive`.
  "Connections and records" is five loose `Label: value` strings spread over
  70px gaps because the card stretches
  ([device.py:87](../../../runtime/raspberry-pi/main/ui/screens/device.py)).
* Settings: stock combos; two separate "Save …" buttons for timeouts — apply on
  change with a transient "Saved" note; the scroll viewport has no top padding so
  cards clip under the tab row (08c1-device-settings-bottom.png); the naked
  "Device settings are ready." label at the bottom
  ([device.py:60](../../../runtime/raspberry-pi/main/ui/screens/device.py)).
* Service: stock history table; the backups card vertically centres a short body
  leaving a blank top half; "Lock Service" is a ghost link among buttons.

Recommendation: a `DSKeyValueList` (muted label left, strong value right,
40px rows, optional status dot/badge) for Overview, Profile, Review and the
network/clock cards; card action rows left-aligned in a footer; table theme from
§1.5; top-align card bodies; status label becomes a slim status strip; Lock
Service becomes a lock icon on the Service tab.

### 3.6 Profile (25)
An 88px black user glyph, three text-list cards, and Restart App (black) / Exit
App (outline) / Log Out (blue). Log Out should not be the blue CTA and Exit App
on a kiosk deserves `destructive` styling (or admin-only). Restart App
duplicates Device → Overview. Use the key/value list; avatar as a 64px tinted
circle.

### 3.7 Video (09)
Good: dark slate header, list rows, transport bar. Fix the blue 48px scrollbar
thumb (global style), keep the no-shadow rule on the card (VLC repaint issue),
and give the amber "unavailable" note the badge tones.

## 4. Modals, dialogs, banners

Three overlay styles (Login/AddPin: floating × on a shadowed card; Video: dark
header with pill buttons; Patient PIN: no header, no close, 16px radius) plus
fourteen `QDialog` subclasses that open as separate top-level windows (editor,
review, pressure notice, text keyboard, staff login, patient editor/portal/
reconcile, Wi-Fi, time zone, calibration restore, report viewer, service PIN,
hardware wizard, upload error, release install). On the kiosk they show a
window-manager frame or none, with no scrim, and look like a different app.

* Build `DSDialog` (title strip with close, body, footer action row, 12px
  radius, `--shadow-lg`) with an `Overlay`-hosted variant, and migrate the
  dialogs to it. Keep `QMessageBox` for the two-button confirms but extend
  `DialogTheme` to add the same title strip.
* Keypad: disabled keys and the *enabled* muted keys (Clear/←) share the same
  grey fill, so a pending patient lookup looks broken
  ([keypad.py:108](../../../runtime/raspberry-pi/main/ui/widgets/ds/keypad.py)).
  Disabled → 40% opacity text on the same fill; muted → white fill, muted text;
  show a small spinner next to "Looking up patient…" instead of greying the pad.
* Login (02, 26, 27): the QR pane is a 320px blank when no request is active;
  show a placeholder frame with the instruction inside it. "Get a new QR code" /
  "Use local staff PIN" are plain `QPushButton`s
  ([login_modal.py:109](../../../runtime/raspberry-pi/main/ui/modals/login_modal.py))
  — make the switch a `ghost` DSButton so one action is primary.
* Banner: `TreatmentStatusPanel` covers the top bar (hides brand + status), shows
  "-- lbs" on non-pressure warnings, and its dismiss glyph is broken. Replace
  with a `DSBanner` docked *below* the top bar, tokens for warning/fault, drawn
  close icon, pressure readout only when relevant. The banner stays suppressed
  during runs (owner decision 2026-09-10).
* Safety alerts (`_show_safety_alert`, `_show_timed_error` in kneespa.py) are
  stock message boxes. Route them through a `DSAlertDialog` overlay (red or amber
  title strip, large Acknowledge button, non-modal as today).
* Dead code: `ui/modals/calibration_dialog.py` and
  `controllers/calibration_controller.py` are not referenced by kneespa.py or any
  live controller (the hardware wizard's `mode="calibration"` replaced them).
  Delete with their tests.

## 5. General UX advice for this device

1. One visual grammar for actions: green = go, red = stop motion, outlined red =
   destructive, blue = navigate/confirm, outline = secondary. Never two of these
   in one button row.
2. Sentence case for every label except the three run controls.
3. Status as pills with dots, not free text, everywhere a state is shown (top
   bar, Treatment badge, Device connections, patient strip).
4. Reserve space for text that appears and disappears; the operator watches the
   Treatment page for 12 minutes and every 15px shift is noticed.
5. Keep touch targets ≥48px and give every tappable element a visible pressed
   state (buttons have one; `ClickableLabel` logo/wordmark rely on
   `press_feedback`).
6. Nothing native: no stock combos, tables, scrollbars or framed dialogs on the
   kiosk.
7. Do not reintroduce what the owner rejected: no modal sheets for Patient /
   Settings / Live Status on Treatment, no Treatment Monitor hero or knee
   imagery, no drag-only controls, no graphics effects on the video card, no top
   banner during runs.

---

## 6. Plan

Branch from `54346b8` as `feat/gui-polish`. Each phase ships independently,
lands with an updated gallery render and green tests, and can be reviewed from
the PNGs alone. Rough effort in focused days.

| Phase | Work | Effort |
|---|---|---|
| 0 | **Decisions (owner)** — colour semantics (§1.1), Home purpose (§3.1), Setup per-row stop + indicator track (§3.2), dialogs as overlays (§4) | 0.5 |
| 1 | **Theme foundation** — type scale, secondary/danger/destructive/success variants, segmented tabs, global QSS for combo/table/checkbox/spinbox/list/scrollbar/tabs, keyboard-only focus, drawn control icons, token sweep (video_modal, top_bar, nav rail, status panel), casing audit | 1.5 |
| 2 | **Chrome + Home** — rail sizing/colour, status pill, avatar ring, new Home view wired to existing `navigate`/`show_video`/gating | 1 |
| 3 | **Treatment** — run-control colours, stable layout, two-column monitor, settings chips, upload tone, editor/review as overlay dialogs | 1 |
| 4 | **Setup** — segmented jog group, captioned target stepper, indicator track, quiet row stops, action-row hierarchy | 1 |
| 5 | **Device / Profile / Support** — key/value list, power row, table theme, top-aligned cards, apply-on-change timeouts, status strip, Profile actions, Support nits | 1.5 |
| 6 | **Dialogs, banners, alerts** — DSDialog base + migration, keypad states, login placeholder, DSBanner, DSAlertDialog, delete dead calibration dialog | 1.5 |
| 7 | **Verification** — before/after gallery diff, touch-target lint (walk the tree, flag interactive widgets <48px), on-Pi check of Plex rendering at 14–16px, VLC modal regression, full test run | 0.5 |

Order: 0 → 1 → 2, then 3 / 4 / 5 in any order, then 6 → 7. Phases 3–5 only
touch view files and existing signal surfaces; no controller or safety code
changes are needed.

### Verification hooks to add in Phase 1
* Extend `screen_gallery.py` with the four extra states rendered for this audit
  (PIN-mode login, warning and fault banners, alert box) and a `--baseline DIR`
  option that writes side-by-side before/after sheets.
* `tests/unit/test_theme_tokens.py`: assert the type scale is strictly
  increasing and that `danger` resolves to a red token.
* `tests/integration/test_screens.py`: assert no interactive widget in the
  shell is smaller than 48×48 and that the Treatment readouts keep one font
  size across `set_outcome` / `clear_outcome`.

---

## 7. Implementation status (2026-09-23, branch `feat/gui-polish`)

Phases 1–6 are implemented as one commit each; Phase 7's automated checks
landed with them. Regenerate before/after sheets with:

```bash
QT_QPA_PLATFORM=offscreen python development/tools/screen_gallery.py \
    --outdir .cache/gallery --baseline .cache/gallery-before
```

Phase 0 decisions were taken as the recommendations above (no owner input
was available): START green / STOP red / destructive red outline; Home as a
device home; Setup keeps a quiet per-row stop and gains the indicator track;
every `QDialog` becomes a frameless in-shell sheet.

Deviations from the recommendations, and why:

* **Control outline colour.** Secondary buttons use a 1px border, but keep
  `#78858e` rather than `--gray-400`: `test_gui_ux` enforces a 3:1 contrast
  floor for control edges, which `--gray-400` (1.7:1) fails.
* **Destructive text** is `--red-500`, not `--red-400` (3.8:1 fails AA for
  18px semibold text); the border stays `--red-400`.
* **Rail labels** use `--text-sm` (16px) semibold rather than a 17px literal,
  and the wordmark uses `--text-xl` (30px) rather than 28px, to stay on the
  type scale.
* **Topic chips** stay 48px tall (the plan's 44px would fail the new
  touch-target lint); `sm` only shrinks the label and group padding.
* **Dialogs as overlays.** `DSDialog` stays a real `QDialog` (so `exec_()`,
  `open()`, modality, `QMessageBox` confirms and the QObject tree are
  unchanged) but is frameless, masked to rounded corners and paired with an
  in-host backdrop widget that paints the scrim and shadow — child-widget
  translucency needs no compositor on the Pi. `QMessageBox` / `QInputDialog` /
  `QProgressDialog` keep working (tests monkeypatch them) and get the same
  frameless title strip from `DialogTheme`.
* **Non-modal notices** (pressure notice, upload error, safety alert) dock
  under the top bar instead of centring, so they never cover the pressure
  readout or STOP.
* **Login card** drops the duplicate logo/wordmark (the brand sits in the
  top bar behind the scrim) to fit the title strip and QR placeholder in
  768px; the full kneespa.com logo is not used anywhere now.
* **"Prepare next treatment"** replaces START while an outcome is showing,
  as recommended; this means starting again after a completed/stopped run
  always goes through the prepare step.

Not done / needs hardware:

* On-Pi check of IBM Plex rendering at 13–16px, window masks and dialog
  stacking under the kiosk window manager, and the VLC modal regression —
  offscreen renders on Windows and Linux (WSL) only.
* `development/tools/e2e_touchscreen.py` drives the screen by pixel
  coordinates that were already stale before this work (e.g. `nav_video`
  hits Device); re-map them against the new layout before the next
  on-device e2e run.

## 8. Owner review changes (2026-09-23)

The owner reviewed the polished GUI and asked for five changes. Four of them
reverse earlier decisions in this plan (§3.1, §3.2, §4 and the video block
during treatment), so they supersede those sections:

1. **Sign-in opens on the staff PIN keypad.** "Sign in with a QR code" is the
   footer option (with "Use staff PIN" to switch back). The controller asks for
   a phone code only when that option is tapped. Flows that re-authenticate an
   existing phone session (a patient changing, an expired phone session,
   rejected staff API session) call `show_login(phone=True)` and still open
   straight to the QR code, since patients have no staff PIN.
2. **Setup has no −/+ target steppers** (they duplicated the jog arrows). The
   read-only indicator track became a full-width, 44px touch slider with a
   36px thumb: tap anywhere or drag to set the target (arrow keys step it).
   The track still fills to the measured position, and nothing moves until
   Go. **Horizontal is never commanded above 0°:**
   `HORIZONTAL_COMMAND_LIMITS = (-25, 0)` drives the Setup range, the Support
   limits and the host clamps in `kneespa.py` (Go and jog). Calibration and
   measured readouts keep the full −25…+5° travel (`ACTUATORS["HORIZONTAL"]
   ["LIMITS"]`). The firmware clamp is still the raw 0–4500 encoder envelope.
   A firmware ceiling at the 0° mark (`BZERO`) would need reflashing and a
   bench check.
3. **Treatment settings card** has a "Treatment settings" label and 72px
   chips and Edit treatment button. The monitor gives up the space: its
   readiness line moved into the header row (monitor ≈280px, was ≈318px at
   1366×768).
4. **Videos are available during treatment.** The player shows a treatment
   strip under its title bar: phase, time left, pressure, "Treatment" (back
   to the monitor) and a red STOP wired to `treatment.estop_requested`. The
   stage gives up the strip's height, so the card size is unchanged. Starting
   a treatment keeps an open video. Stopping, a fault or the treatment ending
   closes it. Videos stay blocked only while the protocol is `stopping`
   (`set_video_guard`). DSDialog alerts are separate top-level windows, so they
   still stack above the embedded VLC surface.
5. **Home uses the full kneespa.com logo as its backdrop**, like a desktop
   wallpaper: large, centred between the greeting and a bottom dock, at 50%
   opacity. The launch tiles (now 112px, icon beside text) and a slim device
   status bar sit in the dock on frosted `--surface-frost` surfaces.
