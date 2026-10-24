/*
 * Desk test for the FT550 decoder. Runs on a laptop, no Pico needed.
 *
 *   cc -I.. -o ft550_test ft550_decoder_test_fs27.c ../ft550_decoder.c && ./ft550_test
 */

#include <math.h>
#include <stdio.h>
#include "ft550_decoder.h"

static int failures = 0;

static void check_float(const char* name, float got, float want) {
    if (fabsf(got - want) > 0.0005f) {
        printf("FAIL %-22s got %.4f want %.4f\n", name, got, want);
        failures++;
    } else {
        printf("ok   %-22s %.3f\n", name, got);
    }
}

static void check_int(const char* name, long got, long want) {
    if (got != want) {
        printf("FAIL %-22s got %ld want %ld\n", name, got, want);
        failures++;
    } else {
        printf("ok   %-22s %ld\n", name, got);
    }
}

int main(void) {
    ft550_sensor_data_t d;
    ft550_init_sensor_data(&d);

    const uint8_t f600[8] = {0x02, 0x8A, 0x03, 0xF5, 0x00, 0xFA, 0x03, 0x84};
    check_int("0x14080600 accepted", ft550_decode_frame(0x14080600, f600, &d), 1);
    check_float("tps %", d.tps, 65.0f);
    check_float("map bar", d.map, 1.013f);
    check_float("air temp C", d.air_temp, 25.0f);
    check_float("engine temp C", d.engine_temp, 90.0f);

    const uint8_t f601[8] = {0x0F, 0xA0, 0x0B, 0xB8, 0x00, 0x64, 0x00, 0x03};
    check_int("0x14080601 accepted", ft550_decode_frame(0x14080601, f601, &d), 1);
    check_float("oil pressure bar", d.oil_pressure, 4.0f);
    check_float("fuel pressure bar", d.fuel_pressure, 3.0f);
    check_float("water pressure bar", d.water_pressure, 0.1f);
    check_int("gear", d.gear, 3);

    const uint8_t f602[8] = {0x03, 0xE8, 0x1F, 0x40, 0xFF, 0x9C, 0x00, 0x01};
    check_int("0x14080602 accepted", ft550_decode_frame(0x14080602, f602, &d), 1);
    check_float("lambda", d.exhaust_o2, 1.0f);
    check_int("rpm", d.rpm, 8000);
    check_float("oil temp C (negative)", d.oil_temp, -10.0f);
    check_int("pit limit", d.pit_limit, 1);

    const uint8_t f603[8] = {0x00, 0x50, 0x00, 0x51, 0x00, 0x52, 0x00, 0x53};
    check_int("0x14080603 accepted", ft550_decode_frame(0x14080603, f603, &d), 1);
    check_int("wheel FR", d.wheel_speed_fr, 80);
    check_int("wheel FL", d.wheel_speed_fl, 81);
    check_int("wheel RR", d.wheel_speed_rr, 82);
    check_int("wheel RL", d.wheel_speed_rl, 83);

    const uint8_t f608[8] = {0x03, 0x20, 0x02, 0xBC, 0x00, 0x02, 0x4E, 0x20};
    check_int("0x14080608 accepted", ft550_decode_frame(0x14080608, f608, &d), 1);
    check_float("brake pressure bar", d.brake_pressure, 20.0f);

    const uint8_t junk[8] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
    check_int("screen frame 0x600 ignored", ft550_decode_frame(0x600, junk, &d), 0);
    check_int("random ext ID ignored", ft550_decode_frame(0x18FF1234, junk, &d), 0);
    check_int("rpm untouched after junk", d.rpm, 8000);
    check_float("tps untouched after junk", d.tps, 65.0f);

    printf("\n%s (%d failure%s)\n", failures ? "FAILED" : "ALL PASSED", failures, failures == 1 ? "" : "s");
    return failures ? 1 : 0;
}
