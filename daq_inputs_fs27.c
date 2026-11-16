/**
 * @file  daq_inputs_fs27.c
 * @brief Reads the spare sensor inputs. See daq_inputs_fs27.h for the pins.
 */
#include "daq_inputs_fs27.h"

#include "hardware/adc.h"
#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"

#define SPARE_I2C            i2c1
#define SPARE_SDA_PIN        2
#define SPARE_SCL_PIN        3
#define ADS_TIMEOUT_US       2000
#define ADS_STEP_MS          3
#define ADS_RETRY_MS         1000
#define ADS_VOLTS_PER_COUNT  (6.144f / 32768.0f)
#define ADC_PERIOD_MS        20
#define FREQ_PERIOD_MS       250
#define FREQ_STOPPED_MS      1000

static const uint8_t ADS_ADDR[2] = {0x48, 0x49};
static const uint8_t FREQ_PIN[4] = {16, 17, 18, 20};

static volatile float spare_raw[DAQ_SPARE_INPUTS];
static volatile uint16_t spare_fitted;

typedef struct {
    bool     fitted;
    bool     converting;
    uint8_t  channel;
    uint32_t next_ms;
} ads_state_t;
static ads_state_t ads[2];

typedef struct {
    volatile uint32_t count;
    volatile uint32_t last_us;
    uint32_t prev_us;
    bool     have_prev;
    uint32_t idle_ms;
} freq_state_t;
static freq_state_t freq[4];
static uint32_t adc_next_ms, freq_next_ms;

static void freq_irq(void) {
    uint32_t now = time_us_32();
    for (int i = 0; i < 4; i++) {
        if (gpio_get_irq_event_mask(FREQ_PIN[i]) & GPIO_IRQ_EDGE_RISE) {
            gpio_acknowledge_irq(FREQ_PIN[i], GPIO_IRQ_EDGE_RISE);
            freq[i].count++;
            freq[i].last_us = now;
        }
    }
}

static bool ads_start(int chip, uint8_t channel) {
    /* single shot, AINx against ground, +/-6.144 V range, 860 samples a second, comparator off */
    uint8_t msg[3] = {0x01, (uint8_t)(0xC1 | (channel << 4)), 0xE3};
    return i2c_write_timeout_us(SPARE_I2C, ADS_ADDR[chip], msg, 3, false, ADS_TIMEOUT_US) == 3;
}

static bool ads_result(int chip, float* volts) {
    uint8_t reg = 0x00, data[2];
    if (i2c_write_timeout_us(SPARE_I2C, ADS_ADDR[chip], &reg, 1, true, ADS_TIMEOUT_US) != 1) return false;
    if (i2c_read_timeout_us(SPARE_I2C, ADS_ADDR[chip], data, 2, false, ADS_TIMEOUT_US) != 2) return false;
    int16_t counts = (int16_t)((data[0] << 8) | data[1]);
    *volts = counts < 0 ? 0.0f : (float)counts * ADS_VOLTS_PER_COUNT;
    return true;
}

static void ads_poll(int chip, uint32_t now) {
    ads_state_t* a = &ads[chip];
    if ((int32_t)(now - a->next_ms) < 0) return;
    bool ok = true;
    if (a->converting) {
        float volts;
        ok = ads_result(chip, &volts);
        if (ok) {
            spare_raw[3 + chip * 4 + a->channel] = volts;
            a->channel = (uint8_t)((a->channel + 1) & 3);
        }
    }
    if (ok) ok = ads_start(chip, a->channel);
    if (ok) {
        a->converting = true;
        a->fitted = true;
        a->next_ms = now + ADS_STEP_MS;
        spare_fitted |= (uint16_t)(1u << chip);
    } else {
        a->converting = false;
        a->fitted = false;
        a->next_ms = now + ADS_RETRY_MS;
        spare_fitted &= (uint16_t)~(1u << chip);
        for (int i = 0; i < 4; i++) spare_raw[3 + chip * 4 + i] = 0.0f;
    }
}

void daq_spare_init(void) {
    adc_init();
    adc_gpio_init(26);
    adc_gpio_init(27);
    adc_gpio_init(28);

    i2c_init(SPARE_I2C, 400 * 1000);
    gpio_set_function(SPARE_SDA_PIN, GPIO_FUNC_I2C);
    gpio_set_function(SPARE_SCL_PIN, GPIO_FUNC_I2C);
    gpio_pull_up(SPARE_SDA_PIN);
    gpio_pull_up(SPARE_SCL_PIN);

    uint32_t mask = 0;
    for (int i = 0; i < 4; i++) {
        gpio_init(FREQ_PIN[i]);
        gpio_set_dir(FREQ_PIN[i], GPIO_IN);
        gpio_pull_up(FREQ_PIN[i]);
        mask |= 1u << FREQ_PIN[i];
    }
    gpio_add_raw_irq_handler_masked(mask, freq_irq);
    for (int i = 0; i < 4; i++) gpio_set_irq_enabled(FREQ_PIN[i], GPIO_IRQ_EDGE_RISE, true);
    irq_set_enabled(IO_IRQ_BANK0, true);
}

void daq_spare_poll(void) {
    uint32_t now = to_ms_since_boot(get_absolute_time());

    if ((int32_t)(now - adc_next_ms) >= 0) {
        adc_next_ms = now + ADC_PERIOD_MS;
        for (int ch = 0; ch < 3; ch++) {
            adc_select_input((uint)ch);
            uint32_t sum = 0;
            for (int k = 0; k < 4; k++) sum += adc_read();
            spare_raw[ch] = (float)sum * (3.3f / (4.0f * 4095.0f));
        }
    }

    ads_poll(0, now);
    ads_poll(1, now);

    if ((int32_t)(now - freq_next_ms) >= 0) {
        freq_next_ms = now + FREQ_PERIOD_MS;
        for (int i = 0; i < 4; i++) {
            freq_state_t* f = &freq[i];
            uint32_t irq = save_and_disable_interrupts();
            uint32_t count = f->count, last = f->last_us;
            f->count = 0;
            restore_interrupts(irq);
            if (count > 0) {
                uint32_t span = last - f->prev_us;
                if (f->have_prev && span > 0) spare_raw[DAQ_SPARE_ANALOG + i] = (float)count * 1000000.0f / (float)span;
                f->prev_us = last;
                f->have_prev = true;
                f->idle_ms = 0;
            } else {
                f->idle_ms += FREQ_PERIOD_MS;
                if (f->idle_ms >= FREQ_STOPPED_MS) {
                    spare_raw[DAQ_SPARE_ANALOG + i] = 0.0f;
                    f->have_prev = false;
                }
            }
        }
    }
}

void daq_spare_read(float raw[DAQ_SPARE_INPUTS], uint16_t* fitted) {
    for (int i = 0; i < DAQ_SPARE_INPUTS; i++) raw[i] = spare_raw[i];
    *fitted = spare_fitted;
}
