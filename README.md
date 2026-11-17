# Yo-kai Watch 4 / 妖怪ウォッチ4 ぼくらは同じ空を見上げている for Android (native port)

An Android app that runs **your own copy** of Yo-kai Watch 4 / 妖怪ウォッチ4 ぼくらは同じ空を見上げている (Nintendo Switch, version 1.0.0) natively on an arm64
phone or tablet. The Switch's operating system services, its audio, video and input, and NVN (the Switch's graphics
API) are reimplemented on Android, with Vulkan for the graphics. The game's own code runs directly on the phone's CPU:
the Switch and Android phones share the same CPU architecture (AArch64).

**No PC needed:** install the APK, pick your game file (`.nsp` or `.xci`) and your `prod.keys` on the phone, let it
prepare the game once (a few minutes), and play. The game is read from your file as it is; nothing is extracted.

> [!IMPORTANT]
> **This project is developed with a lot of AI assitance, but always under the supervision of a human **
> **No game files are included, here or in the APK.** This repository and its releases hold no game code, assets,
> shaders, keys or firmware. The APK is only the engine: it reads the game from your own dump. You need your own
> legally dumped copy of the game (the base game, version 1.0.0) and your own `prod.keys`. How to dump them from your
> console is **not** covered here. Please do not ask for game files or keys.

Yo-kai Watch 4 / 妖怪ウォッチ4 ぼくらは同じ空を見上げている is ©LEVEL-5 Inc. This is an unofficial fan project, not affiliated with or endorsed by LEVEL-5 or Nintendo.

## Install

1. Copy your **Yo-kai Watch 4 1.0.0** `.nsp` (or `.xci`) and your `prod.keys` to the phone
2. Install **ykw4** from the [Releases](../../releases) page
3. Open it and allow "All files access" (for its folder `Internal storage/Yo-kai Watch 4`: settings, saves, shaders).
4. **Game file → Choose**: pick your `.nsp`/`.xci`. **Keys → Choose**: pick your `prod.keys` (and `title.keys` too, if
   your dump needs it; you can select both). The app keeps the keys in its private storage; they are not uploaded or
   included in the APK.
5. Press **Prepare the game**. Keep the app open: it checks the game and translates its ~1500 shaders for your GPU.
6. Press **Play**.

Keep the game file where it is: every start reads the game from it. Saves are kept in
`Internal storage/Yo-kai Watch 4/user/save`; the home screen can import and export them. Mods (LayeredFS style) can be
placed in `Internal storage/Yo-kai Watch 4/mods/<ModName>/romfs/...` (see [docs/MODS.md](docs/MODS.md)).

## Requirements

- An arm64 Android phone or tablet with **Android 10 or newer** and **Vulkan 1.1**, 6 GB of RAM or more (8 GB
  recommended).
- Storage: the game file (about 15 GB) plus about 1 GB for the translated shaders and saves.
- Your own dump of **Yo-kai Watch 4 1.0.0** (JP `0100B880154FC000`) and your console's `prod.keys`.

## Status

- The game works about 15-20 fps on Poco x8 pro (dimensity 8500 ultra / mali-g720mc8)
- Adreno devices are not tested.
- Known issuses: the shaders can 

## How it works

- **Native execution (the loader).** The APK reads `main` and `sdk` from your game file's ExeFS, maps and links them
  as the Switch's loader would, and runs them on the phone's CPU (`runtime/src/nce/`). The few instructions that cannot
  run on Android as they are get patched into small stubs: system calls (`svc`), the thread-pointer registers, and the
  system counter. Calls into Switch system libraries go to the runtime's implementations.
- **The game file, read in place.** The NSP/XCI is opened with your keys (`android/wonder/importer/nxgame.h`) and the
  game's files are decrypted on the fly as the game reads them (`runtime/src/game_image.cpp`).
- **Shaders** are translated once, on the phone, from the game's Maxwell shaders to SPIR-V with
  [Ryujinx](https://github.com/Ryubing/Ryujinx)'s shader translator (MIT), compiled to a native Android library with
  .NET NativeAOT (`libspirvharness.so`). The extraction is `games/ykw4/import/`.
- **The runtime** is the Switch runtime of
  [Super Mario Bros. Wonder Recomp](https://github.com/BelmanteGu/SuperMarioWonderRecomp) (SwitchGamesRecomp, MIT,
  by BelmanteGu / Projeto Belmante). It provides the kernel, the services, NVN on Vulkan, audio (AAudio), hardware video
  decoding (MediaCodec) and touch controls.

## Reporting problems

Open an issue with your phone's model, SoC/GPU, Android version and RAM, what you did and what happened, and the log:
```
adb logcat -s ykw4:V > ykw4-log.txt
```
(run it before starting the game). Never attach game files, keys, or screenshots of copyrighted content beyond what
the report needs.

## En español

Una app de Android que ejecuta **tu propia copia** de Yo-kai Watch 4 (Switch, versión 1.0.0) de forma nativa en un
móvil o tablet arm64. **No hace falta PC.** El APK no lleva nada del juego: lo lee de tu propio archivo.

1. Copia al móvil tu `.nsp` (o `.xci`) de Yo-kai Watch 4 1.0.0 (el juego base, sin la actualización) y tu `prod.keys`
   (por ejemplo a Descargas).
2. Instala **ykw4** desde [Releases](../../releases).
3. Ábrelo y permite el acceso a todos los archivos.
4. **Archivo del juego → Elegir**: tu `.nsp`/`.xci`. **Claves → Elegir**: tu `prod.keys`. La app guarda las claves en
   su almacenamiento privado; no se suben ni se incluyen en el APK.
5. Pulsa **Preparar el juego** y deja la app abierta: comprueba el juego y traduce sus shaders.
6. Pulsa **Jugar**.

No borres ni muevas el archivo del juego: cada vez que juegas se lee de ahí. Puedes poner mods (estilo LayeredFS) en
`Almacenamiento interno/Yo-kai Watch 4/mods/<Nombre>/romfs/...` (ver [docs/MODS.md](docs/MODS.md)). En **Icono → Elegir
imagen** puedes crear un acceso directo con la imagen que quieras. No se proporcionan juegos ni claves.

## Credits and license

- Base of app: [Persona 5 Royal for Android](https://github.com/Brandon04Gonzalez/p5r-android)
- Runtime: [SwitchGamesRecomp / Super Mario Bros. Wonder Recomp](https://github.com/BelmanteGu/SuperMarioWonderRecomp)
  by BelmanteGu (Projeto Belmante), MIT.
- Shader translation: Ryujinx's shader translator (Ryubing), MIT, built into the APK as a native library.
- The native-execution idea is the one Switch emulators call NCE; this implementation is written for this runtime.
- Like the upstream project, this port was written with a lot of AI assistance (Anthropic's Claude), directed and
  tested by a human.

MIT License, see [LICENSE](LICENSE).
