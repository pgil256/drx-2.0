#!/usr/bin/env bash
set -u

# Collect Raspberry Pi display, touchscreen, USB, and power diagnostics.
# This script is intentionally read-only: it does not reset devices or change
# the display configuration while gathering evidence.

MODE="${1:---baseline}"
case "$MODE" in
    --baseline)
        REPORT_KIND="display-baseline"
        ;;
    --failure)
        REPORT_KIND="display-failure"
        ;;
    *)
        echo "Usage: $0 [--baseline|--failure]" >&2
        exit 2
        ;;
esac

REPORT_DIR="${KNEESPA_DISPLAY_REPORT_DIR:-$HOME/KneeSpa-display-diagnostics}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
REPORT_PATH="$REPORT_DIR/${REPORT_KIND}-${TIMESTAMP}.txt"

mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT_PATH") 2>&1

finish() {
    local exit_code=$?

    echo
    echo "Report saved to: $REPORT_PATH"
    echo "Send this report with the monitor manufacturer/model from its rear label."
    if [[ "$MODE" == "--failure" ]]; then
        echo "Also describe whether the picture, touch, and monitor menu were responsive."
    fi
    if [[ -t 0 && "${KNEESPA_DIAGNOSTICS_NO_PAUSE:-0}" != "1" ]]; then
        read -r -p "Press Enter to close this window..." _
    fi
    return "$exit_code"
}
trap finish EXIT

heading() {
    echo
    echo "=== $1 ==="
}

command_available() {
    command -v "$1" >/dev/null 2>&1
}

print_file_if_present() {
    local path="$1"

    if [[ -r "$path" ]]; then
        cat "$path"
    else
        echo "Not available: $path"
    fi
}

print_usb_inventory() {
    local product_file device_dir manufacturer vendor product

    if command_available lsusb; then
        lsusb || true
        echo
        lsusb -t || true
    else
        echo "lsusb is not installed; using the USB sysfs inventory instead."
    fi

    echo
    echo "USB products reported by the kernel:"
    shopt -s nullglob
    for product_file in /sys/bus/usb/devices/*/product; do
        device_dir="${product_file%/product}"
        product="$(tr -d '\000' < "$product_file" 2>/dev/null || true)"
        manufacturer="unknown"
        vendor="unknown"
        if [[ -r "$device_dir/manufacturer" ]]; then
            manufacturer="$(tr -d '\000' < "$device_dir/manufacturer" 2>/dev/null || true)"
        fi
        if [[ -r "$device_dir/idVendor" && -r "$device_dir/idProduct" ]]; then
            vendor="$(<"$device_dir/idVendor"):$(<"$device_dir/idProduct")"
        fi
        printf '%s  %s  %s  %s\n' "$(basename "$device_dir")" "$vendor" "$manufacturer" "$product"
    done
    shopt -u nullglob
}

print_drm_connectors() {
    local connector status_file edid_file found=0

    shopt -s nullglob
    for connector in /sys/class/drm/card*-HDMI-A-*; do
        found=1
        echo
        echo "Connector: $connector"
        status_file="$connector/status"
        if [[ -r "$status_file" ]]; then
            printf 'Status: '
            cat "$status_file"
        fi

        edid_file="$connector/edid"
        if [[ -s "$edid_file" ]]; then
            if command_available edid-decode; then
                edid-decode "$edid_file" || true
            else
                echo "edid-decode is not installed. Raw EDID (base64) follows:"
                base64 "$edid_file" || true
            fi
        else
            echo "No readable EDID was supplied by this connector."
        fi
    done
    shopt -u nullglob

    if [[ "$found" -eq 0 ]]; then
        echo "No HDMI connector was found under /sys/class/drm."
    fi
}

print_display_state() {
    printf 'Session type: %s\n' "${XDG_SESSION_TYPE:-unknown}"
    printf 'Desktop: %s\n' "${XDG_CURRENT_DESKTOP:-unknown}"
    printf 'DISPLAY: %s\n' "${DISPLAY:-not set}"
    printf 'WAYLAND_DISPLAY: %s\n' "${WAYLAND_DISPLAY:-not set}"

    if command_available kmsprint; then
        echo
        echo "kmsprint:"
        kmsprint || true
    else
        echo "kmsprint is not installed."
    fi

    if command_available xrandr; then
        echo
        echo "xrandr:"
        DISPLAY="${DISPLAY:-:0}" xrandr --current || true
    else
        echo "xrandr is not installed."
    fi
}

print_input_devices() {
    print_file_if_present /proc/bus/input/devices

    if command_available libinput; then
        echo
        echo "libinput:"
        libinput list-devices || true
    else
        echo
        echo "libinput is not installed."
    fi

    echo
    echo "Persistent input-device links:"
    if [[ -d /dev/input/by-id ]]; then
        find -L /dev/input/by-id -maxdepth 1 -type c -printf '%f -> %l\n' 2>/dev/null || true
        ls -l /dev/input/by-id 2>/dev/null || true
    else
        echo "/dev/input/by-id is not present."
    fi
    if [[ -d /dev/input/by-path ]]; then
        ls -l /dev/input/by-path 2>/dev/null || true
    fi
}

print_power_state() {
    if command_available vcgencmd; then
        vcgencmd get_throttled || true
        vcgencmd measure_temp || true
        vcgencmd get_config usb_max_current_enable || true
    else
        echo "vcgencmd is not available."
    fi
}

print_boot_configuration() {
    local config found=0

    for config in /boot/config.txt /boot/firmware/config.txt; do
        if [[ -r "$config" ]]; then
            found=1
            echo
            echo "Config: $config"
            grep -E '^(dtoverlay=vc4|hdmi_|display_|disable_fw_kms|usb_)' "$config" || true
        fi
    done
    if [[ "$found" -eq 0 ]]; then
        echo "No readable Raspberry Pi boot config was found."
    fi
}

print_recent_kernel_events() {
    local pattern
    pattern='usb|hid|touch|drm|hdmi|voltage|current|disconnect|reset|over-current|error'

    if command_available journalctl; then
        journalctl -k -b --since '-30 min' --no-pager 2>&1 \
            | grep -Ei "$pattern" \
            | tail -n 300 || true
    elif command_available dmesg; then
        dmesg -T 2>&1 | grep -Ei "$pattern" | tail -n 300 || true
    else
        echo "Neither journalctl nor dmesg is available."
    fi
}

echo "KneeSpa display diagnostics"
printf 'Mode: %s\n' "$MODE"
printf 'Collected: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"

heading "PI MODEL"
if [[ -r /proc/device-tree/model ]]; then
    tr -d '\000' < /proc/device-tree/model
    echo
else
    echo "Pi model is unavailable."
fi

heading "OS AND KERNEL"
print_file_if_present /etc/os-release
uname -srmo || true
printf 'Userspace bits: '
getconf LONG_BIT 2>/dev/null || echo "unknown"

heading "POWER HEALTH"
print_power_state

heading "DISPLAY SESSION"
print_display_state

heading "HDMI MONITOR AND EDID"
print_drm_connectors

heading "USB DEVICES"
print_usb_inventory

heading "INPUT AND TOUCH DEVICES"
print_input_devices

if [[ "$MODE" == "--baseline" ]]; then
    heading "RELEVANT BOOT CONFIGURATION"
    print_boot_configuration
fi

heading "RECENT RELEVANT KERNEL EVENTS"
print_recent_kernel_events

if [[ "$MODE" == "--failure" ]]; then
    heading "OBSERVATIONS TO INCLUDE WHEN SENDING THIS REPORT"
    echo "Picture: updating / frozen / black"
    echo "Touch: responsive / unresponsive"
    echo "Monitor physical menu: responsive / unresponsive"
    echo "Monitor power LED: color and steady/blinking/off"
    echo "SSH or VNC: reachable / unreachable / not tested"
    echo "Result of unplugging HDMI only:"
    echo "Result of unplugging USB data only:"
fi
