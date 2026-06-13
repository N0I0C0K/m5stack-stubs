"""Smoke test: the generated out/M5.pyi must be consumable and correctly typed.

Run: `m5stubgen gen` then `uvx pyright` (uses pyrightconfig.json, stubPath=out).
Exercises Display / Button / Power / BOARD constant / module funcs. Wrong or
missing signatures in the generated stub surface here as pyright errors.
"""
import M5

M5.begin()
M5.Lcd.fillScreen(0x000000)
M5.Lcd.fillRect(0, 0, 100, 50, 0xFFFF)
M5.Lcd.drawLine(0, 0, 10, 10, 0x07E0)
M5.Lcd.drawPixel(5, 5, 0xF800)
M5.Lcd.setTextColor(0xFFFFFF, 0x000000)
M5.Lcd.setCursor(2, 2)
M5.Lcd.setTextSize(1.5)
M5.Lcd.print("hi")
w: int = M5.Lcd.textWidth("hi")

pressed: bool = M5.BtnA.isPressed()
held: bool = M5.BtnA.wasHold()
board: int = M5.getBoard()
adv: int = M5.BOARD.M5CardputerADV
volt = M5.Power.getBatteryVoltage()

M5.update()
