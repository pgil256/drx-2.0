# Bundled fonts

`ui/theme/qss.py:load_fonts()` registers **every `.ttf` / `.otf`** in this
directory with Qt at startup (`QFontDatabase.addApplicationFont`).

## Bundled (IBM Plex, SIL OFL 1.1 — see `LICENSE.txt`)

The design system specifies **IBM Plex Sans** (UI) + **IBM Plex Mono** (numeric
readouts). The static TTFs are committed here so the device is fully
offline-capable:

```
IBMPlexSans-Regular.ttf      (400)
IBMPlexSans-Medium.ttf       (500)
IBMPlexSans-SemiBold.ttf     (600)
IBMPlexSans-Bold.ttf         (700)
IBMPlexMono-Regular.ttf      (400)
IBMPlexMono-Medium.ttf       (500)
IBMPlexMono-SemiBold.ttf     (600)
```

Source: IBM Plex repo, tag `v6.4.0` (each family's `fonts/complete/ttf/`):
https://github.com/IBM/plex

To update, drop replacement TTFs here — they load automatically, no code change.
If you ever remove them, the app falls back to the next family in the
`--font-sans` stack (Segoe UI on Windows; on the Pi, `sudo apt-get install
fonts-ibm-plex`).
