# Hardware Construction

This page documents the current pin allocation and the ECU targets the firmware has been developed for.

## Board-level layout

The system is split into three main hardware interfaces:

- GPS receiver on `uart0`
- LR1121 LoRa radio on a dedicated SPI bus
- MCP2515 CAN controller on a separate SPI bus

That separation keeps the radio, CAN, and GPS paths independent at the wiring level.

## Pin allocation

### GPS

| Signal | GPIO |
| --- | --- |
| GPS TX | GPIO 0 |
| GPS RX | GPIO 1 |

The firmware configures these pins as `uart0` in [`gps.c`](../gps.c).

### LR1121 radio

The LR1121 support layer binds the radio context to these pins:

| Signal | GPIO |
| --- | --- |
| RESET | GPIO 8 |
| BUSY | GPIO 9 |
| CLK | GPIO 10 |
| MOSI | GPIO 11 |
| MISO | GPIO 12 |
| CS | GPIO 13 |
| IRQ | GPIO 14 |
| LED | GPIO 25 |

These definitions live in [`src/gpio/gpio.h`](../src/gpio/gpio.h) and are consumed by [`src/lr1121/wavesahre_lora_1121.c`](../src/lr1121/wavesahre_lora_1121.c).

The radio SPI helper currently initializes `spi1` for the LR1121 path in [`src/spi/spi.h`](../src/spi/spi.h).

### MCP2515 CAN controller

The CAN interface uses the board-support pin map defined in the MCP2515 config layer:

| Signal | GPIO |
| --- | --- |
| SPI SCK | GPIO 6 |
| SPI MOSI | GPIO 7 |
| SPI MISO | GPIO 4 |
| CS0 | GPIO 5 |
| CS1 | GPIO 1 |

The active chip select is `MCP2515_CS0_PIN` / `GPIO 5`, as defined in [`src/mcp2515/Config/DEV_Config.h`](../src/mcp2515/Config/DEV_Config.h).
The CAN support layer initializes `spi0` in [`src/mcp2515/Config/DEV_Config.c`](../src/mcp2515/Config/DEV_Config.c).

## ECU targets

### FT550 Lite (live for FS27)

The live CAN handler in [`can_handler_fs27.c`](../can_handler_fs27.c) passes each frame to the decoder in [`ft550_decoder.c`](../ft550_decoder.c) and [`ft550_decoder.h`](../ft550_decoder.h).

That decoder is structured around extended 29-bit frame IDs `0x14080600` through `0x14080608` and covers sensor groups such as:

- TPS and MAP
- temperatures and pressures
- RPM and wheel speeds
- traction, shocks, g-forces, and brake pressure

### M84 (FS26, reference only)

The FS26 handler in [`can_handler.c`](../can_handler.c) was reworked for MoTeC M84 decoding. It isn't built for FS27, but it's kept for reference. It:

- receives a burst of CAN frames on identifier `0x100`
- assembles them into a temporary block
- searches for the M84 magic sequence `82 81 80 54`
- extracts values such as TPS, RPM, engine temperature, air temperature, battery voltage, and MAP from offsets relative to that anchor

## Practical notes

- GPS uses a separate UART, so it does not share pins with the radio or CAN bus.
- The LR1121 and MCP2515 each have their own SPI wiring and chip select pins.
- The FS27 firmware decodes the FT550 one frame at a time, with four values per frame.
- On the F27 harness the bus already has 120 ohm terminators at both ends, so the Pico-CAN-B terminator should normally be switched off.
