# Telemetry Flow

This page describes the live telemetry path through the firmware.

## GPS

`gps_init()` starts the GPS module at 9600 baud and checks whether the receiver is running at 9600 or 57600. It then configures:

- the selected NMEA output sentences
- 57600 baud for normal operation, falling back to 9600 if the switch fails
- a 5 Hz update rate

Fixed for FS27: the FS26 baud-switch command `$PMTK251,57600*00` had the wrong checksum, so the GPS ignored it and the firmware fell back to 9600 baud without setting 5 Hz. `gps_fs27.c` sends `$PMTK251,57600*2C`.

`gps_process()` buffers incoming NMEA characters, verifies the checksum, and parses:

- GGA for latitude, longitude, altitude, satellites, and HDOP
- RMC for speed and course

The GPS module also applies simple filtering:

- discard low-quality fixes when HDOP is too high
- suppress coordinate drift while the vehicle is stationary

## CAN / FT550 Lite

`can_init()` configures the MCP2515 for 1 Mbps.

`can_process_frame()` in `can_handler_fs27.c` reads one frame at a time and passes it to `ft550_decode_frame()`. The FT550's FTCAN 2.0 simplified broadcast uses nine extended (29-bit) IDs, `0x14080600` to `0x14080608`. Each holds four signed 16-bit big-endian values:

| ID | Values |
| --- | --- |
| 0x14080600 | TPS, MAP, air temp, engine temp |
| 0x14080601 | Oil, fuel and water pressure, gear |
| 0x14080602 | Lambda, RPM, oil temp, pit limit |
| 0x14080603 | Wheel speeds FR, FL, RR, RL |
| 0x14080604 | Traction control slip, retard, cut, heading |
| 0x14080605 | Shock sensors FR, FL, RR, RL |
| 0x14080606 | G-force accel and lateral, yaw rates |
| 0x14080607 | Lambda correction, fuel flow, injection times |
| 0x14080608 | Trans oil temp, trans temp, fuel consumption, brake pressure |

Frames with any other ID (PDM, lambda unit, screen) are read and ignored, so the drain loop keeps emptying the controller.

Battery voltage isn't part of the simplified broadcast, so it reads 0 until FuelTech's standard packet is decoded.

The FS26 MoTeC M84 burst decoder is still in `can_handler.c` for reference.

## LoRa packet

`FS26-DAQ_fs27.c` builds a packed telemetry structure containing:

- magic value `0x46533236` (`FS26`), unchanged so it still matches the receiver
- GPS position, speed, altitude, satellite count, and fix state
- key CAN values such as RPM, engine temp, throttle, pressures, wheel speeds, and heading
- metadata such as the LoRa TX count and the CAN frame count

The packet is sent by `lora_send()` from core 1.

## Dashboard CAN output

The main loop also publishes a compact set of screen frames on the local CAN bus. These are little-endian, as described in `custom_packet.dbc`:

- `0x600` primary engine values (RPM, MAP in kPa ×10, engine temp ×10, TPS ×10)
- `0x601` battery voltage ×100 and air temp ×10
- `0x602` GPS position
- `0x603` GPS and telemetry metadata

The FT550 reports MAP in bar, so it's converted to kPa before sending.
