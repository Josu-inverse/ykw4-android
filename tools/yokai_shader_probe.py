#!/usr/bin/env python3
"""Estructura de los shaders de Yo-kai Watch 4 (contenedor "HBH1") en tu propio RomFS. Solo la libreria estandar.

Lo que ya se sabe (informe3): .csb (compute, sueltos en data/nx/shader), .fsb/.vsb/.fxbin (dentro de
data/nx/shader/shader.cpk). Los .csb y .fsb empiezan por "HBH1", 0x40, 0 y cinco pares (offset, tamano) desde 0x0c.

Que averigua este script, sin volcar codigo:
  * si el encadenado de secciones de HBH1 es siempre el mismo (5 secciones consecutivas);
  * si dentro hay bloques NVN estandar: la seccion "control" (magia 0x98761234) y el bloque de codigo
    (magia 0x12345678), donde estan, y si control+0x704 == tamano del codigo, como en los GSC de P5R
    (games/p5r/tools/gsc_shaders.py). Si lo cumplen, el extractor de P5R se reutiliza casi tal cual;
  * que hay en las secciones pequenas (primeros 16 bytes, y texto si lo es: nombres, no codigo).

Uso (cpk.py tiene que estar en la misma carpeta):
    python yokai_shader_probe.py --romfs RUTA/romfs [--limit 600] [--out informe5.txt]
"""
import argparse
import collections
import importlib.util
import os
import re
import struct
import sys

CTRL_MAGIC = 0x98761234
CODE_MAGIC = 0x12345678
LINES = []


def out(*parts):
    line = " ".join(str(p) for p in parts)
    LINES.append(line)
    print(line)


def title(text):
    out("")
    out("=" * 78)
    out(text)
    out("=" * 78)


def load_cpk_tool():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (here, os.path.join(here, "..", "games", "p5r", "tools")):
        p = os.path.join(cand, "cpk.py")
        if os.path.isfile(p):
            spec = importlib.util.spec_from_file_location("cpk_tool", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def find_u32(data, value):
    needle = struct.pack("<I", value)
    found, i = [], data.find(needle)
    while i != -1:
        found.append(i)
        i = data.find(needle, i + 1)
    return found


def parse_hbh1(data):
    """(tamano de cabecera, [(offset, tamano), ...]) o None si no es HBH1."""
    if len(data) < 0x40 or data[:4] != b"HBH1":
        return None
    hdr = struct.unpack_from("<I", data, 4)[0]
    secs = []
    for i in range(6):
        pos = 0x0c + 8 * i
        if pos + 8 > min(hdr, len(data)):
            break
        off, size = struct.unpack_from("<II", data, pos)
        if off == 0 and size == 0:
            break
        secs.append((off, size))
    return hdr, secs


def where(secs, pos):
    for i, (off, size) in enumerate(secs):
        if off <= pos < off + size:
            return i, pos - off
    return -1, pos


def printable_text(b):
    t = b.split(b"\0")[0]
    if len(t) >= 4 and all(32 <= c < 127 for c in t):
        return t.decode("ascii")
    return None


def fmt(counter, n=5, hexa=False):
    """'valor (N archivos), ...': sin pegar el contador al valor, para que '0x40x5' no se lea como un hexadecimal."""
    return ", ".join(f"{('0x%x' % k) if hexa and isinstance(k, int) else k} ({v})" for k, v in counter.most_common(n))


def analyse(files, examples):
    """files: lista de (nombre, bytes). Agrupa por extension e imprime las conclusiones."""
    by_ext = collections.defaultdict(list)
    for name, data in files:
        by_ext[os.path.splitext(name)[1].lower() or "(sin ext)"].append((name, data))
    for ext, group in sorted(by_ext.items()):
        title(f"Extension {ext}: {len(group)} archivos analizados")
        magics = collections.Counter(d[:4] for _, d in group)
        out("  primeros 4 bytes (entre parentesis, cuantos archivos): " + fmt(magics, 6))
        hb = [(n, d, parse_hbh1(d)) for n, d in group]
        hb = [(n, d, p) for n, d, p in hb if p]
        if not hb:
            for n, d in group[:examples]:
                words = struct.unpack_from("<8I", d.ljust(32, b"\0"), 0)
                out(f"  {n} ({len(d)} B): u32 " + " ".join(f"{w:08x}" for w in words))
            continue
        out(f"  HBH1: {len(hb)}")
        nsecs = collections.Counter(len(p[1]) for _, _, p in hb)
        out("  numero de secciones: " + fmt(nsecs))
        chained = sum(1 for _, _, (h, s) in hb if all(s[i + 1][0] == s[i][0] + s[i][1] for i in range(len(s) - 1)))
        inside = sum(1 for _, d, (h, s) in hb if s and s[-1][0] + s[-1][1] <= len(d))
        out(f"  secciones encadenadas (cada una empieza donde acaba la anterior): {chained}/{len(hb)};"
            f" dentro del archivo: {inside}/{len(hb)}")
        hdrs = collections.Counter(h for _, _, (h, s) in hb)
        out("  tamano de cabecera (u32 en +4): " + fmt(hdrs, 4, hexa=True))
        for i in range(5):
            sizes = collections.Counter(s[i][1] for _, _, (h, s) in hb if len(s) > i)
            if sizes:
                out(f"  seccion {i}: tamanos mas comunes: " + fmt(sizes, 5, hexa=True))

        ctrl_pos, code_pos, delta = collections.Counter(), collections.Counter(), collections.Counter()
        both = no_ctrl = no_code = 0
        for n, d, (h, s) in hb:
            ctl, cod = find_u32(d, CTRL_MAGIC), find_u32(d, CODE_MAGIC)
            for p in ctl:
                ctrl_pos[where(s, p)] += 1
            for p in cod:
                code_pos[where(s, p)] += 1
            no_ctrl += not ctl
            no_code += not cod
            if len(ctl) == 1 and len(cod) == 1:
                both += 1
                c, k = ctl[0], cod[0]
                si, _ = where(s, k)
                end = s[si][0] + s[si][1] if si >= 0 else len(d)
                field = struct.unpack_from("<I", d, c + 0x704)[0] if c + 0x708 <= len(d) else None
                delta["control+0x704 - (fin de seccion - codigo)" if field is None else field - (end - k)] += 1
        out(f"  magia de control 0x{CTRL_MAGIC:08x}: ausente en {no_ctrl}/{len(hb)}; posiciones "
            f"(n de seccion, offset decimal dentro de ella; entre parentesis, archivos): " + fmt(ctrl_pos))
        out(f"  magia de codigo  0x{CODE_MAGIC:08x}: ausente en {no_code}/{len(hb)}; posiciones "
            f"(n de seccion, offset decimal dentro de ella; entre parentesis, archivos): " + fmt(code_pos))
        out(f"  archivos con exactamente un control y un codigo: {both}. Valor de u32@control+0x704 MENOS los bytes "
            f"que hay desde la magia de codigo hasta el fin de su seccion (0 = coinciden; entre parentesis, "
            f"archivos): " + fmt(delta))

        texts = collections.Counter()
        for n, d, (h, s) in hb:
            if len(s) == 5:
                t = printable_text(d[s[4][0]:s[4][0] + s[4][1]])
                if t:
                    texts[t[:60]] += 1
        if texts:
            out(f"  seccion 4 como texto ({sum(texts.values())} archivos), ejemplos: "
                + " | ".join(t for t, _ in texts.most_common(4)))
        for n, d, (h, s) in hb[:examples]:
            out(f"  ejemplo {n} ({len(d)} B): secciones " + " ".join(f"[0x{o:x}+0x{z:x}]" for o, z in s))
            for i, (o, z) in enumerate(s):
                if i != 3:  # la seccion 3 (la grande) puede ser codigo: no se vuelca
                    out(f"      seccion {i}: " + d[o:o + 16].hex(" "))


def main():
    ap = argparse.ArgumentParser(description="Estructura HBH1 de los shaders de tu propio RomFS")
    ap.add_argument("--romfs", required=True)
    ap.add_argument("--shader-cpk", help="ruta relativa al RomFS (por defecto data/nx/shader/shader.cpk)")
    ap.add_argument("--shader-dir", default="data/nx/shader", help="carpeta de shaders sueltos")
    ap.add_argument("--limit", type=int, default=600, help="maximo de archivos del CPK (repartidos)")
    ap.add_argument("--examples", type=int, default=2, help="ejemplos por extension")
    ap.add_argument("--out", default="yokai_shader_report.txt")
    args = ap.parse_args()

    files = []
    loose = os.path.join(args.romfs, *args.shader_dir.split("/"))
    if os.path.isdir(loose):
        for fn in sorted(os.listdir(loose)):
            full = os.path.join(loose, fn)
            if os.path.isfile(full) and not fn.lower().endswith(".cpk"):  # shader.cpk se lee aparte, por dentro
                with open(full, "rb") as f:
                    files.append((f"[suelto] {fn}", f.read()))
    out(f"yokai_shader_probe: {len(files)} archivos sueltos en {args.shader_dir}")

    cpk_rel = args.shader_cpk or args.shader_dir + "/shader.cpk"
    cpk_path = os.path.join(args.romfs, *cpk_rel.split("/"))
    cpk_tool = load_cpk_tool()
    if not os.path.isfile(cpk_path):
        out(f"  no existe {cpk_rel}")
    elif cpk_tool is None:
        out("  falta cpk.py junto a este script")
    else:
        c = cpk_tool.Cpk(cpk_path)
        try:
            entries = sorted(c.files, key=lambda e: e["path"])
            step = max(1, len(entries) // args.limit) if args.limit else 1
            picked = entries[::step][:args.limit] if args.limit else entries
            out(f"  {cpk_rel}: {len(entries)} archivos, se leen {len(picked)} (1 de cada {step})")
            for e in picked:
                files.append((os.path.basename(e["path"]), c.read(e)))
        finally:
            c.f.close()

    if files:
        analyse([(n.replace("[suelto] ", ""), d) for n, d in files], args.examples)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print(f"\nInforme guardado en {args.out}. Revisalo y pega su contenido en el chat.")


if __name__ == "__main__":
    main()
