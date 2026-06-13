# m5stubgen

Generate **Pylance / pyright type stubs** (`.pyi`) for the **M5Stack UIFlow2**
MicroPython firmware — most importantly the `M5` module, which is a compiled C
module that no existing stub package covers.

There is currently **no ready-made stub package** for the UIFlow2 `M5` API
(checked PyPI, `micropython-stubs`, the official repo, and community repos). The
official firmware repo only ships a *local* generator (`tools/gen_stubs.py`)
that runs `pyright --createstub` over the Python libs — and it doesn't touch the
C `M5` module at all. This project fills that gap and aims to publish an
installable stub package to PyPI.

## How it works

**100% from C source — no device required.** Everything is recovered from the
M5Unified MicroPython binding source:

| What | Source |
|------|--------|
| **Parameter & return signatures** (`fillRect(x, y, w, h, color)`) | `m5stack/components/M5Unified/mpy_m5*.cpp` — the `mp_arg_t allowed_args[]` tables + fixed-positional signatures |
| **Module structure** (`M5.Lcd` is a `Display`, `M5.BtnA` a `Button`) + **constant values** (`BOARD.M5CardputerADV = 24`, `COLOR.WHITE = 0xFFFFFF`, `Power.PORT.PWR485 = 1 << 6`) | `m5stack/cmodules/m5unified/*.c` — the module-globals dict, per-type tables and the instance↔type definitions |

The two are combined: the C registration tables give the structure & constants,
the bindings give every method's real signature.

> A device introspection path (`m5stubgen dump --port COMx` + `gen --source device`)
> exists only as a **cross-check** — the C-derived stub is validated to match it.
> You never need a board to generate.

Known limitation: a few constants whose C value is an *enum symbol*
(`MP_ROM_INT(WAS_CLICKED)`) are emitted as `: int` without the literal value;
literal constants keep their values.

## Usage

```bash
m5stubgen fetch            # git sparse-clone the firmware C source -> vendor/
m5stubgen gen              # generate out/M5.pyi  (100% from C, no device)
```

`fetch --ref <tag>` pins a firmware release; the ref is stamped into the stub
header and `vendor/SOURCE.txt`. The generator reports coverage, e.g.
`M5: 220/240 methods with real signatures (92%)` — the `*args` fallback count is
the regression signal when a new firmware drops.

## Status / roadmap

- [x] one-click `fetch` (git sparse-checkout of the firmware source)
- [x] `M5.pyi` generated **fully from C** — real param/return signatures + constant values
- [x] device snapshot as an optional cross-check (C output validated against it)
- [ ] resolve enum-symbol constant values (parse the C enums)
- [ ] `unit` / `hardware` / `driver` via `pyright --createstub` + lazy-package re-export shims
- [ ] PyPI packaging (flat `.pyi` layout, mirroring `micropython-*-stubs`); version tied to firmware

## License

MIT
