# Integrated Control and Data Acquisition System for Kneespa DRx

![A diagram overviewing the project structure.](diagram.png)

## Overview
This repository provides an integrated control and data acquisition system designed for precise hardware device management and data processing. The system is structured to interface with hardware devices, specifically through the HX711 load cell amplifier for accurate weight measurements, and to control these devices via a user-friendly graphical interface. The architecture is modular, focusing on clear separation of concerns, which allows for ease of maintenance, scalability, and integration of additional components or protocols as required.

## System Architecture Codemap
At the core of the system's architecture is the division into four main subgraphs, each responsible for a distinct aspect of the system's functionality:

## 1. Data Acquisition
The Data Acquisition module is centered around the HX711 Data Acquisition component, which interfaces with HX711 load cell amplifiers. This module is crucial for obtaining accurate weight measurements. It employs Python classes for direct communication with the HX711 chip, handling data processing, filtering, and debugging.

Key Files & Modules:

hx711py-master/
HX711-master/

## 2. Control Protocols
This module implements the logic for device control and configuration management. It includes protocols for device operation and facilitates configuration and communication between the system's components and the Arduino microcontroller for executing device-specific commands.

Key Components:

CProtocols.py
DProtocols.py
BProtocols.Arduino.py
calibrate.py

## 3. User Interface and System Management
The GUI and System Control component utilizes PyQt5 to create a graphical user interface that allows users to interact with the system, control devices, and manage system settings. It also includes functionality for executing system commands like rebooting or shutting down.

Key Components:

kneespa.pi.py
kneespa.small.py

## 4. Hardware Devices
This module encompasses the physical devices controlled by the system, including the Arduino microcontroller and various hardware devices. It details the feedback mechanisms and control pathways between the hardware and the control protocols.

Key Components:

Direct interaction with Arduino and hardware devices through serial communication and GPIO pins.
Architectural Invariants
Separation of Concerns: Each module is designed to handle specific functionalities, ensuring a clean separation between data acquisition, device control, GUI interaction, and hardware management.
Modularity: The system's architecture is modular, allowing for easy expansion or modification of individual components without affecting the overall system.
No Circular Dependencies: The architecture is designed to prevent circular dependencies, ensuring that high-level modules do not depend on lower-level modules.
Boundary Definition: Clear boundaries are established between the system's internal components and the external hardware devices it controls. These boundaries are defined by the communication protocols and interfaces.
Boundaries Between Layers and Systems
Data Acquisition and Control Protocols: Acts as the foundational layer that processes and prepares data for higher-level decision-making and control.
Control Protocols and Hardware Devices: Serves as the interface layer that translates high-level commands into hardware-specific actions.
User Interface and System Management: Provides the entry point for human interaction, abstracting the underlying complexity into a user-friendly interface.
Conclusion
This architectural overview outlines the high-level structure and components of the integrated control and data acquisition system. By adhering to principles such as separation of concerns and modularity, the system is designed for robustness, flexibility, and ease of use. Each component within the system plays a critical role in achieving precise control and accurate data acquisition, making it a comprehensive solution for managing and interfacing with hardware devices.

