#!/usr/bin/env python3
"""
Simple script to test the Arduino simulator.
"""
import os
import sys
import time

# Add the project root directory to the Python path
sys.path.insert(0, os.path.abspath('.'))

from tests.fixtures.arduino_simulator import ArduinoSimulator
from tests.fixtures.arduino_mock import ArduinoTestFixture

def main():
    print("Testing Arduino simulator...")
    
    # Create the simulator
    simulator = ArduinoSimulator()
    simulator.connect()
    
    print(f"Simulator created and connected to port: {simulator.serial.port}")
    
    # Send a test command
    print("Sending test command 'T'...")
    simulator.serial._put_data_in_buffer(b"T\n")
    time.sleep(0.1)
    
    # Get the response
    written_data = simulator.serial._get_written_data()
    if written_data:
        print(f"Received data: {written_data.decode('utf-8', errors='replace')}")
    else:
        print("No data received")
    
    # Set the simulator state
    simulator.set_device_state(position_a=100, position_b=200, position_c=300, pressure=30.0)
    print(f"Set simulator state: A={simulator.position_a}, B={simulator.position_b}, "
          f"C={simulator.position_c}, Pressure={simulator.pressure}")
    
    # Test status command
    print("Testing status command...")
    simulator._handle_status()
    time.sleep(0.1)
    
    # Clean up
    simulator.disconnect()
    print("Simulator disconnected")
    
    print("\nTesting Arduino mock fixture...")
    
    # Create the test fixture
    fixture = ArduinoTestFixture()
    arduino, sim = fixture.setup()
    
    print(f"Arduino mock created with simulator")
    
    # Connect the Arduino
    print("Running Arduino connection...")
    arduino.run()
    time.sleep(1)
    
    print(f"Arduino connected: {arduino.connected}")
    print(f"Arduino port: {arduino.current_port}")
    
    # Send a command
    print("Sending command 'T'...")
    result = arduino.send("T")
    print(f"Send result: {result}")
    time.sleep(0.5)
    
    # Send a status command
    print("Sending status command 'S'...")
    result = arduino.send("S")
    print(f"Send result: {result}")
    time.sleep(0.5)
    
    # Clean up
    fixture.teardown()
    print("Arduino mock fixture torn down")
    
    print("\nTest completed successfully!")

if __name__ == "__main__":
    main()