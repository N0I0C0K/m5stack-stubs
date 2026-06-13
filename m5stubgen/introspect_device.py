"""
Device-side introspection: dump the firmware's ``M5`` C-module structure.

Run this ON a board (it imports ``M5`` and walks ``dir()``); the captured stdout
is the snapshot consumed by :mod:`m5stubgen.dump`. It is the only way to recover
the module glue (which objects ``M5`` exposes) and the constant *values*, because
those are assembled in C++ at compile time, not present in parseable source.

Capture with::

    mpremote connect <PORT> run m5stubgen/introspect_device.py > data/m5_dump.txt

This file is pure MicroPython and must stay dependency-free.
"""
import M5

try:
    M5.begin()
except Exception as e:  # noqa: BLE001 - best effort; keep dumping
    print("BEGIN_ERR", e)

# Firmware metadata header (parsed back by dump.firmware_meta)
try:
    import os as _os

    _u = _os.uname()
    print("# mpy:", getattr(_u, "version", _u[3] if len(_u) > 3 else "?"))
except Exception:
    pass
try:
    print("# board:", M5.getBoard())
except Exception:
    pass

_SCALAR = ("int", "float", "str", "bool", "NoneType", "bytes")
_SKIP_RECURSE = _SCALAR + (
    "func",
    "tuple",
    "list",
    "dict",
    "set",
    "module",
    "bytearray",
)
_seen = set()


def _kind(v):
    if isinstance(v, type):
        return "class"
    if callable(v):
        return "func"
    return type(v).__name__


def _walk(obj, path, depth):
    try:
        names = sorted(dir(obj))
    except Exception:
        return
    for a in names:
        if a.startswith("_"):
            continue
        try:
            v = getattr(obj, a)
        except Exception:
            continue
        k = _kind(v)
        line = path + "\t" + a + "\t" + k
        if k in ("int", "float", "bool", "str"):
            try:
                line += "\t" + repr(v)
            except Exception:
                pass
        print(line)
        if depth > 0:
            tn = type(v).__name__
            if isinstance(v, type):
                key = "class:" + path + "." + a
                if key not in _seen:
                    _seen.add(key)
                    _walk(v, path + "." + a, depth - 1)
            elif k not in _SKIP_RECURSE:
                key = "obj:" + tn
                if key not in _seen:
                    _seen.add(key)
                    _walk(v, path + "." + a, depth - 1)


print("###BEGIN_DUMP###")
_walk(M5, "M5", 2)
print("###END_DUMP###")
