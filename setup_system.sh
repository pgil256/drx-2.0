#!/bin/bash

#############################################################################
# KneeSPA System Setup Script for Raspberry Pi 4 (Raspbian Buster)
# This script safely updates and installs required system dependencies
# WITHOUT changing OS version, Python version, or critical system packages
#############################################################################

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if running on Raspberry Pi
check_raspberry_pi() {
    if [ -f /proc/device-tree/model ]; then
        MODEL=$(cat /proc/device-tree/model)
        if [[ $MODEL == *"Raspberry Pi"* ]]; then
            print_status "Detected: $MODEL"
            return 0
        fi
    fi
    print_warning "This script is optimized for Raspberry Pi but will continue anyway."
    return 1
}

# Function to check OS version
check_os_version() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        print_status "Operating System: $NAME $VERSION"
        if [[ $VERSION_CODENAME == "buster" ]]; then
            print_status "Confirmed: Running on Raspbian Buster"
        else
            print_warning "This script is optimized for Buster but will continue."
        fi
    fi
}

# Function to check Python version
check_python_version() {
    PYTHON_VERSION=$(python3 --version 2>&1 | grep -Po '(?<=Python )\d+\.\d+')
    print_status "Python version: $PYTHON_VERSION"
    if [[ $PYTHON_VERSION == "3.7" ]]; then
        print_status "Confirmed: Python 3.7 is installed"
    else
        print_warning "Expected Python 3.7 but found $PYTHON_VERSION"
    fi
}

# Main setup starts here
print_status "========================================="
print_status "KneeSPA System Setup Script"
print_status "========================================="

# Check system
check_raspberry_pi
check_os_version
check_python_version

# Update package lists (safe - doesn't upgrade anything)
print_status "Updating package lists..."
sudo apt-get update

# Install Python 3.7 development files and pip
print_status "Installing Python 3.7 development tools..."
sudo apt-get install -y \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    python3-venv \
    build-essential

# Upgrade pip, setuptools, and wheel to compatible versions
print_status "Upgrading pip and build tools..."
python3 -m pip install --upgrade pip==21.3.1  # Last version to support Python 3.7
python3 -m pip install --upgrade setuptools==59.8.0 wheel==0.37.1

# Install PyQt5 and related packages via apt (better for RPi)
print_status "Installing PyQt5 system packages..."
sudo apt-get install -y \
    python3-pyqt5 \
    python3-pyqt5.qtmultimedia \
    python3-pyqt5.qtmultimediawidgets \
    python3-pyqt5.qtserialport \
    pyqt5-dev-tools \
    qttools5-dev-tools \
    qtbase5-dev \
    qt5-default \
    libqt5svg5-dev \
    libqt5x11extras5-dev

# Install GPIO and hardware libraries
print_status "Installing GPIO and hardware libraries..."
sudo apt-get install -y \
    python3-rpi.gpio \
    python3-gpiozero \
    python3-smbus \
    python3-spidev \
    i2c-tools \
    python3-serial

# Install OpenCV dependencies (optimized for RPi)
print_status "Installing OpenCV and image processing libraries..."
sudo apt-get install -y \
    python3-opencv \
    libopencv-dev \
    libatlas-base-dev \
    libjasper-dev \
    libqtgui4 \
    libqt4-test \
    libhdf5-dev \
    libharfbuzz-dev

# Install VLC for media playback
print_status "Installing VLC media libraries..."
sudo apt-get install -y \
    vlc \
    libvlc-dev \
    python3-vlc

# Install additional system libraries for Python packages
print_status "Installing additional system dependencies..."
sudo apt-get install -y \
    libxml2-dev \
    libxslt1-dev \
    libffi-dev \
    libssl-dev \
    libopenblas-dev \
    liblapack-dev \
    gfortran \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libwebp-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    tcl8.6-dev \
    tk8.6-dev

# Install database libraries
print_status "Installing database libraries..."
sudo apt-get install -y \
    sqlite3 \
    libsqlite3-dev

# Install email/network libraries
print_status "Installing networking libraries..."
sudo apt-get install -y \
    libcurl4-openssl-dev

# Install Git (if not already installed)
print_status "Installing version control tools..."
sudo apt-get install -y git

# Enable I2C, SPI, and Serial interfaces
print_status "Configuring Raspberry Pi interfaces..."
if command -v raspi-config &> /dev/null; then
    # Enable I2C
    sudo raspi-config nonint do_i2c 0
    # Enable SPI
    sudo raspi-config nonint do_spi 0
    # Enable Serial Port (disable console)
    sudo raspi-config nonint do_serial 2

    print_status "Enabled I2C, SPI, and Serial interfaces"
else
    print_warning "raspi-config not found. Please enable I2C, SPI, and Serial manually."
fi

# Add user to required groups
print_status "Adding user to hardware access groups..."
sudo usermod -a -G gpio,i2c,spi,dialout $USER

# Disable serial console (required for Arduino communication)
print_status "Configuring serial port for Arduino communication..."
if [ -f /boot/cmdline.txt ]; then
    # Backup original
    sudo cp /boot/cmdline.txt /boot/cmdline.txt.backup
    # Remove console=serial0 references
    sudo sed -i 's/console=serial0,115200 //g' /boot/cmdline.txt
    print_status "Serial console disabled (backup saved as cmdline.txt.backup)"
fi

# Stop and disable serial getty service
print_status "Disabling serial getty service..."
sudo systemctl stop serial-getty@serial0.service 2>/dev/null || true
sudo systemctl disable serial-getty@serial0.service 2>/dev/null || true
sudo systemctl stop serial-getty@ttyAMA0.service 2>/dev/null || true
sudo systemctl disable serial-getty@ttyAMA0.service 2>/dev/null || true

# Create virtual environment for the project
print_status "Creating Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_status "Virtual environment created in ./venv"
else
    print_status "Virtual environment already exists"
fi

# Activate virtual environment and install Python packages
print_status "Installing Python packages in virtual environment..."
source venv/bin/activate

# Upgrade pip in virtual environment
pip install --upgrade pip==21.3.1

# Install Python packages from requirements.txt
if [ -f "requirements.txt" ]; then
    print_status "Installing packages from requirements.txt..."
    pip install -r requirements.txt
else
    if [ -f "main/requirements.txt" ]; then
        print_status "Installing packages from main/requirements.txt..."
        pip install -r main/requirements.txt
    else
        print_warning "requirements.txt not found"
    fi
fi

# Create .env file from example if it doesn't exist
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    print_status "Creating .env file from .env.example..."
    cp .env.example .env
    print_warning "Please edit .env file with your actual configuration values"
fi

# Set up log directory
print_status "Setting up log directory..."
mkdir -p logs
chmod 755 logs

# Clean apt cache to free up space
print_status "Cleaning up apt cache..."
sudo apt-get autoremove -y
sudo apt-get autoclean

# System information summary
print_status "========================================="
print_status "System Setup Complete!"
print_status "========================================="
print_status ""
print_status "System Information:"
uname -a
python3 --version
pip --version
print_status ""
print_status "Next Steps:"
print_status "1. Log out and log back in for group changes to take effect"
print_status "2. Edit .env file with your configuration"
print_status "3. Activate virtual environment: source venv/bin/activate"
print_status "4. Run the application: python main/kneespa.py"
print_status ""
print_warning "A reboot is recommended for all changes to take effect"
print_warning "Run: sudo reboot"

# Check if reboot is required
if [ -f /var/run/reboot-required ]; then
    print_warning "System reboot required for some changes to take effect!"
fi

print_status "Script completed successfully!"