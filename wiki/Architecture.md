# System Architecture

The firmware is organized around two cooperative cores on the Raspberry Pi Pico 2. An external LoRa receiver sits on the other side of the air link.

## Comprehensive system view

```mermaid
flowchart TB
	subgraph Vehicle[On-vehicle DAQ node]
		GPSHW[GPS receiver on uart0]
		CANHW[FT550 Lite ECU / CAN bus]
		MCP2515[MCP2515 CAN controller]

		subgraph Pico[Raspberry Pi Pico 2]
			Core0[Core 0 GPS + CAN ingest]
			Shared[Thread-safe shared telemetry GPS/CAN snapshots]
			Core1[Core 1 LR1121 LoRa TX]
			Dash[Local dash CAN frames 0x600-0x603]
		end

		GPSHW -->|NMEA| Core0
		CANHW -->|CAN frames| MCP2515 --> Core0
		Core0 --> Shared
		Shared --> Core1
		Core0 --> Dash
	end

	Core1 -->|Packed telemetry packet| LR1121[LR1121 radio]
	LR1121 -->|LoRa RF uplink| Air((RF link))

	subgraph Receiver[Offboard receiver / base station]
		RxRadio[LoRa receiver]
		Decode[Packet decoder / telemetry bridge]
		UI[Dashboard, logger, or monitoring app]
		Storage[(Optional storage / analysis)]
	end

	Air --> RxRadio --> Decode --> UI
	Decode --> Storage
```

## Core responsibilities

### Core 0

Core 0 performs the continuous input side of the system:

- reads GPS NMEA data from `uart0`
- decodes and filters GPS sentences
- drains every CAN frame waiting in the MCP2515 and decodes FT550 frames
- sends the screen CAN frames (0x600–0x603) every 50 ms

### Core 1

Core 1 is dedicated to the wireless uplink:

- initializes the LR1121 radio
- builds a packed telemetry payload
- transmits the payload over LoRa every 500 ms

## Shared data model

Telemetry is copied between cores using thread-safe helper functions and spin locks.
This keeps GPS and CAN state coherent while the LoRa sender runs independently.

## Main data path

1. The GPS UART feeds `gps_process()`.
2. MCP2515 frames feed `can_process_frame()` in `can_handler_fs27.c`, which passes them to `ft550_decode_frame()`.
3. `FS26-DAQ_fs27.c` combines the latest GPS and CAN snapshots into a packed LoRa payload.
4. `lora_send()` transmits the payload and tracks the TX count.
5. The offboard receiver picks up the packet, decodes it, and forwards it to the dashboard.

## Support libraries

- `src/gpio/` and `src/spi/` provide hardware abstraction for the LR1121 stack.
- `src/lr1121/` contains the Semtech-derived radio driver and board integration code.
- `src/mcp2515/` provides MCP2515 CAN controller support.
