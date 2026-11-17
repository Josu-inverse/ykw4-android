package io.github.yokai4recomp;

/** The import on the phone (games/yokai4/import/yokai4_import_jni.cpp): only in ImportActivity's process. */
final class Importer {
    static {
        System.loadLibrary("yokai4import");
    }

    /** Blocking (updateFd -1: no update NSP): 0 when the shaders are ready in dataDir/spirv, else see error(). */
    static native int run(int nspFd, String nspName, int updateFd, String updateName, String keysPath, String titleKeysPath, String dataDir, String workDir,
                          int jobs);

    /** {phase, done, total}: 1 opening the game, 2 extracting the shaders, 3 translating them, 4 finishing, 5 done. */
    static native int[] progress();

    static native String error();

    private Importer() {}
}
