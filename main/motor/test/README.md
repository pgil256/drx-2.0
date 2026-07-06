# Motor firmware native tests

This directory holds the host-side (native) [Unity](https://github.com/ThrowTheSwitch/Unity)
unit tests for the KneeSpa AVR firmware (`main/motor/motor.ino`).

The tests compile `motor.ino` on the host machine (no AVR hardware needed) by
substituting lightweight mock implementations for the Arduino libraries the
firmware depends on. This lets us exercise the command parser, status
reporting, safety logic, and value clamping in CI and on a developer laptop.

## Layout

```
test/
├── README.md                 <- this file
├── arduino_shim.h            <- minimal Arduino core (pins, String, elapsedMillis, wdt) for native builds
├── mock_serial.h             <- mock for Arduino Serial / Serial1 (captures output, injects input)
├── mock_wire.h               <- mock for the I2C Wire library (records commands, returns positions)
├── mock_hx711.h              <- mock for the HX711 load-cell amplifier (configurable pressure)
├── unity/                    <- vendored Unity framework (hermetic runs, no registry needed)
├── test_clamp/
│   └── test_clamp.cpp          <- clampPressureTarget()/clampPositionTarget()/getValue() tests
├── test_command_parse/
│   └── test_command_parse.cpp  <- processCommand() command-handling tests
├── test_safety/
│   └── test_safety.cpp         <- emergencyStop() and X-command safety tests
└── test_status/
    └── test_status.cpp         <- sendStatus() formatting + calibration command tests
```

PlatformIO's Unity test runner treats each `test_*/` subdirectory as a separate
test suite with its own `main()` / `UNITY_BEGIN()` / `UNITY_END()`.

## How the mocks are wired in

Each test file:

1. Guards everything behind `#ifdef UNIT_TEST` (the `native` build defines
   `-DUNIT_TEST`; see `platformio.ini`). `motor.ino` only includes the real
   hardware libraries (`HX711.h`, `elapsedMillis.h`, `Wire.h`, `avr/wdt.h`)
   when `UNIT_TEST` is *not* defined.
2. Includes `<unity.h>`, `../arduino_shim.h` (Arduino core substitutes), and
   the three mock headers (`../mock_*.h`) — the shim must come first.
3. Instantiates the mock globals (`MockWire Wire;`, `MockSerial Serial;`,
   `MockSerial Serial1;`) and stubs `millis()` / `delay()`.
4. Includes the firmware directly with `#include "../../motor.ino"`, which makes
   functions such as `processCommand`, `sendStatus`, and `emergencyStop`
   available to the tests.

When adding a new suite, create `test_<name>/test_<name>.cpp` and copy this
include/`setUp`/`main` pattern from an existing file (e.g.
`test_command_parse/test_command_parse.cpp`). Do not modify the shared mock
headers unless the firmware genuinely needs a new mocked API.

## Running the tests

From `main/motor/`:

```bash
# Hermetic runner: system gcc/g++ + the vendored Unity in test/unity/
# (no PlatformIO or registry access needed) — this is what CI gates on:
bash run_native_tests.sh

# Or invoke PlatformIO (downloads the native platform + Unity on first run):
pio test -e native
```

The `native` environment is defined in `main/motor/platformio.ini`:

```ini
[env:native]
platform = native
test_framework = unity
build_flags = -DUNIT_TEST -std=c++11
build_src_filter = -<*>
```

The `-DUNIT_TEST` flag is what activates the `#ifdef UNIT_TEST` blocks in both
the mock headers and the test files; without it the mocks compile to nothing and
the firmware would expect the real Arduino libraries.

## Offline / registry caveat

`run_native_tests.sh` is fully offline: it uses the system C/C++ compiler and
the vendored Unity sources in `test/unity/`. Only the `pio test -e native`
route downloads packages (the `native` platform and Unity) from the PlatformIO
registry on first run, so it needs connectivity once to populate the package
cache.
