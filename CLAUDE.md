# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build Commands
- Install dependencies: `pip install -r requirements.txt`
- Run application: `python main/kneespa.py`

## Testing
- Run tests: `python -m pytest`
- Run specific test categories: 
  - Unit tests: `python -m pytest -m unit`
  - Integration tests: `python -m pytest -m integration`
  - UI tests: `python -m pytest -m ui`
- Generate coverage report: `python -m pytest --cov=main tests/`

## Code Style Guidelines

### Formatting & Structure
- Follow PEP 8 standards
- Use 4 spaces for indentation
- Maximum line length of 100 characters
- Google-style docstrings for functions and classes

### Naming Conventions
- Classes: CamelCase (e.g., `LoggerAdapter`)
- Functions/variables: snake_case (e.g., `setup_logger`)
- Constants: UPPER_SNAKE_CASE (e.g., `APP_NAME`)

### Imports & Organization
- Order: built-in libs → third-party libs → local modules
- Group imports by category with a blank line between groups

### Type Annotations
- Use type hints for all function parameters and return values
- Import from `typing` module (Optional, Dict, List, etc.)

### Error Handling
- Use custom exceptions from `utils/exceptions.py`
- Log errors with context information
- Classify exceptions by safety criticality