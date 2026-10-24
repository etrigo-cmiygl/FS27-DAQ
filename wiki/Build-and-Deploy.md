# Build and Deploy

## Prerequisites

The project is built with the Raspberry Pi Pico SDK (2.2.0) and targets `PICO_BOARD=pico2`.
VS Code with the Raspberry Pi Pico extension is recommended, since it installs and manages the SDK for you.

## Build

In VS Code, use the `Compile Project` task, which runs Ninja against the `build` directory.

To build manually:

```bash
cmake -S . -B build -G Ninja -DPICO_BOARD=pico2
ninja -C build
```

The output is `build/FS27-DAQ.uf2`, along with the `.elf` and other standard Pico artifacts.

## Flash / run

- Drag and drop: hold BOOTSEL while plugging in USB, then copy `FS27-DAQ.uf2` onto the `RP2350` drive.
- `Run Project` uses `picotool load` with the current ELF.
- `Flash` uses OpenOCD to program the board.
- `Rescue Reset` and `RISC-V Reset (RP2350)` are recovery helpers.

## Desk test

`tests/ft550_decoder_test_fs27.c` checks the FT550 decoder on a laptop, with no Pico needed:

```bash
cd tests
cc -I.. -o ft550_test ft550_decoder_test_fs27.c ../ft550_decoder.c && ./ft550_test
```

It should finish with `ALL PASSED`.

## Useful notes

- `pico_enable_stdio_usb(FS27-DAQ 1)` enables USB serial output.
- `pico_enable_stdio_uart(FS27-DAQ 0)` disables default UART stdio, so the GPS UART can stay dedicated.
- `pico_add_extra_outputs(FS27-DAQ)` generates the UF2 and other standard Pico build artifacts.
- If the LR1121 radio isn't connected, startup can stall for a long time waiting on the radio's BUSY line. Bench-test with the full DAQ unit.
