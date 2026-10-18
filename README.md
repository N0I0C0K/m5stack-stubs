# m5stubgen

Generate **Pylance / pyright type stubs** (`.pyi`) for the **M5Stack UIFlow2**
MicroPython firmware — most importantly the `M5` module, which is a compiled C
module that no existing stub package covers.

Install the generated stubs from [PyPI](https://pypi.org/project/m5stack-stubs/):

```bash
pip install m5stack-stubs
```

This project covers the compiled C `M5` module, which the firmware's Python-only
`pyright --createstub` generator does not cover.

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

## Automatic firmware releases

The `Build & publish stubs` GitHub Actions workflow checks the official
`m5stack/uiflow-micropython` latest stable Release **daily at 09:17 Asia/Shanghai**
(`01:17 UTC`). GitHub may delay scheduled runs. Drafts, prereleases and changes
to `master` alone do not cause an automatic publication.

New package versions follow the official firmware tag: firmware `2.5.3` produces
`m5stack-stubs==2.5.3`. The legacy `0.1.x` packages remain available. Only the
latest stable firmware is synchronized; historical releases are not backfilled.

Each new version is fetched by its exact tag, then the workflow runs binding
regressions, pyright, and wheel checks before publishing with PyPI Trusted
Publishing. The installed PyPI package is checked again, and a GitHub Release
records the firmware tag and verification link. The stub header records the firmware
tag and resolved source commit. All runs share a concurrency lock.

If PyPI already contains that firmware version (including a `.postN` correction)
or a newer stable version, the check exits without building or publishing.
When the exact current version is already available, publishing-enabled runs
verify it and create its GitHub Release record if missing, without uploading it
again. This recovers interrupted post-upload verification on the next run.
Network/API failures stop the run rather than assuming a version is missing.
Failed builds/uploads can be retried on the next daily run or manually; existing
PyPI versions are never overwritten. Post-upload installation retries for up to
five minutes to allow PyPI index propagation. Persistent failures stop the run
and are retried at the next check; inspect the logs for genuine package errors.

To preview the next synchronization without publishing:

```bash
gh workflow run release.yml -f sync_upstream=true -f publish=false
```

To synchronize immediately, explicitly set both inputs to `true`. Leaving both
unset preserves the manual build-only path (`ref` defaults to `master`). The
workflow's `PUBLISH_TO_PYPI` switch disables uploads for all triggers when false.

For a generator-only correction to the same firmware, publish a package Release
such as `v2.5.3.post1` and include this marker in its release notes to keep the
source pinned (legacy package releases without a marker still use `master`):

```html
<!-- m5stubgen-firmware: 2.5.3 -->
```

Scheduled workflows require Actions to remain enabled on the default branch.
GitHub can disable schedules after 60 days of repository inactivity; check the
workflow's status after long idle periods and re-enable it if needed. Failed
runs use GitHub Actions' normal notification settings; no external scheduler or
long-lived publishing token is required.

## Status / roadmap

- [x] one-click `fetch` (git sparse-checkout of the firmware source)
- [x] `M5.pyi` generated **fully from C** — real param/return signatures + constant values
- [x] device snapshot as an optional cross-check (C output validated against it)
- [ ] resolve enum-symbol constant values (parse the C enums)
- [ ] `unit` / `hardware` / `driver` via `pyright --createstub` + lazy-package re-export shims
- [x] PyPI packaging (flat `.pyi` layout, mirroring `micropython-*-stubs`); version tied to firmware
- [x] daily stable firmware detection, validated builds, and automatic PyPI releases

## License

MIT
