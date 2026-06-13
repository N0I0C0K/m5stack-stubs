"""
Command-line interface for m5stubgen.

    m5stubgen dump   --port COM11 [--out data/m5_dump.txt]   # capture device snapshot
    m5stubgen gen    [--dump data/m5_dump.txt] [--bindings vendor/M5Unified] [--out out]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEF_VENDOR = os.path.join(_ROOT, "vendor")
_DEF_DUMP = os.path.join(_ROOT, "data", "m5_dump.txt")
_DEF_BIND = os.path.join(_DEF_VENDOR, "M5Unified")
_DEF_CMOD = os.path.join(_DEF_VENDOR, "cmodules")
_DEF_UNIFIED = os.path.join(_DEF_BIND, "mpy_m5unified.cpp")
_DEF_OUT = os.path.join(_ROOT, "out")
_INTROSPECT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "introspect_device.py"
)


def cmd_dump(args: argparse.Namespace) -> int:
    """Run introspect_device.py on a board via mpremote, save stdout to --out."""
    out = args.out or _DEF_DUMP
    cmd = ["mpremote", "connect", args.port, "run", _INTROSPECT]
    print("$ " + " ".join(cmd), file=sys.stderr)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or "###BEGIN_DUMP###" not in res.stdout:
        sys.stderr.write(res.stdout + res.stderr)
        print("device dump failed", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(res.stdout)
    print("wrote %s (%d lines)" % (out, res.stdout.count("\n") + 1), file=sys.stderr)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    from . import fetch as _fetch

    try:
        _fetch.fetch(args.ref, args.vendor or _DEF_VENDOR)
    except FileNotFoundError:
        print("git not found on PATH (required for fetch)", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print("fetch failed: %s" % e, file=sys.stderr)
        return 1
    return 0


def cmd_gen(args: argparse.Namespace) -> int:
    from . import fetch as _fetch
    from . import generate as gen

    bindings_dir = args.bindings or _DEF_BIND
    out_dir = args.out or _DEF_OUT
    if not os.path.isdir(bindings_dir):
        print(
            "bindings not found: %s — run `m5stubgen fetch` first" % bindings_dir,
            file=sys.stderr,
        )
        return 1
    meta = _fetch.source_meta(args.vendor or _DEF_VENDOR)

    if args.source == "device":
        dump_path = args.dump or _DEF_DUMP
        if not os.path.exists(dump_path):
            print("snapshot not found: %s" % dump_path, file=sys.stderr)
            return 1
        text, cov = gen.from_device(dump_path, bindings_dir)
    else:  # fully from C source (default)
        cmod = args.cmodules or _DEF_CMOD
        unified = args.unified or _DEF_UNIFIED
        for p in (cmod, unified):
            if not os.path.exists(p):
                print(
                    "C source not found: %s — run `m5stubgen fetch` first" % p,
                    file=sys.stderr,
                )
                return 1
        text, cov = gen.from_c(cmod, unified, bindings_dir, meta=meta)

    os.makedirs(out_dir, exist_ok=True)
    out_pyi = os.path.join(out_dir, "M5.pyi")
    with open(out_pyi, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote %s (source=%s)" % (out_pyi, args.source), file=sys.stderr)
    print("M5: %s" % cov, file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="m5stubgen", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser(
        "fetch", help="download firmware C source into vendor/ (needs git)"
    )
    p_fetch.add_argument(
        "--ref",
        default="master",
        help="git ref/tag of uiflow-micropython (default master)",
    )
    p_fetch.add_argument("--vendor", help="vendor dir (default vendor/)")
    p_fetch.set_defaults(func=cmd_fetch)

    p_dump = sub.add_parser(
        "dump", help="(optional) capture a device snapshot for cross-checking"
    )
    p_dump.add_argument(
        "--port", required=True, help="serial port, e.g. COM11 / /dev/ttyACM0"
    )
    p_dump.add_argument("--out", help="output path (default data/m5_dump.txt)")
    p_dump.set_defaults(func=cmd_dump)

    p_gen = sub.add_parser("gen", help="generate M5.pyi")
    p_gen.add_argument(
        "--source",
        choices=["c", "device"],
        default="c",
        help="structure source: 'c' = fully from C (default, no device); "
        "'device' = from a device snapshot",
    )
    p_gen.add_argument(
        "--cmodules", help="dir of m5unified*.c (default vendor/cmodules)"
    )
    p_gen.add_argument("--unified", help="mpy_m5unified.cpp (instance defs)")
    p_gen.add_argument(
        "--dump", help="device snapshot for --source device (default data/m5_dump.txt)"
    )
    p_gen.add_argument(
        "--bindings", help="dir of mpy_m5*.cpp (default vendor/M5Unified)"
    )
    p_gen.add_argument("--vendor", help="vendor dir (for SOURCE.txt firmware ref)")
    p_gen.add_argument("--out", help="output dir (default out/)")
    p_gen.set_defaults(func=cmd_gen)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
