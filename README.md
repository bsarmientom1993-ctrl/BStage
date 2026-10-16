# BStage (BSplayer) 🌲🎵
### Standalone Multitrack Backing Track & Show Player for Live Bands
*Inspired by the architecture and reliability of the M-Live B.Beat ecosystem.*

BStage (BSplayer) turns a **Raspberry Pi** (or Windows / Linux PC) into a dedicated, rock-solid hardware backing track player for stage performance. It outputs multi-channel audio (e.g. Behringer UMC 404HD / 1820), provides a synchronized in-ear click/metronome, drives visual cues on a 4-inch LCD screen, triggers MIDI presets for pedalboards/lights, and can be remotely controlled from any phone or tablet over Wi-Fi.

---

## 🌟 Key Features

- **Zero-Drift Multitrack Audio Engine:**
  - Renders all stems inside a single synchronous audio callback using `sounddevice` / PortAudio (WASAPI on Windows, low-latency ALSA on Raspberry Pi Linux).
  - All stems share the exact same sample pointer — guaranteed zero phase cancellation and zero timing drift across outputs.
- **Dedicated Click & Cue Matrix:**
  - Independent routing for Click / Voice count-ins directly to Hardware Output 4 (drummer/band in-ears) without leaking into the Front-of-House (FOH) PA mix.
- **Single-File Container Format (`.bsp`):**
  - All stems (48 kHz / 24-bit PCM mono WAVs), markers, synchronized lyrics, chords, video, and MIDI cues are packaged into a single `.bsp` (BSplayer Package) file.
  - **In-Memory Streaming:** Audio is read directly from memory into RAM — zero SD-card extraction, zero wear on flash storage, zero disk latency.
- **Magical 4-inch LCD Kiosk Interface (800x480):**
  - Warm woodland/forest aesthetic (roasted walnut `#100c09`, amber tube glow `#e29b38`, moss green `#487e53`, parchment text `#f6efe6`).
  - 4 view modes: **Live Performance**, **4-Stem Hardware Mixer**, **Song Explorer & Setlist Builder**, and **Teleprompter / Chords**.
- **Responsive Web Remote Console:**
  - Live 20 FPS real-time telemetry over WebSockets (VU meters, elapsed time, current section, song position).
  - Full channel strips with faders, mutes, solos, hardware output routing, and setlist editor.
- **REAPER DAW ReaScript Integration:**
  - One-click export script (`reaper/Export_BSplayer_Project.lua`) renders stems at 48 kHz / 24-bit mono, detects markers/regions, extracts lyrics and chords from MIDI/markers, captures MIDI program change / DMX cues, detects video, and bundles the `.bsp` file automatically.
- **Physical Controls & Appliance Mode:**
  - Native GPIO support for physical buttons (Play/Pause, Stop, Prev, Next), KY-040 rotary knob for master volume, and SSD1306 OLED mini display.
  - Automatic boot into full-screen Kiosk mode on Raspberry Pi via systemd.

---

## 📐 System Architecture

```mermaid
graph TD
    DAW["REAPER DAW (PC/Mac)"] -->|Export_BSplayer_Project.lua| BSP["Single Package (.bsp)"]
    BSP -->|USB / Network Upload| STORAGE["BStage Library (projects/)"]

    subgraph RPi ["Raspberry Pi Appliance"]
        STORAGE --> CORE["ProjectService & In-Memory Unpacker"]
        CORE --> ENGINE["AudioEngine (Matrix Mixer 48kHz / 24-bit)"]
        
        ENGINE -->|Out 1-2 (FOH Mix)| DAC["USB Audio Interface (e.g. Behringer UMC404HD)"]
        ENGINE -->|Out 3 (Guitars/Monitors)| DAC
        ENGINE -->|Out 4 (Click / Cue)| DAC
        
        HARDWARE["HardwareManager (GPIO, Rotary, OLED)"] --> ENGINE
        
        API["FastAPI Server + WebSockets (Port 8000)"] --> ENGINE
        API --> KIOSK["4'' LCD Touchscreen (Chromium Kiosk)"]
        API --> REMOTE["Web Remote (Phone / iPad / Laptop)"]
    end
```

---

## 🗂️ Project Structure

```
BStage/
├── main.py                     # Application entry point (Initializes audio, hardware, and server)
├── models/
│   └── project.py              # SongProject, Track, Marker, LyricLine & ShowPlaylist models
├── engine/
│   ├── audio_engine.py         # Multi-channel matrix mixer & in-memory audio reader
│   └── click_generator.py      # Algorithmic metronome click synthesizer
├── services/
│   └── project_service.py      # .bsp package scanner, show/setlist manager & persistence
├── hardware/
│   └── hardware_manager.py     # GPIO buttons, rotary encoder & SSD1306 driver (with PC fallback)
├── web/
│   ├── server.py               # FastAPI server, REST API, WebSocket telemetry & video stream
│   └── static/
│       ├── screen.html/css/js  # 4-inch 800x480 LCD Kiosk UI (Forest/Woodland theme)
│       └── index.html/css/js   # Desktop/mobile web remote control console
├── tools/
│   └── package_bsp.py          # Standalone CLI tool to create, inspect & validate .bsp packages
├── reaper/
│   └── Export_BSplayer_Project.lua # REAPER ReaScript for 1-click project export
├── deploy/
│   ├── bsplayer.service        # Systemd unit file for auto-start on boot
│   ├── install_rpi.sh          # One-click Raspberry Pi installer
│   └── start_kiosk.sh          # Fullscreen Chromium kiosk launcher
├── projects/
│   ├── demo-song.bsp           # Out-of-the-box 4-channel test project
│   └── _shows/                 # Saved setlists / shows JSON
├── requirements.txt            # Python dependencies
└── README.md
```

---

## 🚀 Quick Start (Windows / Mac / Linux PC)

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/bsarmientom1993-ctrl/BStage.git
cd BStage
pip install -r requirements.txt
```

### 2. Run the Player
```bash
python main.py
```
- **4-inch LCD Kiosk Screen:** Open [http://localhost:8000/screen](http://localhost:8000/screen)
- **Web Remote Console:** Open [http://localhost:8000](http://localhost:8000)

---

## 🍓 Raspberry Pi Appliance Installation

To set up your Raspberry Pi as a dedicated standalone device that powers on directly into the player:

1. Flash **Raspberry Pi OS Lite or Desktop (64-bit)** to your microSD card.
2. Clone the repository into `/home/pi/BStage`:
   ```bash
   git clone https://github.com/bsarmientom1993-ctrl/BStage.git /home/pi/BStage
   cd /home/pi/BStage
   ```
3. Run the automated installer:
   ```bash
   chmod +x deploy/install_rpi.sh deploy/start_kiosk.sh
   ./deploy/install_rpi.sh
   ```
4. Reboot:
   ```bash
   sudo reboot
   ```
The device will automatically start the background engine and launch Chromium in fullscreen kiosk mode on your 4-inch display.

---

## 🔌 Hardware Wiring (Raspberry Pi GPIO)

| Component | Function | Raspberry Pi BCM Pin | Physical Pin |
|---|---|---|---|
| **Push Button 1** | Play / Pause | GPIO 17 | Pin 11 |
| **Push Button 2** | Stop | GPIO 27 | Pin 13 |
| **Push Button 3** | Previous Song | GPIO 22 | Pin 15 |
| **Push Button 4** | Next Song | GPIO 23 | Pin 16 |
| **Rotary Encoder** | CLK (A) | GPIO 5 | Pin 29 |
| **Rotary Encoder** | DT (B) | GPIO 6 | Pin 31 |
| **Rotary Encoder** | SW (Button) | GPIO 13 | Pin 33 |
| **SSD1306 OLED** | I2C SDA | GPIO 2 | Pin 3 |
| **SSD1306 OLED** | I2C SCL | GPIO 3 | Pin 5 |

---

## 🎛️ REAPER DAW Export Workflow

1. Open your project in REAPER.
2. Open **Actions $\rightarrow$ Show action list...** (or press `?`).
3. Click **New action $\rightarrow$ Load ReaScript...** and select `reaper/Export_BSplayer_Project.lua`.
4. Run the script:
   - Sets sample rate to 48 kHz / 24-bit PCM mono.
   - Intelligently maps track groups to hardware outputs:
     - `Click`, `Metrónomo`, `Guía` $\rightarrow$ **Out 4** (In-Ear)
     - `Drums`, `Bajo` $\rightarrow$ **Out 1** (FOH L / Main)
     - `Teclados`, `Sintetizadores` $\rightarrow$ **Out 2** (FOH R / Stereo)
     - `Guitarras`, `Leads` $\rightarrow$ **Out 3** (Monitors / Aux)
   - Extracts markers, tempo, lyrics, video, and MIDI cues.
   - Waits for REAPER's render engine to finish 100% and packages everything into `[SongTitle].bsp`.
5. Copy the `.bsp` file to your USB drive or upload it directly through the BStage web interface!

---

## 📄 License
MIT License. Built for musicians, sound engineers, and live performers.
