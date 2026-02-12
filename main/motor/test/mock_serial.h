// main/motor/test/mock_serial.h
#ifndef MOCK_SERIAL_H
#define MOCK_SERIAL_H

#ifdef UNIT_TEST

#include <stdint.h>
#include <string.h>
#include <string>
#include <queue>

#define MAX_OUTPUT_SIZE 4096

class MockSerial {
public:
    // Captured output
    char output[MAX_OUTPUT_SIZE];
    int outputLen = 0;

    // Input queue
    std::queue<std::string> inputQueue;
    std::string currentInput;
    int inputIndex = 0;

    void begin(long baud) {}

    int available() {
        if (inputIndex < (int)currentInput.length()) return 1;
        if (!inputQueue.empty()) {
            currentInput = inputQueue.front();
            inputQueue.pop();
            inputIndex = 0;
            return 1;
        }
        return 0;
    }

    int read() {
        if (inputIndex < (int)currentInput.length()) {
            return currentInput[inputIndex++];
        }
        return -1;
    }

    size_t print(const char* s) {
        int len = strlen(s);
        if (outputLen + len < MAX_OUTPUT_SIZE) {
            memcpy(output + outputLen, s, len);
            outputLen += len;
        }
        return len;
    }

    size_t print(int val) {
        char buf[16];
        snprintf(buf, sizeof(buf), "%d", val);
        return print(buf);
    }

    size_t print(float val) {
        char buf[32];
        snprintf(buf, sizeof(buf), "%.1f", val);
        return print(buf);
    }

    size_t println(const char* s) {
        size_t n = print(s);
        n += print("\n");
        return n;
    }

    size_t println(int val) {
        size_t n = print(val);
        n += print("\n");
        return n;
    }

    size_t println(float val) {
        size_t n = print(val);
        n += print("\n");
        return n;
    }

    size_t println() { return print("\n"); }

    // Test helpers
    void injectCommand(const std::string& cmd) {
        inputQueue.push(cmd + "\n");
    }

    std::string getOutput() {
        return std::string(output, outputLen);
    }

    bool outputContains(const std::string& needle) {
        return getOutput().find(needle) != std::string::npos;
    }

    void reset() {
        outputLen = 0;
        while (!inputQueue.empty()) inputQueue.pop();
        currentInput.clear();
        inputIndex = 0;
    }
};

extern MockSerial Serial;
extern MockSerial Serial1;

#endif // UNIT_TEST
#endif // MOCK_SERIAL_H
