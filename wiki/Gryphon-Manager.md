# Gryphon Manager

The laptop app for the car's data. Code: [`manager/`](../manager) on the `gryphon-manager` branch. Install and usage: [`manager/README.md`](../manager/README.md). The app's own Help view has the wiring, pinout and troubleshooting.

## What it's for

| Job | Where |
| --- | --- |
| Test on the car with the PCAN cable on the debug port C41 | Garage |
| Watch the car from the pits over LoRa | Telemetry |
| Check a car properly and keep a record | Car test |
| Record, replay, compare and export | Sessions |
| Add a sensor or change what goes over the radio | Channels |
| Flash the DAQ | Firmware |

## How data gets in

```
Car CAN bus ── PCAN-USB (listen-only) ──┐
DAQ ── LoRa ── Rocky ── USB serial ─────┼── queue ── hub (20 Hz) ── engine ── views
DAQ ── USB serial (debug lines) ────────┤                 └── recorder
Simulator / Replay ─────────────────────┘
```

Every source produces the same three kinds of item: CAN frames, receiver lines and DAQ debug lines. So the simulator and replay exercise exactly the same code as the real car.

## What it decodes

- FT550 Lite simplified broadcast, extended IDs 0x14080600-0x14080608, four big-endian 16-bit values each. Scalings follow `ft550_decoder.c`.
- DAQ screen frames 0x600-0x603, little-endian, as in `custom_packet.dbc`.
- The 68-byte LoRa packet (`combined_telemetry_packet_t`, magic `FS26`).
- The receiver's FS26 text box, and the new one-line format in [Receiver PKT format](Receiver-PKT-Format.md).
- The DAQ's `[TX]`, `[ECU]`, `[GPS]` and `[CAN]` debug lines. The `[CAN]` line is turned into plain English (sends failing, bus-off, overflow).
- Any extra DBC added in Settings (for the PDM and lambda unit once their IDs are known).

## Device health

| Device | IDs | Expected rate |
| --- | --- | --- |
| ECU (FT550 Lite) | 0x14080600-0x14080608 | 10 Hz, changeable in Settings |
| DAQ (Ryland) | 0x600-0x603 | 20 Hz |
| PDM | not known yet | 10 Hz |
| Lambda unit | not known yet | 10 Hz |
| Steering wheel screen | none: it only listens | n/a |

A device is green when all its frames arrive at half the expected rate or better, amber when slow or some frames are missing, red when it was there and stopped (or never appeared), grey when its ID isn't known. PDM and lambda IDs: in Raw frames, right-click an unknown ID and say which device sends it.

The expected ECU rate of 10 Hz is a starting guess. Set it to whatever the team picks in FTManager.

## The master config

[`manager/config/channels.yaml`](../manager/config/channels.yaml) lists every channel. The Channels view edits it, validates it (duplicate keys, overlapping bits, missing fields) and generates into [`manager/config/generated/`](../manager/config/generated):

| File | Used by |
| --- | --- |
| `gryphon_fs27.dbc` | SavvyCAN, PCAN-View, anything that loads a DBC |
| `gryphon_screen.dbc` | The Winstar GUI Builder (frames 0x600-0x603 only) |
| `gryphon_channels.h` | The firmware: channel table and the radio packet struct |
| `signals.json` | Scripts and the app |

The firmware doesn't include `gryphon_channels.h` yet. Today it's a check that the config and the firmware agree. Making the firmware read its channel table from it is the next step towards a config-driven DAQ.

## Recordings

A session is a folder in `Documents/Gryphon Manager/sessions`:

| File | Contents |
| --- | --- |
| `can.blf` or `can.asc` | Raw CAN, written by python-can |
| `radio.log` | Receiver lines exactly as received, with a timestamp |
| `daq.log` | DAQ debug lines, with a timestamp |
| `alarms.jsonl` | Alarms raised and cleared |
| `meta.json` | Name, date, driver, notes, source, config version, laps |

Nothing is thrown away at record time, so a session can be decoded again later with a better config.

## Safety

- Direct CAN is listen-only by default: PCAN is opened in `BusState.PASSIVE`, slcan with `listen_only=True`.
- "Allow transmit" lives in Settings, asks before it switches on, and the one send tool (Raw frames > Advanced) asks again before each frame.
- DAQ settings changes are refused unless RPM is 0 and speed is about 0.

## Built and not built

Built: all fourteen views, the five sources, the simulator with eight fault scenarios, recording and replay, the car test report, alarms, the config editor and generators, the firmware flasher, the update check, the Windows build in Actions.

Left for later:

- DAQ settings needs firmware support. The page and the [protocol](DAQ-Settings-Protocol.md) are ready.
- Rocky still prints the text box. The app reads it, and reads the [PKT format](Receiver-PKT-Format.md) as soon as Rocky sends it.
- PDM and lambda decoding needs their IDs and layouts.
- Mac build, and PCAN on a Mac.
- Nothing has been tried on the real car or with a real PCAN-USB yet.
