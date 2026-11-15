#!/usr/bin/env python3
"""Shaders de Yo-kai Watch 4 (contenedor HBH1) -> grupos para el harness SPIR-V (tools/maxwell/spirv_harness --batch).

Misma salida que games/p5r/tools/gsc_shaders.py (manifest.tsv, code_<sha1>.bin, ctrl_<sha1>.bin por grupo).

Regla de HBH1 (hipotesis de informe5, comprobada aqui archivo a archivo; lo que no la cumple se descarta y se cuenta):
  seccion 3 = [0x20 bytes de prefacio][codigo: magia 0x12345678 (grafico) o 0x12345679 (compute)][control: magia
  0x98761234, 0x880 bytes]. u32@control+0x704 = tamano del codigo. Se exige: una sola magia de control en la seccion 3,
  codigo en seccion+0x20 con magia valida, y 0 < tamano <= control - codigo. Si ademas tamano == control - codigo se anota
  como "exacto" (la hipotesis fuerte); si no, se sigue usando el tamano del campo, que es lo que el runtime hashea.

Uso:
  python hbh1_shaders.py --romfs RUTA/romfs --out RUTA/salida [--cpk data/nx/shader/shader.cpk] [--stats]
  python hbh1_shaders.py --selftest
"""
import argparse
import collections
import hashlib
import importlib.util
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
CTRL = 0x98761234
CODES = (0x12345678, 0x12345679)
HEADER = ("id\tstage\tcode_off\tcode_size\tctrl_off\tctrl_size\tprogram_start\tprogram_bytes\tconst_off\t"
          "const_size\tcode_sha1_16\tcode_file\tctrl_file\n")


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def _load(name, *cands):
    for p in cands:
        if os.path.isfile(p):
            spec = importlib.util.spec_from_file_location(name, p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    return None


def stage_of_default(d, p, c):
    return "unknown"


def parse(data):
    """(code, ctrl, info) o (None, None, motivo). code/ctrl son offsets absolutos."""
    if len(data) < 0x40 or data[:4] != b"HBH1":
        return None, None, "no HBH1"
    if u32(data, 4) != 0x40:
        return None, None, "cabecera != 0x40"
    secs = [struct.unpack_from("<II", data, 0x0c + 8 * i) for i in range(5)]
    s_off, s_size = secs[3]
    if s_off + s_size > len(data) or s_size < 0x20 + 0x880:
        return None, None, "seccion 3 fuera del archivo o pequena"
    sec = data[s_off:s_off + s_size]
    ctl, i = [], sec.find(struct.pack("<I", CTRL))
    while i != -1:
        ctl.append(i)
        i = sec.find(struct.pack("<I", CTRL), i + 1)
    if len(ctl) != 1:
        return None, None, f"{len(ctl)} magias de control"
    c = ctl[0]
    if c + 0x880 > len(sec):
        return None, None, "control cortado"
    if u32(sec, 0x20) not in CODES:
        return None, None, "sin magia de codigo en +0x20"
    size = u32(sec, c + 0x704)
    if not 0 < size <= c - 0x20:
        return None, None, "tamano de codigo fuera de rango"
    return s_off + 0x20, s_off + c, {"size": size, "exact": size == c - 0x20, "tail": len(sec) - (c + 0x880),
                                    "compute": u32(sec, 0x20) == 0x12345679}


def extract_file(group, name, data, gdir, seen, stage_of, rows):
    p, c, info = parse(data)
    if p is None:
        return info
    s = info["size"]
    code, ctrl = data[p:p + s], data[c:c + 0x880]
    h = hashlib.sha1(code).hexdigest()[:16]
    if h in seen:
        return "dup"
    seen.add(h)
    cf = f"ctrl_{hashlib.sha1(ctrl).hexdigest()[:16]}.bin"
    with open(os.path.join(gdir, f"code_{h}.bin"), "wb") as f:
        f.write(code)
    with open(os.path.join(gdir, cf), "wb") as f:
        f.write(ctrl)
    try:
        stage = "compute" if info["compute"] else stage_of(data, p, c)
    except KeyError:  # geometry/tessellation: exefs_shaders.stage_of solo conoce vertex y pixel
        stage = "other"
    rows.append(f"{group}/{name}\t{stage}\t{p:#x}\t{s:#x}\t{c:#x}\t{0x880:#x}\t{u32(data, c + 0x708):#x}\t"
                f"{u32(data, c + 0x6f8):#x}\t{u32(data, c + 0x700):#x}\t{u32(data, c + 0x6fc):#x}\t{h}\t"
                f"code_{h}.bin\t{cf}\n")
    return "exacto" if info["exact"] else "ok-no-exacto"


def run(files, out, stage_of, stats):
    """files: iterable de (grupo, nombre, bytes)."""
    seen, res, groups = set(), collections.Counter(), {}
    for group, name, data in files:
        gdir = os.path.join(out, group)
        os.makedirs(gdir, exist_ok=True)
        rows = groups.setdefault(group, [])
        res[extract_file(group, name, data, gdir, seen, stage_of, rows)] += 1
    for group, rows in groups.items():
        with open(os.path.join(out, group, "manifest.tsv"), "w", newline="\n") as m:
            m.write(HEADER)
            m.writelines(rows)
    if stats:
        print("resultado:", ", ".join(f"{k}: {v}" for k, v in sorted(res.items())), file=sys.stderr)
    return res


def selftest():
    import tempfile

    def make(code_size, trail=5, magic=0x12345678, ctrl_extra=0, nctrl=1):
        code = struct.pack("<I", magic) + bytes(range(1, 0x2c + 1)) + os.urandom(code_size - 0x30)
        ctrl = bytearray(0x880)
        struct.pack_into("<I", ctrl, 0, CTRL)
        struct.pack_into("<I", ctrl, 0x704, code_size)
        sec = bytes(0x20) + code + bytes(ctrl_extra) + bytes(ctrl) * nctrl + bytes(trail)
        hdr = bytearray(0x40)
        hdr[:4] = b"HBH1"
        struct.pack_into("<II", hdr, 4, 0x40, 0)
        off = 0x40
        for i, sz in enumerate((0x10, 0x10, 0x10, len(sec), 0x10)):
            struct.pack_into("<II", hdr, 0x0c + 8 * i, off, sz)
            off += sz
        return bytes(hdr) + bytes(0x30) + sec + bytes(0x10)

    with tempfile.TemporaryDirectory() as t:
        good = [("g", "a.fsb", make(0x100)), ("g", "b.csb", make(0x200, magic=0x12345679)),
                ("g", "c.vsb", make(0x180, ctrl_extra=8))]
        bad = [("g", "d", make(0x100, nctrl=2)), ("g", "e", b"HBH1" + bytes(0x100)), ("g", "f", make(0x100)[:0x200])]
        r = run(good + bad, t, stage_of_default, False)
        assert r["exacto"] == 2 and r["ok-no-exacto"] == 1, r
        assert r["2 magias de control"] == 1 and sum(r.values()) == 6, r
        rows = open(os.path.join(t, "g", "manifest.tsv")).read().splitlines()
        assert len(rows) == 4 and "compute" in rows[2], rows
        code = open(os.path.join(t, "g", rows[1].split("\t")[11]), "rb").read()
        assert len(code) == 0x100 and struct.unpack_from("<I", code)[0] == 0x12345678
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--romfs")
    ap.add_argument("--out")
    ap.add_argument("--cpk", default="data/nx/shader/shader.cpk")
    ap.add_argument("--loose", default="data/nx/shader")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.romfs and a.out):
        ap.error("hacen falta --romfs y --out")
    cpk = _load("cpk", os.path.join(HERE, "cpk.py"), os.path.join(ROOT, "games", "p5r", "tools", "cpk.py"))
    mx = _load("exefs_shaders", os.path.join(ROOT, "tools", "maxwell", "exefs_shaders.py"))
    stage_of = (lambda d, p, c: mx.stage_of(lambda o: u32(d, o), p, c)) if mx else stage_of_default

    def files():
        loose = os.path.join(a.romfs, *a.loose.split("/"))
        for fn in sorted(os.listdir(loose)) if os.path.isdir(loose) else []:
            fp = os.path.join(loose, fn)
            if os.path.isfile(fp) and not fn.lower().endswith(".cpk"):
                yield "loose", fn, open(fp, "rb").read()
        cp = os.path.join(a.romfs, *a.cpk.split("/"))
        if cpk and os.path.isfile(cp):
            c = cpk.Cpk(cp)
            try:
                for e in sorted(c.files, key=lambda e: e["path"]):
                    yield "shader_cpk", os.path.basename(e["path"]), c.read(e)
            finally:
                c.f.close()

    run(files(), a.out, stage_of, True)


if __name__ == "__main__":
    main()
