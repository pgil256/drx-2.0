KneeSpa Config Presets
======================

`main/config/kneespa.cfg` is the active default runtime configuration.

The files in this directory are archived device-specific or legacy calibration
presets. Use them explicitly with `python main/kneespa.py --config PATH` or copy
one into `main/config/kneespa.cfg` after confirming it matches the target device.

`kneespa_legacy_system.cfg` includes older system, network, logging, and email
sections that are not used by the current `Configuration` loader.
