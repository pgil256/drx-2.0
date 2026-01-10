/**
 * KneeSpa Knee Visualization
 *
 * Renders an animated SVG diagram of the knee joint responding to
 * simulator state changes. Shows decompression (joint gap), lateral
 * tilt, and pulsing effects.
 */

class KneeVisualization {
  static CONFIG = {
    WIDTH: 300,
    HEIGHT: 400,
    BONE_COLOR: '#e8e8e8',
    BONE_STROKE: '#999',
    JOINT_COLOR: '#3498db',
    JOINT_GLOW: '#5dade2',
    FORCE_ARROW_COLOR: '#27ae60',

    // Animation ranges
    MIN_GAP: 4,           // Joint gap at 0 pressure
    MAX_GAP: 30,          // Joint gap at max pressure
    MAX_ROTATION: 20,     // Max rotation degrees
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

    // Create SVG element
    this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this.svg.setAttribute('viewBox', `0 0 ${config.WIDTH} ${config.HEIGHT}`);
    this.svg.setAttribute('class', 'knee-svg');

    // Define gradients and filters
    this.svg.innerHTML = `
      <defs>
        <!-- Bone gradient -->
        <linearGradient id="boneGradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" style="stop-color:#f5f5f5"/>
          <stop offset="50%" style="stop-color:#e8e8e8"/>
          <stop offset="100%" style="stop-color:#d0d0d0"/>
        </linearGradient>

        <!-- Joint glow effect -->
        <filter id="jointGlow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="blur"/>
          <feMerge>
            <feMergeNode in="blur"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>

        <!-- Pulse glow animation -->
        <filter id="pulseGlow" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="8" result="blur"/>
          <feMerge>
            <feMergeNode in="blur"/>
            <feMergeNode in="blur"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>

        <!-- Shadow for depth -->
        <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="2" dy="3" stdDeviation="3" flood-opacity="0.2"/>
        </filter>
      </defs>

      <!-- Background reference lines -->
      <g class="reference-lines" opacity="0.3">
        <line x1="150" y1="50" x2="150" y2="350" stroke="#ccc" stroke-dasharray="5,5"/>
      </g>

      <!-- Femur (upper bone) - fixed position -->
      <g id="femur" filter="url(#shadow)">
        <path d="
          M 100,60
          L 100,140
          C 100,160 110,170 120,175
          L 130,178
          L 170,178
          L 180,175
          C 190,170 200,160 200,140
          L 200,60
          C 200,50 190,40 150,40
          C 110,40 100,50 100,60
          Z
        " fill="url(#boneGradient)" stroke="${config.BONE_STROKE}" stroke-width="2"/>

        <!-- Femur condyles (rounded bottom) -->
        <ellipse cx="130" cy="178" rx="15" ry="12" fill="url(#boneGradient)" stroke="${config.BONE_STROKE}" stroke-width="2"/>
        <ellipse cx="170" cy="178" rx="15" ry="12" fill="url(#boneGradient)" stroke="${config.BONE_STROKE}" stroke-width="2"/>
      </g>

      <!-- Joint space (decompression area) -->
      <g id="jointSpace">
        <rect id="jointRect" x="110" y="190" width="80" height="10"
              fill="${config.JOINT_COLOR}" opacity="0.6" rx="3" filter="url(#jointGlow)"/>

        <!-- Force arrows (appear during pressure) -->
        <g id="forceArrows" opacity="0">
          <polygon points="150,185 145,175 155,175" fill="${config.FORCE_ARROW_COLOR}"/>
          <polygon points="150,210 145,220 155,220" fill="${config.FORCE_ARROW_COLOR}"/>
        </g>
      </g>

      <!-- Tibia (lower bone) - rotates for lateral movement -->
      <g id="tibia" filter="url(#shadow)">
        <g id="tibiaInner">
          <!-- Tibial plateau -->
          <ellipse cx="130" cy="215" rx="18" ry="10" fill="url(#boneGradient)" stroke="${config.BONE_STROKE}" stroke-width="2"/>
          <ellipse cx="170" cy="215" rx="18" ry="10" fill="url(#boneGradient)" stroke="${config.BONE_STROKE}" stroke-width="2"/>

          <!-- Tibia shaft -->
          <path d="
            M 115,225
            L 110,340
            C 110,355 130,360 150,360
            C 170,360 190,355 190,340
            L 185,225
            C 185,215 175,210 150,210
            C 125,210 115,215 115,225
            Z
          " fill="url(#boneGradient)" stroke="${config.BONE_STROKE}" stroke-width="2"/>
        </g>
      </g>

      <!-- Angle indicator arc -->
      <g id="angleIndicator" opacity="0.7">
        <path id="angleArc" d="" fill="none" stroke="${config.JOINT_COLOR}" stroke-width="3" stroke-linecap="round"/>
        <text id="angleText" x="150" y="250" text-anchor="middle" font-size="14" fill="#666"></text>
      </g>

      <!-- Labels -->
      <g class="labels" font-family="Arial, sans-serif" font-size="12" fill="#666">
        <text x="150" y="30" text-anchor="middle" font-weight="bold">FEMUR</text>
        <text x="150" y="385" text-anchor="middle" font-weight="bold">TIBIA</text>
      </g>
    `;

    this.container.appendChild(this.svg);

    // Cache element references
    this.elements = {
      femur: this.svg.querySelector('#femur'),
      tibia: this.svg.querySelector('#tibia'),
      tibiaInner: this.svg.querySelector('#tibiaInner'),
      jointRect: this.svg.querySelector('#jointRect'),
      jointSpace: this.svg.querySelector('#jointSpace'),
      forceArrows: this.svg.querySelector('#forceArrows'),
      angleArc: this.svg.querySelector('#angleArc'),
      angleText: this.svg.querySelector('#angleText')
    };
  }

  /**
   * Update visualization based on simulator state
   * @param {object} state - { pressure, lateralAngle, isPulsing, pulseOffset }
   */
  update(state) {
    this.currentState = { ...state };
    this.updateJointGap();
    this.updateTibiaRotation();
    this.updateForceArrows();
    this.updateAngleIndicator();
    this.updatePulseEffect();
  }

  updateJointGap() {
    const config = KneeVisualization.CONFIG;
    const { pressure, pulseOffset } = this.currentState;

    // Calculate gap based on pressure (0-80 lbs -> MIN_GAP to MAX_GAP pixels)
    const pressureRatio = pressure / 80;
    let gap = config.MIN_GAP + (config.MAX_GAP - config.MIN_GAP) * pressureRatio;

    // Add pulse offset
    gap += pulseOffset;

    // Update joint rectangle
    this.elements.jointRect.setAttribute('height', gap);
    this.elements.jointRect.setAttribute('y', 190 - gap / 2);

    // Move tibia down based on gap
    const tibiaOffset = gap - config.MIN_GAP;
    this.elements.tibia.setAttribute('transform', `translate(0, ${tibiaOffset})`);
  }

  updateTibiaRotation() {
    const { lateralAngle } = this.currentState;

    // Rotate tibia around pivot point (center of tibial plateau)
    const pivotX = 150;
    const pivotY = 215 + this.getTibiaOffset();

    this.elements.tibiaInner.setAttribute('transform',
      `rotate(${lateralAngle}, ${pivotX}, ${pivotY})`
    );
  }

  updateForceArrows() {
    const { pressure } = this.currentState;

    // Show force arrows when pressure is applied
    const opacity = Math.min(pressure / 30, 1);
    this.elements.forceArrows.setAttribute('opacity', opacity);
  }

  updateAngleIndicator() {
    const { lateralAngle } = this.currentState;

    if (Math.abs(lateralAngle) < 1) {
      this.elements.angleArc.setAttribute('d', '');
      this.elements.angleText.textContent = '';
      return;
    }

    // Draw arc showing current angle
    const centerX = 150;
    const centerY = 215 + this.getTibiaOffset();
    const radius = 50;

    const startAngle = -90; // Straight up
    const endAngle = startAngle + lateralAngle;

    const startRad = (startAngle * Math.PI) / 180;
    const endRad = (endAngle * Math.PI) / 180;

    const startX = centerX + radius * Math.cos(startRad);
    const startY = centerY + radius * Math.sin(startRad);
    const endX = centerX + radius * Math.cos(endRad);
    const endY = centerY + radius * Math.sin(endRad);

    const largeArc = Math.abs(lateralAngle) > 180 ? 1 : 0;
    const sweep = lateralAngle > 0 ? 1 : 0;

    const arcPath = `M ${startX} ${startY} A ${radius} ${radius} 0 ${largeArc} ${sweep} ${endX} ${endY}`;
    this.elements.angleArc.setAttribute('d', arcPath);

    // Update angle text
    this.elements.angleText.textContent = `${lateralAngle.toFixed(1)}°`;
    this.elements.angleText.setAttribute('y', centerY + 40);
  }

  updatePulseEffect() {
    const { isPulsing, pulseOffset } = this.currentState;

    if (isPulsing && Math.abs(pulseOffset) > 0) {
      this.elements.jointSpace.setAttribute('filter', 'url(#pulseGlow)');
      // Animate joint color opacity
      const intensity = 0.6 + Math.abs(pulseOffset) / 10;
      this.elements.jointRect.setAttribute('opacity', Math.min(intensity, 0.9));
    } else {
      this.elements.jointSpace.setAttribute('filter', 'url(#jointGlow)');
      this.elements.jointRect.setAttribute('opacity', 0.6);
    }
  }

  getTibiaOffset() {
    const config = KneeVisualization.CONFIG;
    const { pressure, pulseOffset } = this.currentState;
    const pressureRatio = pressure / 80;
    const gap = config.MIN_GAP + (config.MAX_GAP - config.MIN_GAP) * pressureRatio + pulseOffset;
    return gap - config.MIN_GAP;
  }

  // Reset to neutral position
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
