"""Check tuple return annotations in a generated stub or a built wheel."""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
from zipfile import ZipFile


def verify_source(source: str, firmware_ref: str | None = None) -> None:
    tree = ast.parse(source)
    if firmware_ref is not None:
        assert "Firmware: uiflow-micropython %s @ " % firmware_ref in (ast.get_docstring(tree) or ""), \
            "packaged stub does not match the selected firmware ref"
    expected = {
        "_IMU": {
            "getAccel": "tuple[float, float, float]",
            "getGyro": "tuple[float, float, float]",
            "getMag": "tuple[float, float, float]",
        },
        "_Display": {"getCursor": "tuple[int, int]"},
        "UserDisplay": {"getCursor": "tuple[int, int]"},
        "_Touch": {
            "getTouchPointRaw": "tuple[int, int, int, int]",
            "getDetail": "tuple[int, int, int, int, bool, bool, bool, bool, bool, bool, bool]",
        },
    }
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    for cls, methods in expected.items():
        assert cls in classes, "missing class: %s" % cls
        found = {
            node.name: ast.unparse(node.returns) if node.returns else None
            for node in classes[cls].body if isinstance(node, ast.FunctionDef)
        }
        for name, annotation in methods.items():
            actual = found.get(name)
            assert actual == annotation, "%s.%s: expected %s, got %s" % (
                cls, name, annotation, actual,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--firmware-ref")
    args = parser.parse_args()
    path = args.path
    if path.suffix == ".whl":
        with ZipFile(path) as wheel:
            source = wheel.read("M5.pyi").decode("utf-8")
    else:
        source = path.read_text(encoding="utf-8")
    verify_source(source, args.firmware_ref)
    print("verified tuple annotations:", path)


if __name__ == "__main__":
    main()
