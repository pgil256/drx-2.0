"""Static screen copy, mirrored 1:1 from ``app/bundle.jsx``.

Single source for the protocol catalog, phase/step labels, and the Help/Support
reference text so Treatment, Help, and Support stay in sync. Pure data.
"""

# Treatment protocol catalog (bundle.jsx PROTOCOLS).
PROTOCOLS = [
    {"n": 1, "name": "Axial", "title": "Axial Decompression", "angle": 0,
     "desc": "Straight axial decompression — ramp to target pressure, therapeutic "
             "hold (optional pulse), then a smooth reset to zero."},
    {"n": 2, "name": "Left", "title": "Left Lateral + Axial Support", "angle": -12,
     "desc": "Adds a left-side angle under load — ramp, glide center → left angle, "
             "stability hold, smooth reset."},
    {"n": 3, "name": "Right", "title": "Right Lateral + Axial Support", "angle": 12,
     "desc": "Adds a right-side angle under load — ramp, glide center → right angle, "
             "stability hold, smooth reset."},
    {"n": 4, "name": "Oscillate", "title": "Oscillating Decompression", "angle": 0,
     "desc": "Rhythmic left↔right sweep at target pressure for dynamic mobilization."},
]

# Treatment phase -> (badge label, badge tone). (bundle.jsx PHASES)
PHASES = {
    "idle": ("Ready", "neutral"),
    "paused": ("Paused", "warning"),
    "ramping": ("Ramping pressure…", "warning"),
    "positioning": ("Positioning…", "info"),
    "holding": ("Holding…", "success"),
    "pulsing": ("Pulsing…", "success"),
    "oscillating": ("Oscillating…", "info"),
    "complete": ("Protocol Complete", "success"),
    "stopped": ("Protocol Stopped", "danger"),
}

# Treatment stepper (bundle.jsx STEPS).
STEPS = ["Ramp-Up", "Position", "Therapeutic Hold", "Smooth Reset"]

# Help → "Preset Protocols" (bundle.jsx HELP_PROTOCOLS).
HELP_PROTOCOLS = [
    {"n": 1, "title": "Axial Decompression",
     "summary": "Three strategic phases for targeted relief.",
     "phases": [
         ("Ramp-Up", "Gently build to target pressure"),
         ("Therapeutic Hold", "Sustain ideal pressure for the set time — optional rhythmic pulse available"),
         ("Smooth Reset", "Return safely to zero pressure"),
     ]},
    {"n": 2, "title": "Left Lateral + Axial Support",
     "summary": "Four dynamic phases with a left-side tilt.",
     "phases": [
         ("Ramp-Up", "Reach target pressure smoothly"),
         ("Angle Shift", "Glide center → left angle under load"),
         ("Stability Hold", "Hold pressure & angle for the set time — optional pulse for extra stimulus"),
         ("Smooth Reset", "Glide to center & release pressure"),
     ]},
    {"n": 3, "title": "Right Lateral + Axial Support",
     "summary": "Four dynamic phases with a right-side tilt.",
     "phases": [
         ("Ramp-Up", "Reach target pressure smoothly"),
         ("Angle Shift", "Glide center → right angle under load"),
         ("Stability Hold", "Hold pressure & angle for the set time — optional pulse for extra stimulus"),
         ("Smooth Reset", "Glide to center & release pressure"),
     ]},
    {"n": 4, "title": "Oscillating Decompression",
     "summary": "Rhythmic sweep for dynamic mobilization.",
     "phases": [
         ("Ramp-Up", "Reach target pressure smoothly"),
         ("Oscillate", "Sweep left ↔ right at target pressure"),
         ("Smooth Reset", "Return safely to zero pressure"),
     ]},
]

# Help → "Treatment Controls" (bundle.jsx HELP_CONTROLS).
HELP_CONTROLS = [
    ("Max Pressure", "Target decompression force applied along the axis — up to 80 lbs."),
    ("Max Angle L / R", "Lateral tilt held under load, set independently per side — up to ±20°."),
    ("Pulse Rate", "Rhythmic pulses per second during the hold (0 disables) — up to 5/sec."),
    ("Live Status", "On-screen window with the live timer, pressure, and lateral angle."),
]

# Support → troubleshooting accordion (bundle.jsx HELP_FAILURES).
HELP_FAILURES = [
    ("Device won’t start a protocol",
     "Confirm the Arduino is connected (Setup → “Arduino connected”). If not, press "
     "Reset Arduino and wait for re-initialization."),
    ("Pressure not reaching target",
     "Check the pneumatic line for kinks and verify Max Pressure is set above the "
     "minimum, then re-run after a Smooth Reset."),
    ("An actuator won’t move",
     "The actuator may be at a safety limit. Use Reset on that actuator to re-home, "
     "then retry within the allowed range."),
    ("Invalid PIN at login",
     "Re-enter the operator PIN. If it keeps failing, confirm your PIN with your "
     "system administrator."),
    ("Treatment stopped unexpectedly",
     "Emergency Stop or a safety limit likely triggered. Review the live status, "
     "clear the condition, and restart the protocol."),
]

# Safety limits, shared by Setup + Help (bundle.jsx). (label, value, unit)
SAFETY_LIMITS = [
    ("Pressure max", "80", "lbs"),
    ("Axial range", "0–4", "in"),
    ("Lateral range", "±20", "°"),
    ("Horizontal", "−25…+5", "°"),
]
