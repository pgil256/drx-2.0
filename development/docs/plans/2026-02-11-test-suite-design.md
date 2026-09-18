# KneeSpa Test Suite Design

## Goal

CI/CD-friendly test suite that runs on Linux/WSL without hardware, with a separate hardware integration suite for the Raspberry Pi. Covers both Python application code and Arduino firmware.

## Architecture

Three test tiers controlled by pytest markers:

| Tier | Marker | Runs on | Speed | What it tests |
|------|--------|---------|-------|---------------|
| Unit | `@pytest.mark.unit` | Any Linux | <5s | Pure logic, no Qt, no serial |
| Integration | `@pytest.mark.integration` | Any Linux | <30s | FakeArduino + Qt signals |
| Hardware | `@pytest.mark.hardware` | Pi + Arduino | ~60s | Real serial, real GPIO |

Arduino firmware tests run separately via PlatformIO + Unity framework.

**Default CI runs tiers 1+2 only.**

## Directory Structure

```
tests/
├── conftest.py              # Shared fixtures, pytest config
├── unit/
│   ├── test_config.py       # Configuration read/write/defaults
│   ├── test_constants.py    # Safety limit validation
│   ├── test_arduino_parse.py # Status parsing, command formatting
│   └── test_protocol_logic.py # Pressure ramp math, interpolation, bounds
├── integration/
│   ├── test_arduino_comm.py # Connect/disconnect/reconnect/send/receive
│   ├── test_protocols.py    # All 4 protocols against FakeArduino
│   ├── test_reset_worker.py # Reset sequence against FakeArduino
│   └── test_pressure_dialog.py # UI updates from protocol signals
├── hardware/
│   ├── test_serial_hw.py    # Real serial connection smoke test
│   └── test_gpio_hw.py      # Real GPIO pin verification
└── fixtures/
    ├── fake_arduino.py      # FakeArduino simulator
    ├── sample_configs/      # Test .cfg files (valid, corrupt, empty)
    └── expected_responses/  # Golden serial response files

main/motor/
├── platformio.ini
└── test/
    ├── mock_wire.h
    ├── mock_serial.h
    ├── mock_hx711.h
    ├── test_command_parse/
    │   └── test_command_parse.cpp
    ├── test_motor_control/
    │   └── test_motor_control.cpp
    ├── test_safety/
    │   └── test_safety.cpp
    └── test_status/
        └── test_status.cpp
```

## FakeArduino Simulator

The centerpiece of integration testing. A Python class that simulates Arduino firmware behavior over a virtual serial port using `pty` (pseudo-terminal).

### State

```python
class FakeArduino:
    position_a: int = 0
    position_b: int = 0
    position_c: int = 1200  # center
    pressure: float = 0.0
    jerking: bool = False
    b_running: bool = False
    measure_pressure: bool = False
    high_frequency_status: bool = False

    movement_speed: float = 100.0   # units per second
    pressure_rate: float = 5.0      # lbs per second
    stall_after: int | None = None
```

### How it works

- `pty.openpty()` creates a master/slave terminal pair. The Python `Arduino` class connects to the slave path. The FakeArduino reads/writes the master side.
- A background thread processes incoming commands, updates internal state, and sends responses in `STATUS_START|S|posA|posB|posC|pressure|STATUS_END` format.
- Position commands simulate gradual movement over time (not instant), so protocol polling/timeout logic gets exercised realistically.
- Pressure commands simulate gradual ramping with configurable noise/overshoot to test tolerance logic.
- `'T'` command always responds `'OK'`.

### Fault injection

- `simulate_disconnect()` - Close the pty to test reconnection
- `simulate_stall(actuator)` - Stop position updates to test stall detection
- `simulate_pressure_overshoot(amount)` - Test tolerance bounds
- `delay_responses(ms)` - Test timeout handling
- `corrupt_status()` - Send malformed status to test parsing resilience

## Python Unit Tests

### test_config.py

- Read valid config file, verify all CMarks/AMarks/BMarks load correctly
- Read corrupt config (missing sections, bad types), verify graceful fallback to defaults
- Read missing config file, verify defaults are populated
- Write config, read it back, verify round-trip integrity
- Verify default mark values match expected calibration tables
- Verify `a_factor`, `b_factor`, `c_factor` defaults (1900)

### test_constants.py

- `PRESSURE_MAX` is 80, `MIN_PRESSURE` is 10
- Actuator limits are within sane ranges (no negative max, min < max)
- GPIO pins are valid BCM pin numbers
- All UI file paths reference files that exist on disk
- Command prefixes are single characters matching Arduino protocol

### test_arduino_parse.py

- Valid status: `STATUS_START|S|1500|2000|1200|45.3|STATUS_END` parses to correct tuple
- Partial status (missing fields) doesn't crash
- Non-numeric position values handled
- Negative pressure values handled
- Empty string, garbage data, partial delimiters
- `OK` response recognized for connection verify
- `DONE` response recognized for command completion
- Buffer warning messages parsed correctly

### test_protocol_logic.py

- `set_to_c_distance` interpolation: known degree to expected position from CMarks
- Interpolation at exact mark points vs. between marks
- Boundary degrees (-20, +20) clamp correctly
- Pressure tolerance: 3 lbs intermediate, 2 lbs final
- Duration check: elapsed vs. total time comparison

## Python Integration Tests

### test_arduino_comm.py

- Connect to FakeArduino, verify `connection_ready` signal fires
- Send `'T'`, receive `'OK'`, verify connection verified
- Send `'P50'`, receive status with pressure ~50, verify `status_emit` signal values
- Send `'K1500'`, verify position update in status response
- Connection lost: `simulate_disconnect()`, verify `connection_lost` signal fires
- Auto-reconnect: disconnect then reconnect, verify commands resume
- Thread safety: send 10 commands rapidly from different threads, no interleaving or crashes
- Malformed response: `corrupt_status()`, verify no crash and signal not emitted
- Command rate limiting: verify 200ms minimum interval between sends
- `HF1`/`HF0`: enable high-frequency, verify 1Hz updates, then disable

### test_protocols.py

- **Protocol 1 (axial):** Start at 0 pressure, verify ramp from 10 to max in 10 lb increments, each step waits for stabilization, pulse phase starts after ramp
- **Protocol 2 (left lateral):** Verify pressure ramp, then C actuator moves to `max_left` degrees, pulse phase
- **Protocol 3 (right lateral):** Same as 2 but `max_right`
- **Protocol 4 (oscillating):** Verify pressure ramp, then C oscillates between left/right, pulse during oscillation
- **Duration expiry:** Set 1-second duration, verify protocol stops and `finished` signal fires
- **Mid-protocol stop:** Set `is_running = False`, verify clean shutdown, `stopped` signal fires
- **Pulse toggle:** Start with `use_pulse=True`, set to `False` mid-protocol, verify `JS` sent
- **Pressure overshoot:** FakeArduino overshoots by 5 lbs, verify retry and stabilization
- **Stall during movement:** FakeArduino stalls C actuator, verify timeout handling

### test_reset_worker.py

- Commands sent in correct order: `Y` then `L5` then `I14` then `A130` then `I120` then `L0`
- Each step waits for `I2Cstatus` acknowledgment before proceeding
- Timeout on one step: verify retry with DTR reset
- Complete failure: verify `error` signal with descriptive message

### test_pressure_dialog.py

- Pressure <50 lbs renders green styling
- Pressure 50-70 renders orange
- Pressure >70 renders red
- Pressure change <0.5 lbs does not update display
- Pressure change >=0.5 lbs updates display

## Arduino Firmware Tests (PlatformIO + Unity)

### Mock Libraries

- **mock_wire.h** - Stub I2C. Records commands sent, returns configurable position values.
- **mock_serial.h** - Stub Serial1. Captures output strings, allows injecting input strings.
- **mock_hx711.h** - Stub load cell. Returns configurable pressure/weight values.

### test_command_parse.cpp

- `"T\n"` responds `"OK"`
- `"P50\n"` sets `desiredPressure=50`, `measurePressure=true`
- `"I121500\n"` sets actuator 12, `desiredPosition=1500`
- `"K1200\n"` sets C target to 1200
- `"A12430\n"` converts inches to position for actuator 12
- `"J\n"` sets `jerking=true`; `"JS\n"` sets `jerking=false`
- `"HF1\n"` / `"HF0\n"` toggles `highFrequencyStatus`
- `"X\n"` triggers emergency stop state
- Buffer overflow: 101+ bytes produces error, no crash
- Unknown command letter ignored gracefully
- Rapid commands with <200ms gap rate-limited

### test_motor_control.cpp

- Position control: set target, step through `loop()` iterations, verify convergence
- Direction logic: target > current means forward; target < current means reverse
- Speed assignment: actuator A pressure mode is 500; movement mode is 800
- Stall detection: same position 5 times in a row stops motor
- Pressure control: HX711 returns increasing values, motor stops within 0.5 lbs
- Jerk cycle: direction alternates every 200ms, counter increments, resets at 10

### test_safety.cpp

- Emergency stop (`X`): all speeds to 0, `bRunning=false`, `measurePressure=false`, `jerking=false`
- Stop pin (pin 3): LOW triggers `emergencyStop()` during movement
- Stop pin during jerking stops jerking
- Stop pin during pressure ramp stops pressure control
- Commands still accepted after emergency stop (system recoverable)

### test_status.cpp

- `"S\n"` output matches `STATUS_START|S|posA|posB|posC|pressure|STATUS_END`
- High-frequency mode: status sent every ~1000ms in loop
- Status acknowledgment timeout: no `Q` within 2s resets status state
- Calibration commands `L0`, `L1`, `L4`, `L5`, `L6` produce correct responses

## Dependencies

**requirements-test.txt:**
```
pytest>=7.0
pytest-mock
pytest-qt
pytest-cov
pytest-timeout
```

**platformio.ini** (for Arduino tests):
```ini
[env:native]
platform = native
test_framework = unity
build_flags = -DUNIT_TEST
```

## pytest.ini

```ini
[pytest]
markers =
    unit: Pure logic tests, no hardware or Qt
    integration: FakeArduino + Qt signal tests
    hardware: Requires real Pi + Arduino
    arduino: PlatformIO firmware tests
testpaths = tests
timeout = 30
```

## Key Fixtures (conftest.py)

```python
@pytest.fixture
def fake_arduino():
    """Spins up FakeArduino, yields (arduino_instance, fake), tears down."""

@pytest.fixture
def config_file(tmp_path):
    """Creates a temp config file, returns Configuration instance."""

@pytest.fixture
def protocol_factory(fake_arduino):
    """Returns a helper that creates Protocols with sane defaults."""
```

## Running Tests

```bash
# CI default - unit + integration
pytest -m "unit or integration"

# Fast feedback during development
pytest -m unit

# Full integration with coverage
pytest -m "unit or integration" --cov=main

# On the Pi with real hardware
pytest -m hardware

# Arduino firmware tests
cd main/motor && pio test -e native
```

## Environment Notes

- `RPi.GPIO` import guarded: tests patch with `MagicMock` on non-Pi systems. Hardware tests skip the patch.
- Qt offscreen: `QT_QPA_PLATFORM=offscreen` set in test environment so no display server needed.
- FakeArduino uses `pty.openpty()` for virtual serial (Linux-only, which matches our target).
