# KneeSPA Installation Guide for Raspberry Pi 4 (Buster OS)

## System Requirements

- **Hardware**: Raspberry Pi 4 (2GB RAM minimum, 4GB recommended)
- **Operating System**: Raspbian Buster (Debian 10)
- **Python Version**: 3.7.x
- **Storage**: 8GB minimum free space
- **Peripherals**: Arduino via Serial, GPIO access required

## Quick Installation

### 1. Clone or Copy the Project
```bash
cd ~
git clone <repository-url> drx-demo-final
cd drx-demo-final
```

### 2. Make Setup Script Executable
```bash
chmod +x setup_system.sh
```

### 3. Run the Setup Script
```bash
./setup_system.sh
```

This script will:
- Update package lists (NOT the OS)
- Install all system dependencies
- Configure Raspberry Pi interfaces (I2C, SPI, Serial)
- Create Python virtual environment
- Install all Python packages
- Configure serial port for Arduino
- Set up necessary permissions

### 4. Configure Environment Variables
```bash
# Copy the example file
cp .env.example .env

# Edit with your actual values
nano .env
```

**Important**: Update these values in `.env`:
- Email credentials for assistance requests
- Secure PINs (not default 123/456)
- System unlock code

### 5. Reboot the System
```bash
sudo reboot
```

## Manual Installation (Alternative)

If you prefer to install manually or the script fails:

### Step 1: Update Package Lists
```bash
sudo apt-get update
```

### Step 2: Install System Dependencies
```bash
# Python development tools
sudo apt-get install -y python3-dev python3-pip python3-setuptools python3-wheel python3-venv build-essential

# PyQt5 (better to use apt on RPi)
sudo apt-get install -y python3-pyqt5 python3-pyqt5.qtmultimedia python3-pyqt5.qtserialport pyqt5-dev-tools qttools5-dev-tools

# Hardware libraries
sudo apt-get install -y python3-rpi.gpio python3-smbus python3-spidev i2c-tools python3-serial

# OpenCV (optimized for RPi)
sudo apt-get install -y python3-opencv libopencv-dev libatlas-base-dev

# VLC media libraries
sudo apt-get install -y vlc libvlc-dev python3-vlc

# Additional libraries
sudo apt-get install -y libxml2-dev libxslt1-dev libffi-dev libssl-dev sqlite3 libsqlite3-dev
```

### Step 3: Configure Raspberry Pi Interfaces
```bash
# Enable I2C
sudo raspi-config nonint do_i2c 0

# Enable SPI
sudo raspi-config nonint do_spi 0

# Enable Serial (disable console)
sudo raspi-config nonint do_serial 2

# Add user to groups
sudo usermod -a -G gpio,i2c,spi,dialout $USER
```

### Step 4: Disable Serial Console
```bash
# Backup and modify boot config
sudo cp /boot/cmdline.txt /boot/cmdline.txt.backup
sudo sed -i 's/console=serial0,115200 //g' /boot/cmdline.txt

# Disable getty service
sudo systemctl stop serial-getty@serial0.service
sudo systemctl disable serial-getty@serial0.service
```

### Step 5: Create Virtual Environment
```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Upgrade pip (to last Python 3.7 compatible version)
pip install --upgrade pip==21.3.1
```

### Step 6: Install Python Packages
```bash
# With virtual environment activated
pip install -r requirements.txt
```

## Running the Application

### First Time Setup
1. Ensure you've configured `.env` file
2. Log out and log back in (for group permissions)
3. Or reboot: `sudo reboot`

### Starting the Application
```bash
# Navigate to project directory
cd ~/drx-demo-final

# Activate virtual environment
source venv/bin/activate

# Run the application
python main/kneespa.py

# Or with debug mode
python main/kneespa.py --debug --print-logs
```

## Troubleshooting

### Serial Port Issues
```bash
# Check serial port availability
ls -l /dev/serial*

# Verify getty is disabled
systemctl status serial-getty@serial0.service

# Test serial communication
python -c "import serial; print(serial.Serial('/dev/serial0', 9600))"
```

### GPIO Permission Issues
```bash
# Verify group membership
groups

# Should include: gpio i2c spi dialout
# If not, run:
sudo usermod -a -G gpio,i2c,spi,dialout $USER
# Then logout and login again
```

### PyQt5 Import Errors
```bash
# Reinstall PyQt5 via apt
sudo apt-get install --reinstall python3-pyqt5

# Verify installation
python3 -c "from PyQt5 import QtWidgets; print('PyQt5 OK')"
```

### Arduino Connection Issues
1. Check Arduino is connected to `/dev/serial0`
2. Verify baud rate is 9600
3. Ensure serial console is disabled
4. Check Arduino has correct firmware loaded

### Python Package Issues
```bash
# Clear pip cache
pip cache purge

# Reinstall with no cache
pip install --no-cache-dir -r requirements.txt
```

## Verification Checklist

After installation, verify:

- [ ] Python version is 3.7.x: `python3 --version`
- [ ] Virtual environment created: `ls -la venv/`
- [ ] PyQt5 imports correctly: `python3 -c "from PyQt5 import QtWidgets"`
- [ ] GPIO accessible: `python3 -c "import RPi.GPIO"`
- [ ] Serial port available: `ls -l /dev/serial0`
- [ ] .env file configured: `test -f .env && echo "OK"`
- [ ] User in correct groups: `groups | grep -E "(gpio|dialout|i2c|spi)"`

## Security Notes

1. **Never commit `.env` file** to version control
2. **Change default PINs** immediately
3. **Rotate email passwords** if exposed
4. **Use strong passwords** for all accounts
5. **Consider implementing** proper authentication for production

## Maintenance

### Update System Packages (Safe)
```bash
# Only updates package lists and security updates
sudo apt-get update
sudo apt-get upgrade -y
```

### Update Python Packages
```bash
# Activate virtual environment first
source venv/bin/activate

# Update packages
pip install --upgrade -r requirements.txt
```

### Backup Configuration
```bash
# Backup important files
cp .env .env.backup
cp main/config/kneespa.cfg main/config/kneespa.cfg.backup
```

## Support

For issues:
1. Check debug output: `python main/kneespa.py --debug --print-logs`
2. Review log files in `logs/` directory
3. Verify all dependencies installed correctly
4. Ensure hardware connections are secure

## Performance Optimization

For better performance on Raspberry Pi 4:

1. **Enable GPU acceleration**:
   ```bash
   sudo raspi-config
   # Advanced Options > GL Driver > GL (Fake KMS)
   ```

2. **Increase GPU memory split**:
   ```bash
   sudo raspi-config
   # Advanced Options > Memory Split > 256
   ```

3. **Use a fast SD card** (Class 10 or better)

4. **Enable cooling** to prevent throttling

5. **Disable unnecessary services**:
   ```bash
   sudo systemctl disable bluetooth
   sudo systemctl disable avahi-daemon
   ```