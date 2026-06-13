"""
Parse a device introspection snapshot (``data/m5_dump.txt``).

The snapshot is produced by :mod:`m5stubgen.introspect_device` running on a real
board (``dir()`` walk over the ``M5`` C module). It is the authoritative source
for the parts of the API that are **not** in the C source: which objects the
``M5`` module exposes (``Lcd``, ``BtnA``, ...), the class structure, and the
**values** of constants (``BOARD.M5CardputerADV = 24``, ``COLOR.*``, ...).

Each line is TAB-separated::

    <path>\\t<attr>\\t<kind>[\\t<value>]

e.g. ``M5.BOARD\\tM5CardputerADV\\tint\\t24``.
"""
from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional, Tuple

BEGIN = "###BEGIN_DUMP###"
END = "###END_DUMP###"


class Node(NamedTuple):
    attr: str
    kind: str  # class | func | module | int | float | bool | str | <typename>
    value: Optional[str]  # repr of the value for scalar constants, else None


def parse(path: str) -> Dict[str, List[Node]]:
    """Parse the snapshot -> ``{path: [Node, ...]}`` (children keyed by parent path)."""
    children: Dict[str, List[Node]] = {}
    started = False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            s = line.strip()
            if s == BEGIN:
                started = True
                continue
            if s == END:
                break
            if not started or not line:
                continue
            p = line.split("\t")
            if len(p) < 3:
                continue
            parent, attr, kind = p[0], p[1], p[2]
            value = p[3] if len(p) > 3 else None
            children.setdefault(parent, []).append(Node(attr, kind, value))
    return children


def firmware_meta(path: str) -> Dict[str, str]:
    """Read optional ``# key: value`` header comments above the dump markers."""
    meta: Dict[str, str] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            s = raw.strip()
            if s == BEGIN:
                break
            if s.startswith("#") and ":" in s:
                k, _, v = s[1:].partition(":")
                meta[k.strip()] = v.strip()
    return meta
