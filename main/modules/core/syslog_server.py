#!/usr/bin/env python3
"""
KneeSpa Syslog Server

This script runs a syslog server to collect logs from KneeSpa devices.
Run this on your development machine to collect logs from remote devices.


Usage:
  python -m main.modules.core.syslog_server [--host HOST] [--port PORT] [--output FILE]
"""
import sys
import os
import argparse
import signal
import time
from datetime import datetime

from main.modules.utils.remote_logging import (
    create_syslog_server, 
    ThreadedSysLogServer,
    DEFAULT_HOST, 
    DEFAULT_PORT
)

def main():
    """Main function to run the syslog server"""
    parser = argparse.ArgumentParser(description="KneeSpa Syslog Server")
    parser.add_argument("--host", default=DEFAULT_HOST, 
                        help=f"Host to bind to (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, 
                        help=f"Port to listen on (default: {DEFAULT_PORT})")
    parser.add_argument("--max-logs", type=int, default=10000, 
                        help="Maximum number of logs to keep in memory")
    parser.add_argument("--no-console", action="store_true", 
                        help="Disable console output")
    parser.add_argument("--output", type=str, 
                        help="Write logs to file (in addition to console)")
    
    args = parser.parse_args()
    
    # Create and start server
    server = create_syslog_server(args.host, args.port, args.max_logs, not args.no_console)
    
    # Set up output file if specified
    output_file = None
    if args.output:
        try:
            output_dir = os.path.dirname(args.output)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
            output_file = open(args.output, 'a')
            print(f"Writing logs to {args.output}")
        except Exception as e:
            print(f"Error opening output file: {e}")
            output_file = None
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\nShutting down...")
        if output_file:
            output_file.close()
        server.stop()
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    
    print(f"Syslog server started on {args.host}:{args.port}")
    print("Press Ctrl+C to stop the server")
    
    # Keep main thread alive and periodically write logs to file if specified
    last_log_count = 0
    try:
        while True:
            time.sleep(1)
            
            # Write new logs to file if output file is specified
            if output_file:
                logs = server.get_logs()
                if len(logs) > last_log_count:
                    new_logs = logs[last_log_count:]
                    for log in new_logs:
                        output_file.write(log + "\n")
                    output_file.flush()
                    last_log_count = len(logs)
    except KeyboardInterrupt:
        if output_file:
            output_file.close()
        server.stop()

if __name__ == "__main__":
    main()