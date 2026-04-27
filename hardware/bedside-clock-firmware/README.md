# JARVIS Bedside Clock Firmware

## Parts List (Total ~$43 AUD)

| Component | Part | Price | Source |
|-----------|------|-------|--------|
| SBC | Raspberry Pi Zero 2W | ~$20 | Core Electronics AU |
| Display | 0.96" SSD1306 OLED 128x64 (I2C) | ~$8 | AliExpress |
| Microphone | INMP441 I2S MEMS module | ~$5 | AliExpress |
| Speaker | 2W 8Ω with JST connector | ~$4 | AliExpress |
| Amplifier | PAM8302 mono amp board | ~$3 | AliExpress |
| Power | USB-C 5V/2.5A supply | ~$8 | Core Electronics AU |
| Case | 3D-printed (STL in /case/) | ~$1 filament | — |

## Wiring Diagram

```
Raspberry Pi Zero 2W GPIO Pinout:

OLED Display (SSD1306 I2C):
  VCC  → 3.3V (Pin 1)
  GND  → GND  (Pin 6)
  SCL  → GPIO3/SCL1 (Pin 5)
  SDA  → GPIO2/SDA1 (Pin 3)

INMP441 Microphone (I2S):
  VDD  → 3.3V (Pin 17)
  GND  → GND  (Pin 20)
  WS   → GPIO19 (Pin 35) — LRCLK
  SCK  → GPIO18 (Pin 12) — BCLK
  SD   → GPIO20 (Pin 38) — DATA
  L/R  → GND (Left channel)

PAM8302 Amplifier + Speaker:
  VIN  → 5V (Pin 2)
  GND  → GND (Pin 9)
  A+   → GPIO21 (Pin 40) — PWM audio
  A-   → GND
  SPK+ → Speaker +
  SPK- → Speaker -
```

## Setup Instructions

### 1. Flash Raspberry Pi OS Lite (64-bit)
```bash
# Use Raspberry Pi Imager
# Enable SSH, set hostname: jarvis-clock
# Set WiFi credentials
```

### 2. Configure I2S Microphone
```bash
# Add to /boot/config.txt:
dtoverlay=i2s-mmap
dtoverlay=googlevoicehat-soundcard

# Or for INMP441 specifically:
dtoverlay=i2s-mmap
dtparam=i2s=on
```

### 3. Install dependencies
```bash
pip install -r requirements.txt

# Install Tesseract (not needed on Pi)
# Install portaudio for PyAudio:
sudo apt-get install portaudio19-dev python3-pyaudio
```

### 4. Configure server IP
Edit `ws_client.py` and `main.py`:
```python
JARVIS_SERVER_IP = "192.168.1.100"  # ← Your JARVIS PC's IP
JARVIS_WS_URL = f"ws://{JARVIS_SERVER_IP}:8000/ws/remote-device"
```

### 5. Auto-start on boot
```bash
# Add to /etc/rc.local before exit 0:
python3 /home/pi/jarvis-clock/main.py &
```

### 6. Test
```bash
python3 main.py
# Say "hey jarvis" — the display icon should change
```

## Case Design Notes

3D-printable case (FDM, 0.2mm layer height, PLA):
- Front: 68mm × 40mm window for OLED + speaker grille
- Rear: USB-C cutout, ventilation slots
- Internal standoffs for Pi Zero 2W M2.5 screws
- Magnetic lid for access

Print in black PETG for best heat resistance.
