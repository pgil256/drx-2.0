// main/motor/test/mock_hx711.h
#ifndef MOCK_HX711_H
#define MOCK_HX711_H

#ifdef UNIT_TEST

class HX711 {
public:
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

    float get_offset() { return _offset; }

    float get_units(int times = 1) { return _units; }

    // Test helpers
    void setUnits(float units) { _units = units; }

    // Make read()-based sampling (updatePressure) yield `units` given the
    // current scale factor and offset
    void setRawForUnits(float units) {
        _raw = (long)(units * _scale + _offset);
    }
};

#endif // UNIT_TEST
#endif // MOCK_HX711_H
