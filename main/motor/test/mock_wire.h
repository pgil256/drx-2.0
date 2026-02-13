// main/motor/test/mock_wire.h
#ifndef MOCK_WIRE_H
#define MOCK_WIRE_H

#ifdef UNIT_TEST

#include <stdint.h>
#include <string.h>

#define MAX_WIRE_COMMANDS 100
#define MAX_WIRE_DATA 64

struct WireCommand {
    uint8_t address;
    uint8_t data[MAX_WIRE_DATA];
    int dataLen;
};

class MockWire {
public:
    // Recorded commands
    WireCommand commands[MAX_WIRE_COMMANDS];
    int commandCount = 0;

    // Configurable position return values
    uint16_t position_12 = 0;
    uint16_t position_13 = 0;
    uint16_t position_14 = 0;

    // Internal state
    uint8_t _currentAddress = 0;
    uint8_t _txBuffer[MAX_WIRE_DATA];
    int _txLen = 0;
    uint8_t _rxBuffer[4];
    int _rxLen = 0;
    int _rxIndex = 0;

    void begin() {}
    void begin(uint8_t) {}
    void begin(int) {}

    void beginTransmission(uint8_t address) {
        _currentAddress = address;
        _txLen = 0;
    }

    uint8_t write(uint8_t data) {
        if (_txLen < MAX_WIRE_DATA) {
            _txBuffer[_txLen++] = data;
        }
        return 1;
    }

    uint8_t endTransmission() {
        if (commandCount < MAX_WIRE_COMMANDS) {
            commands[commandCount].address = _currentAddress;
            memcpy(commands[commandCount].data, _txBuffer, _txLen);
            commands[commandCount].dataLen = _txLen;
            commandCount++;
        }
        return 0;
    }

    uint8_t requestFrom(uint8_t address, uint8_t count) {
        _rxIndex = 0;
        uint16_t pos = 0;
        if (address == 12) pos = position_12;
        else if (address == 13) pos = position_13;
        else if (address == 14) pos = position_14;

        _rxBuffer[0] = pos & 0xFF;
        _rxBuffer[1] = (pos >> 8) & 0xFF;
        _rxLen = 2;
        return 2;
    }

    int available() { return _rxLen - _rxIndex; }

    uint8_t read() {
        if (_rxIndex < _rxLen) return _rxBuffer[_rxIndex++];
        return 0;
    }

    void reset() {
        commandCount = 0;
        _txLen = 0;
        _rxLen = 0;
        _rxIndex = 0;
    }
};

extern MockWire Wire;

#endif // UNIT_TEST
#endif // MOCK_WIRE_H
