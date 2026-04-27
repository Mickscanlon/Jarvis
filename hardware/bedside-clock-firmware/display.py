"""
display.py - Clock face and JARVIS status on OLED/TFT display
"""
import time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# Display dimensions (SSD1306 128x64 OLED default)
WIDTH, HEIGHT = 128, 64
STATUS_ICONS = {
    "idle": "○",
    "listening": "◎",
    "thinking": "◈",
    "speaking": "◉",
    "working": "⬡",
    "offline": "✕",
}


class ClockDisplay:
    def __init__(self, use_oled: bool = True):
        self.use_oled = use_oled
        self.device = None
        self._status = "idle"
        self._current_task = ""
        self._init_display()

    def _init_display(self):
        try:
            if self.use_oled:
                from luma.core.interface.serial import i2c
                from luma.oled.device import ssd1306
                serial = i2c(port=1, address=0x3C)
                self.device = ssd1306(serial, width=WIDTH, height=HEIGHT)
                print("[Display] OLED initialized.")
            else:
                # TFT via SPI (e.g. ST7789)
                print("[Display] TFT mode not configured.")
        except Exception as e:
            print(f"[Display] Init failed (headless mode): {e}")
            self.device = None

    def _render(self) -> Image.Image:
        img = Image.new("1", (WIDTH, HEIGHT), 0)
        draw = ImageDraw.Draw(img)

        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 20)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 10)
        except Exception:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        now = datetime.now()
        time_str = now.strftime("%H:%M")
        date_str = now.strftime("%a %d %b")

        # Time (large, centered)
        bbox = draw.textbbox((0, 0), time_str, font=font_large)
        tw = bbox[2] - bbox[0]
        draw.text(((WIDTH - tw) // 2, 4), time_str, fill=1, font=font_large)

        # Date
        bbox = draw.textbbox((0, 0), date_str, font=font_small)
        dw = bbox[2] - bbox[0]
        draw.text(((WIDTH - dw) // 2, 30), date_str, fill=1, font=font_small)

        # Status indicator
        icon = STATUS_ICONS.get(self._status, "○")
        draw.text((2, 50), f"JARVIS {icon}", fill=1, font=font_small)

        # Current task (truncated)
        if self._current_task:
            task = self._current_task[:16]
            draw.text((60, 50), task, fill=1, font=font_small)

        return img

    def update(self):
        """Refresh the display."""
        if self.device is None:
            return
        try:
            img = self._render()
            self.device.display(img)
        except Exception as e:
            print(f"[Display] Update error: {e}")

    def set_status(self, status: str):
        self._status = status
        self.update()

    def set_task(self, task: str):
        self._current_task = task
        self.update()

    def run_clock(self, stop_event=None):
        """Continuous clock update loop (runs in thread)."""
        while not (stop_event and stop_event.is_set()):
            self.update()
            time.sleep(10)
