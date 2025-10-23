#!/bin/bash

# --- Configuration ---
# WARNING: Storing passwords in scripts is a security risk.
# Source directory on your Windows machine (format for WSL/Git Bash)
SOURCE_DIR="/mnt/c/Users/user/Desktop/drx/main/"

# Destination directory on the Raspberry Pi devices
DEST_DIR="/home/pi/drx-2.3/main/"

# Array of Raspberry Pi IP addresses
PI_HOSTS=("100.111.162.21" "100.93.117.101" "100.95.232.121")

# Credentials
USER="pi"
PASS="Abbygal01"

# --- Sync Logic ---
echo "Starting sync process..."

for host in "${PI_HOSTS[@]}"; do
    echo "----------------------------------------"
    echo "🔄 Syncing to $host..."
    sshpass -p "$PASS" rsync -avzu --progress -e 'ssh -o StrictHostKeyChecking=no' "$SOURCE_DIR" "$USER@$host:$DEST_DIR"
    echo "✅ Sync to $host complete."
    echo "----------------------------------------"
done

echo "All devices have been synced."