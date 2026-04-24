import { describe, it, expect } from 'vitest';
import { parseCommand } from './parseCommand';

describe('parseCommand', () => {
  it('parses axial commands (A12 <value>)', () => {
    expect(parseCommand('A12 2.5')).toEqual({ kind: 'axial', value: 2.5 });
    expect(parseCommand('A12 0')).toEqual({ kind: 'axial', value: 0 });
  });

  it('parses horizontal commands (B<value>)', () => {
    expect(parseCommand('B-15')).toEqual({ kind: 'horizontal', value: -15 });
    expect(parseCommand('B5')).toEqual({ kind: 'horizontal', value: 5 });
  });

  it('parses lateral commands (K <value>)', () => {
    expect(parseCommand('K -20')).toEqual({ kind: 'lateral', value: -20 });
    expect(parseCommand('K 20')).toEqual({ kind: 'lateral', value: 20 });
  });

  it('parses pressure commands (P<value>)', () => {
    expect(parseCommand('P40')).toEqual({ kind: 'pressure', value: 40 });
  });

  it('parses pulse toggles J and JS', () => {
    expect(parseCommand('J')).toEqual({ kind: 'pulseStart' });
    expect(parseCommand('JS')).toEqual({ kind: 'pulseStop' });
  });

  it('parses emergency stop X', () => {
    expect(parseCommand('X')).toEqual({ kind: 'eStop' });
  });

  it('parses keepalive T', () => {
    expect(parseCommand('T')).toEqual({ kind: 'keepalive' });
  });

  it('returns null for unknown commands', () => {
    expect(parseCommand('Z99')).toBeNull();
    expect(parseCommand('')).toBeNull();
  });
});
