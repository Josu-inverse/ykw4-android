#!/usr/bin/env python3
"""Sondeo de tu propia copia de un juego de Switch (ExeFS + RomFS) para preparar un port.

Solo usa la libreria estandar de Python 3.8+. No sube nada a ningun sitio: escribe un informe de texto que tu
revisas antes de compartirlo. El informe NO contiene claves, ni codigo, ni datos del juego: solo metadatos
(build ID, tamanos, nombres de funciones importadas, listado de archivos, cabeceras de 4 bytes).

Uso:
    python yokai_probe.py --exefs RUTA/exefs --romfs RUTA/romfs [--out informe.txt]

  --exefs  carpeta con main, sdk, rtld, subsdk*, main.npdm (extraida con nstool de tu propio dump)
  --romfs  carpeta con el RomFS extraido (opcional, pero hace falta para saber donde estan los shaders)

Opciones para una segunda pasada (todas escriben solo nombres, o 128 bytes de cabecera si lo pides):
  --symbols-out ARCHIVO   nombres de las funciones que importa el main (para compararlas con el runtime)
  --find REGEX            archivos del RomFS cuya ruta coincide
  --head RUTA             primeros 128 bytes de un archivo del RomFS (repetible)
  --cpk-top N             contenido por extension de los N CPK mas grandes
  --cpk-grep REGEX        nombres dentro de TODOS los CPK que coinciden (necesita cpk.py junto a este script)
  --cpk-head REGEX        primeros 128 bytes de hasta 3 archivos de CPK que coinciden

El informe usa rutas relativas: no incluye tu nombre de usuario ni carpetas de tu equipo.
"""
import argparse
import collections
import hashlib
import os
import re
import struct
import sys

try:  # camino rapido si lz4 esta instalado; si no, se usa el descompresor en Python puro
    import lz4.block as _lz4
except Exception:  # pragma: no cover
    _lz4 = None

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


# --------------------------------------------------------------------------------------------------------------
# LZ4 (bloque crudo, como lo usa el NSO)
# --------------------------------------------------------------------------------------------------------------
def lz4_block(src, out_size):
    if _lz4 is not None:
        return _lz4.decompress(bytes(src), uncompressed_size=out_size)
    dst = bytearray()
    ip, n = 0, len(src)
    while ip < n:
        token = src[ip]
        ip += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[ip]
                ip += 1
                lit += b
                if b != 255:
                    break
        dst += src[ip:ip + lit]
        ip += lit
        if ip >= n:
            break
        off = src[ip] | (src[ip + 1] << 8)
        ip += 2
        if off == 0 or off > len(dst):
            raise ValueError("datos LZ4 invalidos")
        ml = token & 15
        if ml == 15:
            while True:
                b = src[ip]
                ip += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(dst) - off
        if off >= ml:
            dst += dst[start:start + ml]
        else:  # copia solapada: el patron (de `off` bytes) se repite
            pattern = bytes(dst[start:start + off])
            dst += (pattern * (ml // off + 1))[:ml]
    if len(dst) != out_size:
        raise ValueError("tamano LZ4 inesperado")
    return bytes(dst)


# --------------------------------------------------------------------------------------------------------------
# NSO
# --------------------------------------------------------------------------------------------------------------
class Nso:
    pass


def parse_nso(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:4] != b"NSO0":
        raise ValueError("no es un NSO")
    nso = Nso()
    nso.file_size = len(raw)
    nso.sha256 = hashlib.sha256(raw).hexdigest()
    flags = struct.unpack_from("<I", raw, 0x0C)[0]
    nso.build_id = raw[0x40:0x60]
    nso.bss_size = struct.unpack_from("<I", raw, 0x3C)[0]
    nso.segs = []
    names = ("text", "ro", "data")
    segs = []
    for i in range(3):
        file_off, mem_off, size = struct.unpack_from("<III", raw, 0x10 + i * 0x10)
        comp = struct.unpack_from("<I", raw, 0x60 + i * 4)[0]
        blob = raw[file_off:file_off + comp]
        compressed = bool(flags & (1 << i))
        if compressed:
            blob = lz4_block(blob, size)
        nso.segs.append((names[i], mem_off, size, comp, compressed))
        segs.append((mem_off, blob))
    end = segs[2][0] + len(segs[2][1])
    image = bytearray(end)
    for off, blob in segs:
        image[off:off + len(blob)] = blob
    nso.image = bytes(image)
    nso.text = segs[0][1]
    nso.ro = segs[1][1]
    nso.data = segs[2][1]
    nso.imports, nso.exports = [], []
    nso.symbol_error = None
    try:
        parse_symbols(nso)
    except Exception as e:  # el informe sigue aunque la tabla de simbolos no se pueda leer
        nso.symbol_error = str(e)
    return nso


def parse_symbols(nso):
    img = nso.image
    mod0 = struct.unpack_from("<I", img, 4)[0]
    if img[mod0:mod0 + 4] != b"MOD0":
        raise ValueError("MOD0 no encontrado")
    dyn_rel = struct.unpack_from("<i", img, mod0 + 4)[0]
    dyn = {}
    a = mod0 + dyn_rel
    while a + 16 <= len(img):
        tag, val = struct.unpack_from("<qQ", img, a)
        if tag == 0:
            break
        dyn.setdefault(tag, val)
        a += 16
    strtab, symtab = dyn.get(5), dyn.get(6)
    if strtab is None or symtab is None:
        raise ValueError("sin tabla de simbolos")
    syment = dyn.get(11, 24)
    nsyms = (strtab - symtab) // syment if strtab > symtab else 0
    if nsyms > 3_000_000:
        raise ValueError("tabla de simbolos absurda")
    for i in range(nsyms):
        at = symtab + i * syment
        st_name, st_info, _other, st_shndx = struct.unpack_from("<IBBH", img, at)
        if st_name == 0:
            continue
        s = strtab + st_name
        e = img.find(b"\0", s, s + 1024)
        name = img[s:e if e >= 0 else s + 1024].decode("latin-1")
        (nso.imports if st_shndx == 0 else nso.exports).append(name)


def mangled_parts(name):
    """_ZN2nn3hid...  ->  ['nn', 'hid', ...] (solo la cadena de espacios de nombres)."""
    if not name.startswith("_ZN"):
        return []
    parts, i = [], 3
    while i < len(name) and name[i].isdigit():
        j = i
        while j < len(name) and name[j].isdigit():
            j += 1
        n = int(name[i:j])
        parts.append(name[j:j + n])
        i = j + n
    return parts


KEYWORDS = [
    "il2cpp", "unityengine", "unityplayer", "mono", "unreal", "havok", "physx", "bullet", "box2d",
    "criware", "cri ", "adx", "wwise", "fmod", "nvn", "glslc", "vulkan", "egl", "opengl", "vkcreateinstance",
    "libcurl", "openssl", "mbedtls", "lua", "squirrel", "python", "zlib", "lz4", "zstd", "opus", "vp9", "h264",
    "bink", "usm", "level5", "level-5", "yokai", "yo-kai", "youkai", "nintendosdk", "nn::", "sdk mw",
]


def strings_of(buf, minlen=6):
    return re.findall(rb"[\x20-\x7e]{%d,}" % minlen, buf)


def probe_nso(name, path):
    title(f"ExeFS/{name}")
    try:
        nso = parse_nso(path)
    except Exception as e:
        out(f"  no se pudo leer: {e}")
        return None
    out(f"  tamano en disco : {nso.file_size} bytes   sha256: {nso.sha256[:16]}...")
    out(f"  build ID        : {nso.build_id.hex().upper()}")
    out(f"  main_build_id   : {nso.build_id[:8].hex().upper()}   <- primeros 8 bytes (formato del repo)")
    for seg, off, size, comp, compressed in nso.segs:
        out(f"  {seg:<5} off 0x{off:08x}  size 0x{size:08x}  comprimido={'si' if compressed else 'no'}")
    out(f"  bss             : 0x{nso.bss_size:x}")
    out(f"  simbolos        : importados={len(nso.imports)}  exportados={len(nso.exports)}"
        + (f"   (aviso: {nso.symbol_error})" if nso.symbol_error else ""))

    # Espacios de nombres nn:: usados (importados o exportados)
    ns_imp, ns_exp = collections.Counter(), collections.Counter()
    for names, counter in ((nso.imports, ns_imp), (nso.exports, ns_exp)):
        for n in names:
            p = mangled_parts(n)
            if len(p) >= 2 and p[0] == "nn":
                counter[p[1]] += 1
    if ns_imp:
        out("  nn:: importados por espacio de nombres: " + ", ".join(f"{k}({v})" for k, v in ns_imp.most_common(60)))
    if ns_exp:
        out("  nn:: exportados por espacio de nombres: " + ", ".join(f"{k}({v})" for k, v in ns_exp.most_common(60)))

    for label, rx in (("NVN", r"nvn[A-Z]"), ("glslc", r"glslc"), ("Vulkan", r"vk[A-Z]"),
                      ("EGL/GL", r"(egl|gl)[A-Z]"), ("nv (otros)", r"nv(?!n)[A-Za-z]")):
        pat = re.compile(rx)
        found = sorted({n for n in nso.imports + nso.exports if pat.match(n)})
        if found:
            out(f"  {label}: {len(found)} simbolos C. Primeros 40: " + ", ".join(found[:40]))

    # Cadenas: version del SDK, palabras clave, extensiones de archivo
    blob = nso.ro + nso.data
    low = blob.lower()
    sdk = sorted({m.decode("latin-1") for m in re.findall(rb"NintendoSdk_nnSdk-[0-9.]+(?:-\w+)?", blob)})
    mw = sorted({m.decode("latin-1") for m in re.findall(rb"SDK MW\+[ -~]{4,80}", blob)})[:5]
    if sdk:
        out("  version del SDK: " + ", ".join(sdk[:5]))
    if mw:
        out("  cadenas 'SDK MW': " + " | ".join(mw))
    hits = [(k, low.count(k.encode())) for k in KEYWORDS]
    hits = [(k, c) for k, c in hits if c]
    if hits:
        out("  palabras clave en cadenas: " + ", ".join(f"{k.strip()}={c}" for k, c in hits))

    strs = strings_of(blob)
    ext = collections.Counter()
    for s in strs:
        m = re.search(rb"\.([A-Za-z0-9]{2,6})$", s)
        if m and b" " not in s and len(s) < 120:
            ext[m.group(1).decode().lower()] += 1
    if ext:
        out("  extensiones de archivo citadas en cadenas: " + ", ".join(f"{k}({v})" for k, v in ext.most_common(25)))
    paths = sorted({s.decode() for s in strs if b"/" in s and b" " not in s and 8 <= len(s) < 100
                    and re.search(rb"\.[A-Za-z0-9]{2,6}$|/$", s)})
    if paths:
        out(f"  rutas citadas ({len(paths)} distintas), primeras 40:")
        for p in paths[:40]:
            out("    " + p)
    return nso


# --------------------------------------------------------------------------------------------------------------
# main.npdm
# --------------------------------------------------------------------------------------------------------------
def probe_npdm(path):
    title("ExeFS/main.npdm")
    with open(path, "rb") as f:
        d = f.read()
    if d[:4] != b"META":
        out("  no es un NPDM (falta la firma META)")
        return
    flags = d[0x0C]
    prio, core = d[0x0E], d[0x0F]
    sysres, version, stack = struct.unpack_from("<III", d, 0x14)
    name = d[0x20:0x30].split(b"\0")[0].decode("latin-1")
    code = d[0x30:0x40].split(b"\0")[0].decode("latin-1")
    out(f"  nombre: {name!r}  codigo de producto: {code!r}")
    out(f"  flags 0x{flags:02x}  (64 bits={bool(flags & 1)}, espacio de direcciones={(flags >> 1) & 7}, "
        f"optimizar memoria={bool(flags & 0x10)})")
    out(f"  prioridad del hilo principal: {prio}   nucleo: {core}   pila: 0x{stack:x}   version: {version}")
    out(f"  system_resource_size (META+0x14): 0x{sysres:x}   <- va en game::Info")
    aci_off, aci_size = struct.unpack_from("<II", d, 0x70)
    aci = d[aci_off:aci_off + aci_size]
    if aci[:4] != b"ACI0":
        out("  ACI0 no encontrado")
        return
    pid = struct.unpack_from("<Q", aci, 0x10)[0]
    out(f"  Program/Title ID (ACI0): {pid:016X}")
    sac_off, sac_size = struct.unpack_from("<II", aci, 0x28)
    sac, services, i = aci[sac_off:sac_off + sac_size], [], 0
    while i < len(sac):
        b = sac[i]
        n = (b & 7) + 1
        services.append(("server:" if b & 0x80 else "") + sac[i + 1:i + 1 + n].decode("latin-1"))
        i += 1 + n
    out(f"  servicios pedidos ({len(services)}): " + ", ".join(services))
    kac_off, kac_size = struct.unpack_from("<II", aci, 0x30)
    kac = aci[kac_off:kac_off + kac_size]
    caps = [struct.unpack_from("<I", kac, j)[0] for j in range(0, len(kac) - 3, 4)]
    out(f"  capacidades del kernel ({len(caps)}), en hex: " + " ".join(f"{c:08x}" for c in caps))


# --------------------------------------------------------------------------------------------------------------
# RomFS
# --------------------------------------------------------------------------------------------------------------
NAME_KEYS = ("shader", "nvn", "gfx", "glsl", "spirv", "maxwell", "gsc", "pipeline", "lang", "locale", "text",
             "msg", "font", "movie", "video", "sound", "bgm", "voice", "subtitle", "cpk", "pack", "arc")
LANG_DIRS = {"ja", "jp", "en", "us", "eu", "fr", "de", "es", "it", "ko", "kr", "zh", "cn", "tw", "ru", "pt", "nl",
             "jpn", "eng", "fra", "deu", "spa", "ita", "kor", "chs", "cht", "japanese", "english", "french",
             "german", "spanish", "italian", "korean"}


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0


def magic_repr(head):
    m = head[:4]
    if len(m) == 4 and all(32 <= c < 127 for c in m):
        return m.decode()
    return "0x" + m.hex()


def probe_romfs(root):
    title("RomFS")
    files = []  # (ruta relativa, tamano)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            try:
                if os.path.islink(full):
                    continue
                files.append((os.path.relpath(full, root).replace(os.sep, "/"), os.path.getsize(full), full))
            except OSError:
                pass
    total = sum(s for _, s, _ in files)
    out(f"  archivos: {len(files)}   tamano total: {human(total)}")
    if not files:
        out("  (vacio: revisa la ruta de --romfs)")
        return

    top = collections.defaultdict(lambda: [0, 0])
    for rel, size, _ in files:
        key = rel.split("/")[0] if "/" in rel else "(raiz)"
        top[key][0] += 1
        top[key][1] += size
    out("  primer nivel:")
    for k, (c, s) in sorted(top.items(), key=lambda kv: -kv[1][1])[:60]:
        out(f"    {k:<40} {c:>7} archivos  {human(s):>10}")

    second = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for rel, size, _ in files:
        parts = rel.split("/")
        if len(parts) >= 3:
            second[parts[0]][parts[1]][0] += 1
            second[parts[0]][parts[1]][1] += size
    out("  segundo nivel (hasta 15 por carpeta):")
    for k in sorted(second):
        out(f"    {k}/")
        for k2, (c, s) in sorted(second[k].items(), key=lambda kv: -kv[1][1])[:15]:
            out(f"      {k2:<36} {c:>7} archivos  {human(s):>10}")

    ext = collections.defaultdict(lambda: [0, 0])
    for rel, size, _ in files:
        e = rel.rsplit(".", 1)[-1].lower() if "." in rel.rsplit("/", 1)[-1] else "(sin extension)"
        ext[e][0] += 1
        ext[e][1] += size
    out("  extensiones (por tamano):")
    for k, (c, s) in sorted(ext.items(), key=lambda kv: -kv[1][1])[:30]:
        out(f"    .{k:<18} {c:>7} archivos  {human(s):>10}")

    mag = collections.Counter()
    for rel, size, full in files:
        e = rel.rsplit(".", 1)[-1].lower() if "." in rel.rsplit("/", 1)[-1] else "-"
        try:
            with open(full, "rb") as f:
                head = f.read(8)
        except OSError:
            continue
        mag[(e, magic_repr(head))] += 1
    out("  cabeceras de 4 bytes por extension (primeras 40):")
    for (e, m), c in mag.most_common(40):
        out(f"    .{e:<12} {m:<14} x{c}")

    out("  los 30 archivos mas grandes:")
    for rel, size, _ in sorted(files, key=lambda t: -t[1])[:30]:
        out(f"    {human(size):>10}  {rel}")

    hits = [rel for rel, _, _ in files if any(k in rel.lower() for k in NAME_KEYS)]
    out(f"  nombres que parecen shaders/idiomas/audio/paquetes: {len(hits)} (primeros 60)")
    for rel in hits[:60]:
        out("    " + rel)

    langs = sorted({part for rel, _, _ in files for part in rel.lower().split("/")[:-1] if part in LANG_DIRS})
    if langs:
        out("  carpetas con nombre de idioma: " + ", ".join(langs))


# --------------------------------------------------------------------------------------------------------------
# Simbolos importados por el main (para comparar con los hooks HLE del runtime)
# --------------------------------------------------------------------------------------------------------------
def write_symbols(path, nsos):
    """Una linea por simbolo importado por main/subsdk*: nombre y si el sdk lo exporta. Solo nombres de funciones."""
    sdk = nsos.get("sdk")
    sdk_exports = set(sdk.exports) if sdk else set()
    lines = ["# simbolos importados (nombre<TAB>sdk = lo exporta el sdk, ninguno = no lo exporta nadie)"]
    for name in sorted(nsos):
        if name in ("sdk", "rtld"):
            continue
        nso = nsos[name]
        lines.append(f"# modulo {name}: {len(nso.imports)} importados")
        for sym in sorted(set(nso.imports)):
            lines.append(f"{sym}\t{'sdk' if sym in sdk_exports else 'ninguno'}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return len(lines)


# --------------------------------------------------------------------------------------------------------------
# Busquedas dirigidas en el RomFS y dentro de los CPK (solo nombres y, si lo pides, 128 bytes de cabecera)
# --------------------------------------------------------------------------------------------------------------
def find_files(root, regex, cap=300):
    title(f"RomFS: archivos que coinciden con /{regex}/")
    pat = re.compile(regex, re.I)
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/")
            if pat.search(rel):
                n += 1
                if n <= cap:
                    out(f"  {human(os.path.getsize(os.path.join(dirpath, fn))):>10}  {rel}")
    out(f"  total que coinciden: {n}" + (f" (se muestran {cap})" if n > cap else ""))


def head_files(root, rels, nbytes=128):
    title("Cabeceras de archivos pedidos (primeros bytes)")
    for rel in rels:
        full = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(full):
            out(f"  {rel}: no existe")
            continue
        with open(full, "rb") as f:
            head = f.read(nbytes)
        out(f"  {rel}  ({os.path.getsize(full)} bytes)")
        hexdump(head)


def hexdump(data):
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        out(f"    {i:04x}  {chunk.hex(' '):<47}  {''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk)}")


def load_cpk_tool():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (here, os.path.join(here, "..", "games", "p5r", "tools")):
        p = os.path.join(cand, "cpk.py")
        if os.path.isfile(p):
            spec = importlib.util.spec_from_file_location("cpk_tool", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def probe_cpks(root, grep, top, head_regex, only=None, list_all=False, head_n=3):
    cpk_tool = load_cpk_tool()
    if cpk_tool is None:
        title("CPK")
        out("  falta cpk.py: ponlo junto a yokai_probe.py (esta en games/p5r/tools/cpk.py del repo)")
        return
    rel = lambda p: os.path.relpath(p, root).replace(os.sep, "/")
    cpks = []
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".cpk"):
                full = os.path.join(dirpath, fn)
                cpks.append((os.path.getsize(full), full))
    cpks.sort(reverse=True)
    if only:  # --cpk-only: todas las opciones --cpk-* miran solo los CPK cuya ruta coincide
        pat_only = re.compile(only, re.I)
        cpks = [(s, p) for s, p in cpks if pat_only.search(rel(p))]
        title(f"CPK: seleccionados por /{only}/: {len(cpks)}")
        for s, p in cpks[:20]:
            out(f"  {rel(p)}  ({human(s)})")
    opened = {}

    def open_cpk(path):
        if path not in opened:
            try:
                c = cpk_tool.Cpk(path)
                c.f.close()  # Cpk deja el archivo abierto: con 1800 CPK se agotan los descriptores (Errno 24)
                opened[path] = c
            except Exception as e:  # ITOC sin nombres, cabecera rara, etc.
                opened[path] = f"{type(e).__name__}: {e}"
        return opened[path]

    if top:
        title(f"CPK: los {top} mas grandes (contenido por extension)")
        for size, path in cpks[:top]:
            c = open_cpk(path)
            if isinstance(c, str):
                out(f"  {rel(path)}  ({human(size)})  NO LISTABLE: {c}")
                continue
            ext = collections.Counter(os.path.splitext(e["path"])[1].lower() or "(sin ext)" for e in c.files)
            comp = sum(1 for e in c.files if e["extract"] != e["size"])
            out(f"  {rel(path)}  ({human(size)})  {len(c.files)} archivos, {comp} comprimidos: "
                + ", ".join(f"{k}({v})" for k, v in ext.most_common(8)))

    if grep:
        title(f"CPK: nombres internos que coinciden con /{grep}/ (en los {len(cpks)} CPK)")
        pat = re.compile(grep, re.I)
        total = shown = cpks_hit = unlistable = 0
        for size, path in cpks:
            c = open_cpk(path)
            if isinstance(c, str):
                unlistable += 1
                continue
            hits = [e for e in c.files if pat.search(e["path"])]
            if not hits:
                continue
            cpks_hit += 1
            total += len(hits)
            out(f"  {rel(path)}: {len(hits)} coincidencias")
            for e in hits[:12]:
                if shown < 400:
                    out(f"      {e['size']:>10} {e['extract']:>10}  {e['path']}")
                    shown += 1
        out(f"  CPK con coincidencias: {cpks_hit}; coincidencias totales: {total}; CPK no listables: {unlistable}")

    if list_all:
        title(f"CPK: contenido completo (hasta 400 archivos en total) de los {len(cpks)} seleccionados")
        shown = 0
        for size, path in cpks:
            c = open_cpk(path)
            if isinstance(c, str):
                out(f"  {rel(path)}  ({human(size)})  NO LISTABLE: {c}")
                continue
            out(f"  {rel(path)}  ({human(size)})  {len(c.files)} archivos")
            for e in c.files:
                if shown < 400:
                    out(f"      {e['size']:>10} {e['extract']:>10}  {e['path']}")
                    shown += 1
        if shown >= 400:
            out("  (recortado a 400 lineas)")

    # Por que no se pueden listar: motivos agrupados, con el espacio que ocupan y 3 ejemplos de cada uno.
    bad = [(p, v) for p, v in opened.items() if isinstance(v, str)]
    if bad and (grep or list_all or top):
        title(f"CPK no listables: {len(bad)} de {len(opened)} abiertos, motivos")
        by_reason = collections.defaultdict(list)
        for p, v in bad:
            by_reason[v].append(p)
        for reason, paths in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            total_bytes = sum(os.path.getsize(p) for p in paths)
            out(f"  {len(paths):>5} CPK ({human(total_bytes)}): {reason}")
            for p in paths[:3]:
                out(f"        ej: {rel(p)}")

    if head_regex:
        title(f"CPK: cabecera (128 bytes) de hasta {head_n} archivos que coinciden con /{head_regex}/")
        pat = re.compile(head_regex, re.I)
        left = head_n
        for size, path in cpks:
            if left <= 0:
                break
            c = open_cpk(path)
            if isinstance(c, str):
                continue
            for e in c.files:
                if left > 0 and pat.search(e["path"]):
                    c.f = open(c.path, "rb")  # se cerro al listar; se abre solo para esta lectura
                    try:
                        data = c.read(e)
                    finally:
                        c.f.close()
                    out(f"  {rel(path)} :: {e['path']}  ({e['size']} bytes, {e['extract']} descomprimido)")
                    hexdump(data[:128])
                    left -= 1


# --------------------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Sondeo de ExeFS y RomFS de tu propio dump de Switch")
    ap.add_argument("--exefs", help="carpeta del ExeFS extraido")
    ap.add_argument("--romfs", help="carpeta del RomFS extraido")
    ap.add_argument("--out", default="yokai_probe_report.txt", help="archivo del informe (por defecto %(default)s)")
    ap.add_argument("--symbols-out", metavar="ARCHIVO",
                    help="escribe los simbolos importados por main/subsdk* (solo nombres de funciones)")
    ap.add_argument("--find", metavar="REGEX", help="lista los archivos del RomFS cuya ruta coincide")
    ap.add_argument("--head", metavar="RUTA", action="append",
                    help="muestra los primeros 128 bytes de un archivo del RomFS (se puede repetir)")
    ap.add_argument("--cpk-top", type=int, metavar="N", help="resumen del contenido de los N CPK mas grandes")
    ap.add_argument("--cpk-grep", metavar="REGEX", help="busca nombres dentro de TODOS los CPK del RomFS")
    ap.add_argument("--cpk-head", metavar="REGEX",
                    help="muestra los primeros 128 bytes de hasta N archivos de los CPK que coinciden")
    ap.add_argument("--cpk-head-n", type=int, default=3, metavar="N", help="cuantos archivos de --cpk-head (3)")
    ap.add_argument("--cpk-only", metavar="REGEX",
                    help="las opciones --cpk-* miran solo los CPK cuya ruta coincide (ej. shader/shader.cpk)")
    ap.add_argument("--cpk-list", action="store_true",
                    help="lista todo el contenido (nombre y tamanos) de los CPK elegidos con --cpk-only")
    args = ap.parse_args()
    if not args.exefs and not args.romfs:
        ap.error("indica al menos --exefs o --romfs")

    out("yokai_probe: informe de metadatos (sin claves ni contenido del juego)")
    nsos = {}
    if args.exefs:
        if not os.path.isdir(args.exefs):
            sys.exit("--exefs no es una carpeta")
        names = sorted(os.listdir(args.exefs))
        title("ExeFS: archivos")
        for n in names:
            p = os.path.join(args.exefs, n)
            if os.path.isfile(p):
                out(f"  {n:<16} {os.path.getsize(p):>12} bytes")
        if "main.npdm" in names:
            probe_npdm(os.path.join(args.exefs, "main.npdm"))
        else:
            out("  (falta main.npdm)")
        for n in names:
            if n == "main" or n == "sdk" or n == "rtld" or re.fullmatch(r"subsdk\d", n):
                nso = probe_nso(n, os.path.join(args.exefs, n))
                if nso is not None:
                    nsos[n] = nso
        if args.symbols_out:
            count = write_symbols(args.symbols_out, nsos)
            out(f"\n  simbolos importados escritos en {os.path.basename(args.symbols_out)} ({count} lineas)")
    if args.romfs:
        if not os.path.isdir(args.romfs):
            sys.exit("--romfs no es una carpeta")
        probe_romfs(args.romfs)
        if args.find:
            find_files(args.romfs, args.find)
        if args.head:
            head_files(args.romfs, args.head)
        if args.cpk_list and not args.cpk_only:
            ap.error("--cpk-list necesita --cpk-only (listar los 1823 CPK enteros no tiene sentido)")
        if args.cpk_top or args.cpk_grep or args.cpk_head or args.cpk_list:
            probe_cpks(args.romfs, args.cpk_grep, args.cpk_top, args.cpk_head, args.cpk_only, args.cpk_list,
                       args.cpk_head_n)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print(f"\nInforme guardado en {args.out}. Revisalo y pega su contenido en el chat.")


if __name__ == "__main__":
    main()
