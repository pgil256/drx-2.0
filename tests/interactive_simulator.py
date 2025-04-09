#!/usr/bin/env python3
"""
Interactive Arduino Simulator

This script provides an interactive Arduino simulator for manual testing.
It allows you to test Arduino communication without physical hardware.

Usage:
    python interactive_simulator.py [--port PORT] [--errors]

Options:
    --port PORT     Use the specified port name (default: MOCK)
    --errors        Enable random error simulation
"""
import sys
import time
import argparse
import threading
import random
from typing import Dict, Any, Optional

# Add project root to path
sys.path.insert(0, ".")

# Import simulator
from tests.fixtures.arduino_simulator import ArduinoSimulator

# Command list for help display
COMMANDS = {
    "help": "Show this help message",
    "status": "Show current simulator state",
    "set <param> <value>": "Set a parameter (position_a, position_b, position_c, pressure)",
    "error <rate>": "Set error rate (0.0-1.0)",
    "disconnect": "Simulate disconnection",
    "reconnect": "Simulate reconnection",
    "pulse": "Toggle pulse mode",
    "monitor": "Toggle command monitoring",
    "reset": "Reset simulator state",
    "exit": "Exit simulator",
}


class InteractiveSimulator:
    """Interactive wrapper for ArduinoSimulator."""
    
    def __init__(self, port: str = "MOCK", enable_errors: bool = False):
        """Initialize the interactive simulator.
        
        Args:
            port: Port name to simulate
            enable_errors: Whether to enable error simulation
        """
        self.simulator = ArduinoSimulator()
        self.simulator.connect(port=port)
        self.should_exit = False
        self.monitoring = True
        
        if enable_errors:
            self.simulator.set_error_conditions(error_rate=0.1, dropped_bytes_rate=0.05)
            
        # Start monitor thread
        self.monitor_thread = threading.Thread(target=self._monitor_simulator)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
    def run(self):
        """Run the interactive simulator main loop."""
        print("=== KneeSpa Interactive Arduino Simulator ===")
        print(f"Simulating port: {self.simulator.serial.port}")
        print("Type 'help' for available commands")
        
        while not self.should_exit:
            try:
                cmd = input("> ").strip()
                self._process_command(cmd)
            except KeyboardInterrupt:
                print("\nExiting...")
                self.should_exit = True
            except Exception as e:
                print(f"Error: {e}")
                
        # Clean up
        if self.simulator:
            self.simulator.disconnect()
            
    def _process_command(self, cmd: str) -> None:
        """Process a command.
        
        Args:
            cmd: Command string to process
        """
        if not cmd:
            return
            
        parts = cmd.split()
        command = parts[0].lower()
        
        if command == "help":
            self._show_help()
        elif command == "status":
            self._show_status()
        elif command == "set" and len(parts) >= 3:
            self._set_parameter(parts[1], parts[2])
        elif command == "error" and len(parts) >= 2:
            self._set_error_rate(parts[1])
        elif command == "disconnect":
            self.simulator.disconnect()
            print("Simulator disconnected")
        elif command == "reconnect":
            self.simulator.connect()
            print("Simulator reconnected")
        elif command == "pulse":
            self.simulator.is_jerking = not self.simulator.is_jerking
            print(f"Pulse mode: {'ON' if self.simulator.is_jerking else 'OFF'}")
        elif command == "monitor":
            self.monitoring = not self.monitoring
            print(f"Command monitoring: {'ON' if self.monitoring else 'OFF'}")
        elif command == "reset":
            self._reset_simulator()
        elif command == "exit":
            self.should_exit = True
        else:
            print("Unknown command. Type 'help' for available commands.")
            
    def _show_help(self) -> None:
        """Show help message."""
        print("\nAvailable commands:")
        for cmd, desc in COMMANDS.items():
            print(f"  {cmd:<20} - {desc}")
        print()
        
    def _show_status(self) -> None:
        """Show current simulator state."""
        print("\n=== Simulator State ===")
        print(f"Position A: {self.simulator.position_a}")
        print(f"Position B: {self.simulator.position_b}")
        print(f"Position C: {self.simulator.position_c}")
        print(f"Pressure:   {self.simulator.pressure:.1f} lbs")
        print(f"Jerking:    {'YES' if self.simulator.is_jerking else 'NO'}")
        
        if self.simulator.serial:
            print(f"Connected:  YES ({self.simulator.serial.port})")
            print(f"Error rate: {self.simulator.serial._error_rate:.2f}")
        else:
            print("Connected:  NO")
        print()
        
    def _set_parameter(self, param: str, value: str) -> None:
        """Set a parameter value.
        
        Args:
            param: Parameter name
            value: New value
        """
        try:
            if param == "position_a":
                self.simulator.position_a = int(value)
            elif param == "position_b":
                self.simulator.position_b = int(value)
            elif param == "position_c":
                self.simulator.position_c = int(value)
            elif param == "pressure":
                self.simulator.pressure = float(value)
            else:
                print(f"Unknown parameter: {param}")
                return
                
            print(f"Set {param} = {value}")
            
        except ValueError:
            print(f"Invalid value: {value}")
            
    def _set_error_rate(self, rate_str: str) -> None:
        """Set error simulation rate.
        
        Args:
            rate_str: Error rate as string (0.0-1.0)
        """
        try:
            rate = float(rate_str)
            if rate < 0 or rate > 1:
                print("Error rate must be between 0.0 and 1.0")
                return
                
            if self.simulator.serial:
                self.simulator.set_error_conditions(error_rate=rate, dropped_bytes_rate=rate/2)
                print(f"Error rate set to {rate:.2f}")
            else:
                print("Simulator is not connected")
                
        except ValueError:
            print(f"Invalid error rate: {rate_str}")
            
    def _reset_simulator(self) -> None:
        """Reset simulator to default state."""
        self.simulator.position_a = 100
        self.simulator.position_b = 200
        self.simulator.position_c = 300
        self.simulator.pressure = 0.0
        self.simulator.is_jerking = False
        print("Simulator state reset")
        
    def _monitor_simulator(self) -> None:
        """Monitor simulator for commands and display them."""
        last_data = b""
        
        while not self.should_exit:
            try:
                if not self.simulator.serial or not self.monitoring:
                    time.sleep(0.1)
                    continue
                    
                # Check for new commands
                data = self.simulator.serial._get_written_data()
                if data:
                    print(f"\nReceived command: {data.decode('utf-8', errors='replace').strip()}")
                    print(">", end=" ", flush=True)
                    
                # Periodically update jerking if enabled
                if self.simulator.is_jerking and random.random() < 0.1:
                    self.simulator._simulate_jerk()
                    
                time.sleep(0.05)
                
            except Exception as e:
                print(f"\nMonitor error: {e}")
                time.sleep(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Interactive Arduino Simulator")
    parser.add_argument("--port", default="MOCK", help="Simulated port name")
    parser.add_argument("--errors", action="store_true", help="Enable random error simulation")
    
    args = parser.parse_args()
    
    simulator = InteractiveSimulator(port=args.port, enable_errors=args.errors)
    simulator.run()


if __name__ == "__main__":
    main()