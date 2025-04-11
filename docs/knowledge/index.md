# KneeSpa System Knowledge Base

## Overview

This knowledge base provides comprehensive documentation of the KneeSpa system architecture, components, and implementation details. It serves as a reference for developers working on the system.

## Quick Start

### Installation
1. Install dependencies:
```
pip install -r requirements.txt
```

2. Connect the KneeSpa hardware device to your computer/Raspberry Pi.

3. Configure the device settings in `config/kneespa.cfg`

### Running the Application
```
python main/kneespa.py
```

### Testing
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

## Contents

1. [System Overview and Architecture](README.md)
   - Complete system architecture
   - Component breakdowns
   - Directory structure
   - Hardware and software components

2. [System Architecture Diagram](system_architecture.mmd)
   - Visual representation of system components
   - Hierarchical structure visualization
   - Component relationships

3. [Protocol Sequence Diagram](protocol_sequence.mmd)
   - Detailed sequence of protocol execution
   - Communication between components
   - Timing and dependencies

4. [Class Relationships Diagram](class_relationships.mmd)
   - UML-style class diagram
   - Major class dependencies
   - Inheritance and composition relationships

5. [Arduino Command Protocol](arduino_commands.md)
   - Serial communication protocol reference
   - Command formats and parameters
   - Response handling

6. [Protocol Implementations](protocol_implementations.md)
   - Detailed explanation of the three treatment protocols
   - Implementation details with code samples
   - Shared protocol components

7. [Error Handling Strategy](error_handling.md)
   - Error classification and handling patterns
   - Exception hierarchy
   - Recovery mechanisms

8. [Installation and Setup](installation.md)
   - Detailed installation instructions
   - Configuration guidelines
   - Production deployment
   - Development setup

## How to Use This Documentation

- **New Developers**: Start with the System Overview to understand the big picture
- **UI Developers**: Focus on the Class Relationships and System Architecture
- **Hardware Developers**: Check the Arduino Command Protocol and Error Handling
- **Protocol Developers**: Review Protocol Implementations and Protocol Sequence Diagram

## Visualization Tools

The `.mmd` files in this directory are Mermaid diagrams. You can view them using:

- [Mermaid Live Editor](https://mermaid-js.github.io/mermaid-live-editor/)
- VS Code with the Mermaid extension
- Any Markdown viewer that supports Mermaid diagrams

## Maintaining This Documentation

When making changes to the system, please update the corresponding documentation:

1. For new commands, update the Arduino Command Protocol
2. For protocol changes, update the Protocol Implementations
3. For architectural changes, update the System Architecture Diagram
4. For new classes or relationships, update the Class Relationships Diagram

## Development Guidelines

Refer to the main [CLAUDE.md](../../CLAUDE.md) file in the project root for detailed development guidelines and coding standards.

## License
Proprietary software. All rights reserved.
