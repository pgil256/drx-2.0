#!/usr/bin/env python3
"""
Summarize a KneeSpa serial trace (written when the app runs with
KNEESPA_SERIAL_TRACE_FILE set) around any out-of-band lateral reading.

    KNEESPA_SERIAL_TRACE_FILE=/home/pi/serial-trace.log DISPLAY=:0 python3 kneespa.py
    ... run the protocol until the warning appears, stop, quit ...
    python3 development/tools/trace_report.py /home/pi/serial-trace.log

Prints: how many status frames, the lateral range, every out-of-band value
with its count, whether the bad frames were contiguous, the axial position
and pressure at the first bad frame, every command the host sent in the
30 s before it, and the raw lines around it.
"""

import argparse
import os
import re
import sys
from collections import Counter

LINE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\] (?P<dir>RX|TX) (?P<data>.*)$")
STATUS_RE = re.compile(r"STATUS_START\|S\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?[\d.]+)\|STATUS_END")


def parse(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            m = LINE_RE.match(raw.rstrip("\n"))
            if not m:
                continue
            ts, direction, data = m.group("ts"), m.group("dir"), m.group("data")
            frame = None
            if direction == "RX":
                s = STATUS_RE.search(data)
                if s:
                    frame = (int(s.group(1)), int(s.group(2)), int(s.group(3)), float(s.group(4)))
            rows.append((ts, direction, data, frame))
    return rows


def short(row):
    ts, direction, data, frame = row
    clock = ts.split("T")[-1][:12] if "T" in ts else ts
    if frame:
        a, b, c, p = frame
        return "{} {} S a={} b={} c={} p={:.2f}".format(clock, direction, a, b, c, p)
    return "{} {} {}".format(clock, direction, data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default=os.path.expanduser("~/serial-trace.log"))
    ap.add_argument("--c-min", type=int, default=450)
    ap.add_argument("--c-max", type=int, default=2450)
    ap.add_argument("--context", type=int, default=12, help="raw lines to show before/after the first bad frame")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print("No trace at {}".format(args.path))
        return 1
    rows = parse(args.path)
    frames = [(i, r) for i, r in enumerate(rows) if r[3]]
    if not frames:
        print("{} lines, no status frames found".format(len(rows)))
        return 1

    c_vals = [r[3][2] for _, r in frames]
    bad = [(i, r) for i, r in frames if r[3][2] < args.c_min or r[3][2] > args.c_max]
    print("trace: {}".format(args.path))
    print("{} lines, {} status frames, lateral C {}..{}, first frame {}, last frame {}".format(
        len(rows), len(frames), min(c_vals), max(c_vals), short(frames[0][1])[:12], short(frames[-1][1])[:12]))
    if not bad:
        print("No lateral value outside {}..{} in this trace.".format(args.c_min, args.c_max))
        return 0

    values = Counter(r[3][2] for _, r in bad)
    print("{} out-of-band lateral frames. Values seen: {}".format(
        len(bad), ", ".join("{} x{}".format(v, n) for v, n in values.most_common())))

    # Contiguity: are the bad frames one unbroken run of status frames?
    frame_positions = {i: k for k, (i, _) in enumerate(frames)}
    ks = [frame_positions[i] for i, _ in bad]
    runs = 1 + sum(1 for x, y in zip(ks, ks[1:]) if y != x + 1)
    print("Bad frames form {} run(s). First bad frame: {}   Last bad frame: {}".format(
        runs, short(bad[0][1]), short(bad[-1][1])))

    first_i = bad[0][0]
    a, b, c, p = rows[first_i][3]
    print("At the first bad frame: axial={} horizontal={} lateral={} pressure={:.2f} lbs".format(a, b, c, p))

    # What did the host send in the 30 s before it?
    print()
    print("Host commands (TX) in the 40 lines before the first bad frame:")
    for r in rows[max(0, first_i - 40):first_i]:
        if r[1] == "TX" and r[2].strip() != "Q":
            print("   " + short(r))

    # After the run leaves the band, how does it come back?
    last_i = bad[-1][0]
    after = [r for r in rows[last_i + 1:last_i + 6] if r[3]]
    if after:
        print()
        print("First frames after the last bad one:")
        for r in after:
            print("   " + short(r))

    print()
    print("Raw lines around the first bad frame (Q acks omitted):")
    lo = max(0, first_i - args.context)
    hi = min(len(rows), first_i + args.context + 1)
    for i in range(lo, hi):
        r = rows[i]
        if r[1] == "TX" and r[2].strip() == "Q":
            continue
        marker = " <<<" if i == first_i else ""
        print("   " + short(r) + marker)
    return 0


if __name__ == "__main__":
    sys.exit(main())
