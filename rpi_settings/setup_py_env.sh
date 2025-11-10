#!/bin/bash
# Setup script for KneeSpa environment
# Fixes NumPy/OpenCV compatibility issues

echo "Setting up KneeSpa environment..."

# Stop script on any error
set -e

# Update system
echo "Updating system packages..."
sudo apt-get update
sudo apt-get -y upgrade

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get install -y \
    python3-pip \
    python3-dev \
    libatlas-base-dev \
    vlc \
    libvlc-dev \
    python3-vlc \
    python3-opencv

# Uninstall any existing numpy and opencv to avoid conflicts
echo "Removing any existing NumPy and OpenCV installations..."
pip3 uninstall -y numpy
pip3 uninstall -y opencv-python

# Install compatible versions from pip
echo "Installing compatible NumPy and OpenCV versions..."
pip3 install numpy==1.20.3
pip3 install opencv-python==4.5.5.64

# Install other Python dependencies
echo "Installing other Python dependencies..."
pip3 install -r requirements.txt


echo "Environment setup complete!"
echo "You can now run the application with: python3 main/kneespa.py"