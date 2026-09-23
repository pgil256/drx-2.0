"""Operator copy and the protocol catalog shared by the modern screens.

Single source for the protocol catalog, phase/step labels, and the Help/Support
reference text so Treatment, Help, and Support stay in sync. Pure data.
"""

from main.config.constants import ACTUATORS, HORIZONTAL_COMMAND_LIMITS, PRESSURE_MAX

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
    "idle": ("Not started", "neutral"),
    "starting": ("Preparing", "info"),
    "stopping": ("Stopping / recovering", "warning"),
    "fault": ("Recovery required", "danger"),
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
     "summary": "Axial pressure with an optional pulse.",
     "phases": [
         ("Ramp-Up", "Gently build to target pressure"),
         ("Therapeutic Hold", "Hold for the set time, with optional pulse"),
         ("Smooth Reset", "Return safely to zero pressure"),
     ]},
    {"n": 2, "title": "Left Lateral + Axial Support",
     "summary": "Axial pressure with a left-side angle.",
     "phases": [
         ("Ramp-Up", "Reach target pressure smoothly"),
         ("Angle Shift", "Glide center → left angle under load"),
         ("Stability Hold", "Hold pressure and angle, with optional pulse"),
         ("Smooth Reset", "Glide to center & release pressure"),
     ]},
    {"n": 3, "title": "Right Lateral + Axial Support",
     "summary": "Axial pressure with a right-side angle.",
     "phases": [
         ("Ramp-Up", "Reach target pressure smoothly"),
         ("Angle Shift", "Glide center → right angle under load"),
         ("Stability Hold", "Hold pressure and angle, with optional pulse"),
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
    ("Current settings", "Review the selected protocol and settings before starting treatment."),
    ("Edit treatment", "Open the popup to change settings. During treatment, protocol, duration "
     "and motor speed stay locked."),
    ("Pause / resume", "Pauses the protocol and countdown. Pause does not mean pressure has been released."),
    ("Stop + reset", "Stops now, then performs the existing release and homing recovery. Watch device status."),
    ("Measurements", "Selected limits are separate from sensor readings. A dash means a reading is unavailable."),
]

# Support → troubleshooting accordion (bundle.jsx HELP_FAILURES).
HELP_FAILURES = [
    ("Device won’t start a protocol",
     "Read the device status at the top of the screen. Wait for preparation or recovery to "
     "finish. Calibration required needs technician service. A connection alone does not "
     "mean the device is ready to start."),
    ("Pressure not reaching target",
     "Compare measured pressure with the selected limit and read any device notice. "
     "A dash or stale reading is not zero pressure. The pressure notice's Stop action "
     "does not automatically home the device. Contact support if the cause is unclear."),
    ("An actuator won’t move",
     "Check the selected target, measurement, limits and device status. Choosing a target "
             "does not move the axis until Go. Leg length uses an estimate from retracted zero. "
     "Reset and home moves the device; follow the recovery procedure before using it."),
    ("Invalid PIN at login",
     "Re-enter the operator PIN. If it keeps failing, confirm your PIN with your "
     "system administrator."),
    ("Treatment stopped unexpectedly",
     "Read the reported outcome and fault or advisory. Do not assume that dismissing a "
     "notice resolves its cause. Follow the device recovery procedure and wait for Ready "
     "before another treatment. Use the physical emergency stop if motion must be interrupted "
     "while the controller is disconnected."),
]

# Safety limits, shared by Setup + Help (bundle.jsx). (label, value, unit)
TROUBLESHOOTING = {
    "Treatment": [HELP_FAILURES[i] for i in (0, 1, 2, 4)],
    "Connection & sync": [
        ("Arduino is disconnected or firmware is not reported",
         "Read Device → Overview. Check controller power and the serial cable with the device "
         "unoccupied. An older controller may not report a version. If a running device loses "
         "control, use the physical emergency stop. Contact support if reconnection keeps failing."),
        ("Wi-Fi connects but the cloud is unavailable",
         "Open Device → Settings → Test Connection. Internet and cloud results are separate. "
         "Check the selected Wi-Fi network and IP address. Guest networks may need a captive-portal "
         "login; ask your network administrator. An authentication error needs cloud configuration "
         "help rather than repeated Wi-Fi changes."),
        ("Treatments are waiting to sync",
         "Device → Settings shows pending records and the last acknowledged upload. Tap Sync "
         "after the connection is restored. Server retry delays still apply. Records remain "
         "local until acknowledged. Do not delete the upload queue or repeat a treatment to "
         "force an upload."),
        ("An upload needs attention or the queue is unreadable",
         "Read the upload message. Check the linked patient and clinic with an administrator. "
         "Unknown counts can mean a preserved unreadable queue, not zero records. Keep the "
         "device files intact and contact support with the error and diagnostic export."),
    ],
    "Access": [
        HELP_FAILURES[3],
        ("The Service tab asks for a different PIN",
         "Service uses a separate six-digit technician PIN. An operator login does not unlock it. "
         "An administrator can enroll the service PIN if none exists. Leaving Service or logging "
         "out locks it again. Ask your administrator if the technician PIN is unavailable."),
        ("Cloud sign-in, verification code or clinic selection fails",
         "Use your cloud staff email and password. If prompted, enter the current authenticator "
         "code or select recovery-code mode. Check the device's date and time. Select the clinic "
         "this device belongs to. Expired sessions require sign-in again; contact your cloud "
         "administrator for missing clinic access or permissions."),
        ("The device logged out automatically",
         "Check Device → Settings → Automatic logout. Inactivity logs out the operator and "
         "clears cloud staff access. The countdown pauses during treatment, movement, reset "
         "and active service work. Log in again to continue; completed treatment records remain."),
    ],
    "Screen & sound": [
        ("The screen dims or the first touch does nothing",
         "The first touch after app dimming restores brightness without pressing a button. "
         "Tap again once the screen is awake. Adjust brightness and Screen timeout in Device → "
         "Settings. OS screen locking and the display's own power settings are separate."),
        ("Brightness is unavailable",
         "Some HDMI displays do not expose a controllable backlight. Use the display's physical "
         "controls. If this previously worked, refresh Device status and ask a technician to "
         "check the backlight driver and device permissions."),
        ("There is no sound or a video is silent",
         "Check Device → Settings → System volume, then Test Sound. Check the speaker connection "
         "and the system's selected audio output. If the tone works, check the video's own "
         "volume and playback status. Report whether the tone, the video, or both are silent."),
        ("The time is wrong",
         "Check Date and time in Device → Settings. Select the local time zone and enable "
         "automatic time. Internet access may be needed before the status changes to synchronized. "
         "Correct time also helps cloud sign-in and accurate record timestamps."),
    ],
    "Updates & service": [
        ("No software or firmware release is available",
         "Unlock Service and check the latest releases with a cloud staff account. Verify the "
         "selected clinic. Software and firmware are listed separately; an administrator must "
         "upload a release for that platform and deploy the release API."),
        ("A download or checksum check failed",
         "The installed files are unchanged when download verification fails. Restore the "
         "connection and check releases again. If verification keeps failing, contact the "
         "release administrator with the version and request reference shown on screen."),
        ("Firmware flashing failed or the controller does not respond afterward",
         "Keep the device unoccupied. Read the installation result and retain the firmware "
         "backup and update log. Check the Mega 2560 USB cable and selected port. A failed flash "
         "must be recovered and verified by a technician before treatment; do not assume that "
         "restarting the app repairs it."),
        ("Calibration was restored or changed",
         "Remove external loads and use the explicit unloaded reset from Setup. Verify the "
         "new calibration before treatment. Hardware Tests records diagnostic observations; "
         "Calibration records measured positions and factors. Use Service history to review "
         "what was saved and Export Diagnostics when contacting support."),
    ],
}

SAFETY_LIMITS = [
    ("Pressure max", f"{PRESSURE_MAX:g}", "lbs"),
    ("Axial range", "–".join(f"{v:g}" for v in ACTUATORS["AXIAL"]["LIMITS"]), "in"),
    ("Lateral range", " to ".join(f"{v:g}" for v in ACTUATORS["LATERAL"]["LIMITS"]), "°"),
    ("Horizontal", " to ".join(f"{v:g}" for v in HORIZONTAL_COMMAND_LIMITS), "°"),
]
