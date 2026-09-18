# Actuator calibration panel

Log in, open **Setup**, and tap **Calibrate Actuators** at the top of the Manual
Actuator Control card. You can also tap the profile avatar and choose
**Calibrate Actuators**. The panel
uses the application's existing Arduino connection. Finish other movement,
treatment, and reset operations before opening it. Perform calibration with
the device unloaded and measure angles with a physical gauge or reference.

## Angle marks

1. Select **Horizontal** or **Lateral**. Live positions are shown in counts.
2. Use the **−50 / +50** buttons for small jogs or **−200 / +200** for larger
   jogs. Each press requests a bounded position move, not continuous motion.
3. Measure the actual angle. Set **Measured angle** with its **− / +** buttons
   or enter a value, then tap **Record current position**. Selecting or editing
   an angle does not move the device.
4. Record intermediate angles and both endpoints: horizontal **−25° / +5°**,
   lateral **−20° / +20°**. Recording an existing angle replaces its draft value.
   The table distinguishes existing values from measurements recorded in this
   session. Existing values are not automatically reverified.
5. Select a table row and use **Go to selected mark** to check that point
   against the physical gauge. **Remove selected mark** removes it from the draft.
6. Tap **Save calibration** to apply the draft. Changes to angle tables must
   cover the endpoints, follow a consistent position order, and remain inside
   the firmware's position limits. The application interpolates between marks.

## Distance factors

On **Distance factor**, record a start position, jog the actuator, then record
an end position. Measure the actual actuator travel between these positions in
inches and enter it in **Measured travel**. Tap **Calculate factor**, review the
result, then **Use this factor** and **Save calibration**. Start/end samples are
kept separately for each actuator. An already known factor can also be entered
directly and staged with **Use this factor**.

The calculation is `abs(end - start) / measured_inches * 6`, matching the
application's existing B/C distance-readout convention. It does not calculate
angles from inches or change the firmware's fixed inches-per-command constants.
Angle movement uses `BMarks` and `CMarks`; distance factors are `b_factor` and
`c_factor`. Axial and load-cell calibration are outside this panel's scope.

## Saving and stopping

Draft edits do not change live settings until Save. Saving creates a timestamped
`.bak` next to the active configuration file (including a custom `--config`
path), writes atomically, and applies the changed B/C values in memory. Other
configuration sections are preserved. Closing with unsaved edits offers Discard
or Cancel. Saved edits survive later normal configuration writes and restarts.

Movement and recording require fresh, stable feedback. A move must be
acknowledged and settle at its target before another move or capture. Firmware
rejection, stalled movement, connection loss, or a 15-second movement timeout
stops the calibration session. **STOP**, or closing during movement, also stops
it; close the panel and reset Arduino from Setup before moving again. A physical
emergency stop retains control of its existing firmware release sequence.

Software tests use a simulated serial transport. Verify physical direction,
angle accuracy, repeatability, and stop behavior on the unloaded device before
using newly measured calibration for treatment.
