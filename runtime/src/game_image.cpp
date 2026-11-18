#include "game_image.h"

#include <fcntl.h>
#if defined(_WIN32)
#include <io.h>
#else
#include <unistd.h>
#endif

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <mutex>
#include <vector>

#include <nx/runtime.h>

namespace nx {

namespace {

std::unique_ptr<nxi::GameImage> g_image;
std::once_flag g_once;

int open_read(const char* path) {
#if defined(_WIN32)
    return _open(path, _O_RDONLY | _O_BINARY | _O_NOINHERIT);
#else
    return ::open(path, O_RDONLY | O_CLOEXEC);
#endif
}

void close_fd(int fd) {
#if defined(_WIN32)
    _close(fd);
#else
    ::close(fd);
#endif
}

std::string base_name(const std::string& p) {
    size_t s = p.find_last_of("/\\");
    return s == std::string::npos ? p : p.substr(s + 1);
}

void open_image() {
    const char* fd = std::getenv("NX_GAME_FD");
    const char* path = std::getenv("NX_GAME_NSP");
    if (!(fd && *fd) && !(path && *path)) return;
    std::vector<nxi::InputFile> in;
    std::string shown;
    if (fd && *fd) {
        const char* name = std::getenv("NX_GAME_NAME");
        shown = name && *name ? name : "game.nsp";
        in.push_back({shown, std::atoi(fd)});
    } else {
        shown = base_name(path);
        int f = open_read(path);
        if (f < 0) fatal("game: cannot open %s", path);
        in.push_back({shown, f});
    }
    // The update (patch NSP), when one is given: NX_UPDATE_FD + NX_UPDATE_NAME, or NX_UPDATE_NSP (a path).
    std::vector<int> owned;  // the update file opened here by path, closed after opening
    const char* ufd = std::getenv("NX_UPDATE_FD");
    const char* upath = std::getenv("NX_UPDATE_NSP");
    if (ufd && *ufd) {
        const char* uname = std::getenv("NX_UPDATE_NAME");
        in.push_back({uname && *uname ? uname : "update.nsp", std::atoi(ufd)});
        shown += " + update";
    } else if (upath && *upath) {
        int f = open_read(upath);
        if (f < 0) fatal("game: cannot open the update %s", upath);
        owned.push_back(f);
        in.push_back({base_name(upath), f});
        shown += " + update";
    }
    std::vector<int> keys;  // read while opening, then closed
    const char* k = std::getenv("NX_KEYS");
    if (!k || !*k) fatal("game: NX_KEYS (the prod.keys file) is not set");
    if ((keys.emplace_back(open_read(k))) < 0) fatal("game: cannot open the keys file");
    in.push_back({"prod.keys", keys.back()});
    if (const char* t = std::getenv("NX_TITLE_KEYS"); t && *t) {
        int f = open_read(t);
        if (f >= 0) keys.push_back(f), in.push_back({"title.keys", f});
    }
    std::string err;
    g_image = nxi::GameImage::open(in, 0, err);
    for (int f : keys) close_fd(f);
    for (int f : owned) close_fd(f);
    if (!g_image) fatal("game: %s could not be read: %s", shown.c_str(), err.c_str());
    log("game: %s read in place (title %016llx): %zu RomFS files, ExeFS %zu files", shown.c_str(),
        (unsigned long long)g_image->title_id(), g_image->file_count(), g_image->exefs().size());
}

std::vector<std::unique_ptr<nxi::GameImage>> g_addon_owned;
std::vector<AddonImage> g_addons;
std::once_flag g_addon_once;

void open_addons() {
    std::vector<nxi::InputFile> in;
    std::vector<int> owned;
    if (const char* n = std::getenv("NX_DLC_COUNT")) {
        for (int i = 0, count = std::atoi(n); i < count; i++) {
            std::string fk = "NX_DLC_FD_" + std::to_string(i), nk = "NX_DLC_NAME_" + std::to_string(i);
            const char* fd = std::getenv(fk.c_str());
            const char* name = std::getenv(nk.c_str());
            if (fd && *fd) in.push_back({name && *name ? name : "dlc.nsp", std::atoi(fd)});
        }
    } else if (const char* dir = std::getenv("NX_DLC_DIR"); dir && *dir) {
        std::error_code ec;
        for (auto& e : std::filesystem::directory_iterator(dir, ec)) {
            std::string p = e.path().string(), low = p;
            std::transform(low.begin(), low.end(), low.begin(), [](unsigned char ch) { return char(std::tolower(ch)); });
            if (low.size() < 4 || low.compare(low.size() - 4, 4, ".nsp") != 0) continue;
            int f = open_read(p.c_str());
            if (f < 0) continue;
            owned.push_back(f);
            in.push_back({base_name(p), f});
        }
    }
    if (in.empty()) return;
    std::vector<int> keys;
    const char* k = std::getenv("NX_KEYS");
    if (!k || !*k) return;
    int kf = open_read(k);
    if (kf < 0) return;
    keys.push_back(kf);
    in.push_back({"prod.keys", kf});
    if (const char* t = std::getenv("NX_TITLE_KEYS"); t && *t) {
        int f = open_read(t);
        if (f >= 0) keys.push_back(f), in.push_back({"title.keys", f});
    }
    std::vector<std::string> notes;
    g_addon_owned = nxi::GameImage::open_addons(in, game_image() ? game_image()->title_id() : 0, notes);
    for (int f : keys) close_fd(f);
    // The NSP descriptors stay open: the RomFS is read from them for the whole run (the PC ones too).
    for (const std::string& n : notes) log("dlc: %s", n.c_str());
    for (auto& g : g_addon_owned) g_addons.push_back({uint32_t(g->title_id() & 0xFFF), g.get()});
    std::sort(g_addons.begin(), g_addons.end(), [](const AddonImage& a, const AddonImage& b) { return a.index < b.index; });
    for (const AddonImage& a : g_addons)
        log("dlc: index %u = %016llx, %zu RomFS files", a.index, (unsigned long long)a.image->title_id(),
            a.image->file_count());
    if (g_addons.empty() && !notes.empty()) log("dlc: no usable add-on content among %zu files", in.size());
}

}  // namespace

const nxi::GameImage* game_image() {
    std::call_once(g_once, open_image);
    return g_image.get();
}

const std::vector<AddonImage>& addon_images() {
    std::call_once(g_addon_once, open_addons);
    return g_addons;
}

const nxi::GameImage* addon_image(uint32_t index) {
    for (const AddonImage& a : addon_images())
        if (a.index == index) return a.image;
    return nullptr;
}

std::string game_image_path(const std::string& path) {
    std::string out, part;
    auto flush = [&] {
        if (!part.empty() && part != ".") out += (out.empty() ? "" : "/") + part;
        part.clear();
    };
    for (char ch : path) {
        if (ch == '/' || ch == '\\') flush();
        else part += ch;
    }
    flush();
    return out;
}

}  // namespace nx
