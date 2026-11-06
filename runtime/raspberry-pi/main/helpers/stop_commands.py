"""The serial commands the stop paths send, named in one place (checklist A2).

``controllers.stop_controller`` says which stop kind sends which; the
treatment worker's release uses the same names.
"""

STOP_ALL = "X"         # halts every motor and pulsing; jumps the transport queue
RELEASE = "P0"         # backs the axial actuator off until the load cell reads zero
TELEMETRY_OFF = "HF0"  # ends high-frequency status
TELEMETRY_ON = "HF1"   # keeps high-frequency status on after a fault stop

# The release after an operator or on-screen stop, and the shutdown stop.
RELEASE_SEQUENCE = (STOP_ALL, RELEASE, TELEMETRY_OFF)
