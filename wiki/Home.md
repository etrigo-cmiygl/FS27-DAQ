# FS27-DAQ Wiki

FS27-DAQ is a dual-core telemetry data-acquisition system for the FS27 Leeds Gryphons car, forked from Louis Bishop's FS26-DAQ.
The firmware combines GPS positioning, CAN telemetry from the FuelTech FT550 Lite ECU, and LoRa broadcast on the LR1121 radio.
For the receiver that picks up the radio packets, see the [FS26-RCV wiki](https://github.com/LouWasHere/FS26-RCV/wiki).

## Wiki Map

- [System Architecture](Architecture.md)
- [Hardware Construction](Hardware-Construction.md)
- [Telemetry Flow](Telemetry-Flow.md)
- [Build and Deploy](Build-and-Deploy.md)
- [Gryphon Manager](Gryphon-Manager.md), the laptop app (branch `gryphon-manager`)
- [Receiver PKT format](Receiver-PKT-Format.md)
- [DAQ settings protocol](DAQ-Settings-Protocol.md)

## What the firmware does

- Core 0 handles GPS UART processing, CAN reception and the screen frames.
- Core 1 handles LoRa transmission.
- GPS data is parsed from NMEA sentences, filtered, and shared safely across cores.
- CAN data is decoded from the FT550 simplified broadcast and merged into the transmitted telemetry.

## Where to start in the code

- [`FS26-DAQ_fs27.c`](../FS26-DAQ_fs27.c) contains the main dual-core control flow.
- [`can_handler_fs27.c`](../can_handler_fs27.c) handles MCP2515 reception and FT550 decoding.
- [`ft550_decoder.c`](../ft550_decoder.c) maps each FT550 frame ID to sensor values.
- [`gps_fs27.c`](../gps_fs27.c) implements GPS setup, parsing, and filtering.
- [`lr1121_tx.c`](../lr1121_tx.c) implements LR1121 TX-only operation.
- [`FS26_Ryland`](../FS26_Ryland) contains the WinStar SmartDisplay builder project for the steering wheel screen.

`FS26-DAQ.c`, `can_handler.c` and `gps.c` are Louis's FS26 originals. They're kept for reference but aren't built.
