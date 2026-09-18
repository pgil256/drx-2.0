// main/motor/test/mock_hx711.h
#ifndef MOCK_HX711_H
#define MOCK_HX711_H

#ifdef UNIT_TEST

class HX711 {
public:
    enum Result { NOT_READY, SAMPLE, INVALID };
    float _units = 0.0;
    float _scale = 1.0;
    float _offset = 0.0;
    bool _tared = false;
    bool _ready = true;   // is_ready() result (false = sensor unplugged)
    long _raw = 0;        // raw ADC counts returned by read()

    void begin(int dout, int sck) {}

    void set_scale(float scale) { _scale = scale; }

    void tare() {
        _tared = true;
        _offset = (float)_raw;
    }

    bool is_ready() { return _ready; }

    long read() { return _raw; }

    float get_scale() { return _scale; }

    long get_offset() { return (long)_offset; }
    void set_offset(long value) { _offset = value; }
    float units(long raw) { return (raw - _offset) / _scale; }
    Result read_if_ready(long &raw, unsigned long &elapsed) {
        elapsed = 0;
        if (!_ready) return NOT_READY;
        raw = _raw;
        return raw == -8388608L || raw == 8388607L ? INVALID : SAMPLE;
    }

    float get_units(int times = 1) { return _units; }

    // Test helpers
    void setUnits(float units) { _units = units; }

    // Make read()-based sampling (updatePressure) yield `units` given the
    // current scale factor and offset
    void setRawForUnits(float units) {
        _raw = (long)(units * _scale + _offset);
    }
};
using Hx711Sampler = HX711;

#endif // UNIT_TEST
#endif // MOCK_HX711_H
