/**
 * KneeSpa Device Visualization
 *
 * Renders an animated SVG of the complete KneeSpa treatment device
 * showing the chair, patient, and leg apparatus responding to
 * simulator state changes.
 */

class KneeVisualization {
  static CONFIG = {
    WIDTH: 600,
    HEIGHT: 350,

    // Colors matching the actual device
    FRAME_COLOR: '#1a1a1a',
    SEAT_COLOR: '#2d2d2d',
    SEAT_ACCENT: '#3498db',
    BOOT_COLOR: '#808080',
    BOOT_ACCENT: '#3498db',
    ACTUATOR_COLOR: '#666',
    PATIENT_COLOR: '#e8d4c4',
    JOINT_GLOW: '#3498db',

    // Animation ranges
    MIN_EXTENSION: 0,      // Boot position at 0 pressure
    MAX_EXTENSION: 25,     // Boot pulls away at max pressure
    MAX_ROTATION: 20,      // Max tilt degrees
  };

  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.svg = null;
    this.elements = {};
    this.currentState = {
      pressure: 0,
      lateralAngle: 0,
      isPulsing: false,
      pulseOffset: 0
    };

    this.createSVG();
  }

  createSVG() {
    const config = KneeVisualization.CONFIG;

    this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this.svg.setAttribute('viewBox', `0 0 ${config.WIDTH} ${config.HEIGHT}`);
    this.svg.setAttribute('class', 'device-svg');

    this.svg.innerHTML = `
      <defs>
        <!-- Gradients -->
        <linearGradient id="seatGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:#3d3d3d"/>
          <stop offset="50%" style="stop-color:#2d2d2d"/>
          <stop offset="100%" style="stop-color:#1d1d1d"/>
        </linearGradient>

        <linearGradient id="blueAccent" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" style="stop-color:#5dade2"/>
          <stop offset="100%" style="stop-color:#2980b9"/>
        </linearGradient>

        <linearGradient id="bootGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:#909090"/>
          <stop offset="50%" style="stop-color:#707070"/>
          <stop offset="100%" style="stop-color:#606060"/>
        </linearGradient>

        <linearGradient id="skinGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:#f0ddd0"/>
          <stop offset="100%" style="stop-color:#e0c8b8"/>
        </linearGradient>

        <linearGradient id="actuatorGradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" style="stop-color:#888"/>
          <stop offset="50%" style="stop-color:#aaa"/>
          <stop offset="100%" style="stop-color:#888"/>
        </linearGradient>

        <!-- Filters -->
        <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="2" dy="3" stdDeviation="3" flood-opacity="0.3"/>
        </filter>

        <filter id="glowEffect" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="blur"/>
          <feMerge>
            <feMergeNode in="blur"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>

        <filter id="pulseGlow" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="6" result="blur"/>
          <feMerge>
            <feMergeNode in="blur"/>
            <feMergeNode in="blur"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>
      </defs>

      <!-- Base Frame -->
      <g id="frame" filter="url(#shadow)">
        <!-- Main horizontal beam -->
        <rect x="50" y="280" width="500" height="12" rx="2" fill="${config.FRAME_COLOR}"/>

        <!-- Vertical supports -->
        <rect x="70" y="200" width="10" height="85" fill="${config.FRAME_COLOR}"/>
        <rect x="130" y="220" width="10" height="65" fill="${config.FRAME_COLOR}"/>

        <!-- Wheels/casters -->
        <circle cx="70" cy="300" r="12" fill="#444" stroke="#333" stroke-width="2"/>
        <circle cx="70" cy="300" r="6" fill="#222"/>
        <circle cx="180" cy="300" r="12" fill="#444" stroke="#333" stroke-width="2"/>
        <circle cx="180" cy="300" r="6" fill="#222"/>
        <circle cx="480" cy="300" r="12" fill="#444" stroke="#333" stroke-width="2"/>
        <circle cx="480" cy="300" r="6" fill="#222"/>
      </g>

      <!-- Seat Assembly -->
      <g id="seat" filter="url(#shadow)">
        <!-- Seat back frame -->
        <rect x="65" y="80" width="15" height="140" rx="3" fill="${config.FRAME_COLOR}"/>

        <!-- Seat back cushion -->
        <path d="M 85,70
                 L 85,210
                 Q 85,220 95,220
                 L 130,220
                 Q 140,220 145,210
                 L 160,90
                 Q 162,75 150,70
                 L 95,70
                 Q 85,70 85,80 Z"
              fill="url(#seatGradient)" stroke="#1a1a1a" stroke-width="2"/>

        <!-- Blue accent stripe on seat back -->
        <path d="M 95,75 L 95,215 L 105,215 L 115,80 Z" fill="url(#blueAccent)" opacity="0.9"/>

        <!-- Headrest -->
        <ellipse cx="120" cy="60" rx="30" ry="18" fill="url(#seatGradient)" stroke="#1a1a1a" stroke-width="2"/>

        <!-- Seat cushion -->
        <path d="M 130,220
                 L 220,235
                 Q 230,237 230,230
                 L 230,215
                 Q 230,208 220,210
                 L 145,210
                 Q 135,210 130,220 Z"
              fill="url(#seatGradient)" stroke="#1a1a1a" stroke-width="2"/>

        <!-- Side handle -->
        <rect x="55" y="140" width="25" height="8" rx="4" fill="url(#blueAccent)"/>
      </g>

      <!-- Monitor Arm -->
      <g id="monitor">
        <path d="M 140,85 L 170,50 L 200,50" stroke="#888" stroke-width="4" fill="none" stroke-linecap="round"/>
        <rect x="195" y="35" width="40" height="30" rx="3" fill="#222" stroke="#444" stroke-width="1"/>
        <rect x="198" y="38" width="34" height="24" rx="2" fill="#111"/>
      </g>

      <!-- Patient Silhouette -->
      <g id="patient">
        <!-- Torso -->
        <ellipse cx="130" cy="150" rx="35" ry="55" fill="url(#skinGradient)" opacity="0.9"/>

        <!-- Head -->
        <circle cx="125" cy="70" r="22" fill="url(#skinGradient)"/>

        <!-- Upper leg (thigh) - fixed to seat -->
        <path d="M 200,220
                 Q 210,210 230,210
                 L 310,195
                 L 310,215
                 L 230,230
                 Q 210,235 200,230 Z"
              fill="url(#skinGradient)"/>
      </g>

      <!-- Knee Joint Area (treatment zone) -->
      <g id="kneeArea">
        <ellipse id="kneeJoint" cx="320" cy="205" rx="18" ry="15"
                 fill="${config.JOINT_GLOW}" opacity="0.3"/>
      </g>

      <!-- Leg Apparatus (moving part) -->
      <g id="legApparatus">
        <!-- Actuator housing -->
        <rect id="actuatorBase" x="280" y="250" width="180" height="20" rx="3"
              fill="${config.FRAME_COLOR}"/>

        <!-- Linear actuator/piston -->
        <g id="actuator">
          <rect x="300" y="255" width="80" height="10" rx="2" fill="url(#actuatorGradient)"/>
          <rect id="pistonRod" x="375" y="257" width="60" height="6" rx="1" fill="#bbb"/>
        </g>

        <!-- Tilting platform -->
        <g id="tiltPlatform">
          <!-- Platform base that tilts -->
          <rect x="350" y="235" width="120" height="15" rx="2" fill="${config.FRAME_COLOR}"/>

          <!-- Lower leg -->
          <path id="lowerLeg" d="M 330,195
                   Q 340,200 355,205
                   L 440,205
                   L 440,225
                   L 355,225
                   Q 340,220 330,215 Z"
                fill="url(#skinGradient)"/>

          <!-- Boot/cradle assembly -->
          <g id="bootAssembly">
            <!-- Boot base -->
            <path d="M 420,190
                     L 520,190
                     Q 540,190 545,205
                     L 545,230
                     Q 545,245 530,245
                     L 420,245
                     L 420,190 Z"
                  fill="url(#bootGradient)" stroke="#555" stroke-width="2"/>

            <!-- Boot padding/liner -->
            <path d="M 430,195
                     L 510,195
                     Q 525,195 530,205
                     L 530,230
                     Q 530,238 520,238
                     L 430,238
                     L 430,195 Z"
                  fill="#4a4a4a"/>

            <!-- Foot inside boot -->
            <ellipse cx="480" cy="217" rx="35" ry="15" fill="url(#skinGradient)" opacity="0.8"/>

            <!-- Straps -->
            <rect x="440" y="188" width="30" height="8" rx="2" fill="url(#blueAccent)"/>
            <rect x="440" y="240" width="30" height="8" rx="2" fill="url(#blueAccent)"/>
            <rect x="500" y="200" width="8" height="35" rx="2" fill="url(#blueAccent)"/>

            <!-- Boot vents -->
            <g fill="#333" opacity="0.5">
              <rect x="455" y="205" width="15" height="3" rx="1"/>
              <rect x="455" y="212" width="15" height="3" rx="1"/>
              <rect x="455" y="219" width="15" height="3" rx="1"/>
              <rect x="455" y="226" width="15" height="3" rx="1"/>
            </g>
          </g>
        </g>

        <!-- Tilt indicator arc -->
        <g id="tiltIndicator" opacity="0.7">
          <path id="tiltArc" d="" fill="none" stroke="${config.JOINT_GLOW}"
                stroke-width="3" stroke-linecap="round"/>
        </g>
      </g>

      <!-- Force arrows (appear during treatment) -->
      <g id="forceArrows" opacity="0">
        <!-- Axial force arrow -->
        <g id="axialArrow">
          <line x1="545" y1="217" x2="570" y2="217" stroke="#27ae60" stroke-width="3"/>
          <polygon points="570,217 560,212 560,222" fill="#27ae60"/>
        </g>
      </g>

      <!-- Status indicator -->
      <g id="statusIndicator">
        <circle id="statusLight" cx="540" cy="270" r="8" fill="#333"/>
      </g>

      <!-- Logo -->
      <g id="logo" transform="translate(240, 260)">
        <rect x="0" y="0" width="100" height="35" rx="4" fill="url(#blueAccent)"/>
        <text x="50" y="23" text-anchor="middle" font-family="Arial, sans-serif"
              font-size="12" font-weight="bold" fill="white">KneeSpa</text>
      </g>

      <!-- Labels -->
      <g class="labels" font-family="Arial, sans-serif" font-size="10" fill="#666">
        <text x="320" y="175" text-anchor="middle" font-weight="bold">TREATMENT ZONE</text>
      </g>
    `;

    this.container.appendChild(this.svg);

    // Cache element references
    this.elements = {
      legApparatus: this.svg.querySelector('#legApparatus'),
      tiltPlatform: this.svg.querySelector('#tiltPlatform'),
      bootAssembly: this.svg.querySelector('#bootAssembly'),
      lowerLeg: this.svg.querySelector('#lowerLeg'),
      kneeJoint: this.svg.querySelector('#kneeJoint'),
      pistonRod: this.svg.querySelector('#pistonRod'),
      forceArrows: this.svg.querySelector('#forceArrows'),
      axialArrow: this.svg.querySelector('#axialArrow'),
      tiltArc: this.svg.querySelector('#tiltArc'),
      statusLight: this.svg.querySelector('#statusLight')
    };
  }

  /**
   * Update visualization based on simulator state
   */
  update(state) {
    this.currentState = { ...state };
    this.updateAxialExtension();
    this.updateLateralTilt();
    this.updateForceIndicators();
    this.updateStatusLight();
    this.updatePulseEffect();
  }

  updateAxialExtension() {
    const config = KneeVisualization.CONFIG;
    const { pressure, pulseOffset } = this.currentState;

    // Calculate extension based on pressure
    const pressureRatio = pressure / 80;
    let extension = config.MIN_EXTENSION +
                    (config.MAX_EXTENSION - config.MIN_EXTENSION) * pressureRatio;

    // Add pulse offset
    extension += pulseOffset * 0.5;

    // Move the boot assembly outward (to the right)
    this.elements.bootAssembly.setAttribute('transform', `translate(${extension}, 0)`);

    // Extend the piston rod
    const pistonExtension = extension * 0.8;
    this.elements.pistonRod.setAttribute('width', 60 + pistonExtension);

    // Grow the knee joint glow based on decompression
    const glowScale = 1 + (pressureRatio * 0.5);
    this.elements.kneeJoint.setAttribute('rx', 18 * glowScale);
    this.elements.kneeJoint.setAttribute('ry', 15 * glowScale);
    this.elements.kneeJoint.setAttribute('opacity', 0.3 + (pressureRatio * 0.4));
  }

  updateLateralTilt() {
    const { lateralAngle } = this.currentState;

    // Rotate the tilt platform around the knee area
    // Positive angle = tilt right (foot goes up), Negative = tilt left (foot goes down)
    const pivotX = 350;
    const pivotY = 220;

    this.elements.tiltPlatform.setAttribute('transform',
      `rotate(${-lateralAngle * 0.5}, ${pivotX}, ${pivotY})`
    );

    // Update tilt arc indicator
    if (Math.abs(lateralAngle) > 1) {
      this.drawTiltArc(lateralAngle);
    } else {
      this.elements.tiltArc.setAttribute('d', '');
    }
  }

  drawTiltArc(angle) {
    const centerX = 350;
    const centerY = 220;
    const radius = 40;

    const startAngle = 0;
    const endAngle = -angle * 0.5;

    const startRad = (startAngle * Math.PI) / 180;
    const endRad = (endAngle * Math.PI) / 180;

    const startX = centerX + radius * Math.cos(startRad);
    const startY = centerY + radius * Math.sin(startRad);
    const endX = centerX + radius * Math.cos(endRad);
    const endY = centerY + radius * Math.sin(endRad);

    const largeArc = Math.abs(angle) > 180 ? 1 : 0;
    const sweep = angle > 0 ? 0 : 1;

    const arcPath = `M ${startX} ${startY} A ${radius} ${radius} 0 ${largeArc} ${sweep} ${endX} ${endY}`;
    this.elements.tiltArc.setAttribute('d', arcPath);
  }

  updateForceIndicators() {
    const { pressure } = this.currentState;

    // Show force arrows when pressure is applied
    const opacity = Math.min(pressure / 25, 1);
    this.elements.forceArrows.setAttribute('opacity', opacity);

    // Animate arrow position based on extension
    const extension = (pressure / 80) * 25;
    this.elements.axialArrow.setAttribute('transform', `translate(${extension}, 0)`);
  }

  updateStatusLight() {
    const { isRunning, phase, isPulsing } = this.currentState;

    let color = '#333'; // Off

    if (this.currentState.pressure > 0) {
      if (isPulsing) {
        // Pulsing - animate between green shades
        const pulseIntensity = Math.abs(this.currentState.pulseOffset) / 3;
        const green = Math.floor(180 + pulseIntensity * 75);
        color = `rgb(39, ${green}, 60)`;
      } else {
        color = '#27ae60'; // Solid green - active
      }
    }

    this.elements.statusLight.setAttribute('fill', color);
  }

  updatePulseEffect() {
    const { isPulsing, pulseOffset, pressure } = this.currentState;

    if (isPulsing && pressure > 0 && Math.abs(pulseOffset) > 0) {
      this.elements.kneeJoint.setAttribute('filter', 'url(#pulseGlow)');

      // Animate knee glow intensity
      const intensity = 0.4 + Math.abs(pulseOffset) / 8;
      this.elements.kneeJoint.setAttribute('opacity', Math.min(intensity, 0.8));
    } else {
      this.elements.kneeJoint.setAttribute('filter', 'url(#glowEffect)');
    }
  }

  reset() {
    this.update({
      pressure: 0,
      lateralAngle: 0,
      isPulsing: false,
      pulseOffset: 0
    });
  }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { KneeVisualization };
}
