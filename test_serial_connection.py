#!/usr/bin/env python3
"""
Simple serial connection test for Arduino communication
This script helps debug serial communication issues between Raspberry Pi and Arduino
"""

import serial
import time
import sys

def test_serial_connection():
    """Test basic serial communication with Arduino."""

    port = "/dev/serial0"
    baud_rate = 115200

    print("=" * 60)
    print("ARDUINO SERIAL CONNECTION TEST")
    print("=" * 60)
    print(f"Port: {port}")
    print(f"Baud Rate: {baud_rate}")
    print("-" * 60)

    try:
        # Open serial connection
        print("\n1. Opening serial connection...")
        ser = serial.Serial(port, baud_rate, timeout=2)
        print(f"   ✓ Serial port opened successfully")

        # Wait for Arduino to initialize
        print("\n2. Waiting for Arduino to initialize (5 seconds)...")
        time.sleep(5)

        # Clear any startup messages
        print("\n3. Clearing input buffer...")
        ser.reset_input_buffer()
        print("   ✓ Buffer cleared")

        # Read any initial messages
        print("\n4. Reading any startup messages (2 second timeout)...")
        ser.timeout = 2
        while ser.in_waiting > 0:
            data = ser.readline().decode('utf-8', errors='replace').strip()
            if data:
                print(f"   Received: {data}")

        # Send test command
        print("\n5. Sending 'T' test command...")
        ser.reset_input_buffer()  # Clear buffer before sending
        ser.write(b"T\n")
        ser.flush()
        print("   ✓ Command sent")

        # Wait for response
        print("\n6. Waiting for response (10 second timeout)...")
        ser.timeout = 10
        response_received = False
        start_time = time.time()

        while time.time() - start_time < 10:
            if ser.in_waiting > 0:
                response = ser.readline().decode('utf-8', errors='replace').strip()
                print(f"   Received: '{response}'")

                if "OK" in response:
                    print("   ✓ OK response received!")
                    response_received = True
                    break
                elif response:
                    print(f"   Note: Received '{response}' instead of 'OK'")
            time.sleep(0.1)

        if not response_received:
            print("   ✗ No OK response received within timeout")

        # Try DTR reset
        print("\n7. Testing DTR reset...")
        print("   Setting DTR low (reset)...")
        ser.dtr = False
        time.sleep(0.1)
        ser.dtr = True
        print("   DTR set high")
        print("   Waiting 5 seconds for Arduino to restart...")
        time.sleep(5)

        # Clear and read any post-reset messages
        print("\n8. Reading post-reset messages...")
        ser.reset_input_buffer()
        time.sleep(1)
        while ser.in_waiting > 0:
            data = ser.readline().decode('utf-8', errors='replace').strip()
            if data:
                print(f"   Received: {data}")

        # Final test command after reset
        print("\n9. Sending final 'T' test command after reset...")
        ser.reset_input_buffer()
        ser.write(b"T\n")
        ser.flush()

        ser.timeout = 5
        final_response = ser.readline().decode('utf-8', errors='replace').strip()
        if final_response:
            print(f"   Received: '{final_response}'")
            if "OK" in final_response:
                print("   ✓ Communication successful after reset!")
            else:
                print(f"   Note: Received '{final_response}' instead of 'OK'")
        else:
            print("   ✗ No response after reset")

        # Close connection
        print("\n10. Closing serial connection...")
        ser.close()
        print("    ✓ Connection closed")

        print("\n" + "=" * 60)
        print("TEST COMPLETE")
        print("=" * 60)

        if response_received:
            print("\n✅ Serial communication is working!")
            print("\nThe Python application should now be able to connect.")
        else:
            print("\n⚠️  Serial communication issues detected.")
            print("\nPossible solutions:")
            print("1. Check that Arduino Serial1 is connected to Pi serial pins")
            print("2. Verify Arduino code sends 'OK' to Serial1 for 'T' command")
            print("3. Check /dev/serial0 permissions (try: sudo chmod 666 /dev/serial0)")
            print("4. Ensure getty service is disabled:")
            print("   sudo systemctl stop serial-getty@serial0.service")
            print("   sudo systemctl disable serial-getty@serial0.service")
            print("5. Try a different baud rate (9600 on both sides)")
            print("6. Check wiring:")
            print("   - Arduino TX1 (pin 1) → Pi RX (GPIO 15/pin 10)")
            print("   - Arduino RX1 (pin 0) → Pi TX (GPIO 14/pin 8)")
            print("   - Common ground between Arduino and Pi")

    except serial.SerialException as e:
        print(f"\n❌ ERROR: Could not open serial port: {e}")
        print("\nTroubleshooting:")
        print("1. Check if port exists: ls -la /dev/serial*")
        print("2. Check permissions: sudo chmod 666 /dev/serial0")
        print("3. Ensure serial is enabled in raspi-config")
        print("4. Check if another process is using the port:")
        print("   sudo lsof /dev/serial0")
        return 1

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(test_serial_connection())