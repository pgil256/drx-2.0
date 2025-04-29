"""
Protocol Runner Module
Handles the execution of protocol sequences with asyncio support
"""
from datetime import datetime
import time
import threading
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, Callable, Coroutine
from PyQt5 import QtCore
from PyQt5.QtCore import QRunnable, QThreadPool, QObject, pyqtSignal, pyqtSlot

from main.modules.protocols.protocol_settings import ProtocolSettings
from main.modules.utils.logging_utils import get_logger_with_context, timed, Timer
from main.modules.utils.performance_metrics import profiler
from main.config.constants import (
    DEGREES0, MIN_PRESSURE, MAX_SAFE_PRESSURE, 
    HOLD_TIME_SHORT, HOLD_TIME_LONG, PRESSURE_INCREMENT, 
    ANGLE_INCREMENT, DEFAULT_TIMEOUT, CYCLE_DURATION,
    WARMUP_DURATION, COOLDOWN_DURATION, PULSE_INTERVAL_DEFAULT,
    PULSE_COUNT_DEFAULT
)

class WorkerSignals(QObject):
    """Signals for protocol worker thread"""
    started = pyqtSignal(str, int)  # (protocol_name, duration_seconds)
    stopped = pyqtSignal(str, bool)  # (protocol_name, completed_successfully)
    status = pyqtSignal(str, int, int)  # (protocol_name, elapsed_seconds, remaining_seconds)
    pressure = pyqtSignal(int)  # (current_pressure)
    angle = pyqtSignal(float, str)  # (current_angle, side)
    message = pyqtSignal(str)  # (status_message)
    error = pyqtSignal(str)  # (error_message)
    progress = pyqtSignal(int, str)  # (percent_complete, current_operation)
    timeout = pyqtSignal(str)  # (operation_name)
    cancellation_complete = pyqtSignal()  # Emitted when cancellation is completed

class ProtocolRunner(QRunnable):
    """
    Protocol runner for executing treatment sequences with async support
    
    This class handles the actual execution of protocols, including
    timing, pressure control, and movement sequences with proper handling
    of async operations, cancellation, and progress reporting.
    """
    
    def __init__(
        self,
        a_factor: float,
        protocol: str,
        max_pressure: int,
        max_left: float,
        max_right: float,
        duration: int,
        use_pulse: bool = False,
        pulse_interval: int = 5,
        arduino_controller = None
    ):
        """
        Initialize the protocol runner
        
        Args:
            a_factor: The axial actuator factor for positioning
            protocol: The protocol identifier (1, 2, or 3)
            max_pressure: Maximum pressure in pounds
            max_left: Maximum left angle in degrees
            max_right: Maximum right angle in degrees
            duration: Duration in minutes
            use_pulse: Whether to use pulsing
            pulse_interval: Pulse interval in seconds
            arduino_controller: Arduino controller instance
        """
        super().__init__()
        
        # Set up structured logger with component context
        self.logger = get_logger_with_context(
            component="ProtocolRunner",
            protocol=protocol
        )
        
        self.signals = WorkerSignals()
        
        # Store parameters
        self.a_factor = a_factor
        self.protocol = protocol
        self.max_pressure = max_pressure if max_pressure else 40
        self.max_left = max_left if max_left else 20.0
        self.max_right = max_right if max_right else 20.0
        self.duration = duration if duration else 15
        self.use_pulse = use_pulse
        self.pulse_interval = pulse_interval if pulse_interval else 5
        
        # Initialize controller
        self.arduino_controller = arduino_controller
        
        # State variables
        self.is_running = False
        self.stop_requested = False
        self.paused = False
        self.current_pressure = 0
        self.current_angle = 0
        self.current_side = "center"  # "left", "right", or "center"
        self.start_time = None
        self.elapsed_seconds = 0
        
        # Async handling variables
        self.loop = None
        self.current_task = None
        self.thread_pool = ThreadPoolExecutor(max_workers=2)
        self.timeout_handle = None
        self.current_operation = "initializing"
        self.total_steps = 0
        self.current_step = 0
        
        # Performance metrics
        self.progress_percent = 0
        self.operation_durations = {}
        self.operation_start_time = None
        self.operation_name = None
        
        self.logger.info(
            f"Protocol runner initialized", 
            structured_data={
                "protocol": protocol,
                "max_pressure": max_pressure,
                "max_left": max_left,
                "max_right": max_right,
                "duration": duration,
                "use_pulse": use_pulse
            }
        )
    
    @pyqtSlot()
    @timed("protocol_execution")
    def run(self):
        """Run the protocol using asyncio"""
        operation_timer = profiler.start_timer("protocol.run", {
            "protocol": self.protocol,
            "duration": self.duration
        })
        
        self.logger.info(f"Starting protocol {self.protocol}")
        
        try:
            # Initialize state
            self.is_running = True
            self.stop_requested = False
            self.paused = False
            self.current_pressure = 0
            self.current_angle = 0
            self.current_side = "center"
            self.start_time = datetime.now()
            self.elapsed_seconds = 0
            
            # Set up asyncio event loop in this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Emit started signal
            self.signals.started.emit(f"Protocol {self.protocol}", self.duration * 60)
            
            # Determine total steps for progress tracking
            self._calculate_total_steps()
            
            # Log protocol start with detailed parameters
            self.logger.info(
                f"Protocol {self.protocol} execution started", 
                structured_data={
                    "protocol": self.protocol,
                    "duration_minutes": self.duration,
                    "max_pressure": self.max_pressure,
                    "max_left_angle": self.max_left,
                    "max_right_angle": self.max_right,
                    "use_pulse": self.use_pulse,
                    "pulse_interval": self.pulse_interval
                }
            )
            
            # Run the appropriate protocol using asyncio
            if self.protocol == "1":
                self.loop.run_until_complete(self._run_protocol_1_async())
            elif self.protocol == "2":
                self.loop.run_until_complete(self._run_protocol_2_async())
            elif self.protocol == "3":
                self.loop.run_until_complete(self._run_protocol_3_async())
            else:
                raise ValueError(f"Unknown protocol: {self.protocol}")
                
        except asyncio.CancelledError:
            self.logger.info("Protocol execution was cancelled")
            self.signals.message.emit("Protocol cancelled")
        except asyncio.TimeoutError:
            self.logger.error("Protocol execution timed out")
            self.signals.message.emit("Protocol timed out")
            self.signals.error.emit("Protocol execution timed out")
        except Exception as e:
            self.logger.error(
                f"Error running protocol",
                structured_data={
                    "error": str(e),
                    "protocol": self.protocol
                },
                exc_info=True
            )
            self.signals.error.emit(f"Protocol error: {str(e)}")
            self.signals.stopped.emit(f"Protocol {self.protocol}", False)
            
        finally:
            # Ensure cleanup happens
            self._cleanup()
            
            # Clean up asyncio resources
            if self.loop and not self.loop.is_closed():
                self.loop.close()
            
            # Stop and log timer
            if operation_timer:
                duration_ms = profiler.stop_timer(operation_timer)
                if duration_ms:
                    self.logger.info(
                        f"Protocol {self.protocol} execution completed",
                        structured_data={
                            "duration_ms": duration_ms,
                            "protocol": self.protocol,
                            "completed_successfully": not self.stop_requested
                        }
                    )
    
    def stop(self, force=False):
        """
        Stop the protocol execution with proper cancellation
        
        Args:
            force: Whether to force stop immediately
        """
        self.logger.info(
            f"Stopping protocol",
            structured_data={
                "force": force,
                "protocol": self.protocol,
                "elapsed_seconds": self.elapsed_seconds
            }
        )
        
        self.stop_requested = True
        
        # Cancel any running async tasks
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
        
        if force and self.arduino_controller:
            # Immediately stop actuators
            self.arduino_controller.stop_all_actuators()
            self.signals.cancellation_complete.emit()
        else:
            # Handle graceful shutdown
            if self.loop and not self.loop.is_closed():
                try:
                    asyncio.run_coroutine_threadsafe(self._graceful_shutdown(), self.loop)
                except Exception as e:
                    self.logger.error(
                        f"Error during graceful shutdown",
                        structured_data={"error": str(e)},
                        exc_info=True
                    )
                    self.signals.cancellation_complete.emit()
    
    async def _graceful_shutdown(self):
        """Handle graceful shutdown of protocol"""
        shutdown_timer = profiler.start_timer("protocol.graceful_shutdown")
        
        self.signals.message.emit("Gracefully stopping protocol...")
        self.logger.info("Performing graceful shutdown")
        
        try:
            # Reset to safe positions
            await self._set_angle_async(DEGREES0, "center", progress_weight=50)
            await self._apply_pressure_async(0, progress_weight=50)
            
            # Emit completion
            self.signals.cancellation_complete.emit()
            self.logger.info("Graceful shutdown completed successfully")
        except Exception as e:
            self.logger.error(
                f"Error during graceful shutdown",
                structured_data={"error": str(e)},
                exc_info=True
            )
            self.signals.cancellation_complete.emit()
        finally:
            if shutdown_timer:
                profiler.stop_timer(shutdown_timer)
    
    def pause(self):
        """Pause the protocol execution"""
        self.logger.info("Pausing protocol")
        self.paused = True
        self.signals.message.emit("Protocol paused")
        
        # Record pause metric
        profiler.increment("protocol.pauses", 1, {
            "protocol": self.protocol, 
            "elapsed_seconds": self.elapsed_seconds
        })
    
    def resume(self):
        """Resume the protocol execution"""
        self.logger.info("Resuming protocol")
        self.paused = False
        self.signals.message.emit("Protocol resumed")
        
        # Record resume metric
        profiler.increment("protocol.resumes", 1, {
            "protocol": self.protocol, 
            "elapsed_seconds": self.elapsed_seconds
        })
    
    def _calculate_total_steps(self):
        """Calculate total steps for progress tracking"""
        # Estimate steps based on protocol type and duration
        base_steps = 20  # Basic operations: init, warmup, cooldown
        cycles_per_minute = 1.5  # Estimated cycles per minute
        estimated_cycles = self.duration * cycles_per_minute
        
        steps_per_cycle = 10  # Each cycle has pressure changes, angle changes, holds
        
        # Add protocol-specific steps
        if self.protocol == "1":
            steps_per_cycle = 8  # Simpler protocol
        elif self.protocol == "2" or self.protocol == "3":
            steps_per_cycle = 12  # More complex with angle changes
            if self.use_pulse:
                steps_per_cycle += 3  # More steps for pulsing
                
        self.total_steps = base_steps + (estimated_cycles * steps_per_cycle)
        self.current_step = 0
        
        self.logger.debug(
            f"Progress tracking initialized",
            structured_data={
                "total_steps": self.total_steps,
                "estimated_cycles": estimated_cycles,
                "steps_per_cycle": steps_per_cycle
            }
        )
    
    async def _run_protocol_1_async(self):
        """Run Protocol 1: Axial Pressure Only using async/await"""
        protocol_timer = profiler.start_timer("protocol.run_protocol_1")
        
        self.logger.info("Running Protocol 1 (Axial Pressure Only)")
        self.signals.message.emit("Starting Protocol 1: Axial Pressure Only")
        self.current_operation = "initialization"
        
        # Track progress
        self._update_progress(5, "initialization")
        
        # Create task for monitoring timeouts
        self._start_timeout_monitor()
        
        try:
            # Warm-up phase
            self.current_operation = "warm-up"
            await self._run_warmup_async()
            
            if self.stop_requested:
                return
                
            # Main treatment phase
            self.signals.message.emit("Applying axial pressure")
            self.current_operation = "main treatment"
            
            # Calculate number of cycles based on duration
            remaining_seconds = (self.duration * 60) - self.elapsed_seconds
            cycle_time = CYCLE_DURATION.get("1", 30)  # seconds per cycle from constants
            cycles = max(1, int(remaining_seconds / cycle_time))
            
            # Log cycle plan
            self.logger.info(
                f"Starting main treatment phase",
                structured_data={
                    "cycles": cycles,
                    "cycle_time_seconds": cycle_time,
                    "remaining_seconds": remaining_seconds,
                    "use_pulse": self.use_pulse
                }
            )
            
            # Allocate progress - 5% already used, 10% for warmup, 10% for cooldown
            # Remaining 75% for main treatment
            progress_per_cycle = 75 / cycles if cycles > 0 else 0
            
            # Set to center position and stay there
            await self._set_angle_async(DEGREES0, "center")
            await self._hold_async(HOLD_TIME_SHORT)
            
            for cycle in range(cycles):
                if self.stop_requested:
                    return
                    
                cycle_timer = profiler.start_timer(
                    "protocol.cycle", 
                    {"protocol": "1", "cycle": cycle+1, "total_cycles": cycles}
                )
                
                # Log cycle start
                self.logger.debug(
                    f"Starting cycle {cycle+1}/{cycles}",
                    structured_data={
                        "cycle": cycle+1,
                        "total_cycles": cycles
                    }
                )
                
                # Update timers
                await self._update_timer_async()
                
                self.current_operation = f"cycle {cycle+1}/{cycles}: applying pressure"
                # Apply axial pressure with progress weighting
                await self._apply_pressure_async(
                    self.max_pressure, 
                    progress_weight=progress_per_cycle * 0.3
                )
                
                self.current_operation = f"cycle {cycle+1}/{cycles}: holding pressure"
                # Hold with pressure
                await self._hold_async(
                    HOLD_TIME_LONG, 
                    progress_weight=progress_per_cycle * 0.2
                )
                
                # Pulse if requested
                if self.use_pulse:
                    self.current_operation = f"cycle {cycle+1}/{cycles}: pulsing"
                    await self._pulse_pressure_async(
                        pulses=2, 
                        interval=3, 
                        progress_weight=progress_per_cycle * 0.3
                    )
                else:
                    # Additional hold if not pulsing
                    await self._hold_async(
                        HOLD_TIME_LONG, 
                        progress_weight=progress_per_cycle * 0.3
                    )
                    
                # Final hold for this cycle
                await self._hold_async(
                    HOLD_TIME_LONG, 
                    progress_weight=progress_per_cycle * 0.2
                )
                
                # Report cycle progress
                self._update_progress(
                    int(15 + (cycle+1) * progress_per_cycle), 
                    f"Completed cycle {cycle+1}/{cycles}"
                )
                
                # Stop and log cycle timer
                if cycle_timer:
                    cycle_duration = profiler.stop_timer(cycle_timer)
                    if cycle_duration:
                        self.logger.debug(
                            f"Completed cycle {cycle+1}/{cycles}",
                            structured_data={
                                "cycle": cycle+1,
                                "duration_ms": cycle_duration
                            }
                        )
            
            # Cooldown phase
            self.current_operation = "cooldown"
            await self._run_cooldown_async()
            
            # Protocol complete
            if not self.stop_requested:
                self._update_progress(100, "Protocol complete")
                self.signals.message.emit("Protocol 1 complete")
                self.signals.stopped.emit(f"Protocol {self.protocol}", True)
                
                # Log completion metrics
                self.logger.info(
                    f"Protocol 1 completed successfully",
                    structured_data={
                        "elapsed_seconds": self.elapsed_seconds,
                        "cycles_completed": cycles,
                        "operation_durations": self.operation_durations
                    }
                )
                
        finally:
            # Cancel timeout monitor
            self._cancel_timeout_monitor()
            
            # Stop protocol timer
            if protocol_timer:
                protocol_duration = profiler.stop_timer(protocol_timer)
                if protocol_duration:
                    self.logger.info(
                        f"Protocol 1 execution finished",
                        structured_data={
                            "duration_ms": protocol_duration,
                            "completed_successfully": not self.stop_requested
                        }
                    )
    
    async def _run_protocol_2_async(self):
        """Run Protocol 2: Left Angle with Pressure using async/await"""
        protocol_timer = profiler.start_timer("protocol.run_protocol_2")
        
        self.logger.info("Running Protocol 2 (Left Angle with Pressure)")
        self.signals.message.emit("Starting Protocol 2: Left Angle with Pressure")
        self.current_operation = "initialization"
        
        # Track progress
        self._update_progress(5, "initialization")
        
        # Create task for monitoring timeouts
        self._start_timeout_monitor()
        
        try:
            # Warm-up phase
            self.current_operation = "warm-up"
            await self._run_warmup_async()
            
            if self.stop_requested:
                return
                
            # Main treatment phase
            self.signals.message.emit("Left angle treatment with pressure")
            self.current_operation = "main treatment"
            
            # Calculate number of cycles based on duration
            remaining_seconds = (self.duration * 60) - self.elapsed_seconds
            cycle_time = CYCLE_DURATION.get("2", 40)  # seconds per cycle from constants
            cycles = max(1, int(remaining_seconds / cycle_time))
            
            # Log cycle plan
            self.logger.info(
                f"Starting main treatment phase",
                structured_data={
                    "cycles": cycles,
                    "cycle_time_seconds": cycle_time,
                    "remaining_seconds": remaining_seconds,
                    "max_left_angle": self.max_left,
                    "use_pulse": self.use_pulse
                }
            )
            
            # Allocate progress - 5% already used, 10% for warmup, 10% for cooldown
            # Remaining 75% for main treatment
            progress_per_cycle = 75 / cycles if cycles > 0 else 0
            
            for cycle in range(cycles):
                if self.stop_requested:
                    return
                
                cycle_timer = profiler.start_timer(
                    "protocol.cycle", 
                    {"protocol": "2", "cycle": cycle+1, "total_cycles": cycles}
                )
                
                # Log cycle start
                self.logger.debug(
                    f"Starting cycle {cycle+1}/{cycles}",
                    structured_data={
                        "cycle": cycle+1,
                        "total_cycles": cycles
                    }
                )
                
                # Update timers
                await self._update_timer_async()
                
                # Step 1: Apply pressure first
                self.current_operation = f"cycle {cycle+1}/{cycles}: applying pressure"
                await self._apply_pressure_async(
                    self.max_pressure,
                    progress_weight=progress_per_cycle * 0.2
                )
                await self._hold_async(
                    HOLD_TIME_SHORT,
                    progress_weight=progress_per_cycle * 0.1
                )
                
                # Step 2: Set angle to left
                self.current_operation = f"cycle {cycle+1}/{cycles}: setting left angle"
                await self._set_angle_async(
                    self.max_left,
                    "left",
                    progress_weight=progress_per_cycle * 0.2
                )
                await self._hold_async(
                    HOLD_TIME_LONG,
                    progress_weight=progress_per_cycle * 0.2
                )
                
                # Step 3: Pulse if requested
                if self.use_pulse:
                    self.current_operation = f"cycle {cycle+1}/{cycles}: pulsing"
                    await self._pulse_pressure_async(
                        pulses=3,
                        interval=2,
                        progress_weight=progress_per_cycle * 0.2
                    )
                
                # Step 4: Hold with pressure and angle
                self.current_operation = f"cycle {cycle+1}/{cycles}: holding position"
                await self._hold_async(
                    HOLD_TIME_LONG,
                    progress_weight=progress_per_cycle * 0.2
                )
                
                # Brief return to center between cycles
                if cycle < cycles - 1:  # Don't return to center after the last cycle
                    self.current_operation = f"cycle {cycle+1}/{cycles}: returning to center"
                    await self._set_angle_async(
                        DEGREES0,
                        "center",
                        progress_weight=progress_per_cycle * 0.1
                    )
                    await self._hold_async(
                        HOLD_TIME_SHORT,
                        progress_weight=progress_per_cycle * 0.1
                    )
                
                # Report cycle progress
                self._update_progress(
                    int(15 + (cycle+1) * progress_per_cycle), 
                    f"Completed cycle {cycle+1}/{cycles}"
                )
                
                # Stop and log cycle timer
                if cycle_timer:
                    cycle_duration = profiler.stop_timer(cycle_timer)
                    if cycle_duration:
                        self.logger.debug(
                            f"Completed cycle {cycle+1}/{cycles}",
                            structured_data={
                                "cycle": cycle+1,
                                "duration_ms": cycle_duration
                            }
                        )
            
            # Cooldown phase
            self.current_operation = "cooldown"
            await self._run_cooldown_async()
            
            # Protocol complete
            if not self.stop_requested:
                self._update_progress(100, "Protocol complete")
                self.signals.message.emit("Protocol 2 complete")
                self.signals.stopped.emit(f"Protocol {self.protocol}", True)
                
                # Log completion metrics
                self.logger.info(
                    f"Protocol 2 completed successfully",
                    structured_data={
                        "elapsed_seconds": self.elapsed_seconds,
                        "cycles_completed": cycles,
                        "max_left_angle": self.max_left,
                        "operation_durations": self.operation_durations
                    }
                )
                
        finally:
            # Cancel timeout monitor
            self._cancel_timeout_monitor()
            
            # Stop protocol timer
            if protocol_timer:
                protocol_duration = profiler.stop_timer(protocol_timer)
                if protocol_duration:
                    self.logger.info(
                        f"Protocol 2 execution finished",
                        structured_data={
                            "duration_ms": protocol_duration,
                            "completed_successfully": not self.stop_requested
                        }
                    )
    
    async def _run_protocol_3_async(self):
        """Run Protocol 3: Right Angle with Pressure using async/await"""
        protocol_timer = profiler.start_timer("protocol.run_protocol_3")
        
        self.logger.info("Running Protocol 3 (Right Angle with Pressure)")
        self.signals.message.emit("Starting Protocol 3: Right Angle with Pressure")
        self.current_operation = "initialization"
        
        # Track progress
        self._update_progress(5, "initialization")
        
        # Create task for monitoring timeouts
        self._start_timeout_monitor()
        
        try:
            # Warm-up phase
            self.current_operation = "warm-up"
            await self._run_warmup_async()
            
            if self.stop_requested:
                return
                
            # Main treatment phase
            self.signals.message.emit("Right angle treatment with pressure")
            self.current_operation = "main treatment"
            
            # Calculate number of cycles based on duration
            remaining_seconds = (self.duration * 60) - self.elapsed_seconds
            cycle_time = CYCLE_DURATION.get("2", 40)  # seconds per cycle from constants
            cycles = max(1, int(remaining_seconds / cycle_time))
            
            # Log cycle plan
            self.logger.info(
                f"Starting main treatment phase",
                structured_data={
                    "cycles": cycles,
                    "cycle_time_seconds": cycle_time,
                    "remaining_seconds": remaining_seconds,
                    "max_right_angle": self.max_right,
                    "use_pulse": self.use_pulse
                }
            )
            
            # Allocate progress - 5% already used, 10% for warmup, 10% for cooldown
            # Remaining 75% for main treatment
            progress_per_cycle = 75 / cycles if cycles > 0 else 0
            
            for cycle in range(cycles):
                if self.stop_requested:
                    return
                    
                cycle_timer = profiler.start_timer(
                    "protocol.cycle", 
                    {"protocol": "3", "cycle": cycle+1, "total_cycles": cycles}
                )
                
                # Log cycle start
                self.logger.debug(
                    f"Starting cycle {cycle+1}/{cycles}",
                    structured_data={
                        "cycle": cycle+1,
                        "total_cycles": cycles
                    }
                )
                
                # Update timers
                await self._update_timer_async()
                
                # Step 1: Apply pressure first
                self.current_operation = f"cycle {cycle+1}/{cycles}: applying pressure"
                await self._apply_pressure_async(
                    self.max_pressure,
                    progress_weight=progress_per_cycle * 0.2
                )
                await self._hold_async(
                    HOLD_TIME_SHORT,
                    progress_weight=progress_per_cycle * 0.1
                )
                
                # Step 2: Set angle to right
                self.current_operation = f"cycle {cycle+1}/{cycles}: setting right angle"
                await self._set_angle_async(
                    self.max_right,
                    "right",
                    progress_weight=progress_per_cycle * 0.2
                )
                await self._hold_async(
                    HOLD_TIME_LONG,
                    progress_weight=progress_per_cycle * 0.2
                )
                
                # Step 3: Pulse if requested
                if self.use_pulse:
                    self.current_operation = f"cycle {cycle+1}/{cycles}: pulsing"
                    await self._pulse_pressure_async(
                        pulses=3,
                        interval=2,
                        progress_weight=progress_per_cycle * 0.2
                    )
                
                # Step 4: Hold with pressure and angle
                self.current_operation = f"cycle {cycle+1}/{cycles}: holding position"
                await self._hold_async(
                    HOLD_TIME_LONG,
                    progress_weight=progress_per_cycle * 0.2
                )
                
                # Brief return to center between cycles
                if cycle < cycles - 1:  # Don't return to center after the last cycle
                    self.current_operation = f"cycle {cycle+1}/{cycles}: returning to center"
                    await self._set_angle_async(
                        DEGREES0,
                        "center",
                        progress_weight=progress_per_cycle * 0.1
                    )
                    await self._hold_async(
                        HOLD_TIME_SHORT,
                        progress_weight=progress_per_cycle * 0.1
                    )
                
                # Report cycle progress
                self._update_progress(
                    int(15 + (cycle+1) * progress_per_cycle), 
                    f"Completed cycle {cycle+1}/{cycles}"
                )
                
                # Stop and log cycle timer
                if cycle_timer:
                    cycle_duration = profiler.stop_timer(cycle_timer)
                    if cycle_duration:
                        self.logger.debug(
                            f"Completed cycle {cycle+1}/{cycles}",
                            structured_data={
                                "cycle": cycle+1,
                                "duration_ms": cycle_duration
                            }
                        )
            
            # Cooldown phase
            self.current_operation = "cooldown"
            await self._run_cooldown_async()
            
            # Protocol complete
            if not self.stop_requested:
                self._update_progress(100, "Protocol complete")
                self.signals.message.emit("Protocol 3 complete")
                self.signals.stopped.emit(f"Protocol {self.protocol}", True)
                
                # Log completion metrics
                self.logger.info(
                    f"Protocol 3 completed successfully",
                    structured_data={
                        "elapsed_seconds": self.elapsed_seconds,
                        "cycles_completed": cycles,
                        "max_right_angle": self.max_right,
                        "operation_durations": self.operation_durations
                    }
                )
                
        finally:
            # Cancel timeout monitor
            self._cancel_timeout_monitor()
            
            # Stop protocol timer
            if protocol_timer:
                protocol_duration = profiler.stop_timer(protocol_timer)
                if protocol_duration:
                    self.logger.info(
                        f"Protocol 3 execution finished",
                        structured_data={
                            "duration_ms": protocol_duration,
                            "completed_successfully": not self.stop_requested
                        }
                    )
    
    def _start_timeout_monitor(self):
        """Start the timeout monitor task"""
        if self.loop:
            self.timeout_handle = self.loop.create_task(self._monitor_operation_timeout())
    
    def _cancel_timeout_monitor(self):
        """Cancel the timeout monitor task"""
        if self.timeout_handle and not self.timeout_handle.done():
            self.timeout_handle.cancel()
    
    async def _monitor_operation_timeout(self):
        """Monitor operations for timeout"""
        last_operation = None
        last_time = time.time()
        
        while self.is_running and not self.stop_requested:
            await asyncio.sleep(1)
            
            # Check if operation changed
            if self.current_operation != last_operation:
                last_operation = self.current_operation
                last_time = time.time()
            else:
                # Check for timeout if operation hasn't changed
                elapsed = time.time() - last_time
                if elapsed > DEFAULT_TIMEOUT:
                    self.logger.warning(
                        f"Operation timed out",
                        structured_data={
                            "operation": self.current_operation,
                            "elapsed_seconds": elapsed
                        }
                    )
                    self.signals.timeout.emit(self.current_operation)
                    
                    # Record timeout in metrics
                    profiler.increment(
                        "protocol.operation_timeout", 
                        1, 
                        {"operation": self.current_operation}
                    )
    
    def _update_progress(self, percent, operation=None):
        """Update progress percentage and current operation"""
        if operation:
            self.current_operation = operation
        
        # Update stored progress
        self.progress_percent = percent
        
        # Emit signal for UI update
        self.signals.progress.emit(percent, self.current_operation)
        
        # Log progress at 25% increments
        if percent % 25 == 0:
            self.logger.info(
                f"Protocol progress: {percent}%",
                structured_data={
                    "progress_percent": percent,
                    "operation": self.current_operation,
                    "elapsed_seconds": self.elapsed_seconds
                }
            )
    
    def _start_operation_timer(self, operation_name):
        """Start timing an operation for metrics"""
        self.operation_name = operation_name
        self.operation_start_time = time.time()
    
    def _stop_operation_timer(self):
        """Stop timing the current operation and record metrics"""
        if self.operation_start_time and self.operation_name:
            duration = time.time() - self.operation_start_time
            self.operation_durations[self.operation_name] = duration
            
            # Reset for next operation
            self.operation_start_time = None
            self.operation_name = None
            
            return duration
        return None
    
    async def _apply_pressure_async(self, pressure, progress_weight=1.0):
        """
        Apply the specified pressure asynchronously
        
        Args:
            pressure: Target pressure in pounds
            progress_weight: Weight of this operation in progress calculation
        """
        if self.stop_requested:
            return
        
        # Start timing this operation
        self._start_operation_timer(f"apply_pressure_{pressure}")
        timer = profiler.start_timer(
            "protocol.apply_pressure", 
            {"target_pressure": pressure}
        )
            
        if not self.arduino_controller:
            self.logger.warning(
                "Arduino controller not available, skipping pressure control",
                structured_data={"target_pressure": pressure}
            )
            self.current_pressure = pressure
            self.signals.pressure.emit(pressure)
            return
            
        self.logger.debug(
            f"Applying pressure: {pressure} lbs",
            structured_data={"target_pressure": pressure}
        )
        
        self.current_operation = f"applying pressure: {pressure} lbs"
        
        # Safety limit
        if pressure > MAX_SAFE_PRESSURE:
            self.logger.warning(
                f"Pressure exceeds safety limit",
                structured_data={
                    "requested_pressure": pressure,
                    "safety_limit": MAX_SAFE_PRESSURE
                }
            )
            pressure = MAX_SAFE_PRESSURE
        
        # Create task for pressure setting
        self.current_task = asyncio.ensure_future(self._set_pressure_task(pressure))
        
        try:
            # Set timeout for this operation
            result = await asyncio.wait_for(self.current_task, timeout=10.0)
            
            # Update progress
            self.current_step += progress_weight
            progress_percent = min(100, int((self.current_step / self.total_steps) * 100))
            self.signals.progress.emit(progress_percent, self.current_operation)
            
            return result
        except asyncio.TimeoutError:
            self.logger.error(
                f"Timeout while setting pressure",
                structured_data={
                    "target_pressure": pressure,
                    "timeout_seconds": 10.0
                }
            )
            self.signals.timeout.emit(f"Pressure setting to {pressure}")
            
            # Record timeout in metrics
            profiler.increment(
                "protocol.pressure_timeout", 
                1, 
                {"target_pressure": pressure}
            )
            
            return False
        except asyncio.CancelledError:
            self.logger.info(
                f"Pressure setting cancelled",
                structured_data={"target_pressure": pressure}
            )
            raise
        except Exception as e:
            self.logger.error(
                f"Error setting pressure",
                structured_data={
                    "error": str(e),
                    "target_pressure": pressure
                },
                exc_info=True
            )
            return False
        finally:
            # Record operation duration
            self._stop_operation_timer()
            
            # Stop the timer
            if timer:
                duration_ms = profiler.stop_timer(timer)
                if duration_ms:
                    self.logger.debug(
                        f"Pressure application completed",
                        structured_data={
                            "target_pressure": pressure,
                            "duration_ms": duration_ms
                        }
                    )
    
    async def _set_pressure_task(self, pressure):
        """Task to set pressure with error handling"""
        loop = asyncio.get_event_loop()
        try:
            # Run in thread to avoid blocking
            await loop.run_in_executor(
                self.thread_pool, 
                lambda: self._execute_set_pressure(pressure)
            )
            return True
        except Exception as e:
            self.logger.error(
                f"Error in pressure task",
                structured_data={
                    "error": str(e),
                    "target_pressure": pressure
                },
                exc_info=True
            )
            return False
    
    def _execute_set_pressure(self, pressure):
        """Execute pressure setting on Arduino controller"""
        try:
            self.arduino_controller.set_pressure(pressure)
            self.current_pressure = pressure
            self.signals.pressure.emit(pressure)
            return True
        except Exception as e:
            self.logger.error(
                f"Error setting pressure",
                structured_data={
                    "error": str(e),
                    "target_pressure": pressure
                },
                exc_info=True
            )
            return False
    
    async def _set_angle_async(self, angle, side, progress_weight=1.0):
        """
        Set the specified angle asynchronously
        
        Args:
            angle: Target angle in degrees
            side: Which side ("left", "right", or "center")
            progress_weight: Weight of this operation in progress calculation
        """
        if self.stop_requested:
            return
        
        # Start timing this operation
        self._start_operation_timer(f"set_angle_{side}_{angle}")
        timer = profiler.start_timer(
            "protocol.set_angle", 
            {"angle": angle, "side": side}
        )
            
        if not self.arduino_controller:
            self.logger.warning(
                "Arduino controller not available, skipping angle control",
                structured_data={"angle": angle, "side": side}
            )
            self.current_angle = angle
            self.current_side = side
            self.signals.angle.emit(angle, side)
            return
            
        self.logger.debug(
            f"Setting angle: {angle}° ({side})",
            structured_data={"angle": angle, "side": side}
        )
        
        self.current_operation = f"setting angle: {angle}° ({side})"
        
        # Create task for angle setting
        self.current_task = asyncio.ensure_future(self._set_angle_task(angle, side))
        
        try:
            # Set timeout for this operation
            result = await asyncio.wait_for(self.current_task, timeout=15.0)
            
            # Update progress
            self.current_step += progress_weight
            progress_percent = min(100, int((self.current_step / self.total_steps) * 100))
            self.signals.progress.emit(progress_percent, self.current_operation)
            
            return result
        except asyncio.TimeoutError:
            self.logger.error(
                f"Timeout while setting angle",
                structured_data={
                    "angle": angle,
                    "side": side,
                    "timeout_seconds": 15.0
                }
            )
            self.signals.timeout.emit(f"Angle setting to {angle}° ({side})")
            
            # Record timeout in metrics
            profiler.increment(
                "protocol.angle_timeout", 
                1, 
                {"angle": angle, "side": side}
            )
            
            return False
        except asyncio.CancelledError:
            self.logger.info(
                f"Angle setting cancelled",
                structured_data={"angle": angle, "side": side}
            )
            raise
        except Exception as e:
            self.logger.error(
                f"Error setting angle",
                structured_data={
                    "error": str(e),
                    "angle": angle,
                    "side": side
                },
                exc_info=True
            )
            return False
        finally:
            # Record operation duration
            self._stop_operation_timer()
            
            # Stop the timer
            if timer:
                duration_ms = profiler.stop_timer(timer)
                if duration_ms:
                    self.logger.debug(
                        f"Angle setting completed",
                        structured_data={
                            "angle": angle,
                            "side": side,
                            "duration_ms": duration_ms
                        }
                    )
    
    async def _set_angle_task(self, angle, side):
        """Task to set angle with error handling"""
        loop = asyncio.get_event_loop()
        try:
            # Run in thread to avoid blocking
            await loop.run_in_executor(
                self.thread_pool, 
                lambda: self._execute_set_angle(angle, side)
            )
            return True
        except Exception as e:
            self.logger.error(
                f"Error in angle task",
                structured_data={
                    "error": str(e),
                    "angle": angle,
                    "side": side
                },
                exc_info=True
            )
            return False
    
    def _execute_set_angle(self, angle, side):
        """Execute angle setting on Arduino controller"""
        try:
            position = self._angle_to_position(angle, side)
            
            # Determine actuator ID and direction
            if side == "left":
                actuator_id = 2  # C actuator
                direction = 1
            elif side == "right":
                actuator_id = 2  # C actuator
                direction = -1
            else:  # center
                actuator_id = 2  # C actuator
                direction = 0
                position = 0
            
            # Move to position
            if direction != 0:
                steps = abs(position)
                speed = "04"  # Slow speed for smooth movement
                self.arduino_controller.move_actuator(actuator_id, steps, speed, direction)
            else:
                # Center position - could be implemented as a specific reset command
                self.arduino_controller.reset_actuator(actuator_id)
            
            self.current_angle = angle
            self.current_side = side
            self.signals.angle.emit(angle, side)
            return True
        except Exception as e:
            self.logger.error(
                f"Error setting angle",
                structured_data={
                    "error": str(e),
                    "angle": angle,
                    "side": side
                },
                exc_info=True
            )
            return False
    
    async def _pulse_pressure_async(self, pulses=1, interval=2, progress_weight=1.0):
        """
        Pulse the pressure asynchronously
        
        Args:
            pulses: Number of pulses
            interval: Interval between pulses in seconds
            progress_weight: Weight of this operation in progress calculation
        """
        if self.stop_requested:
            return
        
        # Start timing this operation
        self._start_operation_timer(f"pulse_pressure_{pulses}")
        timer = profiler.start_timer(
            "protocol.pulse_pressure", 
            {"pulses": pulses, "interval": interval}
        )
            
        original_pressure = self.current_pressure
        
        self.logger.debug(
            f"Pulsing pressure",
            structured_data={
                "pulses": pulses,
                "interval": interval,
                "original_pressure": original_pressure
            }
        )
        
        self.current_operation = f"pulsing pressure {pulses} times"
        
        # Distribute progress weight across all pulses
        weight_per_pulse = progress_weight / (pulses * 2)
        
        for i in range(pulses):
            if self.stop_requested:
                break
                
            pulse_timer = profiler.start_timer(
                "protocol.single_pulse", 
                {"pulse": i+1, "total": pulses}
            )
            
            # Reduce pressure briefly
            reduced_pressure = max(MIN_PRESSURE, original_pressure * 0.7)
            
            self.logger.debug(
                f"Pulse {i+1}/{pulses}: reducing pressure",
                structured_data={
                    "pulse": i+1,
                    "total": pulses,
                    "original_pressure": original_pressure,
                    "reduced_pressure": reduced_pressure
                }
            )
            
            await self._apply_pressure_async(reduced_pressure, progress_weight=weight_per_pulse)
            
            # Wait
            await self._hold_async(interval / 2, progress_weight=weight_per_pulse * 0.5)
            
            if self.stop_requested:
                break
                
            # Restore pressure
            self.logger.debug(
                f"Pulse {i+1}/{pulses}: restoring pressure",
                structured_data={
                    "pulse": i+1,
                    "total": pulses,
                    "target_pressure": original_pressure
                }
            )
            
            await self._apply_pressure_async(original_pressure, progress_weight=weight_per_pulse)
            
            # Wait
            await self._hold_async(interval / 2, progress_weight=weight_per_pulse * 0.5)
            
            # Report pulse progress
            self.signals.progress.emit(
                min(100, int((self.current_step / self.total_steps) * 100)),
                f"Completed pulse {i+1}/{pulses}"
            )
            
            # Stop pulse timer
            if pulse_timer:
                pulse_duration = profiler.stop_timer(pulse_timer)
                if pulse_duration:
                    self.logger.debug(
                        f"Completed pulse {i+1}/{pulses}",
                        structured_data={
                            "pulse": i+1,
                            "total": pulses,
                            "duration_ms": pulse_duration
                        }
                    )
        
        # Record final metrics
        if timer:
            duration_ms = profiler.stop_timer(timer)
            if duration_ms:
                self.logger.debug(
                    f"Completed {pulses} pressure pulses",
                    structured_data={
                        "pulses": pulses,
                        "interval": interval,
                        "duration_ms": duration_ms
                    }
                )
        
        # Record operation duration
        self._stop_operation_timer()
    
    async def _hold_async(self, seconds, progress_weight=0.5):
        """
        Hold the current position for the specified time asynchronously
        
        Args:
            seconds: Time to hold in seconds
            progress_weight: Weight of this operation in progress calculation
        """
        start_time = time.time()
        elapsed = 0
        
        # Start timing this operation
        self._start_operation_timer(f"hold_{seconds}s")
        timer = profiler.start_timer(
            "protocol.hold", 
            {"seconds": seconds}
        )
        
        self.logger.debug(
            f"Holding position",
            structured_data={
                "seconds": seconds,
                "pressure": self.current_pressure,
                "angle": self.current_angle,
                "side": self.current_side
            }
        )
        
        self.current_operation = f"holding for {seconds}s"
        
        # Update progress at start
        prev_progress = min(100, int((self.current_step / self.total_steps) * 100))
        
        # Calculate progress increments
        increments = max(1, int(seconds / 0.5))  # Update progress every 0.5s
        increment_weight = progress_weight / increments
        
        while elapsed < seconds and not self.stop_requested:
            # Handle pause
            if self.paused:
                await asyncio.sleep(0.5)
                continue
                
            # Update timer display
            await self._update_timer_async()
            
            # Update progress incrementally during hold
            self.current_step += increment_weight
            new_progress = min(100, int((self.current_step / self.total_steps) * 100))
            if new_progress > prev_progress:
                prev_progress = new_progress
                self.signals.progress.emit(
                    new_progress, 
                    f"holding: {int(elapsed)}/{int(seconds)}s"
                )
            
            # Sleep briefly
            await asyncio.sleep(0.1)
            elapsed = time.time() - start_time
        
        # Stop and log hold timer
        if timer:
            duration_ms = profiler.stop_timer(timer)
            if duration_ms:
                self.logger.debug(
                    f"Hold completed",
                    structured_data={
                        "target_seconds": seconds,
                        "actual_seconds": elapsed,
                        "duration_ms": duration_ms
                    }
                )
        
        # Record operation duration
        self._stop_operation_timer()
    
    async def _update_timer_async(self):
        """Update the timer display asynchronously"""
        if self.stop_requested or self.paused:
            return
            
        # Calculate elapsed time
        now = datetime.now()
        self.elapsed_seconds = int((now - self.start_time).total_seconds())
        
        # Calculate remaining time
        remaining_seconds = max(0, (self.duration * 60) - self.elapsed_seconds)
        
        # Update every second
        if self.elapsed_seconds % 1 == 0:
            self.signals.status.emit(
                f"Protocol {self.protocol}", 
                self.elapsed_seconds, 
                remaining_seconds
            )
    
    async def _run_warmup_async(self):
        """Run warm-up phase asynchronously"""
        warmup_timer = profiler.start_timer("protocol.warmup")
        
        self.signals.message.emit("Warm-up phase")
        self.current_operation = "warm-up phase"
        
        self.logger.info("Starting warm-up phase")
        
        # Start with minimal pressure - 10% of total progress
        await self._apply_pressure_async(MIN_PRESSURE, progress_weight=2)
        
        # Set to center position
        await self._set_angle_async(DEGREES0, "center", progress_weight=2)
        await self._hold_async(HOLD_TIME_LONG, progress_weight=2)
        
        # Gradually increase pressure
        await self._apply_pressure_async(MIN_PRESSURE * 2, progress_weight=1)
        await self._hold_async(HOLD_TIME_SHORT, progress_weight=1)
        
        await self._apply_pressure_async(MIN_PRESSURE * 3, progress_weight=1)
        await self._hold_async(HOLD_TIME_SHORT, progress_weight=1)
        
        # Update progress
        self._update_progress(15, "Warm-up complete")
        
        # Log completion
        if warmup_timer:
            duration_ms = profiler.stop_timer(warmup_timer)
            if duration_ms:
                self.logger.info(
                    "Warm-up phase completed",
                    structured_data={
                        "duration_ms": duration_ms,
                        "final_pressure": MIN_PRESSURE * 3
                    }
                )
    
    async def _run_cooldown_async(self):
        """Run cooldown phase asynchronously"""
        if self.stop_requested:
            return
        
        cooldown_timer = profiler.start_timer("protocol.cooldown")
            
        self.signals.message.emit("Cooldown phase")
        self.current_operation = "cooldown phase"
        
        self.logger.info(
            "Starting cooldown phase",
            structured_data={
                "current_pressure": self.current_pressure,
                "current_angle": self.current_angle,
                "current_side": self.current_side
            }
        )
        
        # Return to center position - 10% of total progress
        await self._set_angle_async(DEGREES0, "center", progress_weight=2)
        await self._hold_async(HOLD_TIME_SHORT, progress_weight=2)
        
        # Gradually reduce pressure
        current = self.current_pressure
        if current > MIN_PRESSURE * 2:
            reduced_pressure = int(current / 2)
            await self._apply_pressure_async(reduced_pressure, progress_weight=2)
            await self._hold_async(HOLD_TIME_SHORT, progress_weight=1)
            
        # Minimal pressure
        await self._apply_pressure_async(MIN_PRESSURE, progress_weight=1)
        await self._hold_async(HOLD_TIME_SHORT, progress_weight=1)
        
        # Release pressure
        await self._apply_pressure_async(0, progress_weight=1)
        
        # Update progress
        self._update_progress(95, "Cooldown complete")
        
        # Log completion
        if cooldown_timer:
            duration_ms = profiler.stop_timer(cooldown_timer)
            if duration_ms:
                self.logger.info(
                    "Cooldown phase completed",
                    structured_data={
                        "duration_ms": duration_ms
                    }
                )
    
    def _angle_to_position(self, angle, side):
        """
        Convert angle to actuator position
        
        Args:
            angle: Angle in degrees
            side: Which side ("left", "right", or "center")
            
        Returns:
            Position value for the actuator
        """
        # This is a simplified conversion - would need to be calibrated for the actual hardware
        if side == "center":
            return 0
            
        # Convert angle to steps
        steps = int(abs(angle) * 10)  # Example: 1 degree = 10 steps
        
        return steps
    
    def _cleanup(self):
        """Clean up after protocol execution"""
        cleanup_timer = profiler.start_timer("protocol.cleanup")
        
        self.logger.info("Cleaning up after protocol execution")
        
        # Reset state
        self.is_running = False
        
        # Return to center position
        try:
            if self.arduino_controller:
                # Reset position
                self._execute_set_angle(DEGREES0, "center")
                
                # Release pressure
                self._execute_set_pressure(0)
                
                # Stop all actuators
                self.arduino_controller.stop_all_actuators()
                
                self.logger.info("Hardware reset to safe state")
        except Exception as e:
            self.logger.error(
                f"Error during cleanup",
                structured_data={"error": str(e)},
                exc_info=True
            )
        
        # Emit stopped signal if not already emitted
        if self.stop_requested:
            self.signals.stopped.emit(f"Protocol {self.protocol}", False)
        
        # Log all operation durations
        self.logger.info(
            "Protocol execution summary",
            structured_data={
                "operation_durations": self.operation_durations,
                "total_elapsed_seconds": self.elapsed_seconds,
                "protocol": self.protocol,
                "completed_successfully": not self.stop_requested
            }
        )
        
        # Stop cleanup timer
        if cleanup_timer:
            duration_ms = profiler.stop_timer(cleanup_timer)
            if duration_ms:
                self.logger.debug(
                    "Cleanup completed",
                    structured_data={"duration_ms": duration_ms}
                )