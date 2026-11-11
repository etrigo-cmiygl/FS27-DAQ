from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser

from ... import REPO, __version__, theme
from ...core.sources import PEAK_DRIVER_URL
from ..widgets import View, button, hbox

CSS = f"""
body {{ color: {theme.TEXT}; font-size: 14px; }}
h2 {{ color: {theme.GREEN_BRIGHT}; font-size: 18px; margin-top: 22px; }}
h3 {{ font-size: 15px; margin-top: 14px; }}
td, th {{ padding: 5px 12px; border-bottom: 1px solid {theme.BORDER}; }}
th {{ color: {theme.TEXT_DIM}; text-align: left; }}
code {{ color: {theme.AMBER}; }}
a {{ color: {theme.GREEN_BRIGHT}; }}
.dim {{ color: {theme.TEXT_DIM}; }}
"""

HTML = f"""
<h2 id="start">Start here</h2>
<p>Gryphon Manager is the one laptop app for the car's data. It can listen to the car in three ways, and the
same screens work with all of them:</p>
<table cellspacing="0">
<tr><th>Source</th><th>What you plug in</th><th>What you get</th></tr>
<tr><td>Car (CAN cable)</td><td>PEAK PCAN-USB into the debug port C41</td><td>Everything on the bus. Best for the garage.</td></tr>
<tr><td>Radio (pit receiver)</td><td>The receiver "Rocky" into USB</td><td>What the DAQ radios to the pits, about twice a second.</td></tr>
<tr><td>DAQ over USB</td><td>The DAQ's own USB cable</td><td>The DAQ's debug text: what it decoded and whether its sends work.</td></tr>
<tr><td>Simulator</td><td>Nothing</td><td>A pretend car, with faults you can switch on. For practice and demos.</td></tr>
<tr><td>Replay</td><td>Nothing</td><td>Any recording, played back through every view.</td></tr>
</table>
<p>Pick the source in the top bar, press <b>Connect</b>, and press <b>Record</b> (or Space) to save a session.</p>
<p><b>The app only listens on the car's bus.</b> It can't send anything unless someone switches on
"Allow transmit" in Settings, and even then it asks before each send.</p>

<h2 id="views">What each view does</h2>
<table cellspacing="0">
<tr><td><b>Home</b></td><td>What's connected, device lights, quick buttons.</td></tr>
<tr><td><b>Garage</b></td><td>The car-test screen for the CAN cable: big live values, a light for each device with its
measured rate, bus health, the ECU broadcast-rate check, and whether the DAQ's screen frames match the ECU.</td></tr>
<tr><td><b>Signals</b></td><td>Every decoded value in a table with min, max and rate. Right-click to graph or alarm.</td></tr>
<tr><td><b>Raw frames</b></td><td>Every CAN ID with its bytes, like PCAN-View. Unknown IDs are amber.</td></tr>
<tr><td><b>Graphs</b></td><td>Live plots. Tick signals, pause, zoom, save a PNG.</td></tr>
<tr><td><b>Telemetry</b></td><td>The pit screen: values over the radio, the track map, lap times and link quality.</td></tr>
<tr><td><b>Car test</b></td><td>A step-by-step check that saves a pass/fail report (HTML and PDF) with the raw log.</td></tr>
<tr><td><b>Alarms</b></td><td>Rules like "oil pressure below 1 bar while RPM is above 2000".</td></tr>
<tr><td><b>Sessions</b></td><td>Recordings: replay, compare two, min/max/average, export CSV.</td></tr>
<tr><td><b>Channels</b></td><td>The master list of every value. Generates the DBC files and the firmware header.</td></tr>
<tr><td><b>DAQ settings</b></td><td>Change DAQ behaviour without reflashing (needs newer DAQ firmware).</td></tr>
<tr><td><b>Firmware</b></td><td>Flash the DAQ with a .uf2 file.</td></tr>
</table>
<p class="dim">Keys: Space record, F11 full screen, F10 pit wall mode (big numbers, no sidebar), F1 this page,
Ctrl+1 to Ctrl+9 switch views.</p>

<h2 id="wiring">Wiring the PCAN-USB to the car</h2>
<p>The team's adapter is a PEAK PCAN-USB, opto-isolated (IPEH-002022). It plugs into the car's debug port
<b>C41</b>, a 9-pin D-sub (DB9). The bus runs at 1 Mbps.</p>
<table cellspacing="0">
<tr><th>DB9 pin</th><th>Signal</th></tr>
<tr><td>2</td><td>CAN L</td></tr>
<tr><td>3</td><td>Ground</td></tr>
<tr><td>7</td><td>CAN H</td></tr>
</table>
<p>This is the standard CiA 303-1 pinout. <b>Before the first plug-in, check with a multimeter that C41 really
uses these pins</b>: with the car off, pins 7 and 2 should read about 60 ohm between them.</p>
<p>Termination: the F27 harness has its own 120 ohm resistor at each end of the bus (C17/C20 and C52/C55), so
the reading across CAN H and CAN L is about <b>60 ohm</b>. About 120 means one is missing. About 40 means there
are three, which usually means the DAQ board's own terminator is switched on and should be off.</p>

<h3>First time on a Windows laptop</h3>
<ol>
<li>Install the PEAK driver: download "Device driver setup for Windows" (it covers Windows 11 on ARM too, for Parallels on Apple Silicon) from
<a href="{PEAK_DRIVER_URL}">{PEAK_DRIVER_URL}</a> and run it, leaving PCAN-Basic ticked.</li>
<li>Plug in the PCAN-USB. Its light comes on.</li>
<li>In Parallels on a Mac: Devices &gt; USB &gt; PCAN-USB, so the adapter is given to Windows.</li>
<li>Choose "Car (CAN cable)" and press Connect.</li>
</ol>

<h2 id="sensor">How to add a sensor</h2>
<ol>
<li>Wire the sensor. Easiest is a spare ECU or PDM input, because the value then appears on CAN for free.</li>
<li>Find its frame: connect with the CAN cable, open <b>Raw frames</b>, and watch which bytes change when
you move the sensor. Changed bytes flash green.</li>
<li>Open <b>Channels</b>, press <b>Add a channel</b>, and fill in the ID, start byte, size, scale and units.</li>
<li>Check the box under the table says "No problems", then <b>Save</b>. The value now shows in Signals and Graphs.</li>
<li>To send it over the radio or to the screen as well: set Radio or Screen on the channel, press
<b>Generate files</b>, and give <code>gryphon_channels.h</code> to whoever builds the firmware.</li>
</ol>
<p class="dim">Scale example: the ECU sends throttle as a whole number, 650. With scale 0.1 that's 65.0 %.</p>

<h2 id="flash">How to flash the DAQ</h2>
<ol>
<li>Open <b>Firmware</b>. Press "Look for the latest on GitHub", or choose a .uf2 file.</li>
<li>Unplug the DAQ. Hold the white BOOTSEL button on the Pico, plug in USB, let go.</li>
<li>When the app says it found the Pico, press <b>Flash the DAQ</b>. It restarts by itself.</li>
</ol>

<h2 id="trouble">Troubleshooting</h2>
<table cellspacing="0">
<tr><th>What you see</th><th>What to check</th></tr>
<tr><td>"The PEAK driver isn't installed"</td><td>Install the driver (link above), replug the adapter, Connect again.</td></tr>
<tr><td>"Couldn't open the PCAN-USB"</td><td>Is it plugged in? Is PCAN-View or another app using it? In Parallels, is
the USB device given to Windows?</td></tr>
<tr><td>Connected, but no frames at all</td><td>Ignition on? Right port (C41)? CAN H and L swapped? Wrong bit rate
shows as error frames only.</td></tr>
<tr><td>Bus off, or lots of error frames</td><td>Termination (should read about 60 ohm), a loose connector, or CAN H/L
shorted. Unplug devices one at a time to find the culprit.</td></tr>
<tr><td>ECU light amber, "about 1 Hz"</td><td>In FTManager: Sensors and Calibrations &gt; CAN communication, raise the
simplified broadcast rate.</td></tr>
<tr><td>ECU says "8 of 9 frames"</td><td>That's on the bus itself, so it's the ECU's setup, not the DAQ.</td></tr>
<tr><td>DAQ light red</td><td>Is the DAQ powered (connector C54)? Connect with "DAQ over USB" and read the bus
health card: it explains the DAQ's <code>[CAN]</code> line.</td></tr>
<tr><td>DAQ check says MISMATCH</td><td>The DAQ is forwarding different values from the ECU's: a scaling or firmware
bug. Record it and compare in Sessions.</td></tr>
<tr><td>Steering wheel screen shows zeros</td><td>If the DAQ check is green, the DAQ is sending fine: look at the
screen's wiring and its project. If the DAQ light is red, fix that first.</td></tr>
<tr><td>Battery reads 0</td><td>Known gap. Battery voltage isn't in the FT550's simplified frames yet.</td></tr>
<tr><td>PDM or lambda light is grey</td><td>Their CAN IDs aren't known yet. In Raw frames, right-click an unknown ID
and say which device sends it.</td></tr>
<tr><td>Radio: nothing arriving</td><td>Right COM port? Receiver antenna connected and up high? Is the DAQ powered and
is its LoRa packet count going up (DAQ USB)?</td></tr>
<tr><td>Map is empty</td><td>The GPS needs a clear view of the sky and a minute or two for a first fix.</td></tr>
</table>

<h2 id="files">Where things are kept</h2>
<p>Recordings: <code>Documents / Gryphon Manager / sessions</code><br>
Car test reports: <code>Documents / Gryphon Manager / test reports</code><br>
Settings: <code>Documents / Gryphon Manager / settings.json</code><br>
Code, wiki and new versions: <a href="https://github.com/{REPO}">github.com/{REPO}</a> (branch gryphon-manager,
folder manager)</p>
<p class="dim">Gryphon Manager {__version__}</p>
"""

SECTIONS = [("Start here", "start"), ("Views", "views"), ("Wiring and pinout", "wiring"),
            ("Add a sensor", "sensor"), ("Flash the DAQ", "flash"), ("Troubleshooting", "trouble")]


class HelpView(View):
    title = "Help"
    subtitle = "The 'start here' guide. Everything a new team member needs."
    refresh_every = 1000

    def __init__(self, hub):
        super().__init__(hub)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.document().setDefaultStyleSheet(CSS)
        self.browser.setHtml(HTML)
        row = hbox(spacing=6)
        for text, anchor in SECTIONS:
            row.addWidget(button(text, lambda a=anchor: self.browser.scrollToAnchor(a)))
        row.addStretch(1)
        row.addWidget(button("Show the welcome tour", lambda: self.window_ref.show_welcome()))
        self.root.addLayout(row)
        self.root.addWidget(self.browser, 1)
