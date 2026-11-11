# Gryphon Manager

One laptop app for the car's data. It replaces `fs26_interface.py`, `screen` + `grep`, everyday SavvyCAN use, hand-editing DBC files, and needing VS Code just to flash the DAQ.

It listens to the car three ways, and the same screens work with all of them:

| Source | What you plug in | What you get |
| --- | --- | --- |
| Car (CAN cable) | PEAK PCAN-USB into the debug port C41 | Everything on the bus |
| Radio (pit receiver) | The receiver "Rocky" over USB | What the DAQ radios to the pits |
| DAQ over USB | The DAQ's own USB cable | The DAQ's debug lines |
| Simulator | Nothing | A pretend car with switchable faults |
| Replay | Nothing | Any recording, played back through every view |

On the car's bus the app only listens. The adapter is opened in listen-only mode unless "Allow transmit" is switched on in Settings.

## Run it on Windows (no Python needed)

1. Install the PEAK driver: get "Device driver setup for Windows" from <https://www.peak-system.com/support/downloads/drivers/driver-packages/> and run it, leaving PCAN-Basic ticked. It covers Windows 11 on ARM too (Parallels on an Apple Silicon Mac).
2. Download `GryphonManager-windows.zip`. It's on the repo's Releases page, or under Actions > Gryphon Manager > latest run > Artifacts.
3. Unzip it anywhere and double-click `GryphonManager.exe` inside the `GryphonManager` folder. Windows may show "Windows protected your PC" the first time: More info > Run anyway.
4. Pick "Simulator" in the top bar and press Connect to have a look around. On the car: plug the PCAN-USB into C41, pick "Car (CAN cable)", Connect.

In Parallels, give the adapter to Windows: Devices > USB > PCAN-USB.

Recordings, reports and settings live in `Documents\Gryphon Manager`.

## The views

| View | What it's for |
| --- | --- |
| Home | What's connected, device lights, quick buttons |
| Garage | Testing on the car with the CAN cable: big live values, a light per device with measured vs expected rate, bus health, the ECU ~1 Hz broadcast warning, and the DAQ 0x600-0x603 vs ECU check |
| Signals | Every decoded value with min, max, rate and source ID |
| Raw frames | Every CAN ID like PCAN-View, changed bytes highlighted, unknown IDs in amber |
| Graphs | Live plots, pause, cursor, zoom, save as PNG |
| Telemetry | Radio tiles, offline GPS track map coloured by speed, signal-loss marks, lap timing, link quality |
| Car test | Seven guided steps, saves an HTML + PDF pass/fail report with the raw log |
| Alarms | Rules such as "oil pressure below 1 bar while RPM is above 2000", red banner, optional sound |
| Sessions | Recordings: replay at 0.5-8x, jump to alarm, min/max/avg, overlay two sessions or laps, CSV export |
| Channels | Editor for `config/channels.yaml`. Generate writes the DBCs and the firmware header, with a diff first |
| DAQ settings | Built and disabled until the DAQ firmware supports the settings protocol |
| Firmware | Finds the RP2350 drive, copies the `.uf2`, confirms the DAQ boots |
| Help | The built-in "start here" guide |
| Settings | Adapter, device IDs, units, text size, recording, updates |

Keys: Space record, F11 full screen, F10 pit wall mode, F1 help, Ctrl+1 to Ctrl+9 switch views.

## Run from source

```
cd manager
python -m venv .venv
.venv\Scripts\activate          (Windows)   or   source .venv/bin/activate   (Mac, Linux)
pip install -r requirements-dev.txt
python run.py
```

Python 3.12. The code is cross-platform. On a Mac the PCAN-USB needs the MacCAN PCBUSB library, which hasn't been tested yet. The simulator, replay, the receiver and DAQ USB need nothing extra.

## Tests

```
python -m pytest
```

Everything runs headless (Qt offscreen, simulator, python-can's virtual bus), so it works on Linux in CI. To screenshot every view without a screen:

```
QT_QPA_PLATFORM=offscreen python tools/screenshots.py out_folder
```

## Build the Windows zip

GitHub Actions does it on every push to `gryphon-manager` (`.github/workflows/gryphon-manager.yml`): tests on Linux and Windows, PyInstaller one-folder build, a self-test of the built exe on the simulator, then the zip as an artifact. Pushing a tag like `manager-v1.0.0` also attaches the zip to a GitHub Release, which is what the in-app update check looks at.

By hand: `pyinstaller --noconfirm GryphonManager.spec`, then zip `dist/GryphonManager`.

A Mac build later is one more job in the workflow with `runs-on: macos-latest`.

## How it's laid out

```
manager/
  config/channels.yaml        the master config: every channel, the screen frames, the radio packet
  config/generated/           what Generate writes: team DBC, screen DBC, firmware header, signal list
  gryphon_manager/core/       no Qt in here, so it all runs headless
    config.py generators.py   load, validate and generate from the master config
    engine.py                 live state: signals, frame stats, device health, bus health, the checks
    radio.py                  68-byte LoRa packet, receiver text formats, DAQ debug lines
    simulator.py sources.py   the pretend car, and the real sources (CAN, serial, replay)
    recorder.py               sessions: record, list, load, analyse, CSV export
    alarms.py laps.py cartest.py daq_protocol.py firmware.py
  gryphon_manager/ui/         PySide6: hub.py (20 Hz heartbeat), main_window.py, views/
  tests/  tools/
```

Reader threads only put items on a queue. The hub drains it 20 times a second on the UI thread, so nothing freezes.

## The master config

`config/channels.yaml` is the one place that says what every value is: where it comes from, its scaling, units, range, and whether it goes over the radio or to the screen. FT550 scalings follow `ft550_decoder.c`, which was checked on the car. Where `ftcan_packet.dbc` disagrees (G-force, yaw, heading, TC retard, lambda correction, fuel flow), the channel carries a note that shows in amber in Signals and Channels.

The tests check the config against the firmware: the generated screen DBC must match `custom_packet.dbc`, the FT550 layout must match `ftcan_packet.dbc`, and the generated packet struct must match `combined_telemetry_packet_t` in `FS26-DAQ_fs27.c`.

## Not done yet

See the status doc and the wiki page [Gryphon Manager](../wiki/Gryphon-Manager.md).
