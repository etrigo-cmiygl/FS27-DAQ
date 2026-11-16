/*
 * Desk test for the DAQ settings. Runs on a laptop, no Pico needed.
 *
 *   cc -I.. -o daq_settings_test daq_settings_test_fs27.c ../daq_settings_fs27.c ../ft550_decoder.c -lm
 *   ./daq_settings_test
 *
 * The main job: prove the factory settings send exactly the same bytes as the fixed v1 firmware.
 * v1_radio_packet() and v1_screen_frames() below are copied from FS26-DAQ_fs27.c as it was at v1.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "daq_settings_fs27.h"

static int failures = 0, checks = 0;

static void check(const char* name, int ok) {
    checks++;
    if (!ok) { printf("FAIL %s\n", name); failures++; }
}

/* ---- the v1 firmware, copied ------------------------------------------------------------------ */

typedef struct __attribute__((packed)) {
    uint32_t magic;
    float    latitude;
    float    longitude;
    float    gps_speed_kph;
    float    altitude;
    uint8_t  satellites;
    uint8_t  fix_valid;
    uint16_t rpm;
    float    engine_temp;
    float    tps;
    float    oil_pressure;
    float    fuel_pressure;
    float    brake_pressure;
    float    battery_voltage;
    uint16_t wheel_speed_fr;
    uint16_t wheel_speed_fl;
    uint16_t wheel_speed_rr;
    uint16_t wheel_speed_rl;
    float    g_force_lateral;
    float    heading;
    uint16_t tx_count;
    uint16_t can_frame_count;
} combined_telemetry_packet_t;

static void v1_radio_packet(const daq_inputs_t* in, combined_telemetry_packet_t* packet) {
    const ft550_sensor_data_t can_data = in->can;
    packet->magic = 0x46533236;
    packet->latitude = in->latitude;
    packet->longitude = in->longitude;
    packet->gps_speed_kph = in->speed_kph;
    packet->altitude = in->altitude;
    packet->satellites = (uint8_t)in->satellites;
    packet->fix_valid = in->fix_valid ? 1 : 0;
    packet->rpm = can_data.rpm;
    packet->engine_temp = can_data.engine_temp;
    packet->tps = can_data.tps;
    packet->oil_pressure = can_data.oil_pressure;
    packet->fuel_pressure = can_data.fuel_pressure;
    packet->brake_pressure = can_data.brake_pressure;
    packet->battery_voltage = can_data.battery_voltage;
    packet->wheel_speed_fr = can_data.wheel_speed_fr;
    packet->wheel_speed_fl = can_data.wheel_speed_fl;
    packet->wheel_speed_rr = can_data.wheel_speed_rr;
    packet->wheel_speed_rl = can_data.wheel_speed_rl;
    packet->g_force_lateral = can_data.g_force_lateral;
    packet->heading = can_data.heading;
    packet->tx_count = (uint16_t)in->tx_count;
    packet->can_frame_count = (uint16_t)(in->can_frame_count & 0xFFFF);
}

static void v1_screen_frames(const daq_inputs_t* in, uint8_t out[4][8]) {
    const ft550_sensor_data_t can_data = in->can;
    uint8_t* dash_tx_buf = out[0];
    uint16_t rpm_out = can_data.rpm;
    uint16_t map_out = (uint16_t)(can_data.map * 100.0f * 10.0f);
    int16_t  et_out  = (int16_t)(can_data.engine_temp * 10.0f);
    uint16_t tps_out = (uint16_t)(can_data.tps * 10.0f);
    dash_tx_buf[0] = rpm_out & 0xFF; dash_tx_buf[1] = (rpm_out >> 8);
    dash_tx_buf[2] = map_out & 0xFF; dash_tx_buf[3] = (map_out >> 8);
    dash_tx_buf[4] = et_out & 0xFF;  dash_tx_buf[5] = (et_out >> 8);
    dash_tx_buf[6] = tps_out & 0xFF; dash_tx_buf[7] = (tps_out >> 8);

    uint8_t* aux_tx_buf = out[1];
    memset(aux_tx_buf, 0, 8);
    uint16_t batt_out = (uint16_t)(can_data.battery_voltage * 100.0f);
    int16_t  at_out   = (int16_t)(can_data.air_temp * 10.0f);
    aux_tx_buf[0] = batt_out & 0xFF; aux_tx_buf[1] = (batt_out >> 8);
    aux_tx_buf[2] = at_out & 0xFF;   aux_tx_buf[3] = (at_out >> 8);

    uint8_t* gps_tx_buf = out[2];
    int32_t lat_out = (int32_t)(in->latitude * 10000000.0f);
    int32_t lon_out = (int32_t)(in->longitude * 10000000.0f);
    gps_tx_buf[0] = lat_out & 0xFF;         gps_tx_buf[1] = (lat_out >> 8) & 0xFF;
    gps_tx_buf[2] = (lat_out >> 16) & 0xFF; gps_tx_buf[3] = (lat_out >> 24) & 0xFF;
    gps_tx_buf[4] = lon_out & 0xFF;         gps_tx_buf[5] = (lon_out >> 8) & 0xFF;
    gps_tx_buf[6] = (lon_out >> 16) & 0xFF; gps_tx_buf[7] = (lon_out >> 24) & 0xFF;

    uint8_t* meta_tx_buf = out[3];
    memset(meta_tx_buf, 0, 8);
    uint16_t speed_out = (uint16_t)(in->speed_kph * 10.0f);
    meta_tx_buf[0] = speed_out & 0xFF; meta_tx_buf[1] = (speed_out >> 8);
    meta_tx_buf[2] = in->satellites;
    meta_tx_buf[3] = in->fix_valid ? 1 : 0;
    meta_tx_buf[4] = in->tx_count & 0xFF; meta_tx_buf[5] = (in->tx_count >> 8);
    meta_tx_buf[6] = in->can_frame_count & 0xFF; meta_tx_buf[7] = (in->can_frame_count >> 8);
}

/* ---- pretend car values ------------------------------------------------------------------------ */

static uint32_t seed = 27;
static float rnd(float lo, float hi) {
    seed = seed * 1664525u + 1013904223u;
    return lo + (hi - lo) * (float)(seed >> 8) / 16777216.0f;
}

static void random_inputs(daq_inputs_t* in) {
    memset(in, 0, sizeof(*in));
    ft550_sensor_data_t* c = &in->can;
    c->tps = rnd(0, 100); c->map = rnd(0, 3); c->air_temp = rnd(-20, 80); c->engine_temp = rnd(-20, 130);
    c->oil_pressure = rnd(0, 10); c->fuel_pressure = rnd(0, 10); c->water_pressure = rnd(0, 5);
    c->gear = (int16_t)rnd(-1, 6); c->exhaust_o2 = rnd(0.6f, 1.4f); c->rpm = (uint16_t)rnd(0, 15000);
    c->oil_temp = rnd(-20, 160);
    c->wheel_speed_fr = (uint16_t)rnd(0, 200); c->wheel_speed_fl = (uint16_t)rnd(0, 200);
    c->wheel_speed_rr = (uint16_t)rnd(0, 200); c->wheel_speed_rl = (uint16_t)rnd(0, 200);
    c->heading = rnd(0, 360); c->g_force_lateral = rnd(-3, 3); c->battery_voltage = rnd(0, 16);
    c->brake_pressure = rnd(0, 100);
    in->latitude = rnd(-89, 89); in->longitude = rnd(-179, 179); in->speed_kph = rnd(0, 250);
    in->altitude = rnd(-50, 2000); in->satellites = (int)rnd(0, 30); in->fix_valid = rnd(0, 1) > 0.5f;
    in->tx_count = (uint32_t)rnd(0, 200000); in->can_frame_count = (uint32_t)rnd(0, 16000000);
}

/* ---- protocol helpers -------------------------------------------------------------------------- */

static char replies[16][300];
static int n_replies = 0;
static int commits = 0, fail_flash = 0;
static daq_settings_t live, pending;

static void on_reply(const char* line) {
    if (n_replies < 16) { strncpy(replies[n_replies], line, 299); replies[n_replies][299] = 0; n_replies++; }
}

static bool on_commit(const daq_settings_t* sealed) {
    if (fail_flash) return false;
    commits++;
    live = *sealed;
    return true;
}

static daq_proto_t proto = {&live, &pending, on_reply, on_commit, false};

static const char* ask(const daq_inputs_t* in, const char* body) {
    char line[300];
    daq_proto_format(body, line, sizeof(line));
    n_replies = 0;
    check(body, daq_proto_handle(&proto, in, line));
    return n_replies ? replies[n_replies - 1] : "";
}

static int starts(const char* text, const char* prefix) { return strncmp(text, prefix, strlen(prefix)) == 0; }

int main(void) {
    daq_settings_t factory;
    daq_settings_factory(&factory);
    daq_inputs_t in;

    /* 1. factory settings: structure */
    check("factory valid", daq_settings_valid(&factory));
    check("factory in range", daq_settings_in_range(&factory));
    check("factory radio is the v1 layout", daq_radio_is_factory(&factory));
    check("packet struct is 68 bytes", sizeof(combined_telemetry_packet_t) == 68);
    check("factory packet is 68 bytes", daq_radio_packet_size(&factory) == 68);
    check("radio sleep 500 ms", daq_radio_sleep_ms(&factory) == 500);
    check("screen period 50 ms", daq_screen_period_ms(&factory) == 50);
    check("settings fit in one flash sector", sizeof(daq_settings_t) <= 4096);

    /* 2. factory settings send the same bytes as v1, for 20000 sets of values */
    int packet_mismatch = 0, frame_mismatch = 0, id_mismatch = 0;
    for (int i = 0; i < 20000; i++) {
        random_inputs(&in);
        if (i == 0) memset(&in, 0, sizeof(in));
        if (i == 1) { in.can.engine_temp = -20.0f; in.can.air_temp = -5.5f; in.latitude = -33.86f; in.longitude = -151.2f; }
        if (i == 2) { in.tx_count = 65535; in.can_frame_count = 0xFFFFFFFFu; in.can.rpm = 65535; in.satellites = 255; }
        combined_telemetry_packet_t want;
        uint8_t got[DAQ_MAX_PACKET_BYTES];
        v1_radio_packet(&in, &want);
        int len = daq_build_radio_packet(&factory, &in, got, sizeof(got));
        if (len != 68 || memcmp(got, &want, 68) != 0) packet_mismatch++;
        uint8_t ref[4][8];
        v1_screen_frames(&in, ref);
        for (int f = 0; f < 4; f++) {
            uint32_t id = 0;
            uint8_t buf[8];
            if (!daq_build_screen_frame(&factory, f, &in, &id, buf)) frame_mismatch++;
            else if (memcmp(buf, ref[f], 8) != 0) frame_mismatch++;
            if (id != 0x600u + (uint32_t)f) id_mismatch++;
        }
    }
    check("factory radio packet identical to v1", packet_mismatch == 0);
    check("factory screen frames identical to v1", frame_mismatch == 0);
    check("factory screen IDs are 0x600-0x603", id_mismatch == 0);
    uint32_t id;
    uint8_t buf[8];
    check("frames 4-7 not sent", !daq_build_screen_frame(&factory, 4, &in, &id, buf) &&
                                 !daq_build_screen_frame(&factory, 7, &in, &id, buf));

    /* 3. CRC and flash-copy checks */
    check("CRC-32 standard vector", daq_crc32((const uint8_t*)"123456789", 9) == 0xCBF43926u);
    daq_settings_t bad = factory;
    bad.radio_hz = 5;
    check("change without reseal is caught", !daq_settings_valid(&bad));
    daq_settings_seal(&bad);
    check("resealed is valid", daq_settings_valid(&bad));
    bad.version = 99;
    check("other version rejected", !daq_settings_valid(&bad));
    memset(&bad, 0xFF, sizeof(bad));
    check("blank flash rejected", !daq_settings_valid(&bad));
    memset(&bad, 0, sizeof(bad));
    check("zeroed flash rejected", !daq_settings_valid(&bad));

    /* 4. range checks */
    bad = factory; bad.radio_hz = 1;   check("radio 1 Hz refused", !daq_settings_in_range(&bad));
    bad = factory; bad.radio_hz = 11;  check("radio 11 Hz refused", !daq_settings_in_range(&bad));
    bad = factory; bad.gps_hz = 7;     check("gps 7 Hz refused", !daq_settings_in_range(&bad));
    bad = factory; bad.screen_hz = 0;  check("screen 0 Hz refused", !daq_settings_in_range(&bad));
    bad = factory; bad.frames[1].sig[1].byte = 1; check("overlapping signals refused", !daq_settings_in_range(&bad));
    bad = factory; bad.frames[1].id = 0x600;      check("duplicate frame ID refused", !daq_settings_in_range(&bad));
    bad = factory; bad.frames[0].sig[0].src = 99; check("unknown source refused", !daq_settings_in_range(&bad));
    bad = factory; bad.frames[2].sig[1].byte = 6; check("signal off the end refused", !daq_settings_in_range(&bad));
    bad = factory; bad.n_radio = 0;               check("empty packet refused", !daq_settings_in_range(&bad));

    /* 5. GPS rate commands */
    char cmd[32];
    daq_gps_rate_command(5, cmd, sizeof(cmd));
    check("5 Hz command is the v1 one", strcmp(cmd, "$PMTK220,200*2C\r\n") == 0);
    daq_gps_rate_command(1, cmd, sizeof(cmd));
    check("1 Hz command", strcmp(cmd, "$PMTK220,1000*1F\r\n") == 0);
    daq_gps_rate_command(10, cmd, sizeof(cmd));
    check("10 Hz command", strcmp(cmd, "$PMTK220,100*2F\r\n") == 0);

    /* 6. the protocol */
    live = factory;
    pending = factory;
    memset(&in, 0, sizeof(in));
    check("not a settings line", !daq_proto_handle(&proto, &in, "[TX] RPM:0"));
    check("HELLO", starts(ask(&in, "GM,HELLO"), "$GM,HELLO,fw=FS27-DAQ-2.0,proto=2,settings=0,saved=0*"));
    n_replies = 0;
    daq_proto_handle(&proto, &in, "$GM,HELLO*00");
    check("bad checksum", starts(replies[0], "$GM,ERR,checksum*"));
    check("GET", starts(ask(&in, "GM,GET"), "$GM,VAL,gps_hz=5,radio_hz=2,screen_hz=20,layout=1,frames=4,fields=21,packet=68,unsaved=0*"));
    check("unknown command", starts(ask(&in, "GM,DANCE"), "$GM,ERR,unknown*"));
    check("SET ok", starts(ask(&in, "GM,SET,radio_hz=5,gps_hz=10"), "$GM,OK,settings=0*"));
    check("SET is pending, not live", pending.radio_hz == 5 && live.radio_hz == 2 && commits == 0);
    check("SET out of range", starts(ask(&in, "GM,SET,radio_hz=50"), "$GM,ERR,range*"));
    check("bad SET changed nothing", pending.radio_hz == 5);
    check("SET unknown key", starts(ask(&in, "GM,SET,volume=11"), "$GM,ERR,unknown*"));
    check("GET shows unsaved", strstr(ask(&in, "GM,GET"), "radio_hz=5") && strstr(replies[0], "unsaved=1"));

    in.can.rpm = 1500;
    check("refused while the engine runs", starts(ask(&in, "GM,SAVE"), "$GM,ERR,moving*"));
    in.can.rpm = 0;
    in.speed_kph = 30.0f;
    check("refused while moving", starts(ask(&in, "GM,SET,radio_hz=4"), "$GM,ERR,moving*"));
    check("HELLO still answers while moving", starts(ask(&in, "GM,HELLO"), "$GM,HELLO"));
    in.speed_kph = 0.4f;

    fail_flash = 1;
    check("flash failure reported", starts(ask(&in, "GM,SAVE"), "$GM,ERR,flash*"));
    check("flash failure left live alone", live.radio_hz == 2);
    fail_flash = 0;
    check("SAVE", starts(ask(&in, "GM,SAVE"), "$GM,OK,settings=1*"));
    check("SAVE committed a valid copy", commits == 1 && live.radio_hz == 5 && live.gps_hz == 10 &&
                                         live.counter == 1 && daq_settings_valid(&live));
    check("radio sleep now 200 ms", daq_radio_sleep_ms(&live) == 200);
    check("rate change keeps the v1 packet", daq_radio_packet_size(&live) == 68 && daq_radio_is_factory(&live));

    /* a new screen frame and a custom radio packet */
    check("SF new frame", starts(ask(&in, "GM,SF,4,604,5/0/16/0/1/1000,4/2/16/1/1/10"), "$GM,OK"));
    check("SF bad overlap", starts(ask(&in, "GM,SF,5,605,5/0/16/0/1/1000,9/1/16/1/1/10"), "$GM,ERR,range*"));
    check("SF duplicate ID", starts(ask(&in, "GM,SF,5,600,5/0/16/0/1/1000"), "$GM,ERR,range*"));
    check("SF bad format", starts(ask(&in, "GM,SF,5,605,5/0/16"), "$GM,ERR,format*"));
    check("RP custom", starts(ask(&in, "GM,RP,0,10/2,4/3,5/6"), "$GM,OK"));
    check("RPN", starts(ask(&in, "GM,RPN,3"), "$GM,OK"));
    check("layout version", starts(ask(&in, "GM,SET,layout=7"), "$GM,OK"));
    ask(&in, "GM,GETL");
    check("GETL lists frames, fields, count, OK", n_replies == 8 && starts(replies[4], "$GM,SF,4,604,5/0/16/0/1/1000,4/2/16/1/1/10*") &&
          starts(replies[0], "$GM,SF,0,600,10/0/16/0/1/1,2/2/16/0/100/10,4/4/16/1/1/10,1/6/16/0/1/10*") &&
          starts(replies[5], "$GM,RP,0,10/2,4/3,5/6*") && starts(replies[6], "$GM,RPN,3*") && starts(replies[7], "$GM,OK"));
    check("SAVE custom", starts(ask(&in, "GM,SAVE"), "$GM,OK,settings=2*"));
    in.can.rpm = 0;
    in.can.oil_pressure = 4.25f;
    in.can.engine_temp = -12.3f;
    daq_inputs_t run = in;
    run.can.rpm = 8000;
    check("frame 0x604 built", daq_build_screen_frame(&live, 4, &run, &id, buf) && id == 0x604 &&
          buf[0] == (4250 & 0xFF) && buf[1] == (4250 >> 8) && buf[2] == 0x85 && buf[3] == 0xFF && buf[4] == 0);
    uint8_t pkt[DAQ_MAX_PACKET_BYTES];
    int len = daq_build_radio_packet(&live, &run, pkt, sizeof(pkt));
    float oil;
    memcpy(&oil, pkt + 9, 4);
    check("custom packet: FS27 magic, layout byte, fields", len == 13 && pkt[0] == 0x37 && pkt[1] == 0x32 &&
          pkt[2] == 0x53 && pkt[3] == 0x46 && pkt[4] == 7 && pkt[5] == 0x40 && pkt[6] == 0x1F &&
          pkt[7] == 0xF4 && pkt[8] == 0xFF && oil == 4.25f);
    check("packet too big for the buffer", daq_build_radio_packet(&live, &run, pkt, 8) == 0);

    check("CANCEL drops edits", starts(ask(&in, "GM,SET,screen_hz=10"), "$GM,OK") && pending.screen_hz == 10 &&
          starts(ask(&in, "GM,CANCEL"), "$GM,OK") && pending.screen_hz == 20);
    check("FACTORY", starts(ask(&in, "GM,FACTORY"), "$GM,OK,settings=3*"));
    daq_settings_t f2;
    daq_settings_factory(&f2);
    f2.counter = 3;
    daq_settings_seal(&f2);
    check("FACTORY restores v1 behaviour exactly", memcmp(&live, &f2, sizeof(live)) == 0 && daq_radio_is_factory(&live) &&
          daq_radio_sleep_ms(&live) == 500);

    /* rubbish in never crashes */
    char junk[320];
    for (int i = 0; i < 20000; i++) {
        int n = (int)rnd(0, 319);
        for (int k = 0; k < n; k++) junk[k] = (char)(int)rnd(1, 255);
        junk[n] = 0;
        if (i % 2) memcpy(junk, "$GM,", n < 4 ? (size_t)n : 4);
        daq_proto_handle(&proto, &in, junk);
    }
    const char* nasty[] = {"GM,SF", "GM,SF,9,600", "GM,SF,0,FFFF", "GM,RP", "GM,RP,47,1/0,2/0", "GM,RPN,0", "GM,RPN,99",
                           "GM,SET", "GM,SET,=", "GM,SET,radio_hz", "GM,SET,radio_hz=-1", "GM,RP,0,99/0", "GM,RP,0,1/9",
                           "GM,SF,0,600,1/0/16/0/x/1", "GM,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,"};
    for (unsigned i = 0; i < sizeof(nasty) / sizeof(nasty[0]); i++) check(nasty[i], starts(ask(&in, nasty[i]), "$GM,ERR,"));
    check("still factory after the rubbish", daq_radio_is_factory(&live) && daq_settings_valid(&live));

    printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}
