KneeSpa Config Presets
======================

`devices/local/raspberry-pi/config/kneespa.cfg` is the active default runtime configuration.

The files in this directory are archived device-specific or legacy calibration
presets. Use them explicitly with `python runtime/raspberry-pi/main/kneespa.py --config PATH` or copy
one into that device's config directory after confirming it matches the target device.

`kneespa_legacy_system.cfg` includes older system, network, logging, and email
sections that are not used by the current `Configuration` loader.
