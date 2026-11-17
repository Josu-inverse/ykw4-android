// Yo-kai Watch 4 (Level-5, Nintendo Switch): what the shared runtime needs to know about the game.
//
// Title ID 010086C00AF7C000, main build E2630E9B82591048 (from tools/yokai_probe.py on the player's own dump). Facts
// that decide the port are in games/yokai4/NOTES.md: Nintendo SDK 7.3.2 (older than P5R's 13 and Wonder's 16), NVN
// through nvnBootstrapLoader, Level-5's own engine (G4 assets), CRIWARE (CPK, ADX, USM), PhysX 3.4.
//
// This is the first boot skeleton: no hooks, no frame-rate or culling tricks (P5R's game.cpp has those, with offsets
// of its own build). Add a hook here only for something the log shows the game needs.
#include <cstdlib>

#include <nx/game.h>
#include <nx/runtime.h>

#include "platform.h"

namespace nx {

// The base game (version and region of the dump this port was started from) and its update (the patched `main`, read
// from the update NSP). The hooks go by symbol name, so both run the same glue. More builds go here as their build IDs
// are known (tools/yokai_probe.py prints main_build_id).
static const char* const kKnownBuilds[] = {"E2630E9B82591048", "C7DAB27F22ACD2ED", nullptr};

const game::Info game::kInfo = {"yokai4", "Yo-kai Watch 4", 0x010086C00AF7C000ull, "io.github.yokai4recomp",
                                "private/yokai4", 0 /* main.npdm: system_resource_size 0 (no VAMM) */,
                                "E2630E9B82591048", kKnownBuilds};

void game::after_init() { log("yokai4: after_init (SDK 7.3.2 build, no game-specific patches yet)"); }
void game::renderer_start() { log("yokai4: renderer_start"); }
void game::first_frame() { log("yokai4: first frame presented"); }

}  // namespace nx
