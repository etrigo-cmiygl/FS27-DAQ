/*
 * Runs the receiver's PKT line code on a laptop for Gryphon Manager's tests.
 *
 *   cc -I../receiver -o rcv_pkt_host rcv_pkt_host_fs27.c
 *
 * Each input line is "<rssi> <snr> <packet as hex>". Prints the PKT line, or BAD if the receiver would drop it.
 */
#include <stdio.h>
#include <string.h>
#include "rcv_pkt_fs27.h"

int main(void) {
    static char in[1024], hex[800], out[RCV_LINE_SIZE];
    static uint8_t packet[400];
    while (fgets(in, sizeof(in), stdin)) {
        int rssi, snr;
        hex[0] = 0;
        if (sscanf(in, "%d %d %799s", &rssi, &snr, hex) < 2) continue;
        size_t n = strlen(hex) / 2;
        for (size_t i = 0; i < n; i++) {
            unsigned v;
            sscanf(hex + 2 * i, "%2x", &v);
            packet[i] = (uint8_t)v;
        }
        if (rcv_packet_ok(packet, n) && rcv_format_pkt(packet, n, rssi, snr, out, sizeof(out)) > 0) puts(out);
        else puts("BAD");
        fflush(stdout);
    }
    return 0;
}
