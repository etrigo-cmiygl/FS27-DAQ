#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "pico/mutex.h"
#include "gps.h"
#include "lr1121_tx.h"
#include "can_handler.h"
#include "ft550_decoder.h"
#include "src/mcp2515/MCP2515/MCP2515.h"

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

// GPS telemetry packet structure with integrated CAN data
typedef struct __attribute__((packed)) {
    uint32_t magic;         // 4 bytes - 0x46533236 ("FS26")
    
    // GPS Data
    float    latitude;      // 4 bytes
    float    longitude;     // 4 bytes
    float    gps_speed_kph; // 4 bytes
    float    altitude;      // 4 bytes
    uint8_t  satellites;    // 1 byte
    uint8_t  fix_valid;     // 1 byte
    
    // CAN Data - Engine Parameters
    uint16_t rpm;           // 2 bytes - RPM
    float    engine_temp;   // 4 bytes - °C
    float    tps;           // 4 bytes - Throttle Position %
    
    // CAN Data - Pressures & Fluids
    float    oil_pressure;  // 4 bytes - Bar
    float    fuel_pressure; // 4 bytes - Bar
    float    brake_pressure;// 4 bytes - Bar
    float    battery_voltage; // 4 bytes - V
    
    // CAN Data - Wheel Speeds
    uint16_t wheel_speed_fr;// 2 bytes - km/h
    uint16_t wheel_speed_fl;// 2 bytes - km/h
    uint16_t wheel_speed_rr;// 2 bytes - km/h
    uint16_t wheel_speed_rl;// 2 bytes - km/h
    
    // CAN Data - Dynamics
    float    g_force_lateral;// 4 bytes
    float    heading;       // 4 bytes
    
    // Packet Metadata
    uint16_t tx_count;      // 2 bytes - LoRa TX count
    uint16_t can_frame_count;// 2 bytes - CAN frames received
} combined_telemetry_packet_t;

// Core 1 entry point - LoRa broadcast with GPS + CAN telemetry
void core1_main() {
    safe_printf("Core 1: Initializing LoRa TX...\n");
    lora_tx_init();
    
    core1_running = true;
    
    safe_printf("Core 1: Starting combined telemetry broadcast (GPS + CAN + LoRa)...\n");
    
    while (true) {        
        // Get thread-safe copy of GPS data
        gps_data_t gps;
        gps_get_data_safe(&gps);
        
        // Get thread-safe copy of CAN sensor data
        ft550_sensor_data_t can_data;
        can_get_sensor_data_safe(&can_data);
        
        // Build combined telemetry packet
        combined_telemetry_packet_t packet;
        packet.magic = 0x46533236;  // "FS26" magic number
        
        // GPS Data
        packet.latitude = gps.raw_latitude;
        packet.longitude = gps.raw_longitude;
        packet.gps_speed_kph = gps.speed_kph;
        packet.altitude = gps.altitude;
        packet.satellites = (uint8_t)gps.satellites;
        packet.fix_valid = gps.fix_valid ? 1 : 0;
        
        // CAN Data - Engine Parameters
        packet.rpm = can_data.rpm;
        packet.engine_temp = can_data.engine_temp;
        packet.tps = can_data.tps;
        
        // CAN Data - Pressures & Fluids
        packet.oil_pressure = can_data.oil_pressure;
        packet.fuel_pressure = can_data.fuel_pressure;
        packet.brake_pressure = can_data.brake_pressure;
        packet.battery_voltage = can_data.battery_voltage;
        
        // CAN Data - Wheel Speeds
        packet.wheel_speed_fr = can_data.wheel_speed_fr;
        packet.wheel_speed_fl = can_data.wheel_speed_fl;
        packet.wheel_speed_rr = can_data.wheel_speed_rr;
        packet.wheel_speed_rl = can_data.wheel_speed_rl;
        
        // CAN Data - Dynamics
        packet.g_force_lateral = can_data.g_force_lateral;
        packet.heading = can_data.heading;
        
        // Packet Metadata
        packet.tx_count = (uint16_t)lora_get_tx_count();
        packet.can_frame_count = (uint16_t)(can_get_frame_count() & 0xFFFF);
        
        // Send it (blocking)
        if (lora_send((uint8_t*)&packet, sizeof(packet))) {
            safe_printf("[TX] RPM:%u | Batt:%.2f | TPS:%.3f | EngineTemp:%.1f | TX#%u CAN#%u\n",
                   packet.rpm, packet.battery_voltage, packet.tps, packet.engine_temp,
                   packet.tx_count, packet.can_frame_count);
            safe_printf("[ECU] MAP:%.3f bar | AirTemp:%.1f | Oil:%.2f bar | Fuel:%.2f bar | Water:%.2f bar | Lambda:%.3f\n",
                   can_data.map, can_data.air_temp, can_data.oil_pressure, can_data.fuel_pressure,
                   can_data.water_pressure, can_data.exhaust_o2);
            safe_printf("[GPS] Sats:%d | Fix:%d | Speed:%.1f kph\n",
                   gps.satellites, gps.fix_valid ? 1 : 0, gps.speed_kph);
        } else {
            safe_printf("[TX] FAILED #%lu\n", lora_get_tx_count());
        }
        
        sleep_ms(500);  // TX rate: 2Hz
    }
}

int main() {
    stdio_init_all();
    mutex_init(&printf_mutex);  // Initialize mutex before anything else
    sleep_ms(2000); 
    
    safe_printf("Core 0: Initializing dual-core GPS + LoRa DAQ system...\n");
    
    // Initialize GPS module on core 0
    gps_init();
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

    // Core 0 main loop - dedicated GPS & CAN processing
    while (true) {
        // 1. Poll GPS UART
        gps_process();
        
        // 2. DRAIN LOOP: empty every frame waiting in the MCP2515
        while (can_process_frame()) {
        }
        
        // 3. DASHBOARD BROADCAST (10Hz) - Send the latest GPS + CAN telemetry to the dash via CAN. 
        uint32_t current_time = to_ms_since_boot(get_absolute_time());
        if (current_time - last_dash_tx >= 50) { 
            
            // Get thread-safe copies of the latest telemetry
            ft550_sensor_data_t can_data;
            can_get_sensor_data_safe(&can_data);
            
            gps_data_t gps;
            gps_get_data_safe(&gps);

            // --- FRAME 0x600 (Primary Engine) ---
            uint8_t dash_tx_buf[8];
            uint16_t rpm_out = can_data.rpm;
            // FT550 gives MAP in bar, the screen DBC expects kPa x10 (1 bar = 100 kPa)
            uint16_t map_out = (uint16_t)(can_data.map * 100.0f * 10.0f);
            int16_t  et_out  = (int16_t)(can_data.engine_temp * 10.0f);
            uint16_t tps_out = (uint16_t)(can_data.tps * 10.0f);
            
            dash_tx_buf[0] = rpm_out & 0xFF; dash_tx_buf[1] = (rpm_out >> 8);
            dash_tx_buf[2] = map_out & 0xFF; dash_tx_buf[3] = (map_out >> 8);
            dash_tx_buf[4] = et_out & 0xFF;  dash_tx_buf[5] = (et_out >> 8);
            dash_tx_buf[6] = tps_out & 0xFF; dash_tx_buf[7] = (tps_out >> 8);
            MCP2515_Send(0x600, dash_tx_buf, 8);

            // --- FRAME 0x601 (Battery & Air Temp) ---
            uint8_t aux_tx_buf[8] = {0};
            uint16_t batt_out = (uint16_t)(can_data.battery_voltage * 100.0f);
            int16_t  at_out   = (int16_t)(can_data.air_temp * 10.0f);
            
            aux_tx_buf[0] = batt_out & 0xFF; aux_tx_buf[1] = (batt_out >> 8);
            aux_tx_buf[2] = at_out & 0xFF;   aux_tx_buf[3] = (at_out >> 8);
            MCP2515_Send(0x601, aux_tx_buf, 8);

            // --- FRAME 0x602 (GPS Pos) ---
            uint8_t gps_tx_buf[8];
            int32_t lat_out = (int32_t)(gps.raw_latitude * 10000000.0f);
            int32_t lon_out = (int32_t)(gps.raw_longitude * 10000000.0f);
            
            gps_tx_buf[0] = lat_out & 0xFF;         gps_tx_buf[1] = (lat_out >> 8) & 0xFF;
            gps_tx_buf[2] = (lat_out >> 16) & 0xFF; gps_tx_buf[3] = (lat_out >> 24) & 0xFF;
            gps_tx_buf[4] = lon_out & 0xFF;         gps_tx_buf[5] = (lon_out >> 8) & 0xFF;
            gps_tx_buf[6] = (lon_out >> 16) & 0xFF; gps_tx_buf[7] = (lon_out >> 24) & 0xFF;
            MCP2515_Send(0x602, gps_tx_buf, 8);

            // --- FRAME 0x603 (Meta) ---
            uint8_t meta_tx_buf[8] = {0};
            uint16_t speed_out = (uint16_t)(gps.speed_kph * 10.0f);
            
            meta_tx_buf[0] = speed_out & 0xFF; meta_tx_buf[1] = (speed_out >> 8);
            meta_tx_buf[2] = gps.satellites;
            meta_tx_buf[3] = gps.fix_valid ? 1 : 0;
            meta_tx_buf[4] = lora_get_tx_count() & 0xFF; meta_tx_buf[5] = (lora_get_tx_count() >> 8);
            meta_tx_buf[6] = can_get_frame_count() & 0xFF; meta_tx_buf[7] = (can_get_frame_count() >> 8);
            MCP2515_Send(0x603, meta_tx_buf, 8);

            last_dash_tx = current_time;
        }
        
        // Small delay to prevent locking the bus completely
        sleep_us(100);
    }
}