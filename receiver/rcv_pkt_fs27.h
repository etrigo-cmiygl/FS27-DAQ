/**
 * @file  rcv_pkt_fs27.h
 * @brief The PKT line the receiver sends to the laptop. Plain C, so the desk test can compile it too.
 */
#ifndef RCV_PKT_FS27_H
#define RCV_PKT_FS27_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define RCV_MAX_PACKET   255
#define RCV_LINE_SIZE    (2 * RCV_MAX_PACKET + 24)
#define RCV_MAGIC_FS26   0x46533236u   /* the fixed 68-byte layout */
#define RCV_MAGIC_FS27   0x46533237u   /* custom layouts: followed by a layout version byte */

static inline bool rcv_packet_ok(const uint8_t* packet, size_t length) {
    if (length < 5 || length > RCV_MAX_PACKET) return false;
    uint32_t magic = (uint32_t)packet[0] | ((uint32_t)packet[1] << 8) | ((uint32_t)packet[2] << 16) |
                     ((uint32_t)packet[3] << 24);
    return magic == RCV_MAGIC_FS26 || magic == RCV_MAGIC_FS27;
}

/* Writes "PKT,<rssi>,<snr>,<hex>" into out (no newline). Returns the length, or 0 if it doesn't fit. */
static inline int rcv_format_pkt(const uint8_t* packet, size_t length, int rssi, int snr, char* out, size_t out_size) {
    static const char HEX[] = "0123456789ABCDEF";
    int at = snprintf(out, out_size, "PKT,%d,%d,", rssi, snr);
    if (at < 0 || (size_t)at + 2 * length + 1 > out_size) return 0;
    for (size_t i = 0; i < length; i++) {
        out[at++] = HEX[packet[i] >> 4];
        out[at++] = HEX[packet[i] & 0x0F];
    }
    out[at] = '\0';
    return at;
}

#endif
