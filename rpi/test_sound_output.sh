#!/usr/bin/env bash
set -u

# Interactive Raspberry Pi speaker/VLC diagnostic. Safe to launch from the
# desktop: when no terminal is attached, the script opens one automatically.

SCRIPT_PATH="$(readlink -f -- "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)"
APP_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

open_terminal_if_needed() {
    if [[ -t 0 || "${KNEESPA_SOUND_TEST_TERMINAL:-0}" == "1" ]]; then
        return
    fi

    if command -v lxterminal >/dev/null 2>&1; then
        exec lxterminal --title="KneeSpa Sound Test" \
            -e env KNEESPA_SOUND_TEST_TERMINAL=1 bash "$SCRIPT_PATH"
    fi
    if command -v x-terminal-emulator >/dev/null 2>&1; then
        exec x-terminal-emulator -T "KneeSpa Sound Test" \
            -e env KNEESPA_SOUND_TEST_TERMINAL=1 bash "$SCRIPT_PATH"
    fi
    if command -v xfce4-terminal >/dev/null 2>&1; then
        exec xfce4-terminal --title="KneeSpa Sound Test" \
            --command="env KNEESPA_SOUND_TEST_TERMINAL=1 bash '$SCRIPT_PATH'"
    fi
}

open_terminal_if_needed

REPORT_DIR="${KNEESPA_SOUND_REPORT_DIR:-$HOME/KneeSpa-sound-tests}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
REPORT_PATH="$REPORT_DIR/sound-test-$TIMESTAMP.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT_PATH") 2>&1

finish() {
    local exit_code=$?

    echo
    echo "Report saved to: $REPORT_PATH"
    echo "Send that report back with which tests you could hear."
    if [[ -t 0 && "${KNEESPA_SOUND_TEST_NO_PAUSE:-0}" != "1" ]]; then
        read -r -p "Press Enter to close this window..." _
    fi
    return "$exit_code"
}
trap finish EXIT

heading() {
    echo
    echo "============================================================"
    echo "$1"
    echo "============================================================"
}

command_available() {
    command -v "$1" >/dev/null 2>&1
}

run_limited() {
    local seconds="$1"
    shift

    if command_available timeout; then
        timeout "$seconds" "$@"
        local status=$?
        # timeout=124 is expected for tools that do not exit after one sample.
        [[ $status -eq 124 ]] && return 0
        return "$status"
    fi
    "$@"
}

ask_heard() {
    local prompt="$1"
    local answer

    if [[ ! -t 0 ]]; then
        echo "$prompt Result not entered because no terminal input is available."
        return 2
    fi
    while true; do
        read -r -p "$prompt [y/n]: " answer
        case "${answer,,}" in
            y|yes) return 0 ;;
            n|no) return 1 ;;
            *) echo "Please enter y or n." ;;
        esac
    done
}

answer_text() {
    local status="$1"
    case "$status" in
        0) echo "YES" ;;
        1) echo "NO" ;;
        2) echo "NOT RECORDED" ;;
        *) echo "TEST ERROR" ;;
    esac
}

find_video() {
    local configured="${KNEESPA_SOUND_TEST_VIDEO:-}"
    local candidate

    if [[ -n "$configured" && -f "$configured" ]]; then
        printf '%s\n' "$configured"
        return
    fi
    for candidate in "$APP_DIR"/main/ui/media/videos/*.mp4; do
        if [[ -f "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return
        fi
    done
}

unmute_default_output() {
    heading "Preparing the current default output at 65% volume"
    if command_available wpctl; then
        wpctl set-mute @DEFAULT_AUDIO_SINK@ 0 || true
        wpctl set-volume @DEFAULT_AUDIO_SINK@ 65% || true
        wpctl get-volume @DEFAULT_AUDIO_SINK@ || true
        return
    fi
    if command_available pactl; then
        pactl set-sink-mute @DEFAULT_SINK@ 0 || true
        pactl set-sink-volume @DEFAULT_SINK@ 65% || true
        pactl get-sink-volume @DEFAULT_SINK@ || true
        return
    fi
    if command_available amixer; then
        amixer -q sset Master 65% unmute || true
        amixer -q sset PCM 65% unmute || true
        amixer sget Master 2>/dev/null || amixer sget PCM 2>/dev/null || true
        return
    fi
    echo "No supported volume control was found; leaving volume unchanged."
}

play_system_tone() {
    heading "TEST 1 - Current default speaker output"
    echo "A left/right test tone should play now."
    if command_available speaker-test; then
        run_limited 10 speaker-test -D default -c 2 -t sine -f 880 -l 1
        return $?
    fi
    if command_available aplay && [[ -f /usr/share/sounds/alsa/Front_Center.wav ]]; then
        aplay -D default /usr/share/sounds/alsa/Front_Center.wav
        return $?
    fi
    echo "Neither speaker-test nor the standard ALSA sample is installed."
    echo "Install the Raspberry Pi OS alsa-utils package to enable this test."
    return 127
}

play_video_audio() {
    local device="${1:-}"

    if [[ -z "$VIDEO_PATH" ]]; then
        echo "No KneeSpa MP4 file was found under main/ui/media/videos."
        return 2
    fi
    if ! command_available cvlc; then
        echo "cvlc is not installed; VLC audio cannot be tested."
        return 127
    fi

    echo "Playing the first 20 seconds of: $VIDEO_PATH"
    if [[ -n "$device" ]]; then
        echo "Forced ALSA output: $device"
        run_limited 25 cvlc --intf dummy --no-video --play-and-exit \
            --stop-time=20 -A alsa --alsa-audio-device "$device" "$VIDEO_PATH"
    else
        run_limited 25 cvlc --intf dummy --no-video --play-and-exit \
            --stop-time=20 "$VIDEO_PATH"
    fi
}

heading "KneeSpa Raspberry Pi Sound Test"
echo "This test temporarily unmutes the current output and sets it to 65%."
echo "It does not change KneeSpa files or permanently select a new output."
echo "Repository: $APP_DIR"
echo "User: $(id -un)"
echo "Date: $(date --iso-8601=seconds 2>/dev/null || date)"
echo "OS: $(grep '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d= -f2- || true)"
echo "Kernel: $(uname -srmo)"
echo "Session: ${XDG_SESSION_TYPE:-unknown}"
echo "XDG_RUNTIME_DIR: ${XDG_RUNTIME_DIR:-not set}"

heading "Detected audio outputs"
if command_available wpctl; then
    wpctl status || true
elif command_available pactl; then
    pactl info || true
    pactl list short sinks || true
else
    echo "PipeWire/PulseAudio controls were not found."
fi

echo
echo "ALSA hardware cards:"
if command_available aplay; then
    aplay -l || true
else
    echo "aplay is not installed."
fi

VIDEO_PATH="$(find_video)"
echo
echo "KneeSpa test video: ${VIDEO_PATH:-not found}"

unmute_default_output

SYSTEM_TONE_STATUS=2
if play_system_tone; then
    if ask_heard "Did you hear the speaker test"; then
        SYSTEM_TONE_STATUS=0
    else
        SYSTEM_TONE_STATUS=$?
    fi
else
    echo "The speaker test command reported an error."
    SYSTEM_TONE_STATUS=3
fi

heading "TEST 2 - KneeSpa video audio through VLC's default output"
VLC_DEFAULT_STATUS=2
if play_video_audio; then
    if ask_heard "Did you hear narration or music from the KneeSpa video"; then
        VLC_DEFAULT_STATUS=0
    else
        VLC_DEFAULT_STATUS=$?
    fi
else
    echo "The VLC default-output test reported an error."
    VLC_DEFAULT_STATUS=3
fi

declare -a ALSA_DEVICES=()
declare -a WORKING_DEVICES=()
if command_available aplay; then
    mapfile -t ALSA_DEVICES < <(aplay -L 2>/dev/null | awk '/^sysdefault:/ {print $1}' | sort -u)
fi

if [[ $SYSTEM_TONE_STATUS -ne 0 || $VLC_DEFAULT_STATUS -ne 0 ]]; then
    heading "TEST 3 - Direct HDMI/headphone/USB outputs"
    if [[ ${#ALSA_DEVICES[@]} -eq 0 ]]; then
        echo "No sysdefault ALSA devices were detected."
    else
        echo "The script will try each detected physical output directly."
        for device in "${ALSA_DEVICES[@]}"; do
            echo
            echo "Testing $device"
            if play_video_audio "$device"; then
                if ask_heard "Did you hear the KneeSpa video on $device"; then
                    WORKING_DEVICES+=("$device")
                fi
            else
                echo "VLC could not play through $device."
            fi
        done
    fi
fi

heading "RESULT"
echo "Default speaker tone heard: $(answer_text "$SYSTEM_TONE_STATUS")"
echo "KneeSpa video through default VLC heard: $(answer_text "$VLC_DEFAULT_STATUS")"
if [[ ${#WORKING_DEVICES[@]} -gt 0 ]]; then
    echo "Direct outputs that worked:"
    printf '  %s\n' "${WORKING_DEVICES[@]}"
else
    echo "Direct outputs that worked: none recorded"
fi

echo
if [[ $SYSTEM_TONE_STATUS -eq 0 && $VLC_DEFAULT_STATUS -eq 0 ]]; then
    echo "The Pi speaker path and standalone VLC both work."
    echo "The remaining fault is inside the KneeSpa app/player process."
elif [[ ${#WORKING_DEVICES[@]} -gt 0 ]]; then
    echo "A physical output works, but it is not the current default route."
    echo "The working device name above can be used to configure KneeSpa."
elif [[ $SYSTEM_TONE_STATUS -eq 0 ]]; then
    echo "The default speaker works, but standalone VLC audio does not."
    echo "This points to VLC installation/output configuration."
else
    echo "No working sound route was confirmed. Check powered speakers, cables,"
    echo "and the selected output under the Raspberry Pi desktop speaker icon."
fi
