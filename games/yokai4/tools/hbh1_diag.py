#!/usr/bin/env python3
"""Diagnostico de lo que hbh1_shaders.py descarta (solo metadatos: posiciones, tamanos, extensiones; no vuelca codigo).

Uso (cpk.py en la misma carpeta):  python hbh1_diag.py --romfs RUTA/romfs [--out informe6.txt]
"""
import argparse
import collections
import importlib.util
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
LINES = []


def out(*a):
    s = " ".join(str(x) for x in a)
    LINES.append(s)
    print(s)


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def find(d, v):
    n, r, i = struct.pack("<I", v), [], 0
    i = d.find(n)
    while i != -1:
        r.append(i)
        i = d.find(n, i + 1)
    return r


def load_cpk():
    for p in (os.path.join(HERE, "cpk.py"), os.path.join(HERE, "..", "..", "p5r", "tools", "cpk.py")):
        if os.path.isfile(p):
            spec = importlib.util.spec_from_file_location("cpk", p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--romfs", required=True)
    ap.add_argument("--out", default="informe6.txt")
    a = ap.parse_args()
    base = os.path.join(a.romfs, "data", "nx", "shader")
    files = []
    for fn in sorted(os.listdir(base)):
        fp = os.path.join(base, fn)
        if os.path.isfile(fp) and not fn.lower().endswith(".cpk"):
            files.append((fn, open(fp, "rb").read()))
    cpk = load_cpk()
    c = cpk.Cpk(os.path.join(base, "shader.cpk"))
    try:
        for e in sorted(c.files, key=lambda e: e["path"]):
            files.append((os.path.basename(e["path"]), c.read(e)))
    finally:
        c.f.close()

    nohb = collections.Counter()
    for n, d in files:
        if d[:4] != b"HBH1":
            nohb[(os.path.splitext(n)[1].lower(), d[:4].hex())] += 1
    out("no HBH1 por (extension, primeros 4 bytes):", ", ".join(f"{k} ({v})" for k, v in nohb.most_common(8)))

    out("")
    out("Descartados con HBH1 pero sin magia de codigo en sec3+0x20 (todos):")
    for n, d in files:
        if d[:4] != b"HBH1" or len(d) < 0x40:
            continue
        secs = [struct.unpack_from("<II", d, 0x0c + 8 * i) for i in range(5)]
        so, sz = secs[3]
        sec = d[so:so + sz]
        if len(sec) >= 0x24 and u32(sec, 0x20) in (0x12345678, 0x12345679):
            continue
        ctl, cod8, cod9 = find(sec, 0x98761234), find(sec, 0x12345678), find(sec, 0x12345679)
        field = [u32(sec, c + 0x704) for c in ctl if c + 0x708 <= len(sec)]
        out(f"  {n}: sec3 tam {sz:#x}; control en {[hex(x) for x in ctl]}; 0x12345678 en {[hex(x) for x in cod8]}; "
            f"0x12345679 en {[hex(x) for x in cod9]}; u32@ctl+0x704 {[hex(x) for x in field]}; "
            f"primeros 0x30 de sec3: {sec[:0x30].hex(' ')}")
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")


if __name__ == "__main__":
    main()
