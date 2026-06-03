// main/motor/test/mock_hx711.h
#ifndef MOCK_HX711_H
#define MOCK_HX711_H

#ifdef UNIT_TEST

class HX711 {
public:
    float _units = 0.0;
    float _scale = 1.0;
    bool _tared = false;

    void begin(int dout, int sck) {}

    void set_scale(float scale) { _scale = scale; }

    void tare() { _tared = true; }

    float get_units(int times = 1) { return _units; }

    // Test helper
    void setUnits(float units) { _units = units; }
};

#endif // UNIT_TEST
#endif // MOCK_HX711_H
