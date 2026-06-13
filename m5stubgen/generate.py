"""
Combine the device-dump structure with the C-binding signatures into ``M5.pyi``.

* **Structure & constant values** come from the device snapshot (:mod:`dump`).
* **Parameter & return signatures** come from the C bindings (:mod:`bindings`).

The result is a single ``M5.pyi`` where instance objects (``Lcd``, ``BtnA`` …)
are typed against generated classes whose methods carry real signatures.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import bindings
from .bindings import PREFIX_TO_TYPE, Signature, render_method
from .dump import Node

_SCALAR = {"int", "float", "bool", "str"}
_PYTYPE = {"int": "int", "bool": "int", "float": "float", "str": "str"}
# M5 instance-type name -> binding-file suffix (inverse of PREFIX_TO_TYPE)
_TYPE_TO_PREFIX = {v: k for k, v in PREFIX_TO_TYPE.items()}


class Coverage:
    def __init__(self) -> None:
        self.real = 0
        self.fallback = 0

    def note(self, sig: Signature) -> None:
        if sig and sig[0] is not None:
            self.real += 1
        else:
            self.fallback += 1

    def __str__(self) -> str:
        total = self.real + self.fallback
        pct = (100.0 * self.real / total) if total else 0.0
        return "%d/%d methods with real signatures (%.0f%%)" % (self.real, total, pct)


def _const_line(node: Node, indent: str) -> str:
    pytype = _PYTYPE.get(node.kind, "Any")
    if node.value is not None and node.kind in _SCALAR:
        return "%s%s: %s = %s" % (indent, node.attr, pytype, node.value)
    return "%s%s: %s" % (indent, node.attr, pytype)


def _emit_members(
    path: str,
    indent: str,
    sigmap: Dict[str, Signature],
    children: Dict[str, List[Node]],
    cov: Coverage,
) -> List[str]:
    out: List[str] = []
    kids = children.get(path, [])
    if not kids:
        out.append(indent + "...")
        return out
    for node in sorted(kids, key=lambda n: n.attr):
        if (
            node.kind == "class"
        ):  # nested namespace of constants (BOARD, COLOR, FONTS, ...)
            out.append(indent + "class " + node.attr + ":")
            out.extend(
                _emit_members(
                    path + "." + node.attr, indent + "    ", {}, children, cov
                )
            )
        elif node.kind == "func":
            sig = sigmap.get(node.attr)  # None if absent OR explicitly variadic
            cov.note(sig)
            out.append(render_method(node.attr, sig, indent=indent))
        elif node.kind in _SCALAR:
            out.append(_const_line(node, indent))
        else:  # FONTS entries, opaque objects, ...
            out.append(indent + node.attr + ": Any")
    return out


def _emit_class(
    class_name: str,
    path: str,
    sigmap: Dict[str, Signature],
    children: Dict[str, List[Node]],
    cov: Coverage,
) -> List[str]:
    """Emit a class: nested constant classes/consts from the *structure*, plus the
    methods from the *bindings* (authoritative — every binding function of a type's
    prefix is one of its methods, regardless of how the C method table is built)."""
    out = ["class %s:" % class_name]
    body: List[str] = []
    consts: List[Node] = []
    nested: List[str] = []
    struct_methods: List[str] = []
    for node in children.get(path, []):
        if (
            node.kind == "class"
        ):  # nested constant namespace (FONTS, COLOR, CB_TYPE, ...)
            nested.append(node.attr)
        elif node.kind in _SCALAR:
            consts.append(node)
        elif (
            node.kind == "func"
        ):  # method known to the structure but maybe not the bindings
            struct_methods.append(node.attr)
    for node in sorted(
        consts, key=lambda n: n.attr
    ):  # deterministic order: consts, nested, methods
        body.append(_const_line(node, "    "))
    for name in sorted(nested):
        body.append("    class %s:" % name)
        body.extend(_emit_members(path + "." + name, "        ", {}, children, cov))
    # Methods: bindings are authoritative for signatures; keep structure-only methods
    # (e.g. read/write/close) as *args fallbacks so nothing is dropped.
    for mname in sorted(dict.fromkeys(list(sigmap.keys()) + struct_methods)):
        sig = sigmap.get(mname)
        cov.note(sig)
        body.append(render_method(mname, sig, indent="    "))
    out.extend(body or ["    ..."])
    return out


def generate(
    children: Dict[str, List[Node]],
    sigs: Dict[str, Dict[str, Signature]],
    meta: Optional[Dict[str, str]] = None,
) -> Tuple[str, "Coverage"]:
    """Return ``(M5.pyi source text, coverage)``."""
    cov = Coverage()
    m5 = children.get("M5", [])

    mod_funcs: List[str] = []
    mod_consts: List[Node] = []
    mod_classes: List[str] = []
    mod_modules: List[str] = []
    instances: List[Tuple[str, Optional[str]]] = []  # (attr, type-name|None)
    type_source: Dict[str, str] = {}

    for node in m5:
        if node.kind == "func":
            mod_funcs.append(node.attr)
        elif node.kind == "class":
            mod_classes.append(node.attr)
        elif node.kind == "module":
            mod_modules.append(node.attr)
        elif node.kind in _SCALAR:
            mod_consts.append(node)
        elif node.kind == "NoneType":
            instances.append((node.attr, None))
        else:  # instance of some M5 type (Display, Button, ...)
            instances.append((node.attr, node.kind))
            p = "M5." + node.attr
            if p in children:  # we introspected this one -> use as the class body
                type_source[node.kind] = p
            else:
                type_source.setdefault(node.kind, p)

    fw = (meta or {}).get("firmware", "unknown firmware")
    L: List[str] = ['"""']
    L += [
        "Type stubs for the M5Stack UIFlow2 firmware ``M5`` module.",
        "",
        "AUTO-GENERATED by m5stubgen. Do not edit by hand.",
        "  * structure & constant values: device introspection snapshot",
        "  * parameter & return signatures: M5Unified C bindings (mpy_m5*.cpp)",
        "Firmware: %s" % fw,
        '"""',
        "from typing import Any",
        "",
        "",
    ]

    for tname in sorted(type_source):
        sm = sigs.get(_TYPE_TO_PREFIX.get(tname, ""), {})
        L.extend(_emit_class("_" + tname, type_source[tname], sm, children, cov))
        L.append("")

    for cname in sorted(mod_classes):
        sm = sigs.get("gfx", {}) if cname == "UserDisplay" else {}
        L.extend(_emit_class(cname, "M5." + cname, sm, children, cov))
        L.append("")

    L.append("")
    for attr, tname in sorted(instances):
        L.append(attr + ((": _" + tname) if tname else ": Any"))
    for attr in sorted(mod_modules):
        L.append(attr + ": Any")
    for node in sorted(mod_consts, key=lambda n: n.attr):
        L.append(_const_line(node, ""))
    L.append("")

    unified = sigs.get("unified", {})
    for attr in sorted(mod_funcs):
        sig = unified.get(attr)
        cov.note(sig)
        line = render_method(attr, sig, indent="")
        L.append(line.replace("(self, ", "(", 1).replace("(self)", "()", 1))
    L.append("")
    L.append("")
    L.append("def __getattr__(name: str) -> Any: ...")
    L.append("")

    return "\n".join(L), cov


def from_device(dump_path: str, bindings_dir: str) -> Tuple[str, Coverage]:
    """Generate from a device introspection snapshot + C-binding signatures."""
    from . import dump as _dump

    children = _dump.parse(dump_path)
    meta = _dump.firmware_meta(dump_path)
    sigs = bindings.parse_dir(bindings_dir)
    return generate(children, sigs, meta)


def from_c(
    cmodules_dir: str,
    unified_cpp: str,
    bindings_dir: str,
    meta: Optional[Dict[str, str]] = None,
) -> Tuple[str, Coverage]:
    """Generate fully from C source (structure + constants + signatures). No device."""
    from . import structure

    children = structure.build(cmodules_dir, unified_cpp)
    sigs = bindings.parse_dir(bindings_dir)
    return generate(children, sigs, meta)
