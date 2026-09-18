# Actuator calibration panel: replaced by Hardware Tests & Calibration

The Setup and profile-menu calibration actions now open **Hardware Tests &
Calibration**, a guided wizard protected by a separate six-digit technician PIN.
It covers axial, horizontal and lateral calibration, leg movement checks,
load-cell calibration, stationary stop checks and individually recorded physical
bench observations.

See [Hardware Tests & Calibration](hardware-service.md) for the current operator
procedure, first-administrator PIN enrollment, matching firmware requirements,
configuration and backup behavior, service reports, and deployment verification.

The former two-axis panel's instructions no longer describe the GUI workflow.
In particular, each service move now requires operator confirmation, calibration
is saved only from the review step, and saved changes require an explicit
**Reset Arduino** with the device unloaded before further movement. The
stationary software-stop check precedes the physical stop-input check; both are
separate from the approved physical bench tests of dynamic stopping and release.
