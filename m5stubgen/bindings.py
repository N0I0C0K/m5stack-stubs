"""
Parse the M5Unified MicroPython C bindings (``mpy_m5*.cpp``) into Python
signatures.

These ``.cpp`` files are the *definition site* of the ``M5`` module's Python API.
Every ``mp_obj_t <prefix>_<method>(...)`` is a method of the type named by
``<prefix>`` (``gfx`` -> ``Display``, ``btn`` -> ``Button``, ...). Two
argument-passing styles appear and both are handled:

* **Keyword tables** — ``const mp_arg_t allowed_args[] = { {MP_QSTR_x,
  MP_ARG_INT | MP_ARG_REQUIRED, ...}, ... };`` gives names, types and which
  args are optional (no ``MP_ARG_REQUIRED``).
* **Fixed positional** — ``mp_obj_t f(mp_obj_t self, mp_obj_t msec)`` gives the
  names directly; the element type is inferred from ``mp_obj_get_int(msec)`` etc.

Return types are inferred from ``mp_obj_new_*`` / ``mp_const_none`` in the body.

This is the **device-free, authoritative** source for parameter names & types:
it is exactly what the firmware parses at runtime.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

# A parameter: (name, python_type, required)
Param = Tuple[str, str, bool]
# A signature: (params, return_type)  — or None when not recoverable (-> *args)
Signature = Optional[Tuple[List[Param], str]]

_FUNC_RE = re.compile(r"mp_obj_t\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{", re.S)
_ARGTBL_RE = re.compile(r"const\s+mp_arg_t\s+allowed_args\[\]\s*=\s*\{(.*?)\};", re.S)
_ENTRY_RE = re.compile(r"\{\s*MP_QSTR_(\w+)\s*,\s*([^,{}]+),", re.S)

#: binding-file suffix (``mpy_m5<suffix>.cpp``) -> M5 instance-type name.
PREFIX_TO_TYPE: Dict[str, str] = {
    "gfx": "Display",
    "btn": "Button",
    "spk": "Speaker",
    "power": "Power",
    "imu": "IMU",
    "als": "ALS",
    "led": "Led",
    "mic": "MIC",
    "touch": "Touch",
}


def _obj_type(name: str) -> str:
    """Best-effort element type for an ``MP_ARG_OBJ`` parameter, by name."""
    if name in ("size",):
        return "float"
    if name in ("text", "string", "str"):
        return "str"
    return "Any"


def _flag_type(flags: str, name: str) -> str:
    if "MP_ARG_BOOL" in flags:
        return "bool"
    if "MP_ARG_INT" in flags:
        return "int"
    return _obj_type(name)


def _ret_type(body: str) -> str:
    if "mp_obj_new_bool(" in body:
        return "bool"
    if "mp_obj_new_float(" in body:
        return "float"
    if "mp_obj_new_int" in body or "mp_obj_new_uint" in body:
        return "int"
    if "mp_obj_new_str" in body:
        return "str"
    if "return mp_const_none" in body and "mp_obj_new_" not in body:
        return "None"
    return "Any"


def _infer_fixed_type(name: str, body: str) -> str:
    if re.search(r"mp_obj_get_int\(\s*%s\b" % re.escape(name), body):
        return "int"
    if re.search(r"mp_obj_get_float\(\s*%s\b" % re.escape(name), body):
        return "float"
    if re.search(r"mp_obj_is_true\(\s*%s\b" % re.escape(name), body):
        return "bool"
    return "Any"


def parse_file(path: str) -> Dict[str, Signature]:
    """Parse one ``mpy_m5*.cpp`` -> ``{method_name: signature}``."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        txt = fh.read()
    funcs = list(_FUNC_RE.finditer(txt))
    out: Dict[str, Signature] = {}
    for i, m in enumerate(funcs):
        cname, raw = m.group(1), m.group(2)
        if "_" not in cname:
            continue
        method = cname.split("_", 1)[1]
        end = funcs[i + 1].start() if i + 1 < len(funcs) else len(txt)
        body = txt[m.end() : end]
        rt = _ret_type(body)

        if "mp_map_t" in raw or "n_args" in raw:  # keyword-table style
            tbl = _ARGTBL_RE.search(body)
            if not tbl:
                out[method] = None  # variadic / custom parsing -> *args
                continue
            params: List[Param] = []
            seen_opt = False
            for em in _ENTRY_RE.finditer(tbl.group(1)):
                nm, flags = em.group(1), em.group(2)
                required = ("MP_ARG_REQUIRED" in flags) and not seen_opt
                if not required:
                    seen_opt = True
                params.append((nm, _flag_type(flags, nm), required))
            out[method] = (params, rt)
        else:  # fixed positional style
            params = []
            for j, tok in enumerate(t.strip() for t in raw.split(",") if t.strip()):
                ids = re.findall(r"[A-Za-z_]\w*", tok)
                nm = ids[-1] if ids else ("a%d" % j)
                if nm in ("self", "void"):  # receiver / C empty-arg `(void)`
                    continue
                params.append((nm, _infer_fixed_type(nm, body), True))
            out[method] = (params, rt)
    return out


def parse_dir(bindings_dir: str) -> Dict[str, Dict[str, Signature]]:
    """Parse every ``mpy_m5*.cpp`` in *bindings_dir* -> ``{suffix: {method: sig}}``."""
    sigs: Dict[str, Dict[str, Signature]] = {}
    for fn in sorted(os.listdir(bindings_dir)):
        if fn.startswith("mpy_m5") and fn.endswith(".cpp"):
            suffix = fn[len("mpy_m5") : -len(".cpp")]
            sigs[suffix] = parse_file(os.path.join(bindings_dir, fn))
    return sigs


def render_method(name: str, sig: Signature, *, indent: str = "    ") -> str:
    """Render a method stub line. ``sig=None`` -> ``(*args, **kwargs) -> Any``."""
    if not sig or sig[0] is None:
        return "%sdef %s(self, *args: Any, **kwargs: Any) -> Any: ..." % (indent, name)
    params, rt = sig
    parts = ["self"]
    for nm, ty, required in params:
        parts.append("%s: %s" % (nm, ty) if required else "%s: %s = ..." % (nm, ty))
    return "%sdef %s(%s) -> %s: ..." % (indent, name, ", ".join(parts), rt)
