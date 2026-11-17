// Yo-kai Watch 4's shaders (HBH1) out of the game image, for the translator (spirv_harness --batch):
//   <out>/<group>/manifest.tsv, code_<sha1>.bin, ctrl_<sha1>.bin   (the same layout as P5R's extractor)
#pragma once

#include <cstdint>
#include <functional>
#include <string>

#include "nxgame.h"

namespace yokai4 {

// Distinct code blocks written, or -1 with `error` set. progress(done, total) counts the shader files.
long extract_shaders(const nxi::GameImage& game, const std::string& out_dir,
                     const std::function<void(int, int)>& progress, std::string& error);

}  // namespace yokai4
