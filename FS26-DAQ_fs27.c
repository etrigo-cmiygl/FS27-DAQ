#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "pico/mutex.h"
#include "gps.h"
#include "lr1121_tx.h"
#include "can_handler_fs27.h"
#include "ft550_decoder.h"
#include "src/mcp2515/MCP2515/MCP2515.h"
#include "pico/flash.h"
#include "hardware/sync.h"
#include "daq_settings_fs27.h"
#include "daq_inputs_fs27.h"
#include "daq_flash_fs27.h"

// Global mutex for printf
mutex_t printf_mutex;

// Thread-safe printf wrapper
#define safe_printf(...) do { \
    mutex_enter_blocking(&printf_mutex); \
    printf(__VA_ARGS__); \
    mutex_exit(&printf_mutex); \
} while(0)

// Shared data between cores (protected by spin lock in GPS module)
static volatile bool core1_running = false;

// Settings: what goes in the screen frames and the radio packet, and how often.
// "live" is what's running. "pending" is the copy being edited over USB until it's saved.
// The factory settings behave exactly like the fixed v1 firmware (see daq_settings_fs27.c).
static daq_settings_t live_settings;
static daq_settings_t pending_settings;
static daq_proto_t settings_proto;

void gps_set_rate_hz(int hz);

// Everything the DAQ knows right now, for the frame and packet builders
static void gather_inputs(daq_inputs_t* in) {
    gps_data_t gps;
    gps_get_data_safe(&gps);
    can_get_sensor_data_safe(&in->can);
    in->latitude = gps.raw_latitude;
    in->longitude = gps.raw_longitude;
    in->speed_kph = gps.speed_kph;
    in->altitude = gps.altitude;
    in->satellites = gps.satellites;
    in->fix_valid = gps.fix_valid;
    in->tx_count = lora_get_tx_count();
    in->can_frame_count = can_get_frame_count();
    daq_spare_read(in->spare_raw, &in->spare_fitted);
}

// Core 1 takes its own copy. Interrupts are off for the copy so a settings save
// (which pauses this core through an interrupt) can't land halfway through it.
static void copy_live_settings(daq_settings_t* out) {
    uint32_t irq = save_and_disable_interrupts();
    memcpy(out, &live_settings, sizeof(*out));
    restore_interrupts(irq);
}

// Core 1 entry point - LoRa broadcast with GPS + CAN telemetry
void core1_main() {
    flash_safe_execute_core_init();  // lets core 0 pause this core while it saves settings to flash

    safe_printf("Core 1: Initializing LoRa TX...\n");
    lora_tx_init();
    
    core1_running = true;
    
    safe_printf("Core 1: Starting combined telemetry broadcast (GPS + CAN + LoRa)...\n");
    
    static daq_settings_t settings;
    static uint8_t packet[DAQ_MAX_PACKET_BYTES];

    while (true) {        
        copy_live_settings(&settings);

        // Thread-safe copies of the GPS and CAN data
        daq_inputs_t in;
        gather_inputs(&in);
        
        // Build the telemetry packet from the settings (factory = the 68-byte "FS26" packet)
        int length = daq_build_radio_packet(&settings, &in, packet, sizeof(packet));
        
        // Send it (blocking)
        if (length > 0 && lora_send(packet, (uint8_t)length)) {
            safe_printf("[TX] RPM:%u | Batt:%.2f | TPS:%.3f | EngineTemp:%.1f | TX#%u CAN#%u\n",
                   in.can.rpm, in.can.battery_voltage, in.can.tps, in.can.engine_temp,
                   (uint16_t)in.tx_count, (uint16_t)(in.can_frame_count & 0xFFFF));
            safe_printf("[ECU] MAP:%.3f bar | AirTemp:%.1f | Oil:%.2f bar | Fuel:%.2f bar | Water:%.2f bar | Lambda:%.3f\n",
                   in.can.map, in.can.air_temp, in.can.oil_pressure, in.can.fuel_pressure,
                   in.can.water_pressure, in.can.exhaust_o2);
            safe_printf("[GPS] Sats:%d | Fix:%d | Speed:%.1f kph\n",
                   in.satellites, in.fix_valid ? 1 : 0, in.speed_kph);
        } else {
            safe_printf("[TX] FAILED #%lu\n", lora_get_tx_count());
        }
        
        sleep_ms(daq_radio_sleep_ms(&settings));  // TX rate: 2Hz with factory settings
    }
}

// ---- Settings over USB serial ($GM,... lines, see wiki/DAQ-Settings-Protocol.md) ----

static void settings_reply(const char* line) {
    safe_printf("%s\n", line);
}

static bool settings_commit(const daq_settings_t* sealed) {
    uint8_t old_gps_hz = live_settings.gps_hz;
    if (!daq_flash_save(sealed, &live_settings)) return false;
    if (live_settings.gps_hz != old_gps_hz) gps_set_rate_hz(live_settings.gps_hz);
    return true;
}

static void settings_start(void) {
    bool loaded = daq_flash_load(&live_settings);
    if (!loaded) daq_settings_factory(&live_settings);
    pending_settings = live_settings;
    settings_proto.live = &live_settings;
    settings_proto.pending = &pending_settings;
    settings_proto.reply = settings_reply;
    settings_proto.commit = settings_commit;
    settings_proto.loaded_from_flash = loaded;
    safe_printf("Settings: %s, version %lu, radio %u Hz, screen %u Hz, GPS %u Hz, packet %d bytes\n",
           loaded ? "loaded from flash" : "factory", (unsigned long)live_settings.counter,
           live_settings.radio_hz, live_settings.screen_hz, live_settings.gps_hz,
           daq_radio_packet_size(&live_settings));
}

// Reads whatever has arrived over USB without waiting, and answers complete $GM lines
static void settings_poll(void) {
    static char line[300];
    static int len = 0;
    for (int i = 0; i < 64; i++) {
        int c = getchar_timeout_us(0);
        if (c < 0) break;
        if (c == '\n' || c == '\r') {
            if (len > 0) {
                line[len] = '\0';
                daq_inputs_t in;
                gather_inputs(&in);
                daq_proto_handle(&settings_proto, &in, line);
                len = 0;
            }
        } else if (len < (int)sizeof(line) - 1) {
            line[len++] = (char)c;
        } else {
            len = 0;
        }
    }
}

int main() {
    stdio_init_all();
    mutex_init(&printf_mutex);  // Initialize mutex before anything else
    sleep_ms(2000); 
    
    safe_printf("Core 0: Initializing dual-core GPS + LoRa DAQ system...\n");
    
    // Load the saved settings (or the factory ones) before anything uses them
    settings_start();
    daq_spare_init();

    // Initialize GPS module on core 0
    gps_init();
    if (live_settings.gps_hz != 5) {
        gps_set_rate_hz(live_settings.gps_hz);
    }
    // Initialize CAN bus for ECU data
    can_init();
    
    // Launch core 1 for LR1121
    safe_printf("Core 0: Launching Core 1 for LR1121...\n");
    multicore_launch_core1(core1_main);
    
    // Wait for core 1 to be ready
    while (!core1_running) {
        sleep_ms(10);
    }

    safe_printf("Core 0: Both cores running. Starting GPS processing...\n");
    
    uint32_t last_dash_tx = 0; // Track when we last updated the screen
    uint32_t last_can_status = 0;

    // Core 0 main loop - dedicated GPS & CAN processing
    while (true) {
        // 1. Poll GPS UART
        gps_process();
        
        // 2. DRAIN LOOP: empty every frame waiting in the MCP2515
        while (can_process_frame()) {
        }
        
        // 3. Settings requests from Gryphon Manager over USB
        settings_poll();

        // Spare sensor inputs (ADC pins, the optional ADS1115 boards, frequency pins)
        daq_spare_poll();

        // 4. DASHBOARD BROADCAST (20Hz with factory settings) - send the frames in the settings to the dash via CAN.
        //    Factory settings: 0x600 engine, 0x601 battery + air temp, 0x602 GPS position, 0x603 speed + counters.
        uint32_t current_time = to_ms_since_boot(get_absolute_time());
        if (current_time - last_dash_tx >= daq_screen_period_ms(&live_settings)) { 
            daq_inputs_t in;
            gather_inputs(&in);

            for (int i = 0; i < DAQ_MAX_SCREEN_FRAMES; i++) {
                uint32_t frame_id;
                uint8_t dash_tx_buf[8];
                if (daq_build_screen_frame(&live_settings, i, &in, &frame_id, dash_tx_buf)) {
                    MCP2515_Send(frame_id, dash_tx_buf, 8);
                }
            }

            last_dash_tx = current_time;
        }

        if (current_time - last_can_status >= 1000) {
            can_print_status();
            last_can_status = current_time;
        }
        
        // Small delay to prevent locking the bus completely
        sleep_us(100);
    }
}