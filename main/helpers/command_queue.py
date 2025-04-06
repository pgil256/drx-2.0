from collections import deque
from datetime import datetime
import threading
import time
import logging
from utils.logging import setup_logger

class CommandQueueHandler:
    def __init__(self):
        self.logger = setup_logger(component='Command Queue')
        self._command_queue = deque()
        self._is_processing = False
        self._lock = threading.Lock()
        self._last_command_time = None
        self._min_command_interval = 0.5  # 500ms minimum between commands
        
    def add_command(self, command: str) -> bool:
        """
        Attempt to add command to queue if conditions allow.
        Returns True if command was added, False if rejected.
        """
        with self._lock:
            current_time = datetime.now()
            
            # Check if enough time has passed since last command
            if self._last_command_time:
                time_diff = (current_time - self._last_command_time).total_seconds()
                if time_diff < self._min_command_interval:
                    return False
                    
            # Add command to queue
            self._command_queue.append((command, current_time))
            self._last_command_time = current_time
            return True
            
    def get_next_command(self) -> str:
        """Get next command if available and conditions allow."""
        with self._lock:
            if not self._command_queue or self._is_processing:
                return None
                
            self._is_processing = True
            command, timestamp = self._command_queue.popleft()
            return command
            
    def command_completed(self):
        """Mark current command as completed."""
        with self._lock:
            self._is_processing = False
            
    def clear_queue(self):
        """Clear all pending commands."""
        with self._lock:
            self._command_queue.clear()
            self._is_processing = False
            
    @property
    def is_busy(self) -> bool:
        """Check if currently processing a command."""
        return self._is_processing or len(self._command_queue) > 0
