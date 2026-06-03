/**
 * KneeSpa Device Simulator
 *
 * Mimics the behavior of the real KneeSpa device's Arduino communication layer.
 * Uses an event-driven pattern matching the PyQt signals in helpers/arduino.py
 *
 * Events emitted:
 * - 'status': { pressure, lateralAngle, phase } - continuous state updates
 * - 'phaseChange': { phase, message } - protocol phase transitions
 * - 'complete': protocol finished successfully
 * - 'stopped': protocol cancelled by user
 */

class EventEmitter {
  constructor() {
    this.listeners = {};
  }

  on(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
  }

  off(event, callback) {
    if (!this.listeners[event]) return;
    this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
  }

  emit(event, data) {
    if (!this.listeners[event]) return;
    this.listeners[event].forEach(callback => callback(data));
  }
}

class KneeSpaSimulator extends EventEmitter {
  // Configuration matching real device from config/constants.py
  static CONFIG = {
    PRESSURE_MAX: 80,           // Maximum pressure in lbs
    PRESSURE_MIN: 10,           // Minimum starting pressure
    PRESSURE_INCREMENT: 10,     // Pressure step size
    LATERAL_MIN: -20,           // Max left angle (degrees)
    LATERAL_MAX: 20,            // Max right angle (degrees)

    // Accelerated timing (~10x faster than real device)
    RAMP_DURATION: 3000,        // Time to ramp pressure (ms)
    POSITION_DURATION: 1000,    // Time to change lateral position (ms)
    OSCILLATION_PERIOD: 3000,   // Time between left/right in protocol 4 (ms)
    PULSE_PERIOD: 500,          // Pulse animation cycle (ms)
    STATUS_INTERVAL: 50,        // How often to emit status updates (ms)
    DEMO_DURATION: 15000        // Total protocol duration for demo (ms)
  };

  constructor() {
    super();
    this.reset();
    this.statusInterval = null;
    this.protocolTimeout = null;
    this.animationFrame = null;
  }

  reset() {
    this.state = {
      pressure: 0,
      lateralAngle: 0,
      targetPressure: 0,
      targetAngle: 0,
      isPulsing: false,
      isRunning: false,
      protocol: null,
      phase: 'idle',
      startTime: null,
      elapsedTime: 0,
      pulseOffset: 0
    };
  }

  /**
   * Start a protocol
   * @param {number} protocol - Protocol number (1-4)
   * @param {object} options - { maxPressure, maxLeft, maxRight, usePulse }
   */
  start(protocol, options = {}) {
    if (this.state.isRunning) {
      this.stop();
    }

    this.reset();

    this.state.protocol = protocol;
    this.state.isRunning = true;
    this.state.startTime = Date.now();
    this.state.targetPressure = options.maxPressure || 50;
    this.state.isPulsing = options.usePulse !== false;

    // Set target angles based on protocol
    const maxLeft = options.maxLeft || -15;
    const maxRight = options.maxRight || 15;

    switch (protocol) {
      case 1: // Axial only
        this.state.targetAngle = 0;
        break;
      case 2: // Left lateral
        this.state.targetAngle = maxLeft;
        break;
      case 3: // Right lateral
        this.state.targetAngle = maxRight;
        break;
      case 4: // Oscillating
        this.state.targetAngle = maxLeft; // Start left
        this.oscillationDirection = 1; // Will flip to go right
        break;
    }

    this.emitPhaseChange('ramping', 'Ramping pressure...');
    this.startStatusUpdates();
    this.runProtocol();

    console.log(`[Simulator] Started protocol ${protocol}`, options);
  }

  stop() {
    if (!this.state.isRunning) return;

    console.log('[Simulator] Stopping protocol');

    this.state.isRunning = false;
    this.stopStatusUpdates();

    if (this.protocolTimeout) {
      clearTimeout(this.protocolTimeout);
      this.protocolTimeout = null;
    }

    // Animate back to zero
    this.animateToZero().then(() => {
      this.state.phase = 'idle';
      this.emit('stopped', {});
    });
  }

  togglePulse(enabled) {
    this.state.isPulsing = enabled;
    console.log(`[Simulator] Pulse mode: ${enabled ? 'ON' : 'OFF'}`);
  }

  // Private methods

  startStatusUpdates() {
    this.statusInterval = setInterval(() => {
      this.updateState();
      this.emitStatus();
    }, KneeSpaSimulator.CONFIG.STATUS_INTERVAL);
  }

  stopStatusUpdates() {
    if (this.statusInterval) {
      clearInterval(this.statusInterval);
      this.statusInterval = null;
    }
  }

  updateState() {
    if (!this.state.isRunning) return;

    this.state.elapsedTime = Date.now() - this.state.startTime;

    // Update pulse offset for animation
    if (this.state.isPulsing && this.state.phase === 'holding') {
      const pulsePhase = (Date.now() % KneeSpaSimulator.CONFIG.PULSE_PERIOD) /
                         KneeSpaSimulator.CONFIG.PULSE_PERIOD;
      this.state.pulseOffset = Math.sin(pulsePhase * Math.PI * 2) * 3;
    } else {
      this.state.pulseOffset = 0;
    }
  }

  emitStatus() {
    this.emit('status', {
      pressure: this.state.pressure,
      lateralAngle: this.state.lateralAngle,
      phase: this.state.phase,
      elapsedTime: this.state.elapsedTime,
      isPulsing: this.state.isPulsing,
      pulseOffset: this.state.pulseOffset,
      protocol: this.state.protocol
    });
  }

  emitPhaseChange(phase, message) {
    this.state.phase = phase;
    this.emit('phaseChange', { phase, message });
    console.log(`[Simulator] Phase: ${phase} - ${message}`);
  }

  async runProtocol() {
    const config = KneeSpaSimulator.CONFIG;

    try {
      // Phase 1: Ramp pressure
      await this.animatePressure(config.PRESSURE_MIN, this.state.targetPressure, config.RAMP_DURATION);

      if (!this.state.isRunning) return;

      // Phase 2: Position (for protocols 2, 3, 4)
      if (this.state.protocol !== 1) {
        this.emitPhaseChange('positioning', `Moving to ${this.state.targetAngle}°...`);
        await this.animateAngle(0, this.state.targetAngle, config.POSITION_DURATION);
      }

      if (!this.state.isRunning) return;

      // Phase 3: Hold/Pulse (or oscillate for protocol 4)
      if (this.state.protocol === 4) {
        this.emitPhaseChange('oscillating', 'Oscillating...');
        await this.runOscillation();
      } else {
        this.emitPhaseChange('holding', this.state.isPulsing ? 'Pulsing...' : 'Holding...');
        await this.holdUntilComplete();
      }

      if (!this.state.isRunning) return;

      // Phase 4: Return to neutral
      this.emitPhaseChange('returning', 'Returning to neutral...');
      await this.animateToZero();

      // Complete
      this.state.isRunning = false;
      this.state.phase = 'complete';
      this.stopStatusUpdates();
      this.emit('complete', {});
      console.log('[Simulator] Protocol complete');

    } catch (err) {
      console.error('[Simulator] Protocol error:', err);
    }
  }

  animatePressure(from, to, duration) {
    return new Promise(resolve => {
      const startTime = Date.now();
      const startPressure = this.state.pressure;
      const delta = to - from;

      const animate = () => {
        if (!this.state.isRunning) {
          resolve();
          return;
        }

        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / duration, 1);

        // Ease-out curve for natural feel
        const easeProgress = 1 - Math.pow(1 - progress, 2);
        this.state.pressure = from + (delta * easeProgress);

        if (progress < 1) {
          requestAnimationFrame(animate);
        } else {
          this.state.pressure = to;
          resolve();
        }
      };

      animate();
    });
  }

  animateAngle(from, to, duration) {
    return new Promise(resolve => {
      const startTime = Date.now();
      const delta = to - from;

      const animate = () => {
        if (!this.state.isRunning) {
          resolve();
          return;
        }

        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / duration, 1);

        // Ease-in-out for smooth movement
        const easeProgress = progress < 0.5
          ? 2 * progress * progress
          : 1 - Math.pow(-2 * progress + 2, 2) / 2;

        this.state.lateralAngle = from + (delta * easeProgress);

        if (progress < 1) {
          requestAnimationFrame(animate);
        } else {
          this.state.lateralAngle = to;
          resolve();
        }
      };

      animate();
    });
  }

  async runOscillation() {
    const config = KneeSpaSimulator.CONFIG;
    const maxLeft = this.state.targetAngle;
    const maxRight = -maxLeft; // Symmetric

    const oscillationStart = Date.now();
    const remainingTime = config.DEMO_DURATION - this.state.elapsedTime;

    while (this.state.isRunning && (Date.now() - oscillationStart) < remainingTime) {
      // Move to right
      this.emitPhaseChange('oscillating', `Moving to ${maxRight}°...`);
      await this.animateAngle(this.state.lateralAngle, maxRight, config.POSITION_DURATION);

      if (!this.state.isRunning) return;

      // Hold right
      await this.delay(config.OSCILLATION_PERIOD - config.POSITION_DURATION);

      if (!this.state.isRunning) return;

      // Move to left
      this.emitPhaseChange('oscillating', `Moving to ${maxLeft}°...`);
      await this.animateAngle(this.state.lateralAngle, maxLeft, config.POSITION_DURATION);

      if (!this.state.isRunning) return;

      // Hold left
      await this.delay(config.OSCILLATION_PERIOD - config.POSITION_DURATION);
    }
  }

  holdUntilComplete() {
    return new Promise(resolve => {
      const config = KneeSpaSimulator.CONFIG;
      const holdStart = Date.now();
      const remainingTime = config.DEMO_DURATION - this.state.elapsedTime;

      const checkComplete = () => {
        if (!this.state.isRunning) {
          resolve();
          return;
        }

        if ((Date.now() - holdStart) >= remainingTime) {
          resolve();
          return;
        }

        this.protocolTimeout = setTimeout(checkComplete, 100);
      };

      checkComplete();
    });
  }

  animateToZero() {
    return Promise.all([
      this.animatePressure(this.state.pressure, 0, 1000),
      this.animateAngle(this.state.lateralAngle, 0, 800)
    ]);
  }

  delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  // Getters for UI
  getState() {
    return { ...this.state };
  }

  getProgress() {
    if (!this.state.startTime) return 0;
    return Math.min(this.state.elapsedTime / KneeSpaSimulator.CONFIG.DEMO_DURATION, 1);
  }

  getRemainingTime() {
    const remaining = KneeSpaSimulator.CONFIG.DEMO_DURATION - this.state.elapsedTime;
    return Math.max(0, Math.ceil(remaining / 1000));
  }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { KneeSpaSimulator, EventEmitter };
}
