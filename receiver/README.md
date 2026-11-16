# Pit receiver ("Rocky"), FS27 version

This is Louis's FS26 receiver firmware, copied from <https://github.com/LouWasHere/FS26-RCV> (`FS26-RCV.c`, `lr1121_config.c/.h`). The radio code and settings are his and are unchanged. Credit to Louis for all of it.

What changed for FS27 (`FS26-RCV_fs27.c`):

- Every good packet goes to the laptop untouched as one line, `PKT,<rssi>,<snr>,<hex>`, instead of being decoded and drawn as a text box. Gryphon Manager decodes it. See `wiki/Receiver-PKT-Format.md`.
- It forwards packets that start with either magic number: `FS26` (the standard 68-byte packet) or `FS27` (custom layouts sent with Gryphon Manager's Send to DAQ).
- The receive buffer holds up to 255 bytes instead of 68.
- The `[LORA]`, `[STATS]` and `[FAULT]` lines are still printed.

The radio drivers are shared with the DAQ (`../src`).

Build: `cmake -S receiver -B build-rcv -G Ninja -DPICO_BOARD=pico2 && ninja -C build-rcv`. CI builds `FS27-RCV.uf2` on every push and attaches it to releases.

Not yet run on the real receiver. Louis's original `.uf2` is the fallback. The old `fs26_interface.py` dashboard can't read PKT lines, Gryphon Manager reads both.
