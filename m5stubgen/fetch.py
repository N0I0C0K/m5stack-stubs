"""
Download the M5Stack UIFlow2 firmware source needed for stub generation.

Sparse-checkout (blobless) of ``m5stack/uiflow-micropython`` at a given ref, then
copy just the files we parse into ``vendor/``:

* ``m5stack/components/M5Unified/mpy_m5*.cpp`` — the bindings (signatures)
* ``m5stack/cmodules/m5unified/*.c``           — the registration tables (structure)

No device, no manual vendoring. Requires ``git`` on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

REPO_URL = "https://github.com/m5stack/uiflow-micropython.git"
SPARSE_PATHS = [
    "m5stack/components/M5Unified",
    "m5stack/cmodules/m5unified",
]


def _run(cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True)


def fetch(ref: str, vendor_dir: str) -> str:
    """Clone *ref* sparsely and copy the parsed sources into *vendor_dir*.

    Returns the resolved commit sha (written to ``vendor/SOURCE.txt``).
    """
    bindings_dst = os.path.join(vendor_dir, "M5Unified")
    cmod_dst = os.path.join(vendor_dir, "cmodules")
    tmp = tempfile.mkdtemp(prefix="m5stubgen-")
    try:
        _run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                ref,
                "--filter=blob:none",
                "--sparse",
                REPO_URL,
                tmp,
            ]
        )
        _run(["git", "-C", tmp, "sparse-checkout", "set", *SPARSE_PATHS])
        sha = subprocess.run(
            ["git", "-C", tmp, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        src_bind = os.path.join(tmp, "m5stack", "components", "M5Unified")
        src_cmod = os.path.join(tmp, "m5stack", "cmodules", "m5unified")
        os.makedirs(bindings_dst, exist_ok=True)
        os.makedirs(cmod_dst, exist_ok=True)
        n_b = n_c = 0
        for fn in os.listdir(src_bind):
            if fn.startswith("mpy_m5") and fn.endswith((".cpp", ".h")):
                shutil.copy2(os.path.join(src_bind, fn), os.path.join(bindings_dst, fn))
                n_b += 1
        for fn in os.listdir(src_cmod):
            if fn.endswith((".c", ".h")):
                shutil.copy2(os.path.join(src_cmod, fn), os.path.join(cmod_dst, fn))
                n_c += 1

        with open(
            os.path.join(vendor_dir, "SOURCE.txt"), "w", encoding="utf-8", newline="\n"
        ) as fh:
            fh.write("repo: %s\nref: %s\ncommit: %s\n" % (REPO_URL, ref, sha))
        print(
            "fetched ref=%s commit=%s  (%d bindings, %d cmodules)"
            % (ref, sha[:10], n_b, n_c)
        )
        return sha
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def source_meta(vendor_dir: str):
    """Read vendor/SOURCE.txt -> {'firmware': '<ref> @ <commit>'} for the stub header."""
    path = os.path.join(vendor_dir, "SOURCE.txt")
    if not os.path.exists(path):
        return None
    info = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            k, _, v = line.strip().partition(":")
            info[k.strip()] = v.strip()
    ref = info.get("ref", "?")
    commit = info.get("commit", "")[:10]
    return {"firmware": "uiflow-micropython %s @ %s" % (ref, commit)}
