// development/tests/firmware/mock_wire.h
#ifndef MOCK_WIRE_H
#define MOCK_WIRE_H

#ifdef UNIT_TEST

#include <stdint.h>
#include <string.h>

#define MAX_WIRE_COMMANDS 20000
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
    void setWireTimeout(uint32_t, bool) {}
    bool timeoutFlag = false;
    void clearWireTimeoutFlag() { timeoutFlag = false; }
    bool getWireTimeoutFlag() { return timeoutFlag; }

    void beginTransmission(uint8_t address) {
        _currentAddress = address;
        _txLen = 0;
    }

    uint8_t write(uint8_t data) {
        if (shortMotorWrite && _txLen > 0 &&
            (_txBuffer[0] == 0x85 || _txBuffer[0] == 0x86)) return 0;
        if (_txLen < MAX_WIRE_DATA) {
            _txBuffer[_txLen++] = data;
        }
        return 1;
    }

    // Tests set this to make the next N endTransmission() calls report a
    // bus error (4 = other error), simulating a NACK / timed-out SMC write
    int failTransmissions = 0;
    int motorWriteResult = 0;
    int responseBytes = 2;
    bool responseTimeout = false;
    bool shortMotorWrite = false;

    uint8_t endTransmission() {
        if (commandCount < MAX_WIRE_COMMANDS) {
            commands[commandCount].address = _currentAddress;
            memcpy(commands[commandCount].data, _txBuffer, _txLen);
            commands[commandCount].dataLen = _txLen;
            commandCount++;
        }
        if (failTransmissions > 0) {
            failTransmissions--;
            return 4;
        }
        if (_txLen == 3 && (_txBuffer[0] == 0x85 || _txBuffer[0] == 0x86))
            return motorWriteResult;
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
        _rxLen = responseBytes;
        timeoutFlag = responseTimeout;
        return responseBytes;
    }

    int available() { return _rxLen - _rxIndex; }

    uint8_t read() {
        if (_rxIndex < _rxLen) return _rxBuffer[_rxIndex++];
        return 0;
    }

    void reset() {
        commandCount = 0;
        failTransmissions = 0;
        motorWriteResult = 0;
        responseBytes = 2;
        responseTimeout = shortMotorWrite = false;
        _txLen = 0;
        _rxLen = 0;
        _rxIndex = 0;
    }
};

extern MockWire Wire;

#endif // UNIT_TEST
#endif // MOCK_WIRE_H
