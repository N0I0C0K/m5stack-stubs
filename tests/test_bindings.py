"""Regression test for the C-binding return-type heuristic (``bindings._ret_type``).

No pytest dependency — run directly:  ``uv run python tests/test_bindings.py``

The subtle, easy-to-break property: a function that builds and returns a tuple
also *contains* its element constructors (``mp_obj_new_float`` …). The naive
substring heuristic matched ``mp_obj_new_float(`` first and typed
``imu_getAccel`` as ``-> float`` even though it returns a 3-tuple. Containers
must be detected before the scalar element constructors, and the per-element
type/arity must be recovered from the ``mp_obj_t tuple[N] = {...}`` initializer.
"""
from pathlib import Path

from m5stubgen.bindings import _ret_type, parse_file

# Verbatim bodies from vendor/M5Unified/mpy_m5imu.cpp, mpy_m5gfx.cpp and
# mpy_m5touch.cpp (the text between the function's opening `{` and the next).
_IMU_GET_ACCEL = """
        float x = 0.0f,y = 0.0f,z = 0.0f;
        getImu(self)->getAccel(&x, &y, &z);
        mp_obj_t tuple[3] = {
            mp_obj_new_float(x),
            mp_obj_new_float(y),
            mp_obj_new_float(z),
        };
        return mp_obj_new_tuple(3, tuple);
    }
"""

_GFX_GET_CURSOR = """
    auto gfx = getGfx(&self);
    mp_obj_t tuple[2] = { mp_obj_new_int(gfx->getCursorX())
                          , mp_obj_new_int(gfx->getCursorY())};
    return mp_obj_new_tuple(2, tuple);
}
"""

_TOUCH_GET_TOUCH_POINT_RAW = """
        m5gfx::touch_point_t point = getTouch(&pos_args[0])->getTouchPointRaw(args[ARG_i].u_int);
        mp_obj_t tuple[4] = { mp_obj_new_int(point.x)
                              , mp_obj_new_int(point.y)
                              , mp_obj_new_int(point.size)
                              , mp_obj_new_int(point.id)};
        return mp_obj_new_tuple(4, tuple);
    }
"""

# The mixed-type case: 4 ints then 7 bools. This is what actually locks down
# element ordering — an all-float test would pass even if ordering were dropped.
_TOUCH_GET_DETAIL = """
        auto detail = getTouch(&pos_args[0])->getDetail(args[ARG_i].u_int);
        mp_obj_t tuple[11] = {
            mp_obj_new_int(detail.deltaX()), // 0
            mp_obj_new_int(detail.deltaY()),
            mp_obj_new_int(detail.distanceX()),
            mp_obj_new_int(detail.distanceY()),
            mp_obj_new_bool(detail.isPressed()),
            mp_obj_new_bool(detail.wasPressed()), // 5
            mp_obj_new_bool(detail.wasClicked()),
            mp_obj_new_bool(detail.isReleased()),
            mp_obj_new_bool(detail.wasReleased()),
            mp_obj_new_bool(detail.isHolding()),
            mp_obj_new_bool(detail.wasHold()), // 10
        };
        return mp_obj_new_tuple(11, tuple);
    }
"""

# Scalar bodies must stay classified exactly as before — the fix must not regress.
_IMU_GET_TYPE = "        return mp_obj_new_int(getImu(self)->getType());\n"
_IMU_IS_ENABLED = "        return mp_obj_new_bool(getImu(self)->isEnabled());\n"
_GFX_POWER_OFF = "    auto gfx = getGfx(&self);\n    gfx->powerSaveOff();\n    return mp_const_none;\n"


def test_imu_accel_is_float_triple() -> None:
    # The headline bug: must NOT be `float`.
    assert _ret_type(_IMU_GET_ACCEL) == "tuple[float, float, float]"


def test_int_tuples() -> None:
    assert _ret_type(_GFX_GET_CURSOR) == "tuple[int, int]"
    assert _ret_type(_TOUCH_GET_TOUCH_POINT_RAW) == "tuple[int, int, int, int]"


def test_mixed_tuple_preserves_element_order() -> None:
    assert (
        _ret_type(_TOUCH_GET_DETAIL)
        == "tuple[int, int, int, int, bool, bool, bool, bool, bool, bool, bool]"
    )


def test_scalars_unregressed() -> None:
    assert _ret_type(_IMU_GET_TYPE) == "int"
    assert _ret_type(_IMU_IS_ENABLED) == "bool"
    assert _ret_type(_GFX_POWER_OFF) == "None"
    assert _ret_type('return mp_obj_new_str("hi", 2);') == "str"


def test_tuple_arity_mismatch_falls_back_to_bare_tuple() -> None:
    # Defensive: if the declared arity and parsed elements disagree, don't lie
    # about the shape — emit a bare `tuple` rather than a wrong fixed length.
    body = """
        mp_obj_t tuple[3] = { mp_obj_new_int(a), mp_obj_new_int(b) };
        return mp_obj_new_tuple(3, tuple);
    """
    assert _ret_type(body) == "tuple"


def test_returned_array_is_used() -> None:
    body = """
        mp_obj_t other[2] = {mp_obj_new_int(1), mp_obj_new_int(2)};
        mp_obj_t result[2] = {mp_obj_new_float(x), mp_obj_new_float(y)};
        return mp_obj_new_tuple(2, result);
    """
    assert _ret_type(body) == "tuple[float, float]"


def test_unknown_elements_and_nested_constructors_fall_back() -> None:
    bodies = [
        "mp_obj_t t[2] = {unknown, mp_obj_new_float(x)};",
        "mp_obj_t t[2] = {mp_obj_new_float(mp_obj_new_float(x))};",
        "mp_obj_t t[2] = {mp_obj_new_bytes(x, 2), mp_obj_new_float(y)};",
        "mp_obj_t t[2] = {mp_obj_new_int(x) + mp_obj_new_float(y)};",
    ]
    for body in bodies:
        assert _ret_type(body + "return mp_obj_new_tuple(2, t);") == "tuple"
        assert _ret_type(body + "return mp_obj_new_list(2, t);") == "list"


def test_nested_arguments_and_string_commas() -> None:
    body = """
        mp_obj_t t[2] = {mp_obj_new_str("a,b", 3), mp_obj_new_int(f(x, y))};
        return mp_obj_new_tuple(2, t);
    """
    assert _ret_type(body) == "tuple[str, int]"


def test_list_types() -> None:
    body = "mp_obj_t items[2] = {mp_obj_new_float(x), mp_obj_new_float(y)};"
    assert _ret_type(body + "return mp_obj_new_list(2, items);") == "list[float]"
    body = "mp_obj_t items[2] = {mp_obj_new_int(x), mp_obj_new_float(y)};"
    assert _ret_type(body + "return mp_obj_new_list(2, items);") == "list[float | int]"
    assert _ret_type(body + "return mp_obj_new_list(1, items);") == "list"


def test_generic_containers() -> None:
    for kind in ("tuple", "list"):
        assert _ret_type("return mp_obj_new_%s(n, items);" % kind) == kind
        assert _ret_type("return mp_obj_new_%s(3, items);" % kind) == kind
        assert _ret_type("return mp_obj_new_%s(0, NULL);" % kind) == kind


def test_array_size_and_return_count_must_agree() -> None:
    body = "mp_obj_t t[3] = {mp_obj_new_float(x), mp_obj_new_float(y)};"
    assert _ret_type(body + "return mp_obj_new_tuple(2, t);") == "tuple"
    assert _ret_type(body + "return mp_obj_new_list(2, t);") == "list"


def test_constructor_whitespace_and_comments() -> None:
    body = """
        // mp_obj_new_list(2, other) is not the return value.
        mp_obj_t t[2] = {mp_obj_new_float (x), /* mp_obj_new_int(0), */
                        mp_obj_new_float(y)};
        return mp_obj_new_tuple (2, t);
    """
    assert _ret_type(body) == "tuple[float, float]"
    assert _ret_type('return mp_obj_new_str("mp_obj_new_tuple(0, NULL)", 25);') == "str"


def test_multiple_returns_fall_back_to_generic() -> None:
    body = """
        mp_obj_t t[1] = {mp_obj_new_float(x)};
        if (flag) { return mp_obj_new_tuple(1, t); }
        return mp_obj_new_tuple(0, NULL);
    """
    assert _ret_type(body) == "tuple"


def test_unsized_and_empty_array_initializers() -> None:
    assert _ret_type("mp_obj_t t[] = {mp_obj_new_float(x)}; "
                     "return mp_obj_new_tuple(1, t);") == "tuple[float]"
    assert _ret_type("mp_obj_t t[] = {}; return mp_obj_new_tuple(0, t);") == "tuple[()]"


def test_vendor_bindings() -> None:
    root = Path(__file__).resolve().parents[1] / "vendor" / "M5Unified"
    if not root.is_dir():
        print("skip vendor integration: run m5stubgen fetch first")
        return
    imu = parse_file(str(root / "mpy_m5imu.cpp"))
    for name in ("getAccel", "getGyro", "getMag"):
        sig = imu[name]
        assert sig is not None and sig[1] == "tuple[float, float, float]"
    for filename, method, expected in (
        ("mpy_m5gfx.cpp", "getCursor", "tuple[int, int]"),
        ("mpy_m5touch.cpp", "getTouchPointRaw", "tuple[int, int, int, int]"),
        ("mpy_m5touch.cpp", "getDetail",
         "tuple[int, int, int, int, bool, bool, bool, bool, bool, bool, bool]"),
    ):
        sig = parse_file(str(root / filename))[method]
        assert sig is not None and sig[1] == expected


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all binding tests passed")
