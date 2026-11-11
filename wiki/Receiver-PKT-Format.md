# Receiver PKT format

A simpler output for the pit receiver (Rocky), to replace the text box that `fs26_interface.py` pattern-matches. Gryphon Manager already reads both, so Rocky can switch whenever it suits.

## The line

One line per received packet, ending in `\n`:

```
PKT,<rssi>,<snr>,<hex>
```

| Field | Meaning |
| --- | --- |
| `PKT` | Fixed tag |
| `rssi` | Signal strength in dBm, whole number, e.g. `-71` |
| `snr` | Signal to noise in dB, whole number, e.g. `9` |
| `hex` | The raw packet exactly as received, as hex. 68 bytes is 136 characters |

Example (shortened):

```
PKT,-71,9,36325346...A0860100
```

## Rules

- Send the packet untouched. The laptop decodes it, so a packet layout change never needs a receiver change.
- Only print a `PKT` line for packets that pass the radio CRC. The laptop checks the length and the magic number (`0x46533236`, sent little-endian so the first bytes are `36 32 53 46`).
- Other lines (`[LORA] ...`, `[STATS] ...`) can stay. Anything that doesn't start with `PKT,` is ignored, apart from `[STATS]`.

## Firmware change

In `FS26-RCV.c`, replace the body of `display_telemetry()` with:

```c
printf("PKT,%d,%d,", rssi, snr);
const uint8_t* b = (const uint8_t*)packet;
for (size_t i = 0; i < sizeof(*packet); i++) printf("%02X", b[i]);
printf("\n");
```

## The packet

68 bytes, packed, little-endian. From `combined_telemetry_packet_t` in `FS26-DAQ_fs27.c`:

| Offset | Type | Field |
| --- | --- | --- |
| 0 | u32 | magic `0x46533236` |
| 4 | f32 | latitude |
| 8 | f32 | longitude |
| 12 | f32 | GPS speed, km/h |
| 16 | f32 | altitude, m |
| 20 | u8 | satellites |
| 21 | u8 | fix valid |
| 22 | u16 | RPM |
| 24 | f32 | engine temp, °C |
| 28 | f32 | TPS, % |
| 32 | f32 | oil pressure, bar |
| 36 | f32 | fuel pressure, bar |
| 40 | f32 | brake pressure, bar |
| 44 | f32 | battery, V |
| 48 | 4 x u16 | wheel speeds FR, FL, RR, RL, km/h |
| 56 | f32 | lateral G |
| 60 | f32 | heading |
| 64 | u16 | LoRa TX count |
| 66 | u16 | CAN frame count |

The layout is generated from `manager/config/channels.yaml`, and a test checks it against the firmware struct.
