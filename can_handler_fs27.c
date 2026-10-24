/**
 * @file      can_handler_fs27.c
 * @brief     CAN bus handler for FS27 (FuelTech FT550 Lite, FTCAN 2.0 simplified broadcast)
 */

#include "can_handler.h"
#include "src/mcp2515/MCP2515/MCP2515.h"
#include "src/mcp2515/Config/DEV_Config.h"
#include <stdio.h>

static ft550_sensor_data_t g_sensor_data;
static spin_lock_t* g_spin_lock;
static volatile uint32_t g_frame_count = 0;

void can_init(void) {
    ft550_init_sensor_data(&g_sensor_data);

    g_spin_lock = spin_lock_instance(spin_lock_claim_unused(true));

    DEV_Module_Init();
    MCP2515_Init();

    printf("CAN: Initialized MCP2515 at 1 Mbps for FT550 (FTCAN 2.0 simplified)\n");
}

// Returns true whenever a frame was read, even one we don't decode, so the
// drain loop in main keeps emptying the MCP2515 while the PDM, lambda unit
// and display are also talking on the bus.
bool can_process_frame(void) {
    uint32_t received_id = 0;
    uint8_t rx_buffer[8] = {0};

    if (MCP2515_Receive_Fast(&received_id, rx_buffer) != 0) {
        return false;
    }

    uint32_t lock_owner = spin_lock_blocking(g_spin_lock);
    if (ft550_decode_frame(received_id, rx_buffer, &g_sensor_data)) {
        g_frame_count++;
    }
    spin_unlock(g_spin_lock, lock_owner);

    return true;
}

void can_get_sensor_data_safe(ft550_sensor_data_t* sensor_data) {
    if (!sensor_data) {
        return;
    }

    uint32_t lock_owner = spin_lock_blocking(g_spin_lock);
    *sensor_data = g_sensor_data;
    spin_unlock(g_spin_lock, lock_owner);
}

uint32_t can_get_frame_count(void) {
    return g_frame_count;
}
