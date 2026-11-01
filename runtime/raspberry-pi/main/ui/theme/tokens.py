"""Design tokens for the KneeSpa DRx kiosk.

The PyQt5 app's source of truth for colors, type, spacing, radii and effects.

Since the KneeSpa Design System overhaul the palette, type scale and radii come
from the shared ``design/tokens.json`` at the repository root: ``tokens_shared.py``
(generated, never edited) holds them as ``--ks-<name>`` entries and the semantic
names below alias them with ``var(--ks-…)``. The names used across the UI code and
``app.qss`` are unchanged, so moving a colour means editing the design system and
rerunning ``python design/build_tokens.py``.

Values may reference other tokens with CSS ``var(--x)`` syntax (e.g.
``"--color-primary": "var(--blue-500)"``). Qt's QSS has no ``var()``;
``ui.theme.qss`` resolves these references both for stylesheet rendering and for
direct lookups from Python (``resolve("--color-primary") -> "#0b6bb0"``).

Pure data — this module imports nothing but the generated table, so unit tests
can use it without Qt.

Grammar kept from the original design (one meaning per colour):
  * ``brand`` cyan is identity only (logo, wordmark, the signed-in avatar ring);
    ``action`` blue is every interactive thing.
  * green = go, red fill = stop motion, red outline = destructive.
  * The chrome (top bar, rail) is light like the dashboard's navigation; the only
    dark surface is the ``readout-*`` instrument panel for live numbers.
"""

from .tokens_shared import SHARED

# Every token name keeps its leading "--" so app.qss can be a straight copy of
# the CSS and resolution is a simple substring match.
TOKENS = {
    **SHARED,

    # ── Brand ───────────────────────────────────────────────────────────
    "--brand-cyan": "var(--ks-brand)",          # logo mark + "Spa" wordmark
    "--brand-cyan-dark": "#0083b9",             # pressed brand (derived; no shared step)
    "--brand-cyan-soft": "var(--ks-brand-soft)",
    "--brand-ink": "var(--ks-ink)",             # "Knee" / "DRx" wordmark
    "--brand-alert": "var(--ks-danger)",        # "PAIN" red in tagline

    # ── Primitive palette (aliases onto the shared tokens) ──────────────
    # Hover/pressed steps the shared system does not define are derived here
    # and marked "derived"; keep them darker than the step above.
    "--blue-500": "var(--ks-action)",
    "--blue-600": "var(--ks-action-hover)",
    "--blue-700": "#064670",                    # derived: action pressed
    "--blue-100": "var(--ks-action-soft)",
    "--blue-050": "#f1f7fc",                    # derived: lighter action wash

    "--green-500": "var(--ks-ok)",              # START / positive state
    "--green-600": "#156339",                   # derived: ok hover
    "--green-700": "#104d2c",                   # derived: ok pressed
    "--green-100": "var(--ks-ok-soft)",

    "--red-500": "var(--ks-danger)",            # faults / destructive text
    "--red-600": "var(--ks-danger)",            # STOP fill (white label 5.7:1)
    "--red-700": "#a02825",                     # derived: STOP hover
    "--red-800": "#7f1f1d",                     # derived: STOP pressed
    "--red-400": "var(--ks-danger)",            # destructive outline
    "--red-200": "#f7c9c8",                     # derived: destructive pressed wash
    "--red-100": "var(--ks-danger-soft)",

    "--amber-600": "var(--ks-warn)",            # warning banner fill (white label 5.9:1)
    "--amber-500": "var(--ks-warn)",            # advisory text
    "--amber-100": "var(--ks-warn-soft)",

    # ── Neutrals ────────────────────────────────────────────────────────
    "--ink-900": "var(--ks-ink)",               # strong text
    "--ink-800": "var(--ks-ink)",               # control labels
    "--ink-700": "var(--ks-ink-2)",             # body copy
    "--ink-500": "var(--ks-ink-muted)",
    "--gray-600": "#566573",                    # disabled text: 4.5:1 on --gray-300 (test_gui_ux)
    "--gray-400": "var(--ks-line-strong)",      # quiet control borders
    "--gray-300": "var(--ks-line)",             # dividers / disabled borders
    "--gray-200": "var(--ks-neutral-soft)",     # control fill / chips
    "--gray-100": "var(--ks-surface-2)",        # zebra rows, disabled fill
    "--gray-050": "#f7f9fb",                    # derived: hover wash on white
    "--white": "#ffffff",
    "--black": "#000000",

    # ── Semantic aliases ────────────────────────────────────────────────
    # "dark" is the ink fill used by the few slate buttons; chrome is light now.
    "--color-dark": "var(--ks-ink)",
    "--color-dark-hover": "var(--ks-ink-2)",
    "--color-dark-active": "var(--ks-readout-bg)",
    "--color-primary": "var(--blue-500)",
    "--color-primary-hover": "var(--blue-600)",
    "--color-primary-active": "var(--blue-700)",
    "--color-accent": "var(--brand-cyan)",

    # Action grammar: green = go, red fill = stop motion, red outline =
    # destructive, blue = navigate/confirm, outline = secondary.
    "--color-success": "var(--green-500)",
    "--color-success-hover": "var(--green-600)",
    "--color-danger": "var(--red-600)",
    "--color-danger-hover": "var(--red-700)",
    "--color-destructive": "var(--red-500)",
    "--color-destructive-border": "var(--red-400)",
    "--color-warning": "var(--amber-500)",

    "--surface-page": "var(--ks-surface-2)",
    "--surface-card": "var(--ks-surface)",
    "--surface-sunken": "var(--ks-neutral-soft)",
    "--surface-dark": "var(--ks-readout-bg)",         # dialog title strips, video header
    # Chrome: the top bar and rail are white with a hairline, like the dashboard nav.
    "--surface-chrome": "var(--ks-surface)",
    "--surface-chrome-hover": "var(--ks-surface-2)",
    "--surface-chrome-active": "var(--ks-action-soft)",  # selected rail item
    "--surface-chrome-divider": "var(--ks-line)",
    "--text-chrome": "var(--ks-ink)",
    "--text-chrome-muted": "var(--ks-ink-muted)",
    "--text-chrome-disabled": "var(--ks-line-strong)",
    "--chrome-accent": "var(--ks-action)",            # active rail item, signed-in ring
    "--overlay-scrim": "rgba(15, 20, 28, 0.55)",
    "--on-dark-subtle": "rgba(255, 255, 255, 0.15)",   # pill buttons on a dark fill
    "--on-dark-subtle-hover": "rgba(255, 255, 255, 0.28)",
    "--surface-glass": "rgba(255, 255, 255, 0.92)",    # play disc over video
    "--surface-video": "#1b2838",
    "--surface-video-edge": "#0d141d",
    "--banner-warning": "var(--amber-600)",
    "--banner-fault": "var(--red-600)",
    "--table-selection": "var(--blue-100)",
    "--table-header": "var(--gray-050)",

    # Instrument panel: the one dark surface, shared with the dashboard's demo machine.
    "--readout-bg": "var(--ks-readout-bg)",
    "--readout-fg": "var(--ks-readout-fg)",
    "--readout-muted": "var(--ks-readout-muted)",
    "--readout-accent": "var(--ks-readout-accent)",
    "--readout-line": "var(--ks-readout-line)",
    "--readout-ok": "var(--ks-readout-ok)",
    "--readout-warn": "var(--ks-readout-warn)",
    "--readout-danger": "var(--ks-readout-danger)",

    "--text-strong": "var(--ks-ink)",
    "--text-body": "var(--ks-ink-2)",
    "--text-muted": "var(--ks-ink-muted)",
    "--text-on-dark": "var(--white)",
    "--text-on-dark-muted": "#c6d2db",
    "--text-on-dark-disabled": "#6e8494",
    "--text-on-accent": "var(--white)",

    # 1px control outline; keeps the 3:1 non-text contrast floor on white and
    # gray-200 (test_gui_ux). The shared line-strong is 2.96:1 on gray-200, so
    # this stays a shade darker.
    "--border-control": "#78858e",
    "--border-strong": "var(--border-control)",     # inputs, combos, spin boxes
    "--border-divider": "var(--gray-300)",
    "--border-focus": "var(--ks-focus)",

    # phase status colors (treatment state machine)
    "--phase-ramping": "var(--amber-500)",
    "--phase-positioning": "var(--blue-500)",
    "--phase-holding": "var(--green-500)",
    "--phase-complete": "var(--green-600)",
    "--phase-stopped": "var(--red-500)",

    # ── Typography ──────────────────────────────────────────────────────
    "--font-sans": "var(--ks-font-sans)",
    "--font-mono": "var(--ks-font-mono)",

    "--weight-regular": "400",
    "--weight-medium": "500",
    "--weight-semibold": "600",
    "--weight-bold": "700",

    # Anything read at arm's length (readouts, labels, buttons) stays >= 16px;
    # only captions, eyebrows and units go below. The named steps are the
    # design system's kiosk scale; base sits between its label and body sizes.
    "--text-2xs": "13px",                         # eyebrows, units
    "--text-xs": "14px",                          # captions and badge labels
    "--text-sm": "var(--ks-type-kiosk-label)",    # 16px secondary copy
    "--text-base": "18px",                        # body, control labels
    "--text-md": "var(--ks-type-kiosk-body)",     # 20px emphasized labels
    "--text-lg": "var(--ks-type-kiosk-button)",   # 22px section titles, big buttons
    "--text-xl": "var(--ks-type-kiosk-title)",    # 28px page titles
    "--text-2xl": "var(--ks-type-reading-lg)",    # 36px secondary readings
    # The design system's reading-xl is 64px; at 56px the pressure and time readouts
    # still fit the monitor above the limit row at 1352 × 756 (test_treatment_layout).
    "--text-3xl": "56px",                         # live readings

    "--leading-tight": "1.15",
    "--leading-snug": "1.3",
    "--leading-normal": "1.5",

    "--tracking-eyebrow": "0.06em",
    "--tracking-wide": "0.03em",
    "--tracking-tight": "-0.01em",

    # ── Spacing & sizing (4px grid; 48px min touch target) ──────────────
    "--space-0": "0",
    "--space-1": "var(--ks-space-1)",
    "--space-2": "var(--ks-space-2)",
    "--space-3": "var(--ks-space-3)",
    "--space-4": "var(--ks-space-4)",
    "--space-5": "var(--ks-space-5)",
    "--space-6": "var(--ks-space-6)",
    "--space-8": "var(--ks-space-8)",
    "--space-10": "40px",
    "--space-12": "var(--ks-space-12)",
    "--space-16": "var(--ks-space-16)",

    "--touch-min": "var(--ks-touch-min)",   # 48px minimum hit target
    "--touch-comfortable": "56px",
    "--touch-large": "72px",                # primary START/STOP, keypad keys
    "--rail-width": "108px",                # balances the 84px top bar visually

    # ── Effects: radii (square-ish; pills only for badges) ───────────────
    "--radius-xs": "var(--ks-radius-sm)",   # 4px inputs, chips, table
    "--radius-sm": "var(--ks-radius-sm)",
    "--radius-md": "var(--ks-radius-md)",   # 8px secondary buttons, cards
    "--radius-lg": "var(--ks-radius-lg)",   # 12px primary buttons, panels
    "--radius-xl": "var(--ks-radius-lg)",
    "--radius-pill": "999px",
    "--radius-circle": "50%",

    # ── Effects: elevation (soft, neutral — applied via QGraphicsDropShadowEffect) ──
    "--shadow-sm": "0 2px 4px rgba(0, 0, 0, 0.10)",
    "--shadow-md": "0 4px 12px rgba(0, 0, 0, 0.15)",
    "--shadow-lg": "0 8px 24px rgba(0, 0, 0, 0.20)",
    "--shadow-focus": "0 0 0 3px rgba(11, 107, 176, 0.35)",

    # ── Effects: borders ────────────────────────────────────────────────
    "--border-thin": "1px",      # default control outline
    "--border-thick": "2px",     # checked tabs, keyboard focus
    "--border-heavy": "3px",     # sliders, checkbox indicators

    # ── Effects: motion (applied in Python — QSS has no transition/transform) ──
    "--ease-standard": "ease",
    "--ease-out": "cubic-bezier(0.22, 1, 0.36, 1)",
    "--duration-fast": "0.15s",
    "--duration-normal": "0.3s",
    "--motion-lift": "translateY(-2px)",
    "--motion-press": "scale(0.97)",
}
