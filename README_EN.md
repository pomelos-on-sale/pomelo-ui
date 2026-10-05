# Pure Rust UI System & Framework (ESP32-S3)

[简体中文](README.md) | **English**

> Version 0.1.0

## 📖 Introduction

This project is a pure Rust UI system designed for Waveshare ESP32-S3-Touch-AMOLED-2.16 touch display development boards.

Built on **ESP-IDF v6.1**.

- **Testing Platform**: Currently tested on the **Waveshare ESP32-S3-Touch-AMOLED-2.16** development board.
- **Portability**: Applications and the UI framework are decoupled from hardware; porting only requires implementing display flush, touch input, and `pomelo-hal` peripheral traits.
- **Official Documentation**: [Waveshare ESP32-S3-Touch-AMOLED-2.16 Documentation](https://docs.waveshare.net/ESP32-S3-Touch-AMOLED-2.16)

---

## 🚀 Quick Start

To clone the complete project with all submodules:

```bash
git clone --recurse-submodules https://github.com/pomelos-on-sale/pomelo-ui.git
```

### 1. Run Applications on PC

```bash
cd pomelo-apps 
cargo run -p calculator

cd pomelo-apps 
cargo run -p app-launcher
```

Press Q to go back, W to exit.

### 2. Flash to Hardware Device

- Install **ESP-IDF** (v6.1 or compatible)
- Install **Rust Xtensa Toolchain** (`espup`)
- Connect the board to your computer via USB

```bash
cd pomelo-firmware/firmware

# Build and flash the firmware
./flash.sh
```

Press the PWR key to power on. After booting into the desktop launcher: swipe left / right to change pages, tap an app icon to open the application, press the left button to minimize the application, press the right button to exit the application, and long-press the middle button to power off.

---

## ✨ Feature & Hardware Support

### 1. UI Framework & Graphics Features

| Feature | Status | Description |
| :--- | :---: | :--- |
| **Iced Widgets** | ✅ Supported | Buttons, sliders, custom Canvas, layout containers, etc. |
| **Chinese Typography** | ✅ Supported | Subsetted Source Han Sans bitmap glyph masks, zero runtime vector overhead |
| **System Icons** | ✅ Supported | Material Symbols icon font wrapper, strongly typed constants |
| **Software Rasterizer** | ✅ Supported | Pure-Rust RGB565 engine (`pomelo-gfx`), native 16-bit framebuffer target |
| **Damage Tracking** | ✅ Supported | Partial dirty rectangle tracking, zero redraw overhead for static scenes |
| **PC Simulation** | ✅ Supported | Desktop window simulation and debugging (Q to go back, W to exit) |

### 2. Hardware Abstraction & UI Integration

> Drivers are provided by ESP-IDF. This project wraps them into Rust `pomelo-hal` traits and integrates them into the UI.

| Module | Status | Description |
| :--- | :---: | :--- |
| **Display** | ✅ Integrated | Damage rect presentation, DMA sliced chunking |
| **Touch** | ✅ Integrated | Tap and drag gestures, driven by unified event queue |
| **Wi-Fi** | ✅ Integrated | AP scanning and connection, IP & RSSI signal display on UI |
| **Battery** | ✅ Integrated | Real-time percentage, voltage monitoring, charging state, power key events |
| **Audio** | ✅ Integrated | I2S PCM streaming playback, volume control |
| **Buttons** | ✅ Integrated | Physical button capture for paging, app exit, and power off |
| **RTC Clock** | ✅ Integrated | Continues timekeeping when powered off, auto-syncs RTC with POSIX clock |
| **IMU Sensor** | 🚧 Planned | HAL Trait and simulator ready, board driver pending |
| **Microphone** | 🚧 Planned | Audio capture interface and recording pending |
| **TF Card** | 🚧 Planned | Hardware routed, filesystem support pending |
| **Bluetooth** | 🚧 Planned | Hardware present, BLE protocol stack pending |

---

## 🎨 iced Framework Porting (`ui-framework/`)

- **`ui-framework/iced`**: A customized fork of iced for embedded targets, removing unsupported 64-bit atomics on Xtensa and dependencies on `mmap`.
- **`ui-framework/iced-pomelo-winit`** (package `iced_winit`): Embedded platform runtime adapter handling event loop dispatch, RGB565 framebuffer presentation, damage tracking, and font loading.
- **`ui-framework/iced-pomelo-gfx`**: Renderer backend for iced that records draw commands into batches for the platform layer to replay.
- **`ui-framework/pomelo-gfx`**: A high-performance pure-Rust RGB565 software rasterizer supporting geometry, anti-aliased strokes, and glyph masks.
- **`ui-framework/pomelo-font`**: Embedded typography tooling and assets, providing Chinese font subsetting and pre-baked bitmap glyph tables.
- **`ui-framework/pomelo-material-symbols`**: A wrapper for Google Material Symbols icon font, providing type-safe icon constants and glyph mappings.


---

## 🙌 Contributing

Contributions, bug reports, and pull requests are warmly welcome! Workflow:

- Create an Issue describing the bug or proposed feature
- Fork the repository and create your feature branch
- Develop and test locally with the project's own suite (`cd pomelo-apps && cargo test --workspace`)
- Submit a Pull Request referencing the corresponding Issue

---

## 🤖 AI Disclaimer

All code in this project (underlying drivers, UI framework, and applications) is **generated by AI**. Due to generation constraints and limited verification depth, the following code quality issues may exist:

- **Incomplete Features & Edge Case Quirks**: Certain features may lack full implementations or behave unexpectedly under unusual edge conditions.
- **Potential Bugs & Stability Hazards**: Lacks exhaustive automated test suites; hidden logic defects or panic risks may exist.
- **Unoptimized Performance & Resource Usage**: Not deeply profiled; potential heap allocations or suboptimal rendering loops may lead to unnecessary overhead.
- **Readability & Architectural Drift**: Multi-round incremental generation lacks strict top-down architecture, leading to loose modularity or code redundancy.

> **Disclaimer**: This project is strictly for technical exploration and PoC experimentation. Users assume all risks and responsibilities when using it in production environments.

---
