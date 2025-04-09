# KneeSpa Application

## Overview
KneeSpa is a therapeutic device control application for knee rehabilitation treatments.

## Installation
1. Install dependencies:
```
pip install -r requirements.txt
```

2. Connect the KneeSpa hardware device to your computer/Raspberry Pi.

3. Configure the device settings in `config/kneespa.cfg`

## Running the Application
```
python main/kneespa.py
```

## Testing
Run the automated test suite:
```
python -m pytest
```

Run specific test categories:
```
python -m pytest -m unit          # Unit tests only
python -m pytest -m integration   # Integration tests only
python -m pytest -m ui            # UI tests only
```

Generate coverage report:
```
python -m pytest --cov=main tests/
```

Current test coverage:
- Unit tests and integration tests: 51 tests
- Core modules covered: 
  - exceptions (89%)
  - config (83%)
  - worker_signals (100%)
  - Protocol and hardware stubs (21%)

## Project Structure
- `config/`: Configuration files and constants
- `data/`: User and patient data storage
- `helpers/`: Hardware communication and protocol implementation
- `ui/`: User interface components
- `utils/`: Utility functions and exception handling
- `tests/`: Automated tests
  - `unit/`: Unit tests for individual components
  - `integration/`: Tests for component interactions
  - `ui/`: User interface tests
  - `mocks/`: Mock implementations for hardware testing

## Development
Follow the coding guidelines in `CLAUDE.md` when contributing to this project.

## License
Proprietary software. All rights reserved.