# KneeSpa DRx — PyQt5 GUI Modernization Plan

**Date:** 2026-06-25
**Target design:** `claude-design.zip` (root) → `KneeSpa DRx — Modern Control Interface`
**Design system:** `_ds/kneespa-drx-design-system-3c820074…` (tokens + 10 components + `bundle.jsx` + per-screen screenshots)
**Scope:** Reconfigure the device touchscreen UI to match the modern design **without touching the working hardware/backend layer.**
**Status (2026-06-26):** Verified against the codebase by a 5-agent audit; corrections are folded into the body below and logged in §14.

---

## 1. Executive summary

The design is **not a reskin** — it changes the information architecture and the component vocabulary. The good news: the design system was authored *from this exact repo* (`kneespa.ui`, `constants.py`, `demo/`), so colors, limits, protocols, and copy already line up with our constants.

**Recommended approach: rebuild the *view layer* in code (central QSS theme + a small custom-widget library + per-screen modules), keeping the backend as-is apart from five small, deliberate extensions for the design's new features (§9 / §15).** The monolithic `kneespa.ui` (absolute geometry + ~650 lines of scattered inline stylesheet + orphaned dialogs + reused object names) is a poor base for a token/component-driven design; Qt Designer cannot express most of the new components (custom slider tracks, gauges, dark-header cards, nav rail, keypad). The backend (`Arduino` threading, `Protocols`/`ResetWorker`, GPIO, safety monitoring, CSV/auth, calibration math) is cleanly separable and stays as-is — the **only** deliberate backend/firmware changes are the five scoped feature extensions in §15.

The work is ~5 phases: **(0)** theme foundation → **(1)** component library → **(2)** screens + chrome + modals → **(3)** controller rewire → **(4)** dialog disposition → **(5)** hardware verification.

---

## 2. The target design (what we're building toward)

A fixed **1366×768** clinician touchscreen. Persistent **dark top bar** (96px: knee logo + "Knee**Spa** DRx" wordmark + login/profile avatar) and a **120px left nav rail** (Home · Setup · Protocols · Help · Support · Video). Content area is white with `#f8f9fa` page wash and white **cards** (many with a dark header bar). One brand cyan `#29abe2`, interactive blue `#3498db`, traffic-light status colors, IBM Plex Sans (UI) + IBM Plex Mono (all numeric readouts).

| Screen | Purpose | Layout |
|---|---|---|
| **Home** | Splash | Full logo centered; Login button (logged out) |
| **Setup** | Manual actuator control | Left: "Manual Actuator Control" card with 5 rows (Axial, Lateral, Horizontal, Leg Length, Pressure) each = jog `◀◀ ◀ ▶ ▶▶ ⟲` + slider + Go/Stop; bottom action buttons. Right: "Live Position" + "Safety Limits" cards |
| **Protocols** (Treatment) | Run a treatment | Left: "Treatment Monitor" card (knee viz, protocol title/desc, 4-step stepper, progress bar+timer, START/PAUSE/EMERGENCY STOP). Right: Protocol picker (4 tiles), Settings (4 sliders), Live Status (3 stat readouts) |
| **Help** | Protocol reference | "Preset Protocols" 2×2 grid + "Treatment Controls" + "Safety" cards |
| **Support** | Troubleshooting | Accordion of failure→fix items + "Contact Support" (phone, Request Assistance, Submit Ticket) |
| **Login modal** | PIN entry | Centered white card, 4-dot keypad (1–9, Clear, 0, ⌫) |
| **Video modal** | Demo video | 16:9 player with transport bar |

Screenshots for every screen are in the export under `screenshots/`.

---

## 3. Source-of-truth assets (already on disk)

- **Design tokens:** `_ds/.../tokens/{colors,typography,spacing,effects,fonts}.css`
- **Component reference:** `app/bundle.jsx` (canonical layout/behavior), `_ds/.../_ds_bundle.js` (component API)
- **Art (reuse our existing copies in `main/ui/media/images/`):** `logos/knee.png`, `logos/kneespa-logo-full.png`, `buttons/user-profile.png`, `buttons/play-button.png`, `graphics/1–4.png`. **No new art needed** except the IBM Plex font files (see §10).

---

## 4. Recommended architecture

```
main/ui/
  theme/
    tokens.py          # TOKENS dict: raw + semantic colors, type scale, spacing, radii (from _ds tokens)
    qss.py             # qss(template, TOKENS) helper — resolves var(--x) (Qt QSS has no var())
    app.qss            # global stylesheet template (top bar, rail, cards, base controls)
    fonts/             # IBM Plex Sans/Mono .ttf (bundled for offline Pi) → QFontDatabase.addApplicationFont
  widgets/ds/          # custom component library (see §6)
    button.py badge.py card.py slider.py protocol_button.py
    stat_readout.py gauge.py toggle.py nav_rail_button.py keypad.py
  screens/             # one module per screen, built in code
    home.py setup.py treatment.py help.py support.py
  chrome/
    top_bar.py nav_rail.py
  modals/
    login_modal.py video_modal.py
  kneespa.py           # controller — backend untouched; view construction swapped
```

**Theming:** after `app.setStyle("Fusion")` in `main()`, call `app.setStyleSheet(qss(app_qss, TOKENS))`. Components carry **dynamic properties** (`variant`, `tone`, `size`, `active`) switched at runtime via `setProperty` + `style().polish()`. Box-shadows → `QGraphicsDropShadowEffect` (QSS has no `box-shadow`). **No component needs a custom `paintEvent` for fidelity** — `app/bundle.jsx` never renders Gauge (the only arc-paint component) or Toggle; everything used is QSS + standard widgets.

**Why code, not Qt Designer:** the design is token+component-driven; the current `.ui` mixes **fixed top-level geometry** (with hard `maximumSize` locks — `MainWindow` 1366×768, `stackedWidget` 1246×648 — that fight responsive layouts) with nested inner layouts, and embeds a **~650-line top-level stylesheet** (~733 lines of inline CSS total across 13 blocks). Genuine drift vs the new tokens: `rgb(0,57,138)` (the old primary blue, ×9) and **Arial** (47 `<family>` tags); other literals to migrate include `#3498db`/`#bdc3c7` (×15 each), `#34495e`, `#2c3e50`. (`#e74c3c` is **not** drift — it survives as `--red-400`; the plan's earlier `#27ae60` example doesn't occur in the file.) A code rebuild gives a single source of truth and reusable components, and lets us delete the orphaned dialogs.

**Alternatives considered:** *(b)* in-place restyle of `kneespa.ui` — lower fidelity, can't render the new components, keeps the fragile object-name coupling; *(c)* full rewrite incl. backend — unnecessary risk, the backend is solid. → Recommend (a).

---

## 5. Backend preservation contract (must not break)

These are UI-independent and stay verbatim: `helpers/arduino.py` (`Arduino` on its own `QThread` via `moveToThread`; **12 signals** — `connection_ready/finished/progress/done_emit/ready_to_go_emit/position_emit/pressure_emit/status_emit/buffer_warning/connection_lost/connection_failed/display_weight_emit`, where `finished`/`connection_ready` are load-bearing for the thread wiring), `helpers/protocols.py` (`Protocols` QRunnable), `helpers/reset_worker.py`, `helpers/csv.py`, `helpers/secure_auth.py`, `config/config.py` (calibration `a/b/c_factor`, `calibration`, `CMarks`/`AMarks`/`BMarks`), GPIO setup, the safety monitor in `status_emit()`, calibration math (`set_to_distance`, `set_to_c_distance`, `read_position`), and the Arduino command vocabulary (top-level: `T Q S P Y X G I K A L* J/JS H(F1/F0)` — there is **no** top-level `R`; `R` is only an `F` sub-direction). Firmware additionally enforces its **own** safety clamps (pressure 0–80 lb, per-actuator position limits, >80 lb cutoff) independent of the UI — the rebuild cannot weaken these.

**Tight UI↔backend couplings to refactor behind a clean seam** (today they're load-bearing and fragile):

1. **Start/Stop text state machine** — `start_or_stop_protocol` branches on `start_button.text() == "Start"`. Replace with an explicit `self.protocol_running` flag + a `set_run_state(running)` that updates the new button's appearance.
2. **`BUTTON_STYLES[START/STOP]`** applied in lockstep with text in ~8 places → fold into `set_run_state`.
3. **Label-text-as-data** — `handle_assistance_request` *reads* `username/email/status` QLabels as the data source. Replace with reading `self.current_user` directly.
4. **`actuator_controls` enable/disable group** — the hard-coded list disabled while the MCU is busy. New controls must register into the same gating set (keep the list, point it at the new widgets).
5. **`findChild(objectName)` everywhere** — the new code-built widgets are referenced directly (attributes), removing the string lookups.
6. **Slider sign/scale conventions** — `max_left → -abs`, `max_right → +abs`, axial slider `value = inches×2`, lateral/horizontal gated to multiples of 5, `CMarks` keyed by `"{:.1f}"` degree strings — preserve exactly in the new sliders' change handlers. (Handlers read `self.config.CMarks`; `self.CMarks` built in `__init__` is dead/duplicate state — drop it.)
7. **`I2Cstatus` + `I2Cstatus_event`** — `ResetWorker` signals DONE through these on the controller; both must stay on the controller object. `config.calibration` (default 1.0) feeds the reset `L0` command.
8. **GUI-thread `time.sleep()`** — reset / `ensure_arduino_connection` / `start_protocol` / `status_emit` call `sleep()` on the GUI thread, blocking the event loop; replace with timers / off-thread waits during the rewire.
9. **Asymmetric control-gating & hardcoded ids** — several jog paths (`move_actuator` axial/horizontal, `forward_fast_button_clicked`) call `disable_actuator_controls()` without a paired re-enable, relying on the async `done_emit → enable` path; `move_actuator` also hardcodes the axial id as `A12`. Keep these flows intact (or fix deliberately) when rewiring.

---

## 6. Component mapping (DS → PyQt5)

| Component | Qt base | Technique |
|---|---|---|
| **Button** (primary/success/danger/secondary/ghost × sm/md/lg) | `QPushButton` | QSS via `[variant=…][size=…]` + `:hover/:pressed/:disabled`; shadow via effect |
| **Badge** (neutral/info/success/danger/warning/cyan, `dot`) | `QLabel` | QSS pill; dot = leading "●" or tiny child |
| **Card** (`title` dark header, `headerRight`, `padded`) | `QFrame`+VBox | QSS bg/radius; child dark header `QWidget`; `WA_StyledBackground`; shadow effect |
| **Slider** (label · track · mono value) | `QSlider` | QSS `::groove/::handle/::sub-page/::add-page` (sub/add page = the two-tone fill) |
| **ProtocolButton** (number over name, selected) | `QPushButton` checkable | QSS `:checked/:hover:!checked`; `QButtonGroup` exclusive; two `QLabel`s for two-line content |
| **StatReadout** (big mono value+unit, caption) | `QWidget`+VBox | QSS/`QFont`; unit via rich text span; uppercase caption in Python |
| **Gauge** (arc, tone, center text) | `QWidget` | **DEFERRED — imported but never rendered in `app/bundle.jsx`.** If later needed: custom `paintEvent` (`QPainter.drawArc`, 1/16°, start 90°, span −360·pct, round cap) |
| **Toggle** (square checkbox + check) | `QCheckBox` | **DEFERRED — imported but never rendered in `app/bundle.jsx`** (Pulse is a Slider now). If needed: QSS `::indicator` 26×26 radius4, `:checked` fill + check image |
| **NavRailButton** (icon over label, active) | `QToolButton` `TextUnderIcon` checkable | QSS base/`:hover`/`:checked` (black bg, cyan text, 4px left border) |
| **Keypad** (dots + 3×4 grid) | `QWidget` | title `QLabel` + dots HBox + `QGridLayout` of 12 buttons; emits `valueChanged(str)`/`submitted(str)` |

**Only 8 of the 10 components are required** (Button, Badge, Card, Slider, ProtocolButton, StatReadout, NavRailButton, Keypad); **Gauge + Toggle are imported-but-unused** in the target build and are deferred. `Slider` is a **controlled** widget (`value` is required, paired with `onChange`); `Keypad` also exposes an `onSubmit` the reference app leaves unwired (login fires on a length-4 effect). Full per-component prop/state spec lives in the analysis notes; tokens come straight from `_ds/.../tokens/*.css`.

---

## 7. Screen-by-screen migration

### 7.1 Chrome (replaces `frameTop` + side `frame`)
- **TopBar** ← `top_nav_logo`, `top_nav_brand_label`, `profile_button`, `username_nav`. Logo/wordmark → Home. Avatar = login launcher (logged out) / identity + logout menu (logged in).
- **NavRail** ← `setup_button`, `protocols_button`, `help_button`, `login_button`, `video_player_button`. Items: Home/Setup/Protocols/Help/Support/Video. Keep **login gating** (Setup/Protocols require `current_user`). Replaces both the top tabs and the `QStackedWidget` nav — a `QStackedWidget` can remain as the page container, just driven by the rail.

### 7.2 Home (page 0)
Direct: full logo centered + Login button. Trivial.

### 7.3 Setup (page 1) — biggest restructure
Current = 4 tabs (`setup_tabs`: Axial / Lateral / **Flexion** / Leg Length). New = **one card, 5 rows** + Live Position + Safety Limits.

| New row | Current source (actuator) | Jog handlers (reuse) |
|---|---|---|
| Axial | `Axial` tab (actuator_a) | forward/reverse[/fast]_axial_flexion, reset, go/stop |
| Lateral | `Lateral` tab (actuator_c) | …lateral_flexion… |
| **Horizontal** | **`Flexion` tab** (actuator_b) | …horizontal_flexion… |
| Leg Length | `Leg Length` tab (GPIO extra) | forward/reverse[/fast]_extra, reset_extra |
| Pressure | pressure controls *inside Axial tab* | axial_flexion_pressure go/stop |

- "Live Position" card ← the readout labels (`*_position_label`), now `StatReadout`/`PosRow`.
- "Safety Limits" card ← static, from `constants.py` (Pressure 80, Axial 0–4, Lateral ±20, Horizontal −25…+5).
- **Deltas:** design gives **Leg Length a slider 12–24 in** (current is jog-only, 0–6 in) and adds **"Mark As Default"/"Mark Zero Position"** buttons (no current handler — see §9). Keep our ranges from constants, not the mock's.

### 7.4 Protocols / Treatment (page 2)
- **Protocol picker:** 4 `ProtocolButton`s replace `protocol_number_field` (a `QLineEdit`) + image carousel (`forward/backward_button_protocol_image`, `label_protocol_image`). The carousel arrows — and `profile_button` — are **`QLabel`s driven by `mousePressEvent`**, not real buttons, so they're reimplemented as proper controls. Selected number feeds `start_protocol`'s validation in place of the line-edit text.
- **Settings sliders:** Max Pressure ← `max_pressure_edit`; Max Angle L ← `max_left_edit`; Max Angle R ← `max_right_edit`; **Pulse Rate ← NEW** (replaces the `checkbox_use_pulse` boolean — see §9).
- **Treatment Monitor:** knee viz (`knee.png`, glow while running), protocol title/desc, **4-step stepper** + progress bar + `MM:SS`, and **START / PAUSE / EMERGENCY STOP**. Current has only Start/Stop — **Pause is new** (§9).
- **Live Status card:** Time Left / Pressure / Lateral Angle as `StatReadout`s — **inline, replacing the `Show Timer`/`Show Pressure` checkboxes + overlay dialogs** (§9, §10). Subscribe these to the **`Protocols` worker signals** (`signals.pressure_emit` / `signals.status_emit`) during a run — that's the live telemetry path (fed from `Arduino.status_emit`), not `Arduino.pressure_emit` directly.

### 7.5 Help (page 3)
Replace the single `help_text_edit` blob with the structured "Preset Protocols" 2×2 + "Treatment Controls" + "Safety" cards (content already written in `bundle.jsx`).

### 7.6 Support (NEW — absorbs old Profile actions)
Troubleshooting accordion (`FailureItem`) + "Contact Support": phone `1-833-KNEE-SPA`, **Request Assistance** → existing `email_admin()`, **Submit Ticket** → new (§9). The old **Profile page is removed**; identity/logout move to the top-bar avatar.

---

## 8. Dialog disposition

| Current | Action |
|---|---|
| `login.ui` + `init_login_dialog` | **Replace** with in-app `LoginModal` (DS `Keypad`). Keep real auth (`SecureAuthHelper` + CSV). Fixes the missing-`0` keypad bug. |
| `video-player.ui` + `VideoPlayer` (VLC) | **Keep**, restyle to the Video modal frame. |
| `TimerDialog`, `PressureDialog` overlays | **Retire** in favor of the inline Live Status card (or keep as optional overlays — see §10). |
| `LoadingSpinner` | **Keep** (works with any view). |
| `login-help.ui` | **Drop** (no equivalent; PIN modal is self-explanatory). |
| `enter-patient.ui`, `enter-patient-help.ui`, `enter-tolerance.ui` | **Delete** — already orphaned/unwired (and `show_tolerance_dialog` is referenced but undefined). |

---

## 9. Feature deltas the design introduces (DECIDED 2026-06-26 — build all five; detail in §15)

The design shows five capabilities the current app/firmware lack. **All five are in scope**; the concrete change-points live in §15:

1. **Pause / Resume** treatment — **BUILD IT.** `Protocols` has no `pause()/resume()` (`stop()` is a destructive e-stop), so add real worker pause: an `is_paused` flag honored in the protocol loops that **holds** pressure/position without sending `X`. (§15.1)
2. **Editable Pulse Rate (0–5/sec)** — **MAKE THE 200 ms CONFIGURABLE.** Firmware `jerkInterval` is a hardcoded `const` 200 ms; make it mutable and parse a numeric arg on `J` (e.g. `J120`); the worker maps the slider → interval. Bare `J` stays 200 ms (back-compat). (§15.2)
3. **Lateral-angle live readout** — **APPROXIMATE FROM CURRENT LOGIC.** `status_emit` carries raw `pos_c` (encoder int); compute an approximate angle UI-side by inverse-interpolating `pos_c` over `config.CMarks` (the existing degree→position map, run backwards). No firmware/worker change. (§15.3)
4. **"Mark as Default" (Setup)** — **PERSIST CURRENT SETTINGS AS PROTOCOL DEFAULTS.** Mark saves the current Setup values (e.g. 50 lbs max, 20° left, 20° right — clamped to constants) to `kneespa.cfg`; the Protocols-page Settings sliders load these as their defaults on entry. (§15.4)
5. **Submit Support Ticket** — **SMTP TO DRXCODE + PER-DEVICE ID.** Clicking a troubleshooting issue (or "Submit a Ticket") emails the `drxcode` address via the existing SMTP path, with a unique per-KneeSpa device id and the selected issue. (§15.5)

---

## 10. Cross-cutting decisions

- **Fonts (offline):** the device is an offline Pi; Google Fonts won't load. **Bundle IBM Plex Sans + Mono `.ttf`** and load via `QFontDatabase.addApplicationFont` (recommended), *or* keep Arial/Segoe (lower fidelity).
- **Telemetry surface:** adopt the always-on **inline Live Status card** (recommended) vs keep the floating Timer/Pressure overlays.
- **Tweak-panel options** (`accent`, `chrome`, `density`, `frame`) are design-tool only — bake the defaults: accent `#29abe2`, **dark chrome**, comfortable density. The **device bezel is mockup chrome** — the real app runs fullscreen frameless (`showFullScreen` + `FramelessWindowHint`), so ignore the bezel.

---

## 11. Pre-existing bugs to fix during the rebuild

- Login keypad has **no `0` key** while code loops `range(10)` → PINs with `0` are unenterable. (Fixed by new Keypad.)
- `set_up_tolerance_button` is a **`QLabel`** wired with `.clicked.connect(self.show_tolerance_dialog)` — **doubly broken**: `QLabel` has no `clicked` signal *and* `show_tolerance_dialog` is never defined. (Control removed.)
- `lateral_flexion_position_stop_button` sends `X<actuator_a>` (axial) instead of `actuator_c` (`kneespa.py:1181`) — the **lateral** stop halts the wrong actuator. (The `axial_flexion_pressure_stop → actuator_a` is **correct** — pressure rides the axial channel.) Fixed in the new go/stop wiring.
- Pressure label format inconsistency (`"0 lbs"` on setup reset vs `"0 lb"`/`"N lb"` everywhere else); `reset_flexion_button_clicked` also writes raw unit-less numbers to position labels. (Standardize all readouts — `lbs`, `in`, `°`.)

---

## 12. Phased roadmap

| Phase | Deliverable | Verify |
|---|---|---|
| **0 — Foundation** | `theme/tokens.py`, `qss.py`, `app.qss`, bundled Plex fonts; app stylesheet applied after Fusion | App launches, fonts load, base controls themed |
| **1 — Components** | `widgets/ds/*` (10 components) + a small gallery harness | Each renders per screenshots; states switch |
| **2 — Screens & chrome** | TopBar, NavRail, 5 screens, Login & Video modals (wired to stubs) | Visual match to `screenshots/`; navigation works |
| **3 — Controller rewire** | Swap view construction in `kneespa.py`; introduce `set_run_state`/run-state model (incl. `paused`); repoint `actuator_controls`; preserve slider sign/scale & `CMarks` | Protocol start/stop, actuator jog/go/stop, reset, e-stop, login gating all function in `--debug` |
| **3.5 — Backend/firmware ext.** | The five §15 extensions: worker Pause/Resume; editable Pulse Rate (firmware `jerkInterval` arg → flash + native tests); `pos_c→angle` approximation; config protocol-defaults + persisted device id; `submit_ticket` | Pause holds safely (no `X`); pulse rate changes interval on-device; angle tracks `pos_c`; Mark-as-Default persists; ticket email arrives with device id |
| **4 — Dialogs** | Inline Live Status; restyle Video; delete orphaned `.ui`s; wire the §15 extensions into the screens | No dead UI paths; telemetry updates live |
| **5 — Hardware verify** | On-Pi run: fullscreen, touch targets ≥44px, Arduino/GPIO/safety unaffected | Full treatment on device; safety limits trigger |

Each phase is independently runnable in `--debug` (windowed) before Pi testing.

---

## 13. Risks

- **Touch ergonomics** — keep DS touch sizes (44/56/72px); the Pi screen is the real test.
- **QSS gaps** — no `box-shadow`/`transform`/`text-transform`/`var()`; handled via effects, Python uppercasing, and the `qss()` substitution helper.
- **Backend regressions** — the start/stop-text and label-as-data couplings are the most error-prone; the §5 seam + `--debug` testing mitigate.
- **Feature-delta scope creep** — Pause / Pulse Rate / Mark-Zero / Ticket may pull in firmware/worker work; lock scope in §12 before Phase 4.

---

## 14. Verification log (2026-06-26)

A 5-agent audit fact-checked this plan against the code and the design export. **The architecture, screen IA, dialog disposition, phasing, and the §9 feature-deltas all hold.** Corrections are folded into the body above; the highlights, with evidence:

**Confirmed exactly:** 5-page `stackedWidget`; `setup_tabs` (Axial/Lateral/Flexion/Leg Length) + `DRx_tabs`; the ~650-line top-level stylesheet; the **missing-`0` login keypad bug** (`login.ui` has `pushButton_1..9` only; `kneespa.py:888` loops `range(10)`, so `pushButton_0` is never found/wired — PINs with `0` are unenterable); `show_tolerance_dialog` connected (`kneespa.py:603`) but never defined; orphaned `enter-patient*.ui` + `enter-tolerance.ui`; `Arduino` moveToThread; `Protocols` QRunnable with `use_pulse` **boolean** + `run_pressure_sequence`; `config` `a/b/c_factor` + `CMarks/AMarks/BMarks`; **all 10 DS component APIs** (§6); the design's `Keypad` **has** a `0` key (so the modern login fixes the bug).

**Corrected:**
- **Color drift** — real drift is `rgb(0,57,138)` (old primary blue, ×9) and **Arial** (47 `<family>` tags). `#27ae60` does not occur; `#e74c3c` is **not** drift (kept as `--red-400`). Also migrate `#3498db`/`#bdc3c7` (×15 each), `#34495e`, `#2c3e50`.
- **Wrong-actuator stop** — only the **lateral** position-stop is wrong (`kneespa.py:1181` passes `actuator_a` not `actuator_c`); the pressure-stop→`actuator_a` is correct.
- **Gauge & Toggle are unused** in `app/bundle.jsx` (imported, never rendered) → **no custom `paintEvent` needed**; both deferred. Treatment Live Status = 3 `StatReadout`s; Pulse Rate = a `Slider`.
- **Arduino has 12 signals**, not 7 (added `connection_ready/finished/progress/pressure_emit/display_weight_emit`; `finished`/`connection_ready` are load-bearing for the thread wiring).
- **Command vocabulary** — no top-level `R` (only an `F` sub-direction); real set is `T Q S P Y X G I K A L* J/JS H(F1/F0)`.
- **Exact objectNames** — pages `page_home/page_setup/page_main/help_page/profile_page` (note the prefix/suffix inconsistency); setup tab pages `Axial/Lateral/Flexion/Leg_Length`; `DRx_tabs` is effectively single-page (`preset_protocols_tab`, `tabBarAutoHide`); `MainWindow`/`stackedWidget` carry hard `maximumSize` locks (1366×768 / 1246×648) to remove.

**New couplings/bugs folded into §5/§11 (fix during Phase 3/4):** GUI-thread `time.sleep()` calls block the event loop; `ResetWorker` DONE rides `main_window.I2Cstatus` + `I2Cstatus_event`; `config.calibration` feeds the reset `L0`; `self.CMarks` (`__init__`) is dead/duplicate; `move_actuator` hardcodes `A12` and some jog paths disable controls without a paired re-enable; `set_up_tolerance_button` is a `QLabel` (no `clicked` signal); firmware enforces its **own** safety clamps (pressure 0–80 lb, per-actuator limits, >80 lb cutoff) the UI rebuild must not weaken.

---

## 15. Backend & firmware extensions (decided 2026-06-26)

The five §9 deltas are deliberate, **bounded** exceptions to the "backend untouched" rule (§1/§5); the rest of the preservation contract still holds. Concrete change-points, grounded in the code:

### 15.1 Pause / Resume (worker)
- `helpers/protocols.py`: add `self.is_paused = False`, `pause()` / `resume()` methods, and a `_wait_while_paused()` (sleep-poll on `is_paused and is_running`) called at the existing `if not self.is_running` checkpoints (protocols.py:172/192/208/238/291/307 and the pulse loop at 410). Pause must **hold** — do **not** send `X` (that's `stop()`, which is a destructive e-stop): freeze the phase clock (`elapsed_time`/`check_duration`) and stop issuing new pressure/position commands until resumed.
- `kneespa.py`: the PAUSE button calls `worker.pause()/resume()`; extend the `set_run_state` model (§5.1) with a third `paused` state. START/RESUME disabled while running-not-paused; PAUSE disabled while idle — matches the `bundle.jsx` button-enable logic (L324-326).

### 15.2 Editable Pulse Rate (firmware + worker)
- `motor/motor.ino`: change `const unsigned long jerkInterval = 200;` (L109) → mutable `unsigned long jerkInterval = 200;`. In `case 'J'` (L658-685) the handler already extracts `parameter = cmd.substring(1)`; when `parameter` is non-empty and not `"S"`, set `jerkInterval = parameter.toInt()` (clamped to a sane range) before starting the jerk. Bare `J` keeps 200 ms; `JS` unchanged. Update the native tests in `main/motor/test/test_command_parse/`.
- `helpers/protocols.py`: replace the bare `self.arduino.send("J")` (L402) with `send(f"J{interval_ms}")`. Extend `Protocols.__init__` (L42-53) with a `pulse_rate` (float /sec); map `rate→interval_ms` (`round(1000 / rate)` for `rate>0`; `rate==0` ⇒ no pulse, don't send `J`). Keep `use_pulse` as `rate>0` so the existing loop conditions (L410/470) still work.
- `kneespa.py`: the Pulse Rate slider feeds `worker.pulse_rate` live (same mid-protocol pattern as `max_pressure` at `on_pressure_changed`); a mid-run change re-issues `J{interval}`.

### 15.3 Lateral-angle live readout (UI-side approximation)
- `kneespa.py`: in the `status_emit`→update handler, convert `pos_c`→approx degrees by **inverse-interpolating** over `config.CMarks` (which maps `"{deg}" → position`): find the two marks bracketing `pos_c` and linearly interpolate the degrees (a `pos_c_to_angle()` helper — the backward of `set_to_c_distance`'s forward interpolation). Feed the Live-Status "Lateral Angle" `StatReadout`. No worker/firmware change. Note `config.CMarks` keys are degree strings (e.g. `"-20.0"`), values are encoder positions (`_set_default_c_marks`, config.py:185-192).

### 15.4 Mark-as-Default → protocol defaults (config persistence)
- `config/config.py`: add a `[ProtocolDefaults]` section (cleaner than overloading `Options`) — keys `max_pressure`, `max_left`, `max_right`, `pulse_rate`. `Configuration` already has `update_config()` (L159-183) which writes the cfg and `_ensure_config_sections()`; mirror the `Options` load pattern (L92-123) to read them back with safe defaults.
- `kneespa.py`: Setup's **Mark as Default** reads the current Setup values, **clamps to constants** (`PRESSURE_MAX=80`, lateral `±20`, etc. — ⚠️ the user's "25° right" example exceeds the ±20 lateral limit, so clamp), writes them onto `config`, and calls `config.update_config()`. The Treatment Settings sliders initialize from these persisted defaults on entry (fallback to today's 50/10/10/2 if unset).

### 15.5 Submit ticket → SMTP to drxcode + device id
- **Device id (net-new — none exists today):** add a persisted unique id — a new `config` option (e.g. `[Device] id`) generated once if absent (`uuid4().hex`, or derive from the Pi `/proc/cpuinfo` Serial / NIC MAC for stability across reinstalls), saved via `update_config()`.
- **Recipient:** add `TICKET_EMAIL` to `EMAIL_CONFIG` (`constants.py:179-185`) — the `drxcode` address, from env `KNEESPA_TICKET_EMAIL`.
- **Send:** add `submit_ticket(issue_text)` in `kneespa.py` modeled on `email_admin()` (kneespa.py:928 — reuse `SMTP_SSL` + `MIMEText`): subject `[KneeSpa {device_id}] Support ticket`, body = issue + device id + current user/status. The Support screen wires each troubleshooting `FailureItem` ("user clicks issue") **and** the **Submit a Ticket** button to it; **Request Assistance** keeps calling the existing `email_admin()`.

**Sequencing:** 15.1/15.3/15.4/15.5 are Python-only (Phase 3.5, testable in `--debug`). 15.2's firmware half needs an on-device flash + native-test update and should land before the Pulse Rate slider is wired live; until flashed, the worker can fall back to bare `J` (on/off).
