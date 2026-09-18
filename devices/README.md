# Device state and provisioning

- `local/raspberry-pi/`: active device state on a Pi.
- `profiles/<device-name>/raspberry-pi/`: separate PC copies for individual devices.
- `development/raspberry-pi/`: isolated state for the desktop simulator.
- `templates/`: tracked examples and historical calibration presets.
- `maintenance/`: optional Pi diagnostics and Arduino calibration/scale sketches.

Live state, profiles, and simulator state are ignored by Git. Shared software
updates never sync this directory. Do not copy one device's identity or calibration
to another. See [deployment and migration](../development/docs/deployment.md)
for targeted transfers and first-time upgrades.
