/**
 * @file  daq_flash_fs27.h
 * @brief Load and save the DAQ settings in the Pico's flash.
 */
#ifndef DAQ_FLASH_FS27_H
#define DAQ_FLASH_FS27_H

#include "daq_settings_fs27.h"

/* Copies the saved settings into out. Returns false if there are none or they fail their checks. */
bool daq_flash_load(daq_settings_t* out);

/* Writes sealed settings to flash and copies them into live while core 1 is paused. */
bool daq_flash_save(const daq_settings_t* sealed, daq_settings_t* live);

#endif
