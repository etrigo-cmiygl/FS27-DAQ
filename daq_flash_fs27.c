/**
 * @file  daq_flash_fs27.c
 * @brief Keeps the DAQ settings in the last 4 KB of the Pico's flash.
 *
 * Writing flash needs the other core paused, so core 1 must call
 * flash_safe_execute_core_init() once before daq_flash_save() is used.
 */
#include "daq_flash_fs27.h"

#include <string.h>
#include "hardware/flash.h"
#include "pico/flash.h"
#include "pico/stdlib.h"

#define DAQ_FLASH_OFFSET (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)

static uint8_t sector_copy[FLASH_SECTOR_SIZE];
static daq_settings_t* make_live = NULL;

bool daq_flash_load(daq_settings_t* out) {
    const daq_settings_t* stored = (const daq_settings_t*)(XIP_BASE + DAQ_FLASH_OFFSET);
    if (!daq_settings_valid(stored) || !daq_settings_in_range(stored)) return false;
    memcpy(out, stored, sizeof(*out));
    return true;
}

/* Runs with interrupts off and core 1 paused. */
static void write_sector(void* param) {
    (void)param;
    flash_range_erase(DAQ_FLASH_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(DAQ_FLASH_OFFSET, sector_copy, FLASH_SECTOR_SIZE);
    if (make_live) memcpy(make_live, sector_copy, sizeof(*make_live));
}

bool daq_flash_save(const daq_settings_t* sealed, daq_settings_t* live) {
    if (!daq_settings_valid(sealed) || !daq_settings_in_range(sealed)) return false;
    memset(sector_copy, 0xFF, sizeof(sector_copy));
    memcpy(sector_copy, sealed, sizeof(*sealed));
    make_live = live;
    int rc = flash_safe_execute(write_sector, NULL, 1000);
    make_live = NULL;
    if (rc != PICO_OK) return false;
    return memcmp((const void*)(XIP_BASE + DAQ_FLASH_OFFSET), sealed, sizeof(*sealed)) == 0;
}
