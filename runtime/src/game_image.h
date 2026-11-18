// The game read in place from the player's NSP or XCI (android/wonder/importer/nxgame.h): its ExeFS (the native
// loader's main and sdk) and its RomFS (the rom: mount, hle_fs.cpp), decrypted at each read. Nothing is extracted.
//   NX_GAME_FD + NX_GAME_NAME   a descriptor the Android launcher opened for the file the player picked, and its name
//   NX_GAME_NSP                 or the file's path (the PC)
//   NX_KEYS                     the player's prod.keys (NX_TITLE_KEYS: title.keys, when the dump needs it)
// Without NX_GAME_FD / NX_GAME_NSP the data folder's exefs/ and extract/romfs/ are used, as before.
#pragma once

#include <string>
#include <vector>

#include "nxgame.h"

namespace nx {

// The image, opened on first use; null when no game file is configured. A configured file that does not open is fatal.
const nxi::GameImage* game_image();

// Add-on content (DLC) read in place from the NSPs the player gave: NX_DLC_COUNT with NX_DLC_FD_<i> + NX_DLC_NAME_<i>
// (the Android launcher), or NX_DLC_DIR (a folder with the .nsp files, the PC). Opened on first use, keys as the game's.
// An image's title_id() is the DLC's id (the game's id + 0x1000 + index); its index is the low 12 bits.
struct AddonImage {
    uint32_t index;
    const nxi::GameImage* image;
};
const std::vector<AddonImage>& addon_images();  // ascending index; empty when there is none
const nxi::GameImage* addon_image(uint32_t index);

// A RomFS path for the image: '/'-separated, no leading or doubled slashes, "." parts dropped.
std::string game_image_path(const std::string& path);

}  // namespace nx
