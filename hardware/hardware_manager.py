"""
Hardware Controller for BSplayer on Raspberry Pi.
Supports:
- Push Buttons (Play/Pause, Stop, Next, Previous)
- Rotary Encoder (KY-040: Song Navigation & Volume)
- I2C OLED Display (SSD1306 128x64 or 128x32: Song Title, Timer, BPM, VU)
- Graceful mock fallback when running on Windows/macOS for development.
"""

import time
import threading
from typing import Optional, Callable, Dict, Any

try:
    import RPi.GPIO as GPIO
    RPI_AVAILABLE = True
except (ImportError, RuntimeError):
    RPI_AVAILABLE = False

try:
    from luma.core.interface.serial import i2c
    from luma.core.render import canvas
    from luma.oled.device import ssd1306
    OLED_AVAILABLE = True
except (ImportError, Exception):
    OLED_AVAILABLE = False


class HardwareManager:
    def __init__(
        self,
        on_play_pause: Optional[Callable] = None,
        on_stop: Optional[Callable] = None,
        on_next: Optional[Callable] = None,
        on_prev: Optional[Callable] = None,
        on_volume_change: Optional[Callable[[float], None]] = None,
        get_status_fn: Optional[Callable[[], Dict[str, Any]]] = None
    ):
        self.on_play_pause = on_play_pause
        self.on_stop = on_stop
        self.on_next = on_next
        self.on_prev = on_prev
        self.on_volume_change = on_volume_change
        self.get_status_fn = get_status_fn

        # GPIO Pin Definitions (BCM numbering)
        self.PIN_BTN_PLAY = 17     # Pin 11: Play / Pause
        self.PIN_BTN_STOP = 27     # Pin 13: Stop / Rewind
        self.PIN_BTN_PREV = 22     # Pin 15: Previous Track / Marker
        self.PIN_BTN_NEXT = 23     # Pin 16: Next Track / Marker

        # Rotary Encoder (KY-040)
        self.PIN_ENC_CLK = 5       # Pin 29: Rotary Clock
        self.PIN_ENC_DT = 6        # Pin 31: Rotary Data
        self.PIN_ENC_SW = 13       # Pin 33: Rotary Push Button

        self.last_clk_state = 0
        self.running = False
        self.oled_device = None

        self._init_hardware()

    def _init_hardware(self):
        if not RPI_AVAILABLE:
            print("[HardwareManager] Modo Desarrollo (Windows/PC): Pines GPIO emulados.")
            return

        print("[HardwareManager] Inicializando hardware Raspberry Pi (GPIO + I2C)...")
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # Setup buttons with internal pull-up resistors (buttons connect to GND)
        for pin in [self.PIN_BTN_PLAY, self.PIN_BTN_STOP, self.PIN_BTN_PREV, self.PIN_BTN_NEXT, self.PIN_ENC_SW]:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # Setup Rotary Encoder pins
        GPIO.setup(self.PIN_ENC_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.PIN_ENC_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self.last_clk_state = GPIO.input(self.PIN_ENC_CLK)

        # Add event callbacks with software debounce
        GPIO.add_event_detect(self.PIN_BTN_PLAY, GPIO.FALLING, callback=self._handle_play, bouncetime=250)
        GPIO.add_event_detect(self.PIN_BTN_STOP, GPIO.FALLING, callback=self._handle_stop, bouncetime=250)
        GPIO.add_event_detect(self.PIN_BTN_PREV, GPIO.FALLING, callback=self._handle_prev, bouncetime=250)
        GPIO.add_event_detect(self.PIN_BTN_NEXT, GPIO.FALLING, callback=self._handle_next, bouncetime=250)
        GPIO.add_event_detect(self.PIN_ENC_SW, GPIO.FALLING, callback=self._handle_encoder_click, bouncetime=300)

        # Setup I2C OLED display (SSD1306 128x64)
        if OLED_AVAILABLE:
            try:
                serial = i2c(port=1, address=0x3C)
                self.oled_device = ssd1306(serial, width=128, height=64)
                print("[HardwareManager] Pantalla OLED SSD1306 detectada en I2C 0x3C.")
            except Exception as e:
                print(f"[HardwareManager] No se pudo inicializar OLED: {e}")

    def start_display_loop(self):
        """Starts background thread to update the OLED display at 10 FPS."""
        self.running = True
        thread = threading.Thread(target=self._oled_loop, daemon=True)
        thread.start()

    def _oled_loop(self):
        while self.running:
            if self.oled_device and self.get_status_fn:
                try:
                    status = self.get_status_fn()
                    title = status.get("project_title", "BSplayer")[:18]
                    current_time = status.get("current_time", 0.0)
                    total_time = status.get("duration", 0.0)
                    is_playing = status.get("is_playing", False)
                    marker = status.get("current_marker") or "Track"
                    bpm = status.get("bpm", 120)

                    time_str = f"{int(current_time//60):02d}:{int(current_time%60):02d} / {int(total_time//60):02d}:{int(total_time%60):02d}"
                    play_icon = ">" if is_playing else "||"

                    with canvas(self.oled_device) as draw:
                        # Line 1: Title
                        draw.text((0, 0), title, fill="white")
                        # Line 2: Status & Marker
                        draw.text((0, 16), f"[{play_icon}] {marker} ({bpm} BPM)", fill="white")
                        # Line 3: Time
                        draw.text((0, 32), time_str, fill="white")
                        # Line 4: Progress Bar
                        if total_time > 0:
                            bar_w = int((current_time / total_time) * 128)
                            draw.rectangle((0, 48, 127, 54), outline="white", fill="black")
                            draw.rectangle((0, 48, bar_w, 54), outline="white", fill="white")
                except Exception:
                    pass

            # Polling Rotary Encoder on Raspberry Pi
            if RPI_AVAILABLE:
                self._poll_encoder()

            time.sleep(0.1)

    def _poll_encoder(self):
        clk_state = GPIO.input(self.PIN_ENC_CLK)
        dt_state = GPIO.input(self.PIN_ENC_DT)
        if clk_state != self.last_clk_state and clk_state == 0:
            if dt_state != clk_state:
                # Rotated Clockwise (Volume Up / Next)
                if self.on_volume_change:
                    self.on_volume_change(+0.05)
            else:
                # Rotated Counter-Clockwise (Volume Down / Prev)
                if self.on_volume_change:
                    self.on_volume_change(-0.05)
        self.last_clk_state = clk_state

    # Event Handlers
    def _handle_play(self, channel):
        if self.on_play_pause:
            self.on_play_pause()

    def _handle_stop(self, channel):
        if self.on_stop:
            self.on_stop()

    def _handle_prev(self, channel):
        if self.on_prev:
            self.on_prev()

    def _handle_next(self, channel):
        if self.on_next:
            self.on_next()

    def _handle_encoder_click(self, channel):
        if self.on_play_pause:
            self.on_play_pause()

    def cleanup(self):
        self.running = False
        if RPI_AVAILABLE:
            GPIO.cleanup()
