/**
 * KneeSpa Demo Application Controller
 *
 * Wires together the simulator and visualization, handles UI events,
 * and updates the gauge displays. This mirrors the role of kneespa.py
 * in the real application.
 */

class KneeSpaApp {
  constructor() {
    // Initialize components
    this.simulator = new KneeSpaSimulator();
    this.visualization = new KneeVisualization('knee-diagram');

    // UI state
    this.selectedProtocol = 1;
    this.settings = {
      maxPressure: 50,
      maxLeft: -15,
      maxRight: 15,
      usePulse: true
    };

    // Cache DOM elements
    this.elements = {
      protocolButtons: document.querySelectorAll('.protocol-btn'),
      startButton: document.getElementById('start-btn'),
      stopButton: document.getElementById('stop-btn'),
      pulseCheckbox: document.getElementById('pulse-toggle'),
      pressureGauge: document.getElementById('pressure-gauge'),
      pressureValue: document.getElementById('pressure-value'),
      angleGauge: document.getElementById('angle-gauge'),
      angleValue: document.getElementById('angle-value'),
      statusText: document.getElementById('status-text'),
      progressBar: document.getElementById('progress-bar'),
      progressFill: document.getElementById('progress-fill'),
      timeDisplay: document.getElementById('time-display'),
      pressureSlider: document.getElementById('pressure-slider'),
      pressureSliderValue: document.getElementById('pressure-slider-value'),
      angleSlider: document.getElementById('angle-slider'),
      angleSliderValue: document.getElementById('angle-slider-value')
    };

    this.bindEvents();
    this.setupSimulatorListeners();
    this.updateUI();

    console.log('[App] KneeSpa Demo initialized');
  }

  bindEvents() {
    // Protocol selection
    this.elements.protocolButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const protocol = parseInt(btn.dataset.protocol);
        this.selectProtocol(protocol);
      });
    });

    // Start/Stop buttons
    this.elements.startButton.addEventListener('click', () => this.startProtocol());
    this.elements.stopButton.addEventListener('click', () => this.stopProtocol());

    // Pulse toggle
    this.elements.pulseCheckbox.addEventListener('change', (e) => {
      this.settings.usePulse = e.target.checked;
      this.simulator.togglePulse(this.settings.usePulse);
    });

    // Settings sliders
    if (this.elements.pressureSlider) {
      this.elements.pressureSlider.addEventListener('input', (e) => {
        this.settings.maxPressure = parseInt(e.target.value);
        this.elements.pressureSliderValue.textContent = `${this.settings.maxPressure} lbs`;
      });
    }

    if (this.elements.angleSlider) {
      this.elements.angleSlider.addEventListener('input', (e) => {
        const angle = parseInt(e.target.value);
        this.settings.maxLeft = -angle;
        this.settings.maxRight = angle;
        this.elements.angleSliderValue.textContent = `±${angle}°`;
      });
    }
  }

  setupSimulatorListeners() {
    // Status updates (continuous during operation)
    this.simulator.on('status', (state) => {
      this.visualization.update(state);
      this.updateGauges(state);
      this.updateProgress(state);
    });

    // Phase changes
    this.simulator.on('phaseChange', ({ phase, message }) => {
      this.elements.statusText.textContent = message;
      this.elements.statusText.className = `status-text phase-${phase}`;
    });

    // Protocol complete
    this.simulator.on('complete', () => {
      this.onProtocolComplete();
    });

    // Protocol stopped
    this.simulator.on('stopped', () => {
      this.onProtocolStopped();
    });
  }

  selectProtocol(protocol) {
    this.selectedProtocol = protocol;

    // Update button states
    this.elements.protocolButtons.forEach(btn => {
      const isSelected = parseInt(btn.dataset.protocol) === protocol;
      btn.classList.toggle('selected', isSelected);
    });

    // Update status text
    const protocolNames = {
      1: 'Axial Compression',
      2: 'Left Lateral Tilt',
      3: 'Right Lateral Tilt',
      4: 'Oscillating'
    };
    this.elements.statusText.textContent = `Selected: ${protocolNames[protocol]}`;

    console.log(`[App] Selected protocol ${protocol}`);
  }

  startProtocol() {
    console.log(`[App] Starting protocol ${this.selectedProtocol}`);

    // Update UI state
    this.elements.startButton.disabled = true;
    this.elements.stopButton.disabled = false;
    this.elements.protocolButtons.forEach(btn => btn.disabled = true);

    // Start simulator
    this.simulator.start(this.selectedProtocol, {
      maxPressure: this.settings.maxPressure,
      maxLeft: this.settings.maxLeft,
      maxRight: this.settings.maxRight,
      usePulse: this.settings.usePulse
    });
  }

  stopProtocol() {
    console.log('[App] Stopping protocol');
    this.simulator.stop();
  }

  onProtocolComplete() {
    this.elements.statusText.textContent = 'Protocol Complete';
    this.elements.statusText.className = 'status-text phase-complete';
    this.resetControls();

    // Show completion animation
    this.elements.progressFill.style.background = 'linear-gradient(90deg, #27ae60, #2ecc71)';
    setTimeout(() => {
      this.elements.progressFill.style.background = '';
      this.elements.progressFill.style.width = '0%';
    }, 2000);
  }

  onProtocolStopped() {
    this.elements.statusText.textContent = 'Protocol Stopped';
    this.elements.statusText.className = 'status-text phase-stopped';
    this.resetControls();
    this.elements.progressFill.style.width = '0%';
  }

  resetControls() {
    this.elements.startButton.disabled = false;
    this.elements.stopButton.disabled = true;
    this.elements.protocolButtons.forEach(btn => btn.disabled = false);
  }

  updateGauges(state) {
    // Update pressure gauge
    const pressurePercent = (state.pressure / 80) * 100;
    this.updateCircularGauge(this.elements.pressureGauge, pressurePercent, state.pressure);
    this.elements.pressureValue.textContent = `${state.pressure.toFixed(0)} lbs`;

    // Update angle gauge
    const anglePercent = ((state.lateralAngle + 20) / 40) * 100; // -20 to +20 -> 0 to 100
    this.updateCircularGauge(this.elements.angleGauge, anglePercent, state.lateralAngle, true);
    this.elements.angleValue.textContent = `${state.lateralAngle.toFixed(1)}°`;
  }

  updateCircularGauge(gaugeElement, percent, value, centered = false) {
    if (!gaugeElement) return;

    const circle = gaugeElement.querySelector('.gauge-fill');
    if (!circle) return;

    // For SVG circle gauges
    const radius = 45;
    const circumference = 2 * Math.PI * radius;

    if (centered) {
      // For angle gauge (centered at 50%)
      const offset = circumference * (1 - Math.abs(percent - 50) / 50);
      circle.style.strokeDashoffset = offset;

      // Change color based on direction
      if (value < 0) {
        circle.style.stroke = '#e74c3c'; // Red for left
      } else if (value > 0) {
        circle.style.stroke = '#3498db'; // Blue for right
      } else {
        circle.style.stroke = '#95a5a6'; // Gray for center
      }
    } else {
      // For pressure gauge (0 to 100%)
      const offset = circumference * (1 - percent / 100);
      circle.style.strokeDashoffset = offset;

      // Color gradient based on pressure
      if (percent > 80) {
        circle.style.stroke = '#e74c3c'; // Red - high pressure
      } else if (percent > 50) {
        circle.style.stroke = '#f39c12'; // Orange - medium
      } else {
        circle.style.stroke = '#27ae60'; // Green - low
      }
    }
  }

  updateProgress(state) {
    const progress = this.simulator.getProgress() * 100;
    this.elements.progressFill.style.width = `${progress}%`;

    const remaining = this.simulator.getRemainingTime();
    const minutes = Math.floor(remaining / 60);
    const seconds = remaining % 60;
    this.elements.timeDisplay.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
  }

  updateUI() {
    // Initial UI state
    this.selectProtocol(1);
    this.elements.stopButton.disabled = true;
    this.elements.pulseCheckbox.checked = this.settings.usePulse;

    if (this.elements.pressureSlider) {
      this.elements.pressureSlider.value = this.settings.maxPressure;
      this.elements.pressureSliderValue.textContent = `${this.settings.maxPressure} lbs`;
    }

    if (this.elements.angleSlider) {
      this.elements.angleSlider.value = Math.abs(this.settings.maxLeft);
      this.elements.angleSliderValue.textContent = `±${Math.abs(this.settings.maxLeft)}°`;
    }
  }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  window.app = new KneeSpaApp();
});
