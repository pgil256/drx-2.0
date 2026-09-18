"""Design tokens for the KneeSpa DRx modern UI.

This is a 1:1 Python mirror of the design-system token files
``_ds/kneespa-drx-design-system-3c820074.../tokens/{colors,typography,spacing,effects}.css``
so the PyQt5 app has a single source of truth for colors, type, spacing, radii
and effects.

Values may reference other tokens with CSS ``var(--x)`` syntax (e.g.
``"--color-primary": "var(--blue-500)"``). Qt's QSS has no ``var()``;
``ui.theme.qss`` resolves these references both for stylesheet rendering and for
direct lookups from Python (``resolve("--color-primary") -> "#3498db"``).

Pure data — this module imports nothing, so unit tests can use it without Qt.
"""

# Every token name keeps its leading "--" so app.qss can be a straight copy of
# the CSS and resolution is a simple substring match.
TOKENS = {
    # ── Brand ───────────────────────────────────────────────────────────
    "--brand-cyan": "#29abe2",          # logo mark + "spa" wordmark, active nav
    "--brand-cyan-dark": "#1c8fc0",
    "--brand-cyan-soft": "#e8f6fc",
    "--brand-ink": "#4d4d4d",           # "knee" / "DRx" wordmark gray
    "--brand-alert": "#d83a2c",         # "PAIN" red in tagline

    # ── Primitive palette ───────────────────────────────────────────────
    "--blue-500": "#3498db",            # primary interactive (buttons, sliders)
    "--blue-600": "#2980b9",
    "--blue-700": "#2472a4",
    "--blue-100": "#e6f3ff",
    "--blue-050": "#f0f9ff",

    "--green-500": "#00c800",           # START / go / safe
    "--green-600": "#00a000",
    "--green-100": "#e4f8e4",

    "--red-500": "#c80000",             # STOP / emergency
    "--red-600": "#a00000",
    "--red-400": "#e74c3c",             # destructive secondary (exit)
    "--red-100": "#fdecea",

    "--amber-500": "#f39c12",           # ramping / caution
    "--amber-100": "#fef5e7",

    # ── Neutrals ────────────────────────────────────────────────────────
    "--ink-900": "#1e1e1e",             # nav rail, top bar, dark surfaces
    "--ink-800": "#2c3e50",
    "--ink-700": "#34495e",
    "--ink-500": "#555555",
    "--gray-600": "#666666",
    "--gray-400": "#bdc3c7",            # control borders
    "--gray-300": "#e0e0e0",            # dividers / gridlines
    "--gray-200": "#ecf0f1",            # control fill / chips
    "--gray-100": "#f7f7f7",            # zebra rows
    "--gray-050": "#f8f9fa",            # page wash
    "--white": "#ffffff",

    # ── Semantic aliases ────────────────────────────────────────────────
    "--color-primary": "var(--blue-500)",
    "--color-primary-hover": "var(--blue-600)",
    "--color-primary-active": "var(--blue-700)",
    "--color-accent": "var(--brand-cyan)",

    "--color-success": "var(--green-500)",
    "--color-success-hover": "var(--green-600)",
    "--color-danger": "var(--red-500)",
    "--color-danger-hover": "var(--red-600)",
    "--color-warning": "var(--amber-500)",

    "--surface-page": "var(--gray-050)",
    "--surface-card": "var(--white)",
    "--surface-sunken": "var(--gray-200)",
    "--surface-dark": "var(--ink-900)",

    "--text-strong": "var(--ink-900)",
    "--text-body": "var(--ink-700)",
    "--text-muted": "var(--gray-600)",
    "--text-on-dark": "var(--white)",
    "--text-on-accent": "var(--white)",

    "--border-control": "var(--gray-400)",
    "--border-divider": "var(--gray-300)",
    "--border-focus": "var(--color-primary)",

    # phase status colors (treatment state machine)
    "--phase-ramping": "var(--amber-500)",
    "--phase-positioning": "var(--blue-500)",
    "--phase-holding": "var(--green-500)",
    "--phase-complete": "var(--green-600)",
    "--phase-stopped": "var(--red-500)",

    # ── Typography ──────────────────────────────────────────────────────
    "--font-sans": "'IBM Plex Sans', 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Arial, sans-serif",
    "--font-mono": "'IBM Plex Mono', 'SF Mono', Consolas, 'Courier New', monospace",

    "--weight-regular": "400",
    "--weight-medium": "500",
    "--weight-semibold": "600",
    "--weight-bold": "700",

    "--text-2xs": "12px",   # dense table meta
    "--text-xs": "13px",    # eyebrow labels
    "--text-sm": "15px",    # secondary copy
    "--text-base": "17px",  # body, control labels
    "--text-md": "20px",    # emphasized labels
    "--text-lg": "24px",    # section titles
    "--text-xl": "30px",    # page titles
    "--text-2xl": "40px",   # hero / brand
    "--text-3xl": "56px",   # big numeric readouts

    "--leading-tight": "1.15",
    "--leading-snug": "1.3",
    "--leading-normal": "1.5",

    "--tracking-eyebrow": "0.06em",
    "--tracking-wide": "0.03em",
    "--tracking-tight": "-0.01em",

    # ── Spacing & sizing (4px grid; 44px min touch target) ──────────────
    "--space-0": "0",
    "--space-1": "4px",
    "--space-2": "8px",
    "--space-3": "12px",
    "--space-4": "16px",
    "--space-5": "20px",
    "--space-6": "24px",
    "--space-8": "32px",
    "--space-10": "40px",
    "--space-12": "48px",
    "--space-16": "64px",

    "--touch-min": "44px",          # minimum hit target
    "--touch-comfortable": "56px",
    "--touch-large": "72px",        # primary START/STOP, keypad keys
    "--rail-width": "120px",        # left nav rail on device

    # ── Effects: radii ──────────────────────────────────────────────────
    "--radius-xs": "4px",    # inputs, chips, table
    "--radius-sm": "6px",
    "--radius-md": "8px",    # secondary buttons, cards
    "--radius-lg": "12px",   # primary buttons, panels
    "--radius-xl": "16px",
    "--radius-pill": "999px",
    "--radius-circle": "50%",

    # ── Effects: elevation (soft, neutral — applied via QGraphicsDropShadowEffect) ──
    "--shadow-sm": "0 2px 4px rgba(0, 0, 0, 0.10)",
    "--shadow-md": "0 4px 12px rgba(0, 0, 0, 0.15)",
    "--shadow-lg": "0 8px 24px rgba(0, 0, 0, 0.20)",
    "--shadow-focus": "0 0 0 3px rgba(52, 152, 219, 0.35)",

    # ── Effects: borders ────────────────────────────────────────────────
    "--border-thin": "1px",
    "--border-thick": "2px",     # default control outline
    "--border-heavy": "3px",     # sliders, checkbox indicators

    # ── Effects: motion (applied in Python — QSS has no transition/transform) ──
    "--ease-standard": "ease",
    "--ease-out": "cubic-bezier(0.22, 1, 0.36, 1)",
    "--duration-fast": "0.15s",
    "--duration-normal": "0.3s",
    "--motion-lift": "translateY(-2px)",
    "--motion-press": "scale(0.97)",
}
