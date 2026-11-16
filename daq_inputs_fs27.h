/**
 * @file  daq_inputs_fs27.h
 * @brief The DAQ's spare sensor inputs: three Pico ADC pins, two optional ADS1115 boards, four frequency pins.
 *
 *   A0-A2  GP26, GP27, GP28   0 to 3.3 V
 *   X0-X3  ADS1115 at 0x48    0 to 5 V   (I2C1: SDA GP2, SCL GP3)
 *   X4-X7  ADS1115 at 0x49    0 to 5 V
 *   F0-F3  GP16, GP17, GP18, GP20   pulses, read as Hz
 *
 * Nothing here blocks for long. If an ADS1115 isn't fitted its inputs read 0 V and it's tried again every second.
 */
#ifndef DAQ_INPUTS_FS27_H
#define DAQ_INPUTS_FS27_H

#include <stdint.h>
#include "daq_settings_fs27.h"

void daq_spare_init(void);                                              /* core 0, once */
void daq_spare_poll(void);                                              /* core 0, every main loop pass */
void daq_spare_read(float raw[DAQ_SPARE_INPUTS], uint16_t* fitted);     /* any core */

#endif
