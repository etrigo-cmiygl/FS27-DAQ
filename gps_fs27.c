#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "gps.h"
#include "safe_print.h"

static char nmea_buffer[NMEA_BUFFER_SIZE];
static int buffer_index = 0;
static int total_readings = 0;
static gps_data_t gps_data = {0};

// Spin lock for thread-safe access to gps_data
static spin_lock_t* gps_spin_lock = NULL;

// --- Helper Functions ---

// Custom tokenizer that handles empty fields (e.g. ",,") correctly
static char* nmea_token(char** stringp) {
    char* start = *stringp;
    if (!start) return NULL;
    char* end = strchr(start, ',');
    if (end) {
        *end = '\0';
        *stringp = end + 1;
    } else {
        *stringp = NULL;
    }
    return start;
}

static float nmea_to_decimal(const char* nmea_coord, char direction) {
    if (!nmea_coord || strlen(nmea_coord) == 0) return 0.0;
    float coord = atof(nmea_coord);
    int degrees = (int)(coord / 100);
    float minutes = coord - (degrees * 100);
    float decimal = degrees + (minutes / 60.0);
    if (direction == 'S' || direction == 'W') decimal = -decimal;
    return decimal;
}

static bool verify_nmea_checksum(char* sentence) {
    if (sentence[0] != '$') return false;
    char* asterisk = strrchr(sentence, '*');
    if (asterisk == NULL) return false;
    uint8_t checksum = 0;
    for (char* p = sentence + 1; p < asterisk; p++) checksum ^= *p;
    uint8_t provided_checksum = (uint8_t)strtol(asterisk + 1, NULL, 16);
    return checksum == provided_checksum;
}

// NMEA Parsers

static void parse_gpgga(char* sentence) {
    char* cursor = sentence;
    nmea_token(&cursor); // Skip tag
    
    int field = 1;
    char* token;
    char lat_str[16]={0}, lat_dir=0, lon_str[16]={0}, lon_dir=0, alt_str[16]={0}, sat_str[8]={0};
    
    while ((token = nmea_token(&cursor)) != NULL && field < 15) {
        switch (field) {
            case 2: strncpy(lat_str, token, 15); break;
            case 3: lat_dir = token[0]; break;
            case 4: strncpy(lon_str, token, 15); break;
            case 5: lon_dir = token[0]; break;
            case 7: strncpy(sat_str, token, 7); break;
            case 8: gps_data.hdop = atof(token); break;
            case 9: strncpy(alt_str, token, 15); break;
        }
        field++;
    }
    
    // Parse values locally first
    int sats = (strlen(sat_str) > 0) ? atoi(sat_str) : 0;
    float lat = nmea_to_decimal(lat_str, lat_dir);
    float lon = nmea_to_decimal(lon_str, lon_dir);
    float alt = atof(alt_str);
    float hdop_val = atof(alt_str); // Already parsed above into gps_data.hdop
    bool valid = (strlen(lat_str) > 0 && sats > 0);

    // Update gps_data with spin lock protection
    uint32_t irq_state = spin_lock_blocking(gps_spin_lock);
    gps_data.satellites = sats;
    if (valid) {
        gps_data.fix_valid = true;
        gps_data.raw_latitude = lat;
        gps_data.raw_longitude = lon;
        gps_data.altitude = alt;
    } else {
        gps_data.fix_valid = false;
    }
    spin_unlock(gps_spin_lock, irq_state);
}

static void parse_gprmc(char* sentence) {
    char* cursor = sentence;
    nmea_token(&cursor); // Skip tag
    
    int field = 1;
    char* token;
    char status = 'V';  // V = void (invalid), A = active (valid)
    char speed_str[16]={0}, course_str[16]={0};
    
    while ((token = nmea_token(&cursor)) != NULL && field < 12) {
        switch (field) {
            case 2: status = token[0]; break;  // A=valid, V=invalid
            case 7: strncpy(speed_str, token, 15); break;
            case 8: strncpy(course_str, token, 15); break;
        }
        field++;
    }
    
    // Only use speed/course if status is Active (valid fix)
    float speed = 0.0f;
    float crs = 0.0f;
    if (status == 'A') {
        speed = (strlen(speed_str) > 0) ? atof(speed_str) * 1.852f : 0.0f;
        crs = (strlen(course_str) > 0) ? atof(course_str) : 0.0f;
    }

    // Update with spin lock protection
    uint32_t irq_state = spin_lock_blocking(gps_spin_lock);
    gps_data.speed_kph = speed;
    gps_data.course = crs;
    spin_unlock(gps_spin_lock, irq_state);
}

// Logic Functions

static void apply_filtering_and_print() {
    total_readings++;

    // Print raw status even if no fix, so we know it's alive
    if (!gps_data.fix_valid) {
        // safe_printf("[%d] Searching... (Sats: %d)\n", total_readings, gps_data.satellites);
        return;
    }

    // Filter 1: Accuracy Check
    if (gps_data.hdop > MAX_HDOP_THRESHOLD) {
        // Signal is too weak/noisy
        return;
    }

    // Filter 2: Stationary Anti-Drift (with spin lock)
    uint32_t irq_state = spin_lock_blocking(gps_spin_lock);
    if (gps_data.speed_kph >= MIN_SPEED_THRESHOLD) {
        gps_data.is_moving = true;
        gps_data.display_latitude = gps_data.raw_latitude;
        gps_data.display_longitude = gps_data.raw_longitude;
    } else {
        gps_data.is_moving = false;
        // Keep previous display coordinates (locking them)
        // Unless this is the very first reading
        if (gps_data.display_latitude == 0.0) {
            gps_data.display_latitude = gps_data.raw_latitude;
            gps_data.display_longitude = gps_data.raw_longitude;
        }
    }
    // Copy for printing outside lock
    float disp_lat = gps_data.display_latitude;
    float disp_lon = gps_data.display_longitude;
    float spd = gps_data.speed_kph;
    bool moving = gps_data.is_moving;
    spin_unlock(gps_spin_lock, irq_state);

    // safe_printf("[%d] %s | %.6f, %.6f | %.1f kph | 5Hz\n", 
    //        total_readings,
    //        moving ? "MOVING" : "STATIC",
    //        disp_lat,
    //        disp_lon,
    //        spd);
}

static void process_gps_data() {
    for (int i = 0; i < buffer_index; i++) {
        if (nmea_buffer[i] == '\n' || nmea_buffer[i] == '\r') {
            if (i > 0) {
                nmea_buffer[i] = '\0';
                if (verify_nmea_checksum(nmea_buffer)) {
                    if (strncmp(nmea_buffer, "$GPGGA", 6) == 0 || strncmp(nmea_buffer, "$GNGGA", 6) == 0) {
                        parse_gpgga(nmea_buffer);
                    }
                    else if (strncmp(nmea_buffer, "$GPRMC", 6) == 0 || strncmp(nmea_buffer, "$GNRMC", 6) == 0) {
                        parse_gprmc(nmea_buffer);
                        apply_filtering_and_print();
                    }
                }
            }
            int remaining = buffer_index - (i + 1);
            if (remaining > 0) memmove(nmea_buffer, &nmea_buffer[i + 1], remaining);
            buffer_index = remaining;
            i = -1;
        }
    }
}

// Public Interface Implementation

void gps_init(void) {
    gps_spin_lock = spin_lock_init(spin_lock_claim_unused(true));
    
    safe_printf("1. Initializing GPS at 9600 baud...\n");
    uart_init(GPS_UART_ID, 9600);
    gpio_set_function(GPS_TX_PIN, GPIO_FUNC_UART);
    gpio_set_function(GPS_RX_PIN, GPIO_FUNC_UART);
    
    sleep_ms(1000);  // Longer stabilization time
    
    // Flush any garbage
    while (uart_is_readable(GPS_UART_ID)) uart_getc(GPS_UART_ID);

    // Test if GPS is responding at 9600
    safe_printf("   Checking for GPS at 9600...\n");
    bool found_at_9600 = false;
    absolute_time_t timeout = make_timeout_time_ms(2000);
    while (!time_reached(timeout)) {
        if (uart_is_readable(GPS_UART_ID)) {
            char c = uart_getc(GPS_UART_ID);
            if (c == '$') {
                found_at_9600 = true;
                break;
            }
        }
    }
    
    if (!found_at_9600) {
        // Maybe GPS is already at 57600 from previous run
        safe_printf("   Not found at 9600, trying 57600...\n");
        uart_set_baudrate(GPS_UART_ID, 57600);
        sleep_ms(100);
        while (uart_is_readable(GPS_UART_ID)) uart_getc(GPS_UART_ID);
        
        timeout = make_timeout_time_ms(2000);
        while (!time_reached(timeout)) {
            if (uart_is_readable(GPS_UART_ID)) {
                char c = uart_getc(GPS_UART_ID);
                if (c == '$') {
                    safe_printf("   Found GPS at 57600!\n");
                    goto configure_rate;
                }
            }
        }
        safe_printf("   WARNING: No GPS detected!\n");
        return;
    }
    
    safe_printf("   Found GPS at 9600.\n");
    
    // Configure output sentences first (at 9600)
    safe_printf("2. Configuring GPS output...\n");
    for(int i=0; i<3; i++) { 
        uart_puts(GPS_UART_ID, GPS_CMD_SET_OUTPUT); 
        sleep_ms(100); 
    }
    
    // Switch GPS to 57600 baud
    safe_printf("3. Switching GPS to 57600 baud...\n");
    uart_puts(GPS_UART_ID, "$PMTK251,57600*2C\r\n");
    sleep_ms(500);  // Give GPS time to switch
    
    // Switch Pico UART to match
    uart_set_baudrate(GPS_UART_ID, 57600);
    sleep_ms(200);
    
    // Flush and verify
    while (uart_is_readable(GPS_UART_ID)) uart_getc(GPS_UART_ID);
    
    // Verify we can still communicate
    safe_printf("   Verifying communication at 57600...\n");
    timeout = make_timeout_time_ms(2000);
    bool verified = false;
    while (!time_reached(timeout)) {
        if (uart_is_readable(GPS_UART_ID)) {
            char c = uart_getc(GPS_UART_ID);
            if (c == '$') {
                verified = true;
                break;
            }
        }
    }
    
    if (!verified) {
        safe_printf("   WARNING: Lost GPS after baud switch! Reverting to 9600.\n");
        uart_set_baudrate(GPS_UART_ID, 9600);
        safe_printf(">> GPS running at 9600 baud, 1Hz.\n");
        return;
    }
    
configure_rate:
    // Set 5Hz update rate
    safe_printf("4. Setting 5Hz update rate...\n");
    for(int i=0; i<3; i++) { 
        uart_puts(GPS_UART_ID, GPS_CMD_RATE);
        sleep_ms(100); 
    }
    
    safe_printf(">> GPS Configured: 57600 baud, 5Hz. Waiting for Fix...\n");
}

void gps_process(void) {
    while (uart_is_readable(GPS_UART_ID)) {
        char c = uart_getc(GPS_UART_ID);
        if (buffer_index < NMEA_BUFFER_SIZE - 1) nmea_buffer[buffer_index++] = c;
        else buffer_index = 0; 
        if (c == '\n') process_gps_data();
    }
}

bool gps_is_readable(void) {
    return uart_is_readable(GPS_UART_ID);
}

const gps_data_t* gps_get_data(void) {
    return &gps_data;
}

void gps_get_data_safe(gps_data_t* out) {
    uint32_t irq_state = spin_lock_blocking(gps_spin_lock);
    *out = gps_data;  // Copy entire struct atomically
    spin_unlock(gps_spin_lock, irq_state);
}