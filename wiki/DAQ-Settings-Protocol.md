# DAQ settings protocol (version 1, proposed)

Lets Gryphon Manager change DAQ behaviour without reflashing. The FS27 firmware doesn't implement it yet. The app side is in `manager/gryphon_manager/core/daq_protocol.py`, and the DAQ settings view unlocks itself when a DAQ answers `HELLO`.

## Over USB serial

One line per message:

```
$GM,<COMMAND>[,key=value...]*CS
```

`CS` is the XOR of every character between `$` and `*`, as two upper-case hex digits. That's the NMEA checksum, the same one the PMTK GPS commands use.

| To the DAQ | Meaning |
| --- | --- |
| `$GM,HELLO*CS` | Are you there, and do you speak this? |
| `$GM,GET*CS` | Send me all settings |
| `$GM,SET,key=value,...*CS` | Change these, don't save yet |
| `$GM,SAVE*CS` | Write the current settings to flash (or SD) |
| `$GM,FACTORY*CS` | Go back to the copy built into the firmware |

| From the DAQ | Meaning |
| --- | --- |
| `$GM,HELLO,fw=<text>,proto=1,settings=<n>*CS` | Firmware name, protocol version, settings version in use |
| `$GM,VAL,key=value,...*CS` | Reply to GET |
| `$GM,OK,settings=<n>*CS` | Done. `n` goes up by one on every SAVE |
| `$GM,ERR,<reason>*CS` | Refused: `checksum`, `range`, `unknown`, `moving` |

## Settings

| Key | CAN index | Allowed | Default |
| --- | --- | --- | --- |
| `gps_hz` | 1 | 1, 5, 10 | 5 |
| `gps_radio` | 2 | 0, 1 | 1 |
| `gps_screen` | 3 | 0, 1 | 1 |
| `radio_hz` | 4 | 1 to 10 | 2 |
| `radio_power_dbm` | 5 | 0 to 13 | 13 |
| `radio_sf` | 6 | 5 to 12 | 7 |
| `screen_hz` | 7 | 1 to 50 | 20 |
| `sd_log` | 8 | 0, 1 | 0 |
| `ch.<channel key>` | n/a | off, slow, fast | from `channels.yaml` |

Radio power is capped at 13 dBm, what FS26 ran. Raise the cap only after checking the rules and the law.

## Over CAN

Two standard IDs, chosen clear of the screen frames (0x600-0x603):

| ID | Direction |
| --- | --- |
| 0x6F0 | to the DAQ |
| 0x6F1 | from the DAQ |

| Byte | Contents |
| --- | --- |
| 0 | Command: 0x7F HELLO, 0x01 GET, 0x02 SET, 0x03 SAVE, 0x04 FACTORY. Replies set the top bit |
| 1 | Setting index (0 if none) |
| 2-5 | Value, signed 32-bit, little-endian |
| 6 | Sequence number, echoed in the reply |
| 7 | Sum of bytes 0-6, low 8 bits |

Check 0x6F0 and 0x6F1 against the PDM's IDs before using this on the car. Sending needs "Allow transmit" in the app.

## What the firmware must do

1. Check the checksum. Reply `ERR,checksum` if it's wrong.
2. Check every value against the table. Reply `ERR,range` and change nothing if any is out.
3. Refuse `SET`, `SAVE` and `FACTORY` while the car is moving (RPM above 0 or GPS speed above 2 km/h): `ERR,moving`.
4. Keep a factory copy in the firmware. Use it if the saved settings fail their own checksum, or if a button is held at boot.
5. Reply with the settings version in use, so the app can show what the DAQ is really running.

Note: the GPS only receives. Changing `gps_hz` means the Pico sends a PMTK command to the GPS, not the app.
