#!/bin/bash
# Script to fix NumPy and OpenCV issues in a virtual environment

echo "Fixing NumPy and OpenCV installation..."

# Check if virtual environment is active
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "Error: No virtual environment is active!"
    echo "Please activate your virtual environment first with:"
    echo "  source kneespa_env/bin/activate"
    exit 1
fi

echo "Virtual environment detected: $VIRTUAL_ENV"
echo "Uninstalling existing NumPy and OpenCV..."

# Uninstall any existing packages that might cause conflicts
pip uninstall -y numpy opencv-python

echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-dev libatlas-base-dev

echo "Installing NumPy first with specific version..."
pip install numpy==1.20.3

echo "Verifying NumPy installation..."
python3 -c "import numpy; print(f'NumPy version: {numpy.__version__}')"

echo "Installing OpenCV with compatible version..."
pip install opencv-python==4.5.5.64

echo "Verifying OpenCV installation..."
python3 -c "import cv2; print(f'OpenCV version: {cv2.__version__}')"

echo "Installation complete!"
echo "Now run your application with: python3 kneespa.py --debug"