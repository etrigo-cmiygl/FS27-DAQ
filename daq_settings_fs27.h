/**
 * @file  daq_settings_fs27.h
 * @brief DAQ settings: what goes in the screen frames and the radio packet, and how often.
 *
 * Plain C with no Pico SDK calls, so it also compiles on a laptop for the desk test
 * (tests/daq_settings_test_fs27.c). The factory settings reproduce the fixed FS27 v1
 * firmware exactly: screen frames 0x600-0x603, the 68-byte "FS26" LoRa packet, 2 Hz radio,
 * 20 Hz screen, 5 Hz GPS.
 *
 * Protocol: see wiki/DAQ-Settings-Protocol.md (version 2).
 */
#ifndef DAQ_SETTINGS_FS27_H
#define DAQ_SETTINGS_FS27_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "ft550_decoder.h"

#define DAQ_FW_NAME              "FS27-DAQ-2.0"
#define DAQ_PROTO_VERSION        2
#define DAQ_SETTINGS_MAGIC       0x47533237u   /* "72SG" little-endian */
#define DAQ_SETTINGS_VERSION     1
#define DAQ_MAX_SCREEN_FRAMES    8
#define DAQ_MAX_FRAME_SIGNALS    8
#define DAQ_MAX_RADIO_FIELDS     48
#define DAQ_MAX_PACKET_BYTES     200
#define DAQ_LEGACY_PACKET_MAGIC  0x46533236u   /* "FS26": the fixed v1 layout */
#define DAQ_CUSTOM_PACKET_MAGIC  0x46533237u   /* "FS27": followed by a layout version byte */

/* Where a value comes from. 1-36 are the FT550 simplified frames in order (frame * 4 + value + 1). */
typedef enum {
    DAQ_SRC_NONE = 0,
    DAQ_SRC_TPS = 1, DAQ_SRC_MAP, DAQ_SRC_AIR_TEMP, DAQ_SRC_ENGINE_TEMP,
    DAQ_SRC_OIL_PRESSURE, DAQ_SRC_FUEL_PRESSURE, DAQ_SRC_WATER_PRESSURE, DAQ_SRC_GEAR,
    DAQ_SRC_LAMBDA, DAQ_SRC_RPM, DAQ_SRC_OIL_TEMP, DAQ_SRC_PIT_LIMIT,
    DAQ_SRC_WHEEL_FR, DAQ_SRC_WHEEL_FL, DAQ_SRC_WHEEL_RR, DAQ_SRC_WHEEL_RL,
    DAQ_SRC_TC_SLIP, DAQ_SRC_TC_RETARD, DAQ_SRC_TC_CUT, DAQ_SRC_HEADING,
    DAQ_SRC_SHOCK_FR, DAQ_SRC_SHOCK_FL, DAQ_SRC_SHOCK_RR, DAQ_SRC_SHOCK_RL,
    DAQ_SRC_G_ACCEL, DAQ_SRC_G_LATERAL, DAQ_SRC_YAW_FRONTAL, DAQ_SRC_YAW_LATERAL,
    DAQ_SRC_LAMBDA_CORRECTION, DAQ_SRC_FUEL_FLOW, DAQ_SRC_INJ_TIME_A, DAQ_SRC_INJ_TIME_B,
    DAQ_SRC_TRANS_OIL_TEMP, DAQ_SRC_TRANS_TEMP, DAQ_SRC_FUEL_CONSUMPTION, DAQ_SRC_BRAKE_PRESSURE,
    DAQ_SRC_BATTERY = 37,
    DAQ_SRC_GPS_LAT = 40, DAQ_SRC_GPS_LON, DAQ_SRC_GPS_SPEED, DAQ_SRC_GPS_ALT, DAQ_SRC_GPS_SATS, DAQ_SRC_GPS_FIX,
    DAQ_SRC_TX_COUNT = 50, DAQ_SRC_CAN_COUNT = 51,
    DAQ_SRC_LIMIT = 52
} daq_source_t;

typedef enum { DAQ_T_U8 = 0, DAQ_T_I8, DAQ_T_U16, DAQ_T_I16, DAQ_T_U32, DAQ_T_I32, DAQ_T_F32, DAQ_T_LIMIT } daq_type_t;

typedef struct __attribute__((packed)) {
    uint8_t src;        /* daq_source_t */
    uint8_t byte;       /* first data byte, 0-7 */
    uint8_t bits;       /* 8, 16 or 32 */
    uint8_t is_signed;
    float   m1;         /* sent value = source * m1 * m2, then cut down to a whole number */
    float   m2;
} daq_screen_signal_t;

typedef struct __attribute__((packed)) {
    uint16_t id;        /* standard CAN ID */
    uint8_t  n;         /* signals in use, 0 = frame not sent */
    uint8_t  reserved;
    daq_screen_signal_t sig[DAQ_MAX_FRAME_SIGNALS];
} daq_screen_frame_t;

typedef struct __attribute__((packed)) {
    uint8_t src;        /* daq_source_t */
    uint8_t type;       /* daq_type_t */
} daq_radio_field_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint16_t length;
    uint32_t crc;       /* CRC-32 of everything after this field */
    uint32_t counter;   /* goes up by one on every save */
    uint8_t  gps_hz;    /* 1, 5 or 10 */
    uint8_t  radio_hz;  /* 2 to 10 */
    uint8_t  screen_hz; /* 1 to 50 */
    uint8_t  layout_version;   /* sent in custom radio packets so the pit side can tell layouts apart */
    uint8_t  n_radio;
    uint8_t  reserved[3];
    daq_screen_frame_t frames[DAQ_MAX_SCREEN_FRAMES];
    daq_radio_field_t  radio[DAQ_MAX_RADIO_FIELDS];
} daq_settings_t;

/* Everything the DAQ knows right now, gathered by the main program. */
typedef struct {
    ft550_sensor_data_t can;
    float    latitude, longitude, speed_kph, altitude;
    int      satellites;
    bool     fix_valid;
    uint32_t tx_count;
    uint32_t can_frame_count;
} daq_inputs_t;

uint32_t daq_crc32(const uint8_t* data, size_t len);
void daq_settings_factory(daq_settings_t* s);
void daq_settings_seal(daq_settings_t* s);
bool daq_settings_valid(const daq_settings_t* s);       /* magic, version, length and CRC */
bool daq_settings_in_range(const daq_settings_t* s);    /* every value allowed */
bool daq_radio_is_factory(const daq_settings_t* s);
int  daq_radio_packet_size(const daq_settings_t* s);

/* Fills buf (8 bytes) for screen frame idx. Returns false if that frame isn't in use. */
bool daq_build_screen_frame(const daq_settings_t* s, int idx, const daq_inputs_t* in, uint32_t* id, uint8_t buf[8]);
/* Fills buf with the radio packet. Returns its length, or 0 if it doesn't fit. */
int  daq_build_radio_packet(const daq_settings_t* s, const daq_inputs_t* in, uint8_t* buf, int max);

uint32_t daq_radio_sleep_ms(const daq_settings_t* s);
uint32_t daq_screen_period_ms(const daq_settings_t* s);
/* Writes e.g. "$PMTK220,200*2C\r\n" for 5 Hz into out (at least 32 bytes). */
void daq_gps_rate_command(int hz, char* out, size_t out_size);

/* The settings conversation. `live` is what the DAQ is running, `pending` is being edited. */
typedef struct {
    daq_settings_t* live;
    daq_settings_t* pending;
    void (*reply)(const char* line);                 /* send one line back (no newline) */
    bool (*commit)(const daq_settings_t* sealed);    /* save to flash and make live; false if it failed */
    bool loaded_from_flash;
} daq_proto_t;

/* Handles one line. Returns true if it was a settings line ($GM,...), false if it wasn't for us. */
bool daq_proto_handle(daq_proto_t* p, const daq_inputs_t* in, const char* line);
void daq_proto_format(const char* body, char* out, size_t out_size);   /* adds $ and *CS */

#endif
