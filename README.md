# FS27 Leeds Gryphons DAQ "Ryland"

Data acquisition and telemetry firmware for the Leeds Gryphon Racing FS27 car, running on a Raspberry Pi Pico 2. It's forked from Louis Bishop's FS26 DAQ ([LouWasHere/FS26-DAQ](https://github.com/LouWasHere/FS26-DAQ)), which this builds on directly.

The DAQ:

- reads engine data from the FuelTech FT550 Lite ECU over CAN (1 Mbps, FTCAN 2.0 simplified broadcast)
- adds GPS position from a Quectel L76B
- sends a compact set of CAN frames (0x600–0x603) for the steering wheel screen
- broadcasts a 68-byte telemetry packet over LoRa (2.4 GHz) to the pit receiver, [Rocky](https://github.com/LouWasHere/FS26-RCV)

See the [wiki](wiki/Home.md) for architecture, hardware, telemetry flow and build notes.

## What's changed for FS27

FS26 finished the season on a MoTeC M84. FS27 is back on the FT550 Lite, so the live CAN decoding has been switched back to FuelTech.

Louis's original files are kept untouched for reference. Each changed file is a copy with `_fs27` added to the name, and the build uses the `_fs27` versions.

| FS27 file (built) | Based on (kept, not built) | Change |
| --- | --- | --- |
| `can_handler_fs27.c` | `can_handler.c` | Uses the FT550 decoder (`ft550_decoder.c`) instead of the M84 burst decoder. Every frame read keeps the drain loop going, so frames from the PDM, lambda unit and screen don't stall it. |
| `FS26-DAQ_fs27.c` | `FS26-DAQ.c` | Converts FT550 MAP (bar) to kPa for screen frame 0x600, to match `custom_packet.dbc`. |
| `gps_fs27.c` | `gps.c` | Fixes the checksum on the GPS baud-rate command (`$PMTK251,57600*2C`, was `*00`), so the switch to 57600 baud and 5 Hz no longer fails. |
| `tests/ft550_decoder_test_fs27.c` | n/a (new) | Desk test for the FT550 decoder. Runs on a laptop. |
| `CMakeLists.txt` | n/a (edited in place, since CMake needs this exact name) | Builds the `_fs27` files. The target is renamed `FS27-DAQ`, so the output is `FS27-DAQ.uf2`. |

Known gaps:

- Battery voltage isn't in the FT550 simplified frames, so it reads 0 until FuelTech's standard packet is decoded.
- The telemetry magic number is still `FS26` (0x46533236), on purpose. The receiver checks for it, so it should only change when Rocky is updated at the same time.

## Building

The easiest route is VS Code with the Raspberry Pi Pico extension, which installs the Pico SDK (2.2.0) for you. Open the folder and press Compile.

To build by hand with the SDK installed:

```
cmake -S . -B build -G Ninja -DPICO_BOARD=pico2
ninja -C build
```

## Flashing

1. Hold BOOTSEL on the Pico while plugging in USB. It appears as a drive called `RP2350`.
2. Drag `build/FS27-DAQ.uf2` onto it.
3. Open the USB serial port at 115200 baud to see the output.

## Testing

Desk test, no hardware needed. From the `tests` folder:

```
cc -I.. -o ft550_test ft550_decoder_test_fs27.c ../ft550_decoder.c && ./ft550_test
```

Bench test: connect a second CAN device (e.g. SavvyCAN) at 1 Mbps and send an FT550 frame such as extended ID `0x14080602`, data `03 E8 1F 40 FF 9C 00 01`. The DAQ should print `RPM:8000`, and screen frame 0x600 should decode as 8000 rpm with `custom_packet.dbc`.

On the car, compare the DAQ's output against FTManager's live values with the ECU's simplified CAN broadcast enabled.

## Credit

The original FS26 system, firmware and documentation are by Louis Bishop ([louisj.dev](https://louisj.dev/projects/posts/fs26-daq/)).
