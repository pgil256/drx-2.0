# KneeSpa System Installation and Setup

This guide provides detailed instructions for setting up the KneeSpa system for development and production use.

## Prerequisites

Before beginning installation, ensure your system meets these requirements:

- **Hardware Requirements**
  - Raspberry Pi 4 or newer (recommended) or PC with USB ports
  - Arduino Uno or Arduino Mega
  - KneeSpa actuator hardware
  - 5V power supply for logic
  - 24V power supply for motors

- **Software Requirements**
  - Python 3.7 or newer
  - PyQt5
  - Git (for development)
  - Arduino IDE (for firmware modifications)

## Installation Steps

### 1. Clone or Download the Repository

```bash
# For development
git clone https://github.com/yourusername/drx-2.1.git
cd drx-2.1

# Or extract the downloaded zip file
```

### 2. Install Python Dependencies

```bash
# Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install required packages
pip install -r requirements.txt
```

### 3. Connect Hardware

1. Connect the Arduino to the Raspberry Pi or PC via USB
2. Connect the actuator motor controllers to the Arduino
3. Connect the power supplies to the motor controllers
4. Verify connections against the hardware wiring diagram

### 4. Configure Settings

1. Copy the example configuration file:
   ```bash
   cp main/config/kneespa.cfg.example main/config/kneespa.cfg
   ```

2. Edit the configuration file with your specific hardware details:
   ```bash
   nano main/config/kneespa.cfg
   ```

   Key settings to configure:
   - Serial port (typically `/dev/ttyS0` on Raspberry Pi, COM port on Windows)
   - Actuator calibration values
   - Default protocol parameters

### 5. Upload Arduino Firmware

1. Open `main/motor/motor.ino` in the Arduino IDE
2. Select the appropriate board type (Uno or Mega)
3. Select the correct port
4. Upload the firmware to the Arduino

### 6. Run the Application

```bash
python main/kneespa.py
```

## Raspberry Pi Setup

For Raspberry Pi deployment, additional configuration is recommended:

### Enable Serial Communication

```bash
# Enable hardware serial
sudo raspi-config
# Navigate to:
# Interface Options -> Serial -> Disable serial login shell -> Enable serial hardware
```

### Autostart Configuration

To make the application start automatically on boot:

1. Create a systemd service file:
   ```bash
   sudo nano /etc/systemd/system/kneespa.service
   ```

2. Add the following content:
   ```
   [Unit]
   Description=KneeSpa Therapeutic Application
   After=multi-user.target

   [Service]
   Type=idle
   User=pi
   WorkingDirectory=/home/pi/drx-2.1
   ExecStart=/home/pi/drx-2.1/venv/bin/python /home/pi/drx-2.1/main/kneespa.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. Enable the service:
   ```bash
   sudo systemctl enable kneespa.service
   sudo systemctl start kneespa.service
   ```

## Testing the Installation

1. Run the automated test suite:
   ```bash
   python -m pytest
   ```

2. Test specific components:
   ```bash
   # Test Arduino communication
   python -m pytest tests/unit/test_arduino.py
   
   # Test protocol execution
   python -m pytest tests/unit/test_protocols.py
   ```

3. Interactive hardware testing:
   ```bash
   python tests/interactive_simulator.py
   ```

## Troubleshooting

### Common Issues

1. **Serial Port Connection Failures**
   - Verify the correct port in the configuration
   - Check USB connections
   - Ensure proper permissions: `sudo chmod 666 /dev/ttyS0`

2. **Arduino Not Responding**
   - Reset the Arduino using the reset button
   - Verify the firmware is correctly uploaded
   - Check power connections

3. **Actuator Movement Issues**
   - Verify motor controller connections
   - Check power supply voltages
   - Review calibration values in the configuration

4. **UI Display Problems**
   - Ensure PyQt5 is properly installed
   - Check display settings on the Raspberry Pi
   - Try running with `DISPLAY=:0` environment variable

### Logs

Check the following log files for troubleshooting:

- `main/logs/kneespa.log` - General application logs
- `main/logs/error.log` - Error-specific logs
- `main/logs/debug.log` - Detailed debug information

## Production Deployment Guidelines

For production deployment:

1. **Lock Down Environment**
   - Remove development tools
   - Use a dedicated user account
   - Secure the Raspberry Pi OS

2. **Regular Backups**
   - Back up the patient and user data regularly
   - Back up the configuration files

3. **Monitoring**
   - Set up log rotation
   - Implement remote monitoring if possible

4. **Regular Maintenance**
   - Update the system regularly
   - Check logs for errors or warnings
   - Perform regular calibration checks

## Development Setup

For development:

1. **Environment Setup**
   - Use a dedicated virtual environment
   - Install development tools: `pip install -r requirements-dev.txt`

2. **Test-Driven Development**
   - Run tests before and after making changes
   - Maintain test coverage

3. **Version Control**
   - Make regular commits
   - Follow the branching strategy documented in CLAUDE.md

4. **Documentation**
   - Update documentation when making changes
   - Follow the documentation guidelines
