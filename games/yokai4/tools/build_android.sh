#!/usr/bin/env bash
# Android build of Yo-kai Watch 4, native execution: cmake (NDK) -> libyokai4.so + libyokai4import.so (+ the prebuilt
# libspirvharness.so, the shader translator) -> aapt2 -> javac/d8 -> zipalign -> apksigner -> private/yokai4/apk/yokai4.apk.
# The APK has the launcher (games/yokai4/java: pick the NSP and prod.keys, options, mods, FPS counter) and the on-device
# importer that translates the game's shaders once; the game is read from the player's NSP as it is.
#
# The shader translator is built once from the repository root (the same one P5R uses):
#   docker run --rm -v "$PWD:/src" -w /src mcr.microsoft.com/dotnet/sdk:10.0 sh games/p5r/tools/build_harness_android.sh
#
# Needs the Android SDK (ANDROID_HOME or ANDROID_SDK_ROOT) with NDK 28.2.13676358, build-tools 35.0.0 and platform
# android-35, cmake, ninja, zip, and the Vulkan headers 1.4.357 (VULKAN_SDK, or private/third_party/Vulkan-Headers-1.4.357,
# see docs/BUILD.md). Signing: ~/.android/debug.keystore (created if missing) or YOKAI4_KEYSTORE (+ _PASSWORD, _ALIAS).
# Usage: games/yokai4/tools/build_android.sh [--install]
set -euo pipefail

root="$(cd "$(dirname "$0")/../../.." && pwd)"
install=0
while [ $# -gt 0 ]; do
    case "$1" in
        --install) install=1; shift ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

sdk="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"
ndk="$sdk/ndk/28.2.13676358"
bt="$sdk/build-tools/35.0.0"
jar="$sdk/platforms/android-35/android.jar"
for p in "$ndk" "$bt" "$jar"; do [ -e "$p" ] || { echo "missing $p" >&2; exit 1; }; done

priv="$root/private/yokai4"
out="$priv/apk"
build="$priv/ba"
diag="${NX_DIAGNOSTICS:-ON}"   # on for the first boots: the log is what the work goes by
case "$diag" in 1|on|ON|true|TRUE) diag=ON ;; *) diag=OFF ;; esac

export VULKAN_SDK="${VULKAN_SDK:-$root/private/third_party/Vulkan-Headers-1.4.357}"
# CMake asks for Include/ (the Windows SDK layout); the Vulkan-Headers checkout has include/.
if [ ! -d "$VULKAN_SDK/Include" ] && [ -d "$VULKAN_SDK/include" ]; then
    mkdir -p "$priv/vulkan-sdk"
    ln -sfn "$VULKAN_SDK/include" "$priv/vulkan-sdk/Include"
    export VULKAN_SDK="$priv/vulkan-sdk"
fi
[ -d "$VULKAN_SDK/Include" ] || { echo "no Vulkan headers: set VULKAN_SDK (docs/BUILD.md)" >&2; exit 1; }

configure=0
[ -f "$build/build.ninja" ] || configure=1
if [ -f "$build/CMakeCache.txt" ] && ! grep -q "^NX_DIAGNOSTICS:BOOL=$diag$" "$build/CMakeCache.txt"; then configure=1; fi
if [ "$configure" = 1 ]; then
    cmake -S "$root" -B "$build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_TOOLCHAIN_FILE="$ndk/build/cmake/android.toolchain.cmake" \
        -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-29 -DANDROID_STL=c++_static \
        -DNX_GAME=yokai4 -DNX_NCE=ON -DNX_DIAGNOSTICS=$diag
fi
harness="$root/private/build/spirv_harness_android/libspirvharness.so"
if [ ! -f "$harness" ]; then
    echo "missing $harness" >&2
    echo "build it once from the repository root: docker run --rm -v \"$root:/src\" -w /src mcr.microsoft.com/dotnet/sdk:10.0 sh games/p5r/tools/build_harness_android.sh" >&2
    exit 1
fi
cmake --build "$build" --target yokai4 yokai4import

host="$(uname -s | tr '[:upper:]' '[:lower:]')-x86_64"
llvm="$ndk/toolchains/llvm/prebuilt/$host/bin"
rm -rf "$out"
mkdir -p "$out/lib/arm64-v8a"
"$llvm/llvm-strip" --strip-unneeded -o "$out/lib/arm64-v8a/libyokai4.so" "$build/libyokai4.so"
"$llvm/llvm-strip" --strip-unneeded -o "$out/lib/arm64-v8a/libyokai4import.so" "$build/libyokai4import.so"
"$llvm/llvm-strip" --strip-unneeded -o "$out/lib/arm64-v8a/libspirvharness.so" "$harness"
# libadrenotools' hook libraries (custom GPU drivers): found by name in nativeLibraryDir at run time; optional.
for h in libhook_impl.so libmain_hook.so libfile_redirect_hook.so libgsl_alloc_hook.so; do
    f="$(find "$build" -name "$h" -print -quit)"
    [ -n "$f" ] && cp "$f" "$out/lib/arm64-v8a/$h"
done

"$bt/aapt2" compile --dir "$root/android/res" -o "$out/res.zip"
res_zips=("$out/res.zip")
manifest="$root/games/yokai4/AndroidManifest.xml"
icon_res="$root/games/yokai4/icon/res"
if [ -d "$icon_res" ]; then
    "$bt/aapt2" compile --dir "$icon_res" -o "$out/icon.zip"
    res_zips+=("$out/icon.zip")
    sed 's|<application|<application android:icon="@mipmap/ic_launcher"|' "$manifest" > "$out/AndroidManifest.xml"
    manifest="$out/AndroidManifest.xml"
fi
"$bt/aapt2" link -o "$out/base.apk" -I "$jar" --manifest "$manifest" "${res_zips[@]}"
(cd "$out" && zip -q -r -9 base.apk lib)
# The Java classes (games/yokai4/java: Launcher, ImportActivity, Importer, ControlsEditor, LogProvider, Lang, TextInput).
mkdir -p "$out/classes" "$out/dex"
find "$root/games/yokai4/java" -name '*.java' > "$out/sources.txt"
javac -encoding UTF-8 -source 1.8 -target 1.8 -Xlint:-options -bootclasspath "$jar" -d "$out/classes" @"$out/sources.txt"
find "$out/classes" -name '*.class' > "$out/classes.txt"
"$bt/d8" --release --min-api 29 --lib "$jar" --output "$out/dex" @"$out/classes.txt"
(cd "$out/dex" && zip -q -j "$out/base.apk" classes.dex)
"$bt/zipalign" -f -p 4 "$out/base.apk" "$out/aligned.apk"

ks="${YOKAI4_KEYSTORE:-$HOME/.android/debug.keystore}"
ks_pass="${YOKAI4_KEYSTORE_PASSWORD:-android}"
key_alias="${YOKAI4_KEY_ALIAS:-androiddebugkey}"
if [ ! -f "$ks" ] && [ -z "${YOKAI4_KEYSTORE:-}" ]; then
    mkdir -p "$(dirname "$ks")"
    keytool -genkeypair -keystore "$ks" -storepass android -keypass android -alias androiddebugkey -keyalg RSA \
        -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US"
fi
"$bt/apksigner" sign --ks "$ks" --ks-key-alias "$key_alias" --ks-pass "pass:$ks_pass" \
    --key-pass "pass:${YOKAI4_KEY_PASSWORD:-$ks_pass}" --out "$out/yokai4.apk" "$out/aligned.apk"
"$bt/apksigner" verify "$out/yokai4.apk"
echo "APK: $out/yokai4.apk ($(du -h "$out/yokai4.apk" | cut -f1))"
if [ "$install" = 1 ]; then "$sdk/platform-tools/adb" install -r "$out/yokai4.apk"; fi
