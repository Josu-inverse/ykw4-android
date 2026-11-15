# Yo-kai Watch 4 (Switch): notas del port

Todo sale de `tools/yokai_probe.py` sobre el dump propio del jugador. Aquí solo hay metadatos, nada del juego.

## Identidad

| Dato | Valor |
|---|---|
| Title ID | `010086C00AF7C000` |
| `main` build ID (8 bytes) | `E2630E9B82591048` |
| SDK de Nintendo | 7.3.2 (P5R usa SDK 13, Wonder SDK 16) |
| NVN / libz / libcurl | 7.3.2 |
| `main.npdm` | 64 bits, espacio de direcciones 39 bits, `system_resource_size` 0, hilo principal prioridad 44 núcleo 0 |
| Módulos del ExeFS | `main` (11,7 MB), `sdk` (5,3 MB), `rtld`; sin `subsdk*` |
| bss de `main` | 0x1525878 (~22 MB) |

Servicios que pide el npdm (44): acc:u0, aoc:u, apm, appletOE, audin:u, audout:u, audren:u, banana, bcat:u, bsd:u,
bsdcfg, caps:su, caps:u, csrng, friend:u, fsp-srv, hid, htc, htc:tenv, htcs, hwopus, irs, ldn:u, ldr:ro, lm, mii:u,
mm:u, nfc:mf:u, nfc:user, nfp:user, nifm:u, nim:eca, nsd:u, ntc, nvdrv, pcm, pctl, pl:u, prepo:u, set, sfdnsres, ssl,
time:u, vi:u.

## Motor y middleware (por cadenas del `main`)

- No es Unity ni Mono (il2cpp: 0). Motor propio de Level-5: texturas `.g4tx`, modelos `.g4md`, paquetes `.g4pk`/`.g4pkm`,
  `.g4la`, mallas de colisión `.col` (cabecera `PXCL`, PhysX 3.4.0).
- Audio y vídeo: CRIWARE (CPK, ADX, ACB/AWB, USM/CRID). También aparecen FMOD y Opus. Lua, Bullet y NEX 4.6.2 (red) están
  enlazados.
- Gráficos: NVN por `nvnBootstrapLoader` (el `main` solo importa ese símbolo NVN; el `sdk` lo exporta). Shaders
  precompilados: el `sdk` solo exporta los `glslc_*` de asignación, el `main` no importa ninguna función de compilación.
- Shaders: rutas `#/shader/*.cfxo` y `#/shader/shader_list.cfg.bin` (`cs_*` son compute). Formato CFXO por descubrir;
  falta saber en qué CPK están.

## RomFS (5,1 GB, 3714 archivos, todo bajo `data/`)

- `data/common` (2623 archivos, 3,9 GB) y `data/nx` (1090 archivos, 1,2 GB, sonido y mapas de Switch).
- 1823 CPK (2,9 GB), 5 USM (1,1 GB; `yw4_eved_0001.usm` 655 MB), AWB 1 GB, ACB 139 MB.
- `gamedata_all.cpk`, `gamedata_us.cpk`, `gamedata_eu.cpk`, `gamedata_jp.cpk`: datos por región en el mismo dump.
- `data/cpk_list.cfg.bin`: lista de CPK del juego (formato por mirar).
- Voces con carpeta `ja`.

## Cómo encaja en el runtime

El runtime resuelve los imports del `main` así: primero un hook `NX_HLE` por nombre de símbolo, si no la función
exportada por el `sdk` (que se ejecuta nativa y habla IPC con los servicios del runtime), y si no, un stub que registra
la llamada. Con SDK 7.3.2 los nombres mangleados pueden diferir de los de SDK 13/16 en algunas firmas, así que la lista
de imports (`--symbols-out`) es el trabajo pendiente más concreto.

## Imports del `main` contra los hooks del runtime (`imports.txt`, 573 imports, todos los resuelve el `sdk`)

El runtime tiene 1300 `NX_HLE`. Con este `main` (SDK 7.3.2) coinciden de forma exacta unos 100. Los que existen con otra
firma (enteros donde el SDK nuevo usa enums, o argumentos de más) no engancharían: `nn::socket` (12), `vi::CreateLayer`
(lleva `int, int` extra), `ngc::ProfanityFilter::GetContentVersion` (devuelve el valor, no un `Result`) y
`err::ShowError(ErrorResultVariant const&)`. Un import sin hook ejecuta el código nativo del `sdk` y habla IPC con los
servicios del runtime, que no tiene `bsd:u`, `nifm:u`, `ssl`, `vi:u`, `ldn:u`, `nfc:*`, `friend:u`.

Cubierto en `games/yokai4/hle_sdk7.cpp` (60 hooks, solo las funciones que van por IPC; sin conexión, como `hle_net.cpp`) y
en `runtime/src/hle_vi.cpp` (alias de `CreateLayer` y `CloseDisplay`/`DestroyLayer`/`Finalize`). Comprobado: compilan
(`-fsyntax-only`), no duplican ningún hook y todos los símbolos están en `imports.txt`. No se ha ejecutado nada.
Se dejaron nativas a propósito las funciones puras (`Inet*`, `GAIStrError`, `SetLastErrno`): es una suposición.

Sin cubrir, a mirar con el primer log: `nn::ldn` (26), `nn::nfc` (13), `nn::swkbd` (11), `nn::web` (3), `nn::friends`
(5), `nn::ec`, y de `nn::fs`: `RenameFile`, `DeleteDirectory`, `MountAddOnContent` (un guardado que renombre fallaría).
`nn::oe` (11), `nn::time` (8) y `nn::account` (16) van por IPC a `appletOE`, `time:u` y `acc:u0`, que el runtime sí tiene.

## Shaders: lo que se sabe (informe3)

- Los `.cfxo` que cita el `main` no están en el RomFS: en `data/nx/shader/` hay `.csb` (compute, sueltos), y dentro de
  `data/nx/shader/shader.cpk` (1932 archivos) `.vsb`, `.fsb` y `.fxbin`. Los nombres coinciden (`cs_buffer_lerp`).
- `.csb` y `.fsb` empiezan por `HBH1`, `0x40`, `0` y cinco pares (offset, tamaño) desde +0x0c, encadenados: en los dos
  ejemplos vistos [0x40+0x60][0xa0+0x60][0x100+0x20][0x120+0xb90][0xcb0+0x4d] (el `.fsb`: 0x40, 0x30, 0x20, 0xe40, 0x3b).
  La sección 3 es la grande y probablemente el código. Falta confirmar si trae los bloques NVN estándar (control
  0x98761234 + código 0x12345678, como los GSC de P5R): lo mide `tools/yokai_shader_probe.py`.
- `.fxbin` (512 B a unos KB) y `shader_list.cfg.bin` (88 KB) parecen tablas de hashes de 8 bytes; formato sin analizar.

## Herramientas

- `tools/yokai_probe.py`: sondeo de ExeFS y RomFS. Error corregido: no cerraba los CPK y con 1823 CPK se agotaban los
  descriptores (`Errno 24`): 802 salían "no listables" y las búsquedas `--cpk-grep` solo cubrían 1021. No eran CPK sin
  nombres. Con el arreglo se listan todos (probado con 300 CPK y límite de 64 descriptores).
- `tools/yokai_shader_probe.py`: estructura HBH1 de los shaders.

## Lista de trabajo

1. [hecho] `game::Info` de yokai4 y `known_builds` por juego (`runtime/src/main.cpp` ya no tiene la lista de P5R).
   Comprobado solo con `g++ -fsyntax-only` (sin errores en `games/yokai4/game.cpp`, `games/p5r/game.cpp`, `main.cpp`);
   no se ha enlazado ni ejecutado nada.
1b. [hecho] Botones táctiles de yokai4 en `runtime/src/touch_layout.cpp` (copia de la tabla de P5R; sin ella el juego
   no dibuja ningún botón).
2. [hecho, ver arriba] Imports de `main` contra los `NX_HLE`; faltan ldn/nfc/swkbd/web/friends y 3 de fs.
3. [hecho a medias] Shaders: `games/yokai4/tools/hbh1_shaders.py` (extractor offline, misma salida que `gsc_shaders.py`).
   Solo probado con archivos sintéticos (`--selftest`); falta correrlo sobre el RomFS real y ver cuántos cumplen la regla.
4. Extractor de shaders de Yo-kai Watch 4 para el importador (reutilizar el lector CPK de
   `games/p5r/import/p5r_shaders.cpp`) y traducción Maxwell a SPIR-V con el harness de Ryujinx.
5. Launcher Java, manifest, importador JNI (Title ID) y script de build del APK, a partir de los de P5R.
6. Primer arranque en el móvil: leer `nx.log`/`nx.log.prev`, arreglar servicios, formatos de textura y GPU.
7. Vídeo USM (CRIWARE): decide cómo se reproducen los 1,1 GB de películas (P5R usa `hle_movie.cpp`).
8. Entrada: HID por API con layouts de SDK 7 (`hle_hid.cpp` tiene secciones para SDK 13 y 16).

## Shaders HBH1: regla usada por el extractor (informe5 + dos ejemplos revisados a mano)

Sección 3 = [prefacio de 0x20 bytes][código, magia 0x12345678 (gráfico) o 0x12345679 (compute) en +0x20][control, magia
0x98761234, 0x880 bytes][cola sin explicar]. Tamaño del código = u32 en control+0x704. El "no hay magia de código" de
los `.csb` era un fallo del sondeo (solo buscaba 0x12345678). El extractor descarta y cuenta los archivos que no cumplen
la regla; `--stats` imprime el resumen. Ejecutar: `python games/yokai4/tools/hbh1_shaders.py --romfs RUTA/romfs --out RUTA/salida --stats`.
