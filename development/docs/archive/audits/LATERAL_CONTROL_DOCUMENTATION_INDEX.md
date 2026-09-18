# Lateral Control Documentation Index

Complete documentation for the lateral control system in KneeSPA application.

## Documents Overview

### 1. LATERAL_CONTROL_SUMMARY.txt
**Purpose**: Quick reference and comprehensive summary  
**Size**: 13 KB, 341 lines  
**Best for**: Getting overview, understanding execution flow

**Contains**:
- Quick findings summary
- Detailed line-by-line code locations
- Complete execution flow from button click to timer completion
- Key components and variables
- Important notes about control locking
- Debugging tips
- File locations

**Start here**: If you need quick answers about what/where/why

---

### 2. LATERAL_CONTROL_ANALYSIS.md
**Purpose**: Deep technical analysis with code examples  
**Size**: 13 KB, 371 lines  
**Best for**: Understanding implementation details

**Contains**:
- Detailed lateral button handler implementation
- Control enable/disable methods with full code
- Actuator controls list with all buttons
- Complete move_actuator method for lateral movement
- QTimer scheduling mechanism details
- Button-to-control flow diagram
- Key code locations table

**Start here**: If you need to understand how the system works

---

### 3. LATERAL_CONTROL_QUICK_REFERENCE.md
**Purpose**: Condensed reference guide  
**Size**: 5.2 KB, 191 lines  
**Best for**: Quick lookups and specific questions

**Contains**:
- Quick access points for all major components
- Control disable/enable methods (side-by-side)
- Movement execution details
- What triggers the scheduling message
- Lateral button metadata table
- Actuator mapping
- Key variables table
- Command sequence flow
- Debugging suggestions
- Common issues and checks

**Start here**: If you need to find something specific quickly

---

### 4. LATERAL_CONTROL_FLOW_DIAGRAM.md
**Purpose**: Visual representation of control flows  
**Size**: 27 KB, 373 lines  
**Best for**: Understanding system behavior visually

**Contains**:
1. Complete button-click-to-movement-complete flow chart
   - All 8 phases of the process
   - Decision points and error paths
   - Arduino communication
   - Control re-enabling with scheduling

2. Control disable/enable state machine
   - Visual state transitions
   - When states change
   - Flow between states

3. Data flow diagram
   - Position calculation
   - Boundary checking
   - Config lookup
   - State and UI updates
   - Arduino communication

4. Timing diagram
   - Precise timeline from button click to ready state
   - State transitions at each time point
   - Delay measurements

5. Lateral button parameter matrix
   - All buttons with parameters
   - Step sizes and speeds
   - Direction indicators

6. Control hierarchy
   - Protocol vs manual mode
   - Button states by context
   - Scheduling logic

**Start here**: If you're a visual learner

---

## Quick Navigation

### Finding Information by Topic

**BUTTON HANDLERS**
- Overview: LATERAL_CONTROL_SUMMARY.txt, Quick Findings #1
- Detailed: LATERAL_CONTROL_ANALYSIS.md, Section 1
- Quick ref: LATERAL_CONTROL_QUICK_REFERENCE.md, Section 1 & 5
- Visual: LATERAL_CONTROL_FLOW_DIAGRAM.md, Section 5

**CONTROL ENABLE/DISABLE**
- Overview: LATERAL_CONTROL_SUMMARY.txt, Quick Findings #2
- Detailed: LATERAL_CONTROL_ANALYSIS.md, Section 2
- Quick ref: LATERAL_CONTROL_QUICK_REFERENCE.md, Section 2
- Visual: LATERAL_CONTROL_FLOW_DIAGRAM.md, Section 2

**SCHEDULING MESSAGE**
- Overview: LATERAL_CONTROL_SUMMARY.txt, Quick Findings #3
- Detailed: LATERAL_CONTROL_ANALYSIS.md, Section 5
- Quick ref: LATERAL_CONTROL_QUICK_REFERENCE.md, Section 4
- Location: Line 542 in main/kneespa.py

**TIMER SCHEDULING**
- Overview: LATERAL_CONTROL_SUMMARY.txt, Quick Findings #4
- Detailed: LATERAL_CONTROL_ANALYSIS.md, Section 5
- Quick ref: LATERAL_CONTROL_QUICK_REFERENCE.md, Section 2
- Visual: LATERAL_CONTROL_FLOW_DIAGRAM.md, Section 4

**COMPLETE FLOW**
- Step-by-step: LATERAL_CONTROL_SUMMARY.txt, Execution Flow Summary
- Detailed: LATERAL_CONTROL_ANALYSIS.md, Section 6
- Visual: LATERAL_CONTROL_FLOW_DIAGRAM.md, Section 1
- Reference: LATERAL_CONTROL_QUICK_REFERENCE.md, Section 8

---

## File Location Reference

All documentation in:
```
/mnt/c/users/user/desktop/drx-demo-final/
```

Source code in:
```
/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py
```

Key code sections:
- Lines 504-526: actuator_controls list
- Lines 536-545: disable/enable methods
- Lines 1154-1165: button handlers
- Lines 1228-1364: move_actuator method
- Lines 1308-1364: lateral movement code
- Lines 1687-1693: set_done signal handler

---

## Key Facts Summary

| Aspect | Details |
|--------|---------|
| Lateral Actuator | self.actuator_c |
| Button Handlers | Lines 1154-1165 |
| Control Methods | Lines 536-545 |
| Enable/Disable All | Both affect 26 total buttons |
| Timer Delay | 200 milliseconds |
| Timer Type | QTimer.singleShot() |
| Position Range | -20° to +20° |
| Step Size (Slow) | 5° |
| Step Size (Fast) | 10° |
| Arduino Command | "K{position}" |
| Scheduling Message | Line 542 |
| Protocol Flag | protocol_running |
| Triggered By | set_done() signal |

---

## How to Use These Documents

**I want to understand the big picture:**
1. Start with LATERAL_CONTROL_SUMMARY.txt
2. Read "Quick Findings" section
3. Read "Execution Flow Summary" section

**I need to fix a bug:**
1. Start with LATERAL_CONTROL_QUICK_REFERENCE.md
2. Look at "Common Issues & Checks" section (Section 10)
3. Use specific line numbers to navigate to code

**I'm debugging and need flow visualization:**
1. Open LATERAL_CONTROL_FLOW_DIAGRAM.md
2. Look at the appropriate diagram
3. Cross-reference with timing information

**I need implementation details:**
1. Start with LATERAL_CONTROL_ANALYSIS.md
2. Find the relevant section
3. Read the code examples and explanations

**I need quick answers:**
1. Use LATERAL_CONTROL_QUICK_REFERENCE.md
2. Use the "For Debugging" section
3. Use the tables for parameter lookups

---

## Key Concepts

### Control Locking
When any actuator movement starts, ALL control buttons (lateral, horizontal, axial, leg-length) are disabled to prevent conflicting commands.

### Timer Scheduling
After movement completes, buttons are re-enabled with a 200ms delay using QTimer.singleShot(). This prevents rapid clicking and allows Arduino to settle.

### State-Based Enabling
Control re-enabling only happens if `protocol_running == False`. During protocol execution, buttons stay disabled to prevent manual intervention.

### Calibration Dependency
Lateral movements map angle degrees (e.g., 5.0°) to calibrated firmware positions (e.g., 50) via config.CMarks dictionary.

### Serial Communication
Lateral commands use "K{position}" format and are sent via /dev/serial0 at 9600 baud. Arduino confirms completion by sending "done" signal.

---

## Document Generation

These documents were generated on: **2025-11-11**

Generated for: **KneeSPA Lateral Control System**

Repository: `/mnt/c/users/user/desktop/drx-demo-final`

Branch: `refactor-architecture`

Generated documents:
1. LATERAL_CONTROL_SUMMARY.txt - This summary file
2. LATERAL_CONTROL_ANALYSIS.md - Comprehensive technical analysis
3. LATERAL_CONTROL_QUICK_REFERENCE.md - Quick reference guide
4. LATERAL_CONTROL_FLOW_DIAGRAM.md - Visual flow diagrams
5. LATERAL_CONTROL_DOCUMENTATION_INDEX.md - This index file

---

## Version Information

Source File Version: main/kneespa.py (current)
Python Version: 3.7 (per CLAUDE.md)
Framework: PyQt5
Platform: Raspberry Pi 4 (target platform)

---

## Next Steps

1. **Read Documentation**: Start with the appropriate document based on your needs
2. **Reference Code**: Use line numbers to navigate to source code in main/kneespa.py
3. **Test Understanding**: Use debugging tips to verify behavior
4. **Ask Questions**: Use documentation to form specific questions

---
