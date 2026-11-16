/**
 * @file  daq_settings_fs27.c
 * @brief DAQ settings, the generic screen frame and radio packet builders, and the settings protocol.
 */
#include "daq_settings_fs27.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---- CRC and housekeeping --------------------------------------------------------------------- */

uint32_t daq_crc32(const uint8_t* data, size_t len) {
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)-(int32_t)(crc & 1u));
    }
    return ~crc;
}

static uint32_t settings_crc(const daq_settings_t* s) {
    size_t skip = offsetof(daq_settings_t, crc) + sizeof(s->crc);
    return daq_crc32((const uint8_t*)s + skip, sizeof(*s) - skip);
}

void daq_settings_seal(daq_settings_t* s) {
    s->magic = DAQ_SETTINGS_MAGIC;
    s->version = DAQ_SETTINGS_VERSION;
    s->length = (uint16_t)sizeof(*s);
    s->crc = settings_crc(s);
}

bool daq_settings_valid(const daq_settings_t* s) {
    return s->magic == DAQ_SETTINGS_MAGIC && s->version == DAQ_SETTINGS_VERSION &&
           s->length == sizeof(*s) && s->crc == settings_crc(s);
}

static void add_signal(daq_screen_frame_t* f, uint8_t src, uint8_t byte, uint8_t bits, uint8_t is_signed,
                       float m1, float m2) {
    daq_screen_signal_t* g = &f->sig[f->n++];
    g->src = src; g->byte = byte; g->bits = bits; g->is_signed = is_signed; g->m1 = m1; g->m2 = m2;
}

static const daq_radio_field_t FACTORY_RADIO[] = {
    {DAQ_SRC_GPS_LAT, DAQ_T_F32}, {DAQ_SRC_GPS_LON, DAQ_T_F32}, {DAQ_SRC_GPS_SPEED, DAQ_T_F32},
    {DAQ_SRC_GPS_ALT, DAQ_T_F32}, {DAQ_SRC_GPS_SATS, DAQ_T_U8}, {DAQ_SRC_GPS_FIX, DAQ_T_U8},
    {DAQ_SRC_RPM, DAQ_T_U16}, {DAQ_SRC_ENGINE_TEMP, DAQ_T_F32}, {DAQ_SRC_TPS, DAQ_T_F32},
    {DAQ_SRC_OIL_PRESSURE, DAQ_T_F32}, {DAQ_SRC_FUEL_PRESSURE, DAQ_T_F32}, {DAQ_SRC_BRAKE_PRESSURE, DAQ_T_F32},
    {DAQ_SRC_BATTERY, DAQ_T_F32},
    {DAQ_SRC_WHEEL_FR, DAQ_T_U16}, {DAQ_SRC_WHEEL_FL, DAQ_T_U16}, {DAQ_SRC_WHEEL_RR, DAQ_T_U16},
    {DAQ_SRC_WHEEL_RL, DAQ_T_U16},
    {DAQ_SRC_G_LATERAL, DAQ_T_F32}, {DAQ_SRC_HEADING, DAQ_T_F32},
    {DAQ_SRC_TX_COUNT, DAQ_T_U16}, {DAQ_SRC_CAN_COUNT, DAQ_T_U16},
};
#define FACTORY_RADIO_COUNT ((int)(sizeof(FACTORY_RADIO) / sizeof(FACTORY_RADIO[0])))

void daq_settings_factory(daq_settings_t* s) {
    memset(s, 0, sizeof(*s));
    s->gps_hz = 5;
    s->radio_hz = 2;
    s->screen_hz = 20;
    s->layout_version = 1;

    daq_screen_frame_t* f = &s->frames[0];          /* 0x600: primary engine */
    f->id = 0x600;
    add_signal(f, DAQ_SRC_RPM, 0, 16, 0, 1.0f, 1.0f);
    add_signal(f, DAQ_SRC_MAP, 2, 16, 0, 100.0f, 10.0f);          /* bar -> kPa, then x10 */
    add_signal(f, DAQ_SRC_ENGINE_TEMP, 4, 16, 1, 1.0f, 10.0f);
    add_signal(f, DAQ_SRC_TPS, 6, 16, 0, 1.0f, 10.0f);

    f = &s->frames[1];                              /* 0x601: battery and air temp */
    f->id = 0x601;
    add_signal(f, DAQ_SRC_BATTERY, 0, 16, 0, 1.0f, 100.0f);
    add_signal(f, DAQ_SRC_AIR_TEMP, 2, 16, 1, 1.0f, 10.0f);

    f = &s->frames[2];                              /* 0x602: GPS position */
    f->id = 0x602;
    add_signal(f, DAQ_SRC_GPS_LAT, 0, 32, 1, 1.0f, 10000000.0f);
    add_signal(f, DAQ_SRC_GPS_LON, 4, 32, 1, 1.0f, 10000000.0f);

    f = &s->frames[3];                              /* 0x603: speed and counters */
    f->id = 0x603;
    add_signal(f, DAQ_SRC_GPS_SPEED, 0, 16, 0, 1.0f, 10.0f);
    add_signal(f, DAQ_SRC_GPS_SATS, 2, 8, 0, 1.0f, 1.0f);
    add_signal(f, DAQ_SRC_GPS_FIX, 3, 8, 0, 1.0f, 1.0f);
    add_signal(f, DAQ_SRC_TX_COUNT, 4, 16, 0, 1.0f, 1.0f);
    add_signal(f, DAQ_SRC_CAN_COUNT, 6, 16, 0, 1.0f, 1.0f);

    s->n_radio = (uint8_t)FACTORY_RADIO_COUNT;
    memcpy(s->radio, FACTORY_RADIO, sizeof(FACTORY_RADIO));
    daq_settings_seal(s);
}

static bool source_ok(uint8_t src) {
    return (src >= 1 && src <= DAQ_SRC_BATTERY) || (src >= DAQ_SRC_GPS_LAT && src <= DAQ_SRC_GPS_FIX) ||
           src == DAQ_SRC_TX_COUNT || src == DAQ_SRC_CAN_COUNT;
}

static int type_size(uint8_t type) {
    switch (type) {
        case DAQ_T_U8: case DAQ_T_I8: return 1;
        case DAQ_T_U16: case DAQ_T_I16: return 2;
        default: return 4;
    }
}

bool daq_radio_is_factory(const daq_settings_t* s) {
    return s->n_radio == FACTORY_RADIO_COUNT && memcmp(s->radio, FACTORY_RADIO, sizeof(FACTORY_RADIO)) == 0;
}

int daq_radio_packet_size(const daq_settings_t* s) {
    int size = daq_radio_is_factory(s) ? 4 : 5;
    for (int i = 0; i < s->n_radio && i < DAQ_MAX_RADIO_FIELDS; i++) size += type_size(s->radio[i].type);
    return size;
}

bool daq_settings_in_range(const daq_settings_t* s) {
    if (s->gps_hz != 1 && s->gps_hz != 5 && s->gps_hz != 10) return false;
    if (s->radio_hz < 2 || s->radio_hz > 10) return false;
    if (s->screen_hz < 1 || s->screen_hz > 50) return false;
    if (s->n_radio < 1 || s->n_radio > DAQ_MAX_RADIO_FIELDS) return false;
    for (int i = 0; i < s->n_radio; i++) {
        if (!source_ok(s->radio[i].src) || s->radio[i].type >= DAQ_T_LIMIT) return false;
    }
    if (daq_radio_packet_size(s) > DAQ_MAX_PACKET_BYTES) return false;
    for (int i = 0; i < DAQ_MAX_SCREEN_FRAMES; i++) {
        const daq_screen_frame_t* f = &s->frames[i];
        if (f->n == 0) continue;
        if (f->n > DAQ_MAX_FRAME_SIGNALS || f->id > 0x7FF) return false;
        for (int k = 0; k < i; k++) {
            if (s->frames[k].n && s->frames[k].id == f->id) return false;
        }
        uint8_t used = 0;
        for (int j = 0; j < f->n; j++) {
            const daq_screen_signal_t* g = &f->sig[j];
            if (!source_ok(g->src)) return false;
            if (g->bits != 8 && g->bits != 16 && g->bits != 32) return false;
            if (g->byte + g->bits / 8 > 8) return false;
            if (!(g->m1 == g->m1) || !(g->m2 == g->m2)) return false;
            uint8_t mask = (uint8_t)(((1u << (g->bits / 8)) - 1u) << g->byte);
            if (used & mask) return false;
            used |= mask;
        }
    }
    return true;
}

/* ---- reading a source ------------------------------------------------------------------------ */

typedef struct {
    uint8_t  kind;   /* 0 = float, 1 = unsigned whole number, 2 = signed whole number */
    float    f;
    uint32_t u;
} daq_value_t;

static daq_value_t vf(float f) { daq_value_t v = {0, f, 0}; return v; }
static daq_value_t vu(uint32_t u) { daq_value_t v = {1, 0.0f, u}; return v; }
static daq_value_t vi(int32_t i) { daq_value_t v = {2, 0.0f, (uint32_t)i}; return v; }

static daq_value_t source_value(const daq_inputs_t* in, uint8_t src) {
    const ft550_sensor_data_t* c = &in->can;
    switch (src) {
        case DAQ_SRC_TPS: return vf(c->tps);
        case DAQ_SRC_MAP: return vf(c->map);
        case DAQ_SRC_AIR_TEMP: return vf(c->air_temp);
        case DAQ_SRC_ENGINE_TEMP: return vf(c->engine_temp);
        case DAQ_SRC_OIL_PRESSURE: return vf(c->oil_pressure);
        case DAQ_SRC_FUEL_PRESSURE: return vf(c->fuel_pressure);
        case DAQ_SRC_WATER_PRESSURE: return vf(c->water_pressure);
        case DAQ_SRC_GEAR: return vi(c->gear);
        case DAQ_SRC_LAMBDA: return vf(c->exhaust_o2);
        case DAQ_SRC_RPM: return vu(c->rpm);
        case DAQ_SRC_OIL_TEMP: return vf(c->oil_temp);
        case DAQ_SRC_PIT_LIMIT: return vi(c->pit_limit);
        case DAQ_SRC_WHEEL_FR: return vu(c->wheel_speed_fr);
        case DAQ_SRC_WHEEL_FL: return vu(c->wheel_speed_fl);
        case DAQ_SRC_WHEEL_RR: return vu(c->wheel_speed_rr);
        case DAQ_SRC_WHEEL_RL: return vu(c->wheel_speed_rl);
        case DAQ_SRC_TC_SLIP: return vf(c->traction_ctrl_slip);
        case DAQ_SRC_TC_RETARD: return vf(c->traction_ctrl_retard);
        case DAQ_SRC_TC_CUT: return vf(c->traction_ctrl_cut);
        case DAQ_SRC_HEADING: return vf(c->heading);
        case DAQ_SRC_SHOCK_FR: return vf(c->shock_fr);
        case DAQ_SRC_SHOCK_FL: return vf(c->shock_fl);
        case DAQ_SRC_SHOCK_RR: return vf(c->shock_rr);
        case DAQ_SRC_SHOCK_RL: return vf(c->shock_rl);
        case DAQ_SRC_G_ACCEL: return vf(c->g_force_accel);
        case DAQ_SRC_G_LATERAL: return vf(c->g_force_lateral);
        case DAQ_SRC_YAW_FRONTAL: return vf(c->yaw_rate_frontal);
        case DAQ_SRC_YAW_LATERAL: return vf(c->yaw_rate_lateral);
        case DAQ_SRC_LAMBDA_CORRECTION: return vf(c->lambda_correction);
        case DAQ_SRC_FUEL_FLOW: return vf(c->fuel_flow_total);
        case DAQ_SRC_INJ_TIME_A: return vf(c->inj_time_bank_a);
        case DAQ_SRC_INJ_TIME_B: return vf(c->inj_time_bank_b);
        case DAQ_SRC_TRANS_OIL_TEMP: return vf(c->trans_oil_temp);
        case DAQ_SRC_TRANS_TEMP: return vf(c->trans_temp);
        case DAQ_SRC_FUEL_CONSUMPTION: return vf(c->fuel_consumption);
        case DAQ_SRC_BRAKE_PRESSURE: return vf(c->brake_pressure);
        case DAQ_SRC_BATTERY: return vf(c->battery_voltage);
        case DAQ_SRC_GPS_LAT: return vf(in->latitude);
        case DAQ_SRC_GPS_LON: return vf(in->longitude);
        case DAQ_SRC_GPS_SPEED: return vf(in->speed_kph);
        case DAQ_SRC_GPS_ALT: return vf(in->altitude);
        case DAQ_SRC_GPS_SATS: return vi(in->satellites);
        case DAQ_SRC_GPS_FIX: return vu(in->fix_valid ? 1u : 0u);
        case DAQ_SRC_TX_COUNT: return vu(in->tx_count);
        case DAQ_SRC_CAN_COUNT: return vu(in->can_frame_count);
        default: return vu(0);
    }
}

static float as_float(daq_value_t v) {
    if (v.kind == 0) return v.f;
    if (v.kind == 2) return (float)(int32_t)v.u;
    return (float)v.u;
}

/* Cuts a float down to a whole number the same way the v1 firmware's casts did. */
static uint32_t float_to_bits(float x, uint8_t bits, uint8_t is_signed) {
    if (bits == 8)  return is_signed ? (uint32_t)(uint8_t)(int8_t)x : (uint32_t)(uint8_t)x;
    if (bits == 16) return is_signed ? (uint32_t)(uint16_t)(int16_t)x : (uint32_t)(uint16_t)x;
    return is_signed ? (uint32_t)(int32_t)x : (uint32_t)x;
}

static void put_le(uint8_t* buf, uint32_t value, int bytes) {
    for (int i = 0; i < bytes; i++) buf[i] = (uint8_t)(value >> (8 * i));
}

bool daq_build_screen_frame(const daq_settings_t* s, int idx, const daq_inputs_t* in, uint32_t* id, uint8_t buf[8]) {
    if (idx < 0 || idx >= DAQ_MAX_SCREEN_FRAMES) return false;
    const daq_screen_frame_t* f = &s->frames[idx];
    if (f->n == 0 || f->n > DAQ_MAX_FRAME_SIGNALS) return false;
    memset(buf, 0, 8);
    for (int j = 0; j < f->n; j++) {
        const daq_screen_signal_t* g = &f->sig[j];
        if (g->byte + g->bits / 8 > 8) continue;
        daq_value_t v = source_value(in, g->src);
        uint32_t raw;
        if (v.kind != 0 && g->m1 == 1.0f && g->m2 == 1.0f) {
            raw = v.u;
        } else {
            raw = float_to_bits(as_float(v) * g->m1 * g->m2, g->bits, g->is_signed);
        }
        put_le(buf + g->byte, raw, g->bits / 8);
    }
    *id = f->id;
    return true;
}

int daq_build_radio_packet(const daq_settings_t* s, const daq_inputs_t* in, uint8_t* buf, int max) {
    int size = daq_radio_packet_size(s);
    if (size > max) return 0;
    int at = 4;
    if (daq_radio_is_factory(s)) {
        put_le(buf, DAQ_LEGACY_PACKET_MAGIC, 4);
    } else {
        put_le(buf, DAQ_CUSTOM_PACKET_MAGIC, 4);
        buf[at++] = s->layout_version;
    }
    for (int i = 0; i < s->n_radio; i++) {
        daq_value_t v = source_value(in, s->radio[i].src);
        uint8_t type = s->radio[i].type;
        if (type == DAQ_T_F32) {
            float f = as_float(v);
            memcpy(buf + at, &f, 4);
            at += 4;
            continue;
        }
        int bytes = type_size(type);
        uint8_t is_signed = (type == DAQ_T_I8 || type == DAQ_T_I16 || type == DAQ_T_I32);
        uint32_t raw = v.kind != 0 ? v.u : float_to_bits(v.f, (uint8_t)(bytes * 8), is_signed);
        put_le(buf + at, raw, bytes);
        at += bytes;
    }
    return at;
}

uint32_t daq_radio_sleep_ms(const daq_settings_t* s) {
    uint8_t hz = (s->radio_hz < 2 || s->radio_hz > 10) ? 2 : s->radio_hz;
    return 1000u / hz;
}

uint32_t daq_screen_period_ms(const daq_settings_t* s) {
    uint8_t hz = (s->screen_hz < 1 || s->screen_hz > 50) ? 20 : s->screen_hz;
    return 1000u / hz;
}

static uint8_t nmea_checksum(const char* body) {
    uint8_t cs = 0;
    while (*body) cs ^= (uint8_t)*body++;
    return cs;
}

void daq_gps_rate_command(int hz, char* out, size_t out_size) {
    char body[24];
    if (hz != 1 && hz != 5 && hz != 10) hz = 5;
    snprintf(body, sizeof(body), "PMTK220,%d", 1000 / hz);
    snprintf(out, out_size, "$%s*%02X\r\n", body, nmea_checksum(body));
}

/* ---- the settings protocol ------------------------------------------------------------------- */

void daq_proto_format(const char* body, char* out, size_t out_size) {
    snprintf(out, out_size, "$%s*%02X", body, nmea_checksum(body));
}

static void send(daq_proto_t* p, const char* body) {
    char line[300];
    daq_proto_format(body, line, sizeof(line));
    p->reply(line);
}

static void send_ok(daq_proto_t* p) {
    char body[48];
    snprintf(body, sizeof(body), "GM,OK,settings=%lu", (unsigned long)p->live->counter);
    send(p, body);
}

static bool moving(const daq_inputs_t* in) {
    return in->can.rpm > 0 || in->speed_kph > 2.0f;
}

static bool parse_uint(const char* text, int base, unsigned long max, unsigned long* out) {
    char* end;
    if (*text == '\0' || *text == '-') return false;
    unsigned long v = strtoul(text, &end, base);
    if (*end != '\0' || v > max) return false;
    *out = v;
    return true;
}

/* "a/b/c" -> pieces. Changes the text in place. Returns how many pieces. */
static int split(char* text, char sep, char** parts, int max) {
    int n = 0;
    parts[n++] = text;
    for (char* c = text; *c; c++) {
        if (*c == sep) {
            *c = '\0';
            if (n == max) return max + 1;
            parts[n++] = c + 1;
        }
    }
    return n;
}

static bool set_value(daq_settings_t* s, const char* key, const char* value) {
    unsigned long v;
    if (!parse_uint(value, 10, 255, &v)) return false;
    if (strcmp(key, "gps_hz") == 0) s->gps_hz = (uint8_t)v;
    else if (strcmp(key, "radio_hz") == 0) s->radio_hz = (uint8_t)v;
    else if (strcmp(key, "screen_hz") == 0) s->screen_hz = (uint8_t)v;
    else if (strcmp(key, "layout") == 0) s->layout_version = (uint8_t)v;
    else return false;
    return true;
}

static const char* cmd_screen_frame(daq_settings_t* s, char** arg, int n) {
    unsigned long idx, id;
    if (n < 2 || !parse_uint(arg[0], 10, DAQ_MAX_SCREEN_FRAMES - 1, &idx)) return "range";
    if (!parse_uint(arg[1], 16, 0x7FF, &id)) return "range";
    daq_screen_frame_t f;
    memset(&f, 0, sizeof(f));
    f.id = (uint16_t)id;
    if (n - 2 > DAQ_MAX_FRAME_SIGNALS) return "range";
    for (int i = 2; i < n; i++) {
        char* piece[6];
        unsigned long src, byte, bits, sg;
        if (split(arg[i], '/', piece, 6) != 6) return "format";
        if (!parse_uint(piece[0], 10, 255, &src) || !parse_uint(piece[1], 10, 7, &byte) ||
            !parse_uint(piece[2], 10, 32, &bits) || !parse_uint(piece[3], 10, 1, &sg)) return "range";
        char *e1, *e2;
        float m1 = strtof(piece[4], &e1), m2 = strtof(piece[5], &e2);
        if (*piece[4] == '\0' || *e1 != '\0' || *piece[5] == '\0' || *e2 != '\0') return "format";
        add_signal(&f, (uint8_t)src, (uint8_t)byte, (uint8_t)bits, (uint8_t)sg, m1, m2);
    }
    daq_settings_t trial = *s;
    trial.frames[idx] = f;
    if (!daq_settings_in_range(&trial)) return "range";
    *s = trial;
    return NULL;
}

static const char* cmd_radio_fields(daq_settings_t* s, char** arg, int n) {
    unsigned long start;
    if (n < 2 || !parse_uint(arg[0], 10, DAQ_MAX_RADIO_FIELDS - 1, &start)) return "range";
    if ((int)start + (n - 1) > DAQ_MAX_RADIO_FIELDS) return "range";
    daq_settings_t trial = *s;
    for (int i = 1; i < n; i++) {
        char* piece[2];
        unsigned long src, type;
        if (split(arg[i], '/', piece, 2) != 2) return "format";
        if (!parse_uint(piece[0], 10, 255, &src) || !parse_uint(piece[1], 10, DAQ_T_LIMIT - 1, &type)) return "range";
        if (!source_ok((uint8_t)src)) return "range";
        trial.radio[start + i - 1].src = (uint8_t)src;
        trial.radio[start + i - 1].type = (uint8_t)type;
    }
    *s = trial;
    return NULL;
}

static void send_layout(daq_proto_t* p) {
    const daq_settings_t* s = p->pending;
    char body[280];
    for (int i = 0; i < DAQ_MAX_SCREEN_FRAMES; i++) {
        const daq_screen_frame_t* f = &s->frames[i];
        if (f->n == 0) continue;
        int at = snprintf(body, sizeof(body), "GM,SF,%d,%X", i, f->id);
        for (int j = 0; j < f->n && at < (int)sizeof(body) - 40; j++) {
            const daq_screen_signal_t* g = &f->sig[j];
            at += snprintf(body + at, sizeof(body) - at, ",%u/%u/%u/%u/%.9g/%.9g", g->src, g->byte, g->bits,
                           g->is_signed, (double)g->m1, (double)g->m2);
        }
        send(p, body);
    }
    for (int start = 0; start < s->n_radio; start += 12) {
        int at = snprintf(body, sizeof(body), "GM,RP,%d", start);
        for (int i = start; i < s->n_radio && i < start + 12; i++) {
            at += snprintf(body + at, sizeof(body) - at, ",%u/%u", s->radio[i].src, s->radio[i].type);
        }
        send(p, body);
    }
    snprintf(body, sizeof(body), "GM,RPN,%u", s->n_radio);
    send(p, body);
}

bool daq_proto_handle(daq_proto_t* p, const daq_inputs_t* in, const char* line) {
    char work[300];
    size_t len = strlen(line);
    while (len && (line[len - 1] == '\r' || line[len - 1] == '\n' || line[len - 1] == ' ')) len--;
    if (len < 4 || strncmp(line, "$GM,", 4) != 0) return false;
    if (len >= sizeof(work)) { send(p, "GM,ERR,format"); return true; }
    memcpy(work, line + 1, len - 1);
    work[len - 1] = '\0';
    char* star = strrchr(work, '*');
    unsigned long given;
    if (!star || strlen(star + 1) != 2 || !parse_uint(star + 1, 16, 255, &given)) { send(p, "GM,ERR,checksum"); return true; }
    *star = '\0';
    if (nmea_checksum(work) != (uint8_t)given) { send(p, "GM,ERR,checksum"); return true; }

    char* tok[24];
    int n = split(work, ',', tok, 24);
    if (n < 2 || n > 24) { send(p, "GM,ERR,format"); return true; }
    const char* cmd = tok[1];
    char** arg = &tok[2];
    int nargs = n - 2;
    char body[200];

    if (strcmp(cmd, "HELLO") == 0) {
        snprintf(body, sizeof(body), "GM,HELLO,fw=%s,proto=%d,settings=%lu,saved=%d", DAQ_FW_NAME, DAQ_PROTO_VERSION,
                 (unsigned long)p->live->counter, p->loaded_from_flash ? 1 : 0);
        send(p, body);
        return true;
    }
    if (strcmp(cmd, "GET") == 0) {
        const daq_settings_t* s = p->pending;
        int frames = 0;
        for (int i = 0; i < DAQ_MAX_SCREEN_FRAMES; i++) frames += s->frames[i].n ? 1 : 0;
        snprintf(body, sizeof(body), "GM,VAL,gps_hz=%u,radio_hz=%u,screen_hz=%u,layout=%u,frames=%d,fields=%u,packet=%d,"
                 "unsaved=%d", s->gps_hz, s->radio_hz, s->screen_hz, s->layout_version, frames, s->n_radio,
                 daq_radio_packet_size(s), memcmp(p->pending, p->live, sizeof(*p->live)) != 0 ? 1 : 0);
        send(p, body);
        return true;
    }
    if (strcmp(cmd, "GETL") == 0) {
        send_layout(p);
        send_ok(p);
        return true;
    }
    if (strcmp(cmd, "CANCEL") == 0) {
        *p->pending = *p->live;
        send_ok(p);
        return true;
    }

    bool changes = strcmp(cmd, "SET") == 0 || strcmp(cmd, "SF") == 0 || strcmp(cmd, "RP") == 0 ||
                   strcmp(cmd, "RPN") == 0 || strcmp(cmd, "SAVE") == 0 || strcmp(cmd, "FACTORY") == 0;
    if (!changes) { send(p, "GM,ERR,unknown"); return true; }
    if (moving(in)) { send(p, "GM,ERR,moving"); return true; }

    const char* err = NULL;
    if (strcmp(cmd, "SET") == 0) {
        daq_settings_t trial = *p->pending;
        if (nargs < 1) err = "format";
        for (int i = 0; i < nargs && !err; i++) {
            char* kv[2];
            if (split(arg[i], '=', kv, 2) != 2) err = "format";
            else if (!set_value(&trial, kv[0], kv[1])) err = "unknown";
        }
        if (!err && !daq_settings_in_range(&trial)) err = "range";
        if (!err) *p->pending = trial;
    } else if (strcmp(cmd, "SF") == 0) {
        err = cmd_screen_frame(p->pending, arg, nargs);
    } else if (strcmp(cmd, "RP") == 0) {
        err = cmd_radio_fields(p->pending, arg, nargs);
    } else if (strcmp(cmd, "RPN") == 0) {
        unsigned long count;
        if (nargs != 1 || !parse_uint(arg[0], 10, DAQ_MAX_RADIO_FIELDS, &count) || count < 1) err = "range";
        else p->pending->n_radio = (uint8_t)count;
    } else {
        daq_settings_t next;
        if (strcmp(cmd, "FACTORY") == 0) daq_settings_factory(&next);
        else next = *p->pending;
        if (!daq_settings_in_range(&next)) err = "range";
        else {
            next.counter = p->live->counter + 1;
            daq_settings_seal(&next);
            if (!p->commit(&next)) err = "flash";
            else {
                *p->pending = *p->live;
                p->loaded_from_flash = true;
            }
        }
    }
    if (err) {
        snprintf(body, sizeof(body), "GM,ERR,%s", err);
        send(p, body);
    } else {
        send_ok(p);
    }
    return true;
}
