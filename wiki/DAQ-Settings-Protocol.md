# DAQ settings protocol (version 2)

Lets Gryphon Manager change what the DAQ does without rebuilding firmware. Implemented in the FS27 DAQ firmware v2 (`daq_settings_fs27.c`, `daq_flash_fs27.c`) and in the app (`manager/gryphon_manager/core/daq_protocol.py`). The v1 firmware ignores these lines, and the app carries on working with it.

The firmware side has only been compiled and desk-tested (`tests/daq_settings_test_fs27.c`). It hasn't run on a Pico yet.

## The idea

- The DAQ keeps its settings in the last 4 KB of the Pico's flash, with a version number and a CRC-32.
- No saved settings, or settings that fail their checks: the DAQ uses the factory settings built into the firmware.
- Factory settings behave exactly like the fixed v1 firmware: screen frames 0x600-0x603, the 68-byte `FS26` radio packet, radio 2 Hz, screen 20 Hz, GPS 5 Hz. The desk test proves this byte for byte against a copy of the v1 code.
- Edits go to a pending copy. Nothing changes on the car until `SAVE`, which checks everything, writes flash, and switches over.

## Lines

USB serial, 115200, one line per message, same port as the `[TX]` debug lines:

```
$GM,<COMMAND>[,arguments...]*CS
```

`CS` is the XOR of every character between `$` and `*`, as two upper-case hex digits (the NMEA checksum).

| To the DAQ | Meaning |
| --- | --- |
| `$GM,HELLO*CS` | Are you there, and which protocol? |
| `$GM,GET*CS` | The simple settings |
| `$GM,GETL*CS` | The layouts: one `SF` line per screen frame, `RP` lines for the radio packet, `RPN`, then `OK` |
| `$GM,SET,key=value,...*CS` | Change simple settings (pending) |
| `$GM,SF,<slot>,<id hex>,<signal>,...*CS` | Set screen frame `slot` (0-7). No signals = frame off |
| `$GM,RP,<start>,<field>,...*CS` | Set radio packet fields from position `start` |
| `$GM,RPN,<count>*CS` | How many radio fields are in use |
| `$GM,CANCEL*CS` | Throw away pending edits |
| `$GM,SAVE*CS` | Check, write to flash, start using them |
| `$GM,FACTORY*CS` | Back to factory settings, saved |

| From the DAQ | Meaning |
| --- | --- |
| `$GM,HELLO,fw=FS27-DAQ-2.0,proto=2,settings=<n>,saved=<0 or 1>*CS` | `n` goes up by one on every save. `saved=0` means it's running factory settings |
| `$GM,VAL,gps_hz=5,radio_hz=2,screen_hz=20,layout=1,frames=4,fields=21,packet=68,unsaved=0*CS` | Reply to GET (shows the pending copy) |
| `$GM,OK,settings=<n>*CS` | Done |
| `$GM,ERR,<reason>*CS` | `checksum`, `format`, `range`, `unknown`, `moving`, `flash` |

## Simple settings

| Key | Allowed | Factory |
| --- | --- | --- |
| `gps_hz` | 1, 5, 10 | 5 |
| `radio_hz` | 2 to 10 | 2 |
| `screen_hz` | 1 to 50 | 20 |
| `layout` | 0 to 255 | 1 |

`layout` is the radio layout version. Bump it whenever the radio packet fields change, so the pit side can tell layouts apart.

## Screen frame signals

Each signal is `source/byte/bits/signed/m1/m2`:

- `source`: where the value comes from (table below)
- `byte`: first data byte, 0-7. `bits`: 8, 16 or 32. `signed`: 0 or 1. Little-endian.
- the value sent is `source x m1 x m2`, cut down to a whole number

Factory frame 0x600 is `$GM,SF,0,600,10/0/16/0/1/1,2/2/16/0/100/10,4/4/16/1/1/10,1/6/16/0/1/10`: RPM, MAP (bar x100 = kPa, x10), engine temp x10, throttle x10.

Up to 8 frames, 8 signals each, standard IDs only. Overlapping signals and duplicate IDs are refused.

## Radio packet fields

Each field is `source/type`. Types: 0 u8, 1 i8, 2 u16, 3 i16, 4 u32, 5 i32, 6 f32. Up to 48 fields and 200 bytes.

- Fields exactly as factory: the packet is the v1 one. 4 bytes of magic `0x46533236` ("FS26"), then the fields. 68 bytes.
- Any other field list: magic `0x46533237` ("FS27"), then one byte holding `layout`, then the fields.

## Sources

| Number | Value |
| --- | --- |
| 1-36 | FT550 simplified frames in order: `frame x 4 + position + 1`. 1 TPS, 2 MAP, 3 air temp, 4 engine temp, 5 oil pressure, 6 fuel pressure, 7 water pressure, 8 gear, 9 lambda, 10 RPM, 11 oil temp, 12 pit limit, 13-16 wheel speeds FR FL RR RL, 17 TC slip, 18 TC retard, 19 TC cut, 20 heading, 21-24 shocks, 25 G accel, 26 G lateral, 27 yaw frontal, 28 yaw lateral, 29 lambda correction, 30 fuel flow, 31 injection A, 32 injection B, 33 trans oil temp, 34 trans temp, 35 fuel used, 36 brake pressure |
| 37 | Battery voltage (reads 0 for now) |
| 40-45 | GPS latitude, longitude, speed, altitude, satellites, fix |
| 50, 51 | LoRa packets sent, ECU frames decoded |

Spare inputs (Pico ADC, ADS1115, frequency) aren't in the firmware yet. They'll get source numbers from 60.

## Safety

- `SET`, `SF`, `RP`, `RPN`, `SAVE` and `FACTORY` are refused with `ERR,moving` while RPM is above 0 or GPS speed is above 2 km/h.
- Every value is range-checked. A bad line changes nothing.
- Saving pauses the radio core for the fraction of a second the flash write takes.
- Not settable yet: radio power and spreading factor, CAN bitrate, SD logging, and settings over CAN (IDs 0x6F0 / 0x6F1 from the version 1 draft).
