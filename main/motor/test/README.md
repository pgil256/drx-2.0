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
├── mock_serial.h             <- mock for Arduino Serial / Serial1 (captures output, injects input)
├── mock_wire.h               <- mock for the I2C Wire library (records commands, returns positions)
├── mock_hx711.h              <- mock for the HX711 load-cell amplifier (configurable pressure)
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
   `-DUNIT_TEST`; see `platformio.ini`).
2. Includes `<unity.h>` and the three mock headers (`../mock_*.h`).
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
# Convenience wrapper (checks for pio, then runs the native env):
bash run_native_tests.sh

# Or invoke PlatformIO directly:
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

The first `pio test -e native` run downloads the `native` platform and the Unity
test framework from the PlatformIO package registry. **If the machine cannot
reach that registry (offline, restricted network), the download fails and the
tests cannot be built or run.** CI runs these tests in an environment with
registry access. Locally, you need connectivity (at least for the first run, to
populate the PlatformIO package cache).
