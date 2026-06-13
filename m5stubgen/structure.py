"""
Recover the ``M5`` API *structure* (and constant values) from C source — no
device required.

The MicroPython binding registers everything in plain C tables in
``m5stack/cmodules/m5unified/*.c`` (+ the instance definitions in
``components/M5Unified/mpy_m5unified.cpp``):

* ``mp_module_m5_globals_table`` — the ``M5`` module attributes
  (``Lcd``, ``BtnA``, ``begin``, ``BOARD`` …).
* per-type ``*_member`` tables — each type's methods + nested constant types.
* constant tables — ``MP_ROM_INT(value)`` (``BOARD.M5CardputerADV = 24``,
  ``COLOR.WHITE = 0xFFFFFF``, ``PORT.PWR485 = 1 << 6`` …).
* ``<T>_obj_t m5_<name> = {&mp_<x>_type, ...}`` — which type each instance is.

We parse these into the same ``{path: [Node]}`` mapping that
:func:`m5stubgen.dump.parse` produces from a device snapshot, so
:mod:`m5stubgen.generate` is source-agnostic. Because both paths yield the same
model, the device snapshot doubles as a regression fixture for this parser.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from .dump import Node

#: Stable C type-var -> (friendly class name, binding-file suffix). The C symbol
#: names are firmware-stable; the friendly names match m5stubgen.bindings.PREFIX_TO_TYPE.
TYPEVAR: Dict[str, Tuple[str, str]] = {
    "mp_gfxdevice_type": ("Display", "gfx"),
    "mp_gfxuserdevice_type": ("UserDisplay", "gfx"),
    "mp_btn_type": ("Button", "btn"),
    "mp_spk_type": ("Speaker", "spk"),
    "mp_power_type": ("Power", "power"),
    "mp_imu_type": ("IMU", "imu"),
    "mp_als_type": ("ALS", "als"),
    "mp_led_type": ("Led", "led"),
    "mp_mic_type": ("MIC", "mic"),
    "mp_touch_type": ("Touch", "touch"),
}

_TABLE = re.compile(r"mp_rom_map_elem_t\s+(\w+)\s*\[\]\s*=\s*\{(.*?)\};", re.S)
_ENTRY = re.compile(
    r"MP_ROM_QSTR\(MP_QSTR_(\w+)\)\s*,\s*"
    r"(MP_ROM_INT\([^)]*\)|MP_ROM_PTR\(\s*&\s*\w+\s*\)|MP_OBJ_FROM_PTR\(\s*&\s*\w+\s*\))"
)
_DICT = re.compile(r"MP_DEFINE_CONST_DICT\(\s*(\w+)\s*,\s*(\w+)\s*\)")
_TYPESTRUCT = re.compile(r"mp_obj_type_t\s+(\w+)\s*=\s*\{(.*?)\};", re.S)
_OBJTYPE = re.compile(
    r"MP_DEFINE_CONST_OBJ_TYPE\(\s*(\w+)\s*,\s*MP_QSTR_(\w+)(.*?)\)", re.S
)
_INSTANCE = re.compile(r"\b\w+_obj_t\s+(m5_\w+)\s*=\s*\{[^&]*&\s*(\w+_type)\b", re.S)

_INT = re.compile(r"MP_ROM_INT\(\s*(.+?)\s*\)", re.S)
_PTR = re.compile(r"MP_ROM_PTR\(\s*&\s*(\w+)\s*\)")
_OBJFROM = re.compile(r"MP_OBJ_FROM_PTR\(\s*&\s*(\w+)\s*\)")

MODULE_TABLE = "mp_module_m5_globals_table"


def _strip_comments(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    return s


def _eval_int(expr: str) -> Optional[int]:
    expr = expr.strip()
    if not re.fullmatch(r"[0-9xXa-fA-F\s<>|&+\-*/()~]+", expr):
        return None
    try:
        return int(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - validated above
    except Exception:
        return None


def _classify(val: str) -> Tuple[str, object]:
    """Return ('int', value) or ('sym', symbol) or ('other', None).

    Both MP_ROM_PTR(&x) and MP_OBJ_FROM_PTR(&x) yield a symbol; the *symbol*
    decides whether it's a type / instance / function / opaque object (resolved
    by the caller, which has the symbol tables)."""
    if val.lstrip().startswith("MP_ROM_INT"):
        m = _INT.search(val)
        return "int", (_eval_int(m.group(1)) if m else None)
    m = _PTR.search(val) or _OBJFROM.search(val)
    if m:
        return "sym", m.group(1)
    return "other", None


class _CSource:
    def __init__(self, text: str) -> None:
        self.tables: Dict[str, List[Tuple[str, str]]] = {}
        for m in _TABLE.finditer(text):
            self.tables[m.group(1)] = _ENTRY.findall(m.group(2))
        self.dict2table = {m.group(1): m.group(2) for m in _DICT.finditer(text)}
        self.typevar2name: Dict[str, str] = {}
        self.typevar2dict: Dict[str, str] = {}
        for m in _TYPESTRUCT.finditer(text):
            var, body = m.group(1), m.group(2)
            nm = re.search(r"\.name\s*=\s*MP_QSTR_(\w+)", body)
            ld = re.search(r"\.locals_dict\s*=\s*[^&]*&\s*(\w+)", body)
            if nm:
                self.typevar2name[var] = nm.group(1)
            if ld:
                self.typevar2dict[var] = ld.group(1)
        for m in _OBJTYPE.finditer(text):
            var, name, rest = m.group(1), m.group(2), m.group(3)
            self.typevar2name.setdefault(var, name)
            ld = re.search(r"locals_dict\s*,\s*[^&]*&\s*(\w+)", rest)
            if ld:
                self.typevar2dict.setdefault(var, ld.group(1))
        self.instvar2typevar = {
            m.group(1): m.group(2) for m in _INSTANCE.finditer(text)
        }

    def is_type(self, sym: str) -> bool:
        return sym in TYPEVAR or sym in self.typevar2name

    def type_entries(self, typevar: str) -> List[Tuple[str, str]]:
        dictname = self.typevar2dict.get(typevar)
        table = self.dict2table.get(dictname) if dictname else None
        return self.tables.get(table, []) if table else []

    def type_name(self, typevar: str) -> str:
        if typevar in TYPEVAR:
            return TYPEVAR[typevar][0]
        return self.typevar2name.get(typevar, "Any")


def _emit_type(
    src: _CSource, typevar: str, path: str, children: Dict[str, List[Node]]
) -> None:
    # Instance types (in TYPEVAR) have a method table; nested types (FONTS, COLOR,
    # CB_TYPE, ...) only hold constants/objects.
    method_type = typevar in TYPEVAR
    nodes: List[Node] = []
    for key, val in src.type_entries(typevar):
        kind, data = _classify(val)
        if kind == "int":
            nodes.append(Node(key, "int", str(data) if data is not None else None))
        elif kind == "sym":
            sym = str(data)
            if src.is_type(
                sym
            ):  # nested constant type exposed as attr (FONTS, COLOR, ...)
                nodes.append(Node(key, "class", None))
                _emit_type(src, sym, path + "." + key, children)
            elif (
                sym.endswith("_obj") and method_type
            ):  # a method (read/write/close/...)
                nodes.append(Node(key, "func", None))
            else:  # opaque object (e.g. a font under FONTS)
                nodes.append(Node(key, "Any", None))
    children[path] = nodes


def build(cmodules_dir: str, unified_cpp: str) -> Dict[str, List[Node]]:
    """Parse the C registration into the ``{path: [Node]}`` model."""
    text = ""
    for fn in sorted(os.listdir(cmodules_dir)):
        if fn.endswith(".c"):
            with open(
                os.path.join(cmodules_dir, fn), encoding="utf-8", errors="replace"
            ) as fh:
                text += _strip_comments(fh.read()) + "\n"
    with open(unified_cpp, encoding="utf-8", errors="replace") as fh:
        text += _strip_comments(fh.read())

    src = _CSource(text)
    children: Dict[str, List[Node]] = {}
    carriers: Dict[str, str] = {}  # TypeName -> module attr that carries the members
    mod: List[Node] = []

    for key, val in src.tables.get(MODULE_TABLE, []):
        kind, data = _classify(val)
        if kind == "int":
            mod.append(Node(key, "int", str(data) if data is not None else None))
            continue
        if kind != "sym":
            continue
        sym = str(data)
        if sym in src.instvar2typevar:  # an instance (Lcd, BtnA, ...)
            tv = src.instvar2typevar[sym]
            tname = src.type_name(tv)
            mod.append(Node(key, tname, None))
            if tname not in carriers:  # first instance carries the class body
                carriers[tname] = key
                _emit_type(src, tv, "M5." + key, children)
        elif src.is_type(
            sym
        ):  # a type exposed at module level (BOARD, UserDisplay, ...)
            mod.append(Node(key, "class", None))
            _emit_type(src, sym, "M5." + key, children)
        elif sym.endswith("_obj"):  # module function
            mod.append(Node(key, "func", None))
        else:  # opaque module object (e.g. Widgets submodule)
            mod.append(Node(key, "module", None))
    children["M5"] = mod
    return children
