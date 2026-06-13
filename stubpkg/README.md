# m5stack-stubs

Type stubs (`.pyi`) for the **M5Stack UIFlow2** MicroPython firmware, so editors
(Pylance / pyright) give autocomplete and type checking for the `M5` module —
which is a compiled C module that no other stub package covers.

```bash
pip install m5stack-stubs
```

Then `import M5` resolves with real method signatures and constant values:

```python
import M5
M5.Lcd.fillRect(0, 0, 100, 50, 0xFFFF)   # fillRect(x, y, w, h, color=...) -> None
pressed: bool = M5.BtnA.isPressed()        # isPressed() -> bool
adv = M5.BOARD.M5CardputerADV              # 24
```

Generated from the official firmware C source by
[m5stubgen](https://github.com/N0I0C0K/m5stack-stubs). The package version tracks
the firmware release it was generated from.

> Stub-only package — it ships `.pyi` files only and has no runtime effect.

## License

MIT
