// development/tests/firmware/mock_sequence.h
// One counter shared by the Wire and Serial mocks, so a test can tell
// whether an I2C write happened before or after some serial output.
#ifndef MOCK_SEQUENCE_H
#define MOCK_SEQUENCE_H

#ifdef UNIT_TEST

// Each test program is one translation unit, so one counter per program.
static unsigned long mockSequence = 0;

static inline unsigned long nextMockSequence() { return ++mockSequence; }

#endif // UNIT_TEST
#endif // MOCK_SEQUENCE_H
