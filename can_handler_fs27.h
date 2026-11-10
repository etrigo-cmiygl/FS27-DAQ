/**
 * @file      can_handler.h
 * @brief     CAN bus handler with MCP2515 interface and FT550 frame reception
 * 
 * Provides high-level CAN bus initialization, frame reception, and thread-safe
 * access to decoded FT550 sensor data.
 */

#ifndef CAN_HANDLER_H
#define CAN_HANDLER_H

#include <stdbool.h>
#include <stdint.h>
#include "ft550_decoder.h"
#include "pico/sync.h"

/**
 * @brief Initialize CAN bus for FT550 communication
 * 
 * Configures MCP2515 for:
 * - 1 Mbps baud rate
 * - Extended 29-bit CAN identifiers
 * - RX filters for all FT550 frame IDs (0x14080600-0x14080608)
 * 
 * Must be called before any other CAN operations.
 */
void can_init(void);

/**
 * @brief Poll for incoming CAN frames and update sensor data
 * 
 * Non-blocking function that checks for new frames on the RX buffer
 * and updates the internal sensor data structure if frames are received.
 * Call this periodically (e.g., at 100Hz to match ECU broadcast rate).
 * 
 * @return true if a frame was received and processed, false otherwise
 */
bool can_process_frame(void);

/**
 * @brief Get a thread-safe copy of the latest sensor data
 * 
 * Acquires a spin lock, copies the sensor data, and releases the lock.
 * Safe to call from multiple cores/threads.
 * 
 * @param sensor_data Pointer to ft550_sensor_data_t structure to fill with data
 */
void can_get_sensor_data_safe(ft550_sensor_data_t* sensor_data);

/**
 * @brief Get the count of successfully received and decoded frames
 * 
 * @return Total number of frames processed since can_init()
 */
uint32_t can_get_frame_count(void);

/**
 * @brief Print MCP2515 error counters and flags (call from core 0 only)
 */
void can_print_status(void);

#endif // CAN_HANDLER_H
