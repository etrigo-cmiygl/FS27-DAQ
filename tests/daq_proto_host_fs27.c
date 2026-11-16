/*
 * Runs the DAQ's real settings protocol code on a laptop, so Gryphon Manager's tests can talk to it.
 *
 *   cc -I.. -o daq_proto_host daq_proto_host_fs27.c ../daq_settings_fs27.c ../ft550_decoder.c -lm
 *
 * Reads lines on stdin, prints the DAQ's replies. Lines starting with '!' set the pretend car:
 *   !rpm=1500   !speed=30   !flashfail=1   !raw=<input>,<volts or Hz>   !fitted=<0-3>   !packet
 * After each input line it prints a line holding only "." so the caller knows the replies are complete.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "daq_settings_fs27.h"

static daq_settings_t live, pending;
static int flash_fail = 0;

static void reply(const char* line) { printf("%s\n", line); }
static bool commit(const daq_settings_t* sealed) {
    if (flash_fail) return false;
    live = *sealed;
    return true;
}

int main(void) {
    daq_proto_t proto = {&live, &pending, reply, commit, false};
    daq_inputs_t in;
    char line[400];
    memset(&in, 0, sizeof(in));
    daq_settings_factory(&live);
    pending = live;
    while (fgets(line, sizeof(line), stdin)) {
        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == '!') {
            if (strncmp(line, "!rpm=", 5) == 0) in.can.rpm = (uint16_t)atoi(line + 5);
            else if (strncmp(line, "!speed=", 7) == 0) in.speed_kph = (float)atof(line + 7);
            else if (strncmp(line, "!flashfail=", 11) == 0) flash_fail = atoi(line + 11);
            else if (strncmp(line, "!fitted=", 8) == 0) in.spare_fitted = (uint16_t)atoi(line + 8);
            else if (strncmp(line, "!raw=", 5) == 0) {
                int idx = atoi(line + 5);
                const char* comma = strchr(line, ',');
                if (comma && idx >= 0 && idx < DAQ_SPARE_INPUTS) in.spare_raw[idx] = (float)atof(comma + 1);
            }
            else if (strcmp(line, "!packet") == 0) {
                uint8_t buf[DAQ_MAX_PACKET_BYTES];
                int n = daq_build_radio_packet(&live, &in, buf, sizeof(buf));
                for (int i = 0; i < n; i++) printf("%02X", buf[i]);
                printf("\n");
            }
        } else {
            daq_proto_handle(&proto, &in, line);
        }
        printf(".\n");
        fflush(stdout);
    }
    return 0;
}
