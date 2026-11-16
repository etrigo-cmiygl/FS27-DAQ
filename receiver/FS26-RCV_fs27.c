/*!
 * @file      FS26-RCV_fs27.c
 *
 * @brief     LoRa telemetry receiver for LR1121 + Pico ("Rocky"), FS27 version.
 *
 * Written by Louis for FS26 (https://github.com/LouWasHere/FS26-RCV, FS26-RCV.c). The radio code is his,
 * unchanged. The FS27 change: instead of decoding the packet and drawing a text box, every good packet
 * is passed to the laptop untouched as one line,
 *
 *     PKT,<rssi>,<snr>,<hex of the raw packet>
 *
 * so Gryphon Manager does the decoding and a packet layout change never needs a receiver change.
 * See wiki/Receiver-PKT-Format.md.
 */

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "lr1121_config.h"
#include "rcv_pkt_fs27.h"

/*
 * -----------------------------------------------------------------------------
 * --- PRIVATE VARIABLES -------------------------------------------------------
 */

static volatile bool rx_done_flag = false;
static volatile bool rx_error_flag = false;
static uint32_t rx_count = 0;
static uint32_t error_count = 0;
static uint32_t header_error_count = 0;
static uint32_t crc_error_count = 0;
static uint32_t timeout_count = 0;
static uint32_t cad_done_count = 0;  // Channel Activity Detection without full RX

/*
 * -----------------------------------------------------------------------------
 * --- PRIVATE FUNCTIONS -------------------------------------------------------
 */

static void lora_hardware_reset(void) {
    printf("[LORA] Executing physical hardware reset...\n");
    gpio_init(RADIO_RESET);
    gpio_set_dir(RADIO_RESET, GPIO_OUT);
    
    // Pull NRESET low to kill the silicon state
    gpio_put(RADIO_RESET, 0);
    sleep_ms(20);
    // Bring it back high to boot
    gpio_put(RADIO_RESET, 1);
    
    // Give the internal PLLs time to stabilize
    sleep_ms(100); 
}

/**
 * @brief GPIO interrupt handler for LR1121 DIO
 */
static void rx_isr(uint gpio, uint32_t events) {
    rx_done_flag = true;
}

/**
 * @brief Initialize the LR1121 radio for RX-only operation
 */
static void lora_rx_init(void)
{
    printf("[LORA] Initializing LR1121 for RX...\n");
    
    lora_init_io_context(&lr1121);
    lora_init_io(&lr1121);
    lora_spi_init(&lr1121);

    printf("[LORA] LR11XX driver version: %s\n", lr11xx_driver_version_get_version_string());

    lora_system_init(&lr1121);
    lora_print_version(&lr1121);
    lora_radio_init(&lr1121);
    
    // Log RX configuration for debugging
    printf("\nReceiver Configuration:\n");
    printf("   RF frequency  = %lu Hz\n", (unsigned long)RF_FREQ_IN_HZ);
    printf("   Payload length = %u bytes\n", PAYLOAD_LENGTH);
    printf("   Spreading factor = LR11XX_RADIO_LORA_SF7\n");
    printf("   Bandwidth        = LR11XX_RADIO_LORA_BW_800\n");
    printf("   Coding rate      = LR11XX_RADIO_LORA_CR_4_5\n");
    printf("   Preamble length = %u symbol(s)\n", LORA_PREAMBLE_LENGTH);
    printf("   Header mode     = LR11XX_RADIO_LORA_PKT_EXPLICIT\n");
    printf("   CRC mode        = LR11XX_RADIO_LORA_CRC_OFF\n");
    printf("   IQ              = LR11XX_RADIO_LORA_IQ_STANDARD\n");
    printf("   Sync word       = 0x%02X\n", LORA_SYNCWORD);
    printf("   RX boost        = %s\n\n", ENABLE_RX_BOOST_MODE ? "enabled" : "disabled");
    
    lora_init_irq(&lr1121, &rx_isr);

    ASSERT_LR11XX_RC(lr11xx_system_set_dio_irq_params(
        &lr1121,
        LR11XX_SYSTEM_IRQ_RX_DONE | LR11XX_SYSTEM_IRQ_CRC_ERROR | 
        LR11XX_SYSTEM_IRQ_TIMEOUT | LR11XX_SYSTEM_IRQ_HEADER_ERROR,
        0));
    ASSERT_LR11XX_RC(lr11xx_system_clear_irq_status(&lr1121, 0xFFFFFFFF));

    // Print any system error flags detected at init
    uint16_t sys_errors = 0;
    if (lr11xx_system_get_errors(&lr1121, &sys_errors) == LR11XX_STATUS_OK) {
        if (sys_errors != 0) {
            printf("[LORA] System errors at init: 0x%04X\n", sys_errors);
        } else {
            printf("[LORA] No system errors at init\n");
        }
    } else {
        printf("[LORA] Failed to read system errors at init\n");
    }

    printf("[LORA] RX initialization complete\n");
}

/**
 * @brief Start continuous receive mode
 */
static void lora_start_rx(void)
{
    // Ensure radio is in standby before RX
    ASSERT_LR11XX_RC(lr11xx_system_set_standby(&lr1121, LR11XX_SYSTEM_STANDBY_CFG_RC));
    
    // Clear any pending IRQs
    ASSERT_LR11XX_RC(lr11xx_system_clear_irq_status(&lr1121, 0xFFFFFFFF));
    
    rx_done_flag = false;
    rx_error_flag = false;
    
    // Start reception (RX_CONTINUOUS = 0xFFFFFF for continuous mode)
    printf("[LORA] Starting RX (continuous)\n");
    printf("[DEBUG] Calling set_rx_with_timeout_in_rtc_step with RX_CONTINUOUS=0x%06X\n", RX_CONTINUOUS);
    
    lr11xx_status_t rc = lr11xx_radio_set_rx_with_timeout_in_rtc_step(&lr1121, RX_CONTINUOUS);
    if (rc != LR11XX_STATUS_OK) {
        printf("[DEBUG] ERROR: set_rx_with_timeout_in_rtc_step returned %d\n", rc);
    } else {
        printf("[DEBUG] set_rx_with_timeout_in_rtc_step success\n");
    }
    
    // Check radio state immediately after starting RX
    sleep_ms(10);
    lr11xx_system_irq_mask_t irq_check;
    lr11xx_system_get_irq_status(&lr1121, &irq_check);
    printf("[DEBUG] IRQ status immediately after RX start: 0x%08lX\n", (unsigned long)irq_check);
    
    int8_t rssi_check = 0;
    if (lr11xx_radio_get_rssi_inst(&lr1121, &rssi_check) == LR11XX_STATUS_OK) {
        printf("[DEBUG] RSSI check after RX start: %d dBm\n", rssi_check);
    }
    
    ASSERT_LR11XX_RC(rc);
}

/**
 * @brief Receive data over LoRa (blocking until packet received)
 * 
 * @param buffer Pointer to buffer to store received data
 * @param max_length Maximum buffer size
 * @param received_length Pointer to store actual received length
 * @param rssi Pointer to store RSSI value (can be NULL)
 * @param snr Pointer to store SNR value (can be NULL)
 * @return true if packet received successfully, false on error/timeout
 */
/**
 * @brief Receive data over LoRa (blocking until packet received)
 * 
 * @param buffer Pointer to buffer to store received data
 * @param max_length Maximum buffer size
 * @param received_length Pointer to store actual received length
 * @param rssi Pointer to store RSSI value (can be NULL)
 * @param snr Pointer to store SNR value (can be NULL)
 * @return true if packet received successfully, false on error/timeout
 */
static bool lora_receive(uint8_t* buffer, uint8_t max_length, uint8_t* received_length, 
                         int8_t* rssi, int8_t* snr)
{
    uint32_t poll_count = 0;
    
    // Wait for RX to complete
    while (!rx_done_flag) {
        lr11xx_system_irq_mask_t irq_status;
        lr11xx_system_get_irq_status(&lr1121, &irq_status);
        
        // --- THE SHIELD: Catch and silently discard 2.4GHz Wi-Fi/Bluetooth noise ---
        if (irq_status & (LR11XX_SYSTEM_IRQ_HEADER_ERROR | LR11XX_SYSTEM_IRQ_CRC_ERROR)) {
            
            if (irq_status & LR11XX_SYSTEM_IRQ_HEADER_ERROR) header_error_count++;
            if (irq_status & LR11XX_SYSTEM_IRQ_CRC_ERROR) crc_error_count++;
            
            // Clear ONLY the error flags from the silicon
            lr11xx_system_clear_irq_status(&lr1121, LR11XX_SYSTEM_IRQ_HEADER_ERROR | LR11XX_SYSTEM_IRQ_CRC_ERROR);
            
            // Tell the radio to immediately go back to continuous listening
            lr11xx_radio_set_rx_with_timeout_in_rtc_step(&lr1121, RX_CONTINUOUS);
            
            // Reset safety timeout (the radio is alive, it's just processing background noise)
            poll_count = 0; 
            continue; 
        }
        // ---------------------------------------------------------------------------

        // --- THE SUCCESS CONDITION: We got a full, valid packet ---
        if (irq_status & LR11XX_SYSTEM_IRQ_RX_DONE) {
            rx_done_flag = true;
            rx_error_flag = false;
            break;
        }
        
        // --- THE FAIL CONDITION: A genuine timeout ---
        if (irq_status & LR11XX_SYSTEM_IRQ_TIMEOUT) {
            timeout_count++;
            rx_done_flag = true;
            rx_error_flag = true;
            return false;
        }

        // Periodic heartbeat while waiting (every ~1 second)
        poll_count++;
        if ((poll_count % 1000) == 0) {
            int8_t inst_rssi = 0;
            if (lr11xx_radio_get_rssi_inst(&lr1121, &inst_rssi) == LR11XX_STATUS_OK) {
                // Heartbeat print removed to keep terminal clean, but RSSI can be checked here
            }
        }
        
        // Safety timeout: if stuck for 5 seconds without ANY radio events, force exit
        if (poll_count > 5000) {
            printf("[LORA] Safety timeout after 5s, forcing exit\n");
            rx_done_flag = true;
            rx_error_flag = true;
            return false;
        }

        sleep_ms(1);
    }
    
    // Clear all IRQs for the next receive cycle
    lr11xx_system_clear_irq_status(&lr1121, 0xFFFFFFFF);
    
    // Extract the valid packet metadata
    lr11xx_radio_pkt_status_lora_t pkt_status;
    lr11xx_radio_get_lora_pkt_status(&lr1121, &pkt_status);
    
    if (rssi != NULL) *rssi = pkt_status.rssi_pkt_in_dbm;
    if (snr != NULL)  *snr = pkt_status.snr_pkt_in_db;
    
    // Extract the valid packet payload
    lr11xx_radio_rx_buffer_status_t rx_buffer_status;
    lr11xx_radio_get_rx_buffer_status(&lr1121, &rx_buffer_status);
    
    uint8_t payload_len = rx_buffer_status.pld_len_in_bytes;
    
    // Safeguard against buffer overflows
    if (payload_len > max_length) {
        printf("[LORA] Packet too large: %d > %d\n", payload_len, max_length);
        return false;
    }
    
    *received_length = payload_len;
    
    // Read the payload from the radio silicon into the microcontroller's memory
    lr11xx_regmem_read_buffer8(&lr1121, buffer, rx_buffer_status.buffer_start_pointer, payload_len);
    
    rx_count++;
    return true;
}
/*
 * -----------------------------------------------------------------------------
 * --- MAIN --------------------------------------------------------------------
 */

int main()
{
    // Initialize stdio
    stdio_init_all();
    sleep_ms(2000);  // Wait for USB serial connection
    
    printf("\n");
    printf("========================================\n");
    printf("  FS27 Telemetry Receiver (PKT lines)\n");
    printf("  LR1121 LoRa @ 2.4GHz\n");
    printf("========================================\n");
    printf("\n");
    
    // Initialize LoRa receiver
    lora_rx_init();

    // Receive buffer: big enough for any LoRa packet, so longer custom layouts fit too
    static uint8_t rx_buffer[RCV_MAX_PACKET];
    static char line[RCV_LINE_SIZE];
    uint8_t rx_length;
    int8_t rssi, snr;
    
    printf("[LORA] Listening for telemetry, forwarding packets as PKT lines...\n");
    printf("[LORA] Frequency: %lu Hz\n", (unsigned long)RF_FREQ_IN_HZ);
    printf("[LORA] Radio configured payload length: %u bytes\n", PAYLOAD_LENGTH);
    printf("\n");
    
    // Main receive loop
    int consecutive_errors = 0; // NEW: Watchdog counter

    while (true) {
        // Start listening
        lora_start_rx();
        
        // Wait for packet
        if (lora_receive(rx_buffer, sizeof(rx_buffer), &rx_length, &rssi, &snr)) {
            consecutive_errors = 0; // Reset watchdog on a good packet!

            // Pass the packet on untouched if it starts with one of the DAQ's magic numbers
            if (rcv_packet_ok(rx_buffer, rx_length)) {
                rcv_format_pkt(rx_buffer, rx_length, rssi, snr, line, sizeof(line));
                puts(line);
            } else {
                printf("[LORA] Invalid magic...\n");
            }
        } else {
            consecutive_errors++;
            sleep_ms(5); // Give USB stack breathing room

            // The Self-Healing Trigger
            if (consecutive_errors >= 4) {
                printf("\n[FAULT] Radio state machine deadlocked. Watchdog triggered!\n");
                
                lora_hardware_reset(); // Nuke the silicon
                lora_rx_init();        // Reconfigure the radio
                
                consecutive_errors = 0;
            }
            // Print error statistics every 10 failures
            if (((header_error_count + crc_error_count + timeout_count) % 10) == 0 && 
                (header_error_count + crc_error_count + timeout_count) > 0) {
                printf("[STATS] RX Success: %lu | Header Errors: %lu | CRC Errors: %lu | Timeouts: %lu\n",
                       rx_count, header_error_count, crc_error_count, timeout_count);
            }
        }
        
        // Small delay before next receive cycle
        sleep_ms(10);
    }
    
    return 0;
}
