export type ParsedCommand =
  | { kind: 'axial'; value: number }
  | { kind: 'horizontal'; value: number }
  | { kind: 'lateral'; value: number }
  | { kind: 'pressure'; value: number }
  | { kind: 'pulseStart' }
  | { kind: 'pulseStop' }
  | { kind: 'eStop' }
  | { kind: 'keepalive' };

export function parseCommand(raw: string): ParsedCommand | null {
  const s = raw.trim();
  if (s === 'J') return { kind: 'pulseStart' };
  if (s === 'JS') return { kind: 'pulseStop' };
  if (s === 'X') return { kind: 'eStop' };
  if (s === 'T') return { kind: 'keepalive' };

  const axialMatch = s.match(/^A12\s+(-?\d+(?:\.\d+)?)$/);
  if (axialMatch) return { kind: 'axial', value: parseFloat(axialMatch[1]) };

  const horizontalMatch = s.match(/^B(-?\d+(?:\.\d+)?)$/);
  if (horizontalMatch) return { kind: 'horizontal', value: parseFloat(horizontalMatch[1]) };

  const lateralMatch = s.match(/^K\s+(-?\d+(?:\.\d+)?)$/);
  if (lateralMatch) return { kind: 'lateral', value: parseFloat(lateralMatch[1]) };

  const pressureMatch = s.match(/^P(-?\d+(?:\.\d+)?)$/);
  if (pressureMatch) return { kind: 'pressure', value: parseFloat(pressureMatch[1]) };

  return null;
}
