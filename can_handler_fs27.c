/**
 * @file      can_handler_fs27.c
 * @brief     CAN bus handler for FS27 (FuelTech FT550 Lite, FTCAN 2.0 simplified broadcast)
 */

#include "can_handler_fs27.h"
#include "src/mcp2515/MCP2515/MCP2515.h"
#include "src/mcp2515/Config/DEV_Config.h"
#include <stdio.h>
#include "safe_print.h"

static ft550_sensor_data_t g_sensor_data;
static spin_lock_t* g_spin_lock;
static volatile uint32_t g_frame_count = 0;

static void can_reg_write(uint8_t addr, uint8_t data) {
    DEV_Digital_Write(MCP2515_CS_PIN, 0);
    DEV_SPI_WriteByte(CAN_WRITE);
    DEV_SPI_WriteByte(addr);
    DEV_SPI_WriteByte(data);
    DEV_Digital_Write(MCP2515_CS_PIN, 1);
}

static uint8_t can_reg_read(uint8_t addr) {
    DEV_Digital_Write(MCP2515_CS_PIN, 0);
    DEV_SPI_WriteByte(CAN_READ);
    DEV_SPI_WriteByte(addr);
    uint8_t data = DEV_SPI_ReadByte();
    DEV_Digital_Write(MCP2515_CS_PIN, 1);
    return data;
}

void can_init(void) {
    ft550_init_sensor_data(&g_sensor_data);

    g_spin_lock = spin_lock_instance(spin_lock_claim_unused(true));

    DEV_Module_Init();
    MCP2515_Init();
    can_reg_write(RXB0CTRL, 0x64);

    printf("CAN: Initialized MCP2515 at 1 Mbps for FT550 (FTCAN 2.0 simplified), RX rollover on\n");
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

void can_print_status(void) {
    uint8_t tec = can_reg_read(TEC);
    uint8_t rec = can_reg_read(REC);
    uint8_t eflg = can_reg_read(EFLG);
    uint8_t txctrl = can_reg_read(TXB0CTRL);
    safe_printf("[CAN] TEC:%u | REC:%u | EFLG:0x%02X | TXB0CTRL:0x%02X | RX:%lu\n",
                tec, rec, eflg, txctrl, (unsigned long)g_frame_count);
}
