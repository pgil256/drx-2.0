#include <unity.h>
#include <stdint.h>
#include <initializer_list>
#define DRX_FIRMWARE_TEST
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT_PULLUP 2
uint32_t word;
int clocks, reads, clockLevel, dataMode;
bool ready, releaseData, loseReady;
unsigned long micros() { return clocks; }
void pinMode(int pin, int mode) { if (pin == 7) dataMode=mode; }
void digitalWrite(int pin, int level) {
    if (pin == 6) { clockLevel=level; if (level==HIGH) ++clocks; }
}
int digitalRead(int pin) {
    ++reads;
    if (clocks==0) return (!ready || (loseReady && reads==2)) ? HIGH : LOW;
    if (clocks==25) return releaseData ? HIGH : LOW;
    return (word >> (24-clocks)) & 1;
}
#include "../../../../runtime/arduino/motor/hx711_sampler.h"
Hx711Sampler sampler;
void setUp() {
    clocks=reads=0; ready=releaseData=true; loseReady=false; word=0;
    sampler.begin(7,6); sampler.set_offset(0); sampler.set_scale(1);
}
void tearDown() {}
void test_not_ready_has_no_clocks() {
    ready=false; long raw=99; unsigned long duration=0;
    TEST_ASSERT_EQUAL(Hx711Sampler::NOT_READY, sampler.read_if_ready(raw,duration));
    TEST_ASSERT_EQUAL(0,clocks); TEST_ASSERT_EQUAL(99,raw);
    TEST_ASSERT_EQUAL(INPUT_PULLUP,dataMode); TEST_ASSERT_EQUAL(LOW,clockLevel);
}
void test_readiness_race_returns_without_waiting() {
    loseReady=true; long raw=99; unsigned long duration=0;
    TEST_ASSERT_EQUAL(Hx711Sampler::NOT_READY, sampler.read_if_ready(raw,duration));
    TEST_ASSERT_EQUAL(0,clocks);
}
void test_positive_negative_and_gain_clock() {
    for (int32_t value : {123456, -123456, 0}) {
        setUp(); word = (uint32_t)value & 0xffffff;
        long raw=0; unsigned long duration=0;
        TEST_ASSERT_EQUAL(Hx711Sampler::SAMPLE, sampler.read_if_ready(raw,duration));
        TEST_ASSERT_EQUAL(value,raw); TEST_ASSERT_EQUAL(25,clocks);
        TEST_ASSERT_EQUAL(LOW,clockLevel);
    }
}
void test_rails_and_stuck_low_rejected() {
    for (uint32_t value : {0x7fffffU,0x800000U,0U}) {
        setUp(); word=value; if(value==0) releaseData=false;
        long raw=0; unsigned long duration=0;
        TEST_ASSERT_EQUAL(Hx711Sampler::INVALID,sampler.read_if_ready(raw,duration));
        TEST_ASSERT_EQUAL(25,clocks); TEST_ASSERT_EQUAL(LOW,clockLevel);
    }
}
int main() {
    UNITY_BEGIN(); RUN_TEST(test_not_ready_has_no_clocks);
    RUN_TEST(test_readiness_race_returns_without_waiting);
    RUN_TEST(test_positive_negative_and_gain_clock);
    RUN_TEST(test_rails_and_stuck_low_rejected); return UNITY_END();
}
