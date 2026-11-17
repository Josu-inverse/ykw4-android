// yokai4_shaders.h. Yo-kai Watch 4's shaders (the HBH1 container) out of the game image, on the phone: what
// games/yokai4/tools/hbh1_shaders.py does on the PC, with the same output layout for the translator
// (spirv_harness --batch): <out>/<group>/manifest.tsv, code_<sha1>.bin, ctrl_<sha1>.bin.
// Groups: "loose" (data/nx/shader/* but the CPK) and "shader_cpk" (every file of data/nx/shader/shader.cpk).
#include "yokai4_shaders.h"

#include <sys/stat.h>

#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <map>
#include <set>
#include <stdexcept>
#include <vector>

#if defined(_WIN32)
#include <direct.h>
#endif

namespace yokai4 {

namespace {

struct Fail : std::runtime_error {
    using std::runtime_error::runtime_error;
};

uint32_t le32(const uint8_t* p) { return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24; }
uint64_t le64(const uint8_t* p) { return uint64_t(le32(p)) | uint64_t(le32(p + 4)) << 32; }
uint16_t be16(const uint8_t* p) { return uint16_t(p[0] << 8 | p[1]); }
uint32_t be32(const uint8_t* p) { return uint32_t(p[0]) << 24 | uint32_t(p[1]) << 16 | uint32_t(p[2]) << 8 | p[3]; }
uint64_t be64(const uint8_t* p) { return uint64_t(be32(p)) << 32 | be32(p + 4); }

// ---- SHA-1 (the harness names blocks by the first 16 hex digits of their SHA-1) ----

std::string sha1_16(const uint8_t* data, size_t n) {
    uint32_t h[5] = {0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0};
    auto rol = [](uint32_t x, int s) { return (x << s) | (x >> (32 - s)); };
    auto block = [&](const uint8_t* p) {
        uint32_t w[80];
        for (int i = 0; i < 16; i++) w[i] = be32(p + 4 * i);
        for (int i = 16; i < 80; i++) w[i] = rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
        uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4];
        for (int i = 0; i < 80; i++) {
            uint32_t f, k;
            if (i < 20) f = (b & c) | (~b & d), k = 0x5A827999;
            else if (i < 40) f = b ^ c ^ d, k = 0x6ED9EBA1;
            else if (i < 60) f = (b & c) | (b & d) | (c & d), k = 0x8F1BBCDC;
            else f = b ^ c ^ d, k = 0xCA62C1D6;
            uint32_t t = rol(a, 5) + f + e + k + w[i];
            e = d, d = c, c = rol(b, 30), b = a, a = t;
        }
        h[0] += a, h[1] += b, h[2] += c, h[3] += d, h[4] += e;
    };
    size_t i = 0;
    for (; i + 64 <= n; i += 64) block(data + i);
    uint8_t tail[128] = {};
    size_t rest = n - i;
    std::memcpy(tail, data + i, rest);
    tail[rest] = 0x80;
    size_t len = rest + 1 + 8 <= 64 ? 64 : 128;
    uint64_t bits = uint64_t(n) * 8;
    for (int j = 0; j < 8; j++) tail[len - 1 - j] = uint8_t(bits >> (8 * j));
    block(tail);
    if (len == 128) block(tail + 64);
    char out[41];
    for (int j = 0; j < 5; j++) std::snprintf(out + 8 * j, 9, "%08x", h[j]);
    return std::string(out, 16);
}

// ---- CRI: @UTF tables, CPK, CRILAYLA ----

struct Value {
    int type = -1;
    uint64_t u = 0;
    std::string s;
};
using Row = std::map<std::string, Value>;

std::vector<Row> read_utf(std::vector<uint8_t> d) {
    if (d.size() < 0x20) throw Fail("CPK: table too short");
    if (std::memcmp(d.data(), "@UTF", 4) != 0) {  // obfuscated
        uint32_t m = 0x655F;
        for (uint8_t& b : d) b ^= uint8_t(m), m = m * 0x4115;
        if (std::memcmp(d.data(), "@UTF", 4) != 0) throw Fail("CPK: not an @UTF table");
    }
    const uint8_t* p = d.data();
    const size_t base = 8;
    size_t rows_off = base + be16(p + 10), strings_off = base + be32(p + 12), data_off = base + be32(p + 16);
    uint16_t ncols = be16(p + 24), row_len = be16(p + 26);
    uint32_t nrows = be32(p + 28);
    auto at = [&](size_t o, size_t n) {
        if (o + n > d.size()) throw Fail("CPK: table data out of range");
        return p + o;
    };
    auto cstr = [&](uint32_t o) {
        size_t s = strings_off + o;
        at(s, 1);
        size_t e = s;
        while (e < d.size() && p[e]) e++;
        return std::string(reinterpret_cast<const char*>(p + s), e - s);
    };
    auto value = [&](int t, size_t pos, Value& v) -> size_t {
        v.type = t;
        switch (t) {
            case 0: case 1: v.u = *at(pos, 1); return 1;
            case 2: case 3: v.u = be16(at(pos, 2)); return 2;
            case 4: case 5: case 8: v.u = be32(at(pos, 4)); return 4;
            case 6: case 7: case 9: v.u = be64(at(pos, 8)); return 8;
            case 0xA: v.s = cstr(be32(at(pos, 4))); return 4;
            case 0xB: {  // data: offset, size (not needed here)
                at(pos, 8);
                v.u = be32(p + pos + 4);
                return 8;
            }
        }
        throw Fail("CPK: unknown @UTF column type");
    };
    struct Col {
        std::string name;
        int storage, type;
        Value constant;
    };
    std::vector<Col> cols;
    size_t pos = 0x20;
    for (int i = 0; i < ncols; i++) {
        uint8_t flags = *at(pos, 1);
        Col c{cstr(be32(at(pos + 1, 4))), flags & 0xF0, flags & 0x0F, {}};
        pos += 5;
        if (c.storage == 0x30) pos += value(c.type, pos, c.constant);
        cols.push_back(std::move(c));
    }
    std::vector<Row> rows(nrows);
    for (uint32_t r = 0; r < nrows; r++) {
        size_t q = rows_off + size_t(r) * row_len;
        for (const Col& c : cols) {
            if (c.storage == 0x50) q += value(c.type, q, rows[r][c.name]);
            else if (c.storage == 0x30) rows[r][c.name] = c.constant;
        }
    }
    (void)data_off;
    return rows;
}

std::vector<uint8_t> crilayla(const std::vector<uint8_t>& src) {
    if (src.size() < 0x110 || std::memcmp(src.data(), "CRILAYLA", 8) != 0) return src;
    uint32_t usize = le32(src.data() + 8), hoff = le32(src.data() + 12);
    if (0x10 + uint64_t(hoff) + 0x100 > src.size() || usize > (1u << 30)) throw Fail("CRILAYLA: bad header");
    std::vector<uint8_t> out(size_t(usize) + 0x100);
    std::memcpy(out.data(), src.data() + 0x10 + hoff, 0x100);
    int64_t pos = int64_t(src.size()) - 0x100 - 1;
    uint32_t bits = 0;
    int nbits = 0;
    auto get = [&](int n) {
        uint32_t v = 0;
        while (n) {
            if (nbits == 0) {
                if (pos < 0) throw Fail("CRILAYLA: stream ends early");
                bits = src[size_t(pos--)];
                nbits = 8;
            }
            int take = std::min(n, nbits);
            v = (v << take) | ((bits >> (nbits - take)) & ((1u << take) - 1));
            nbits -= take, n -= take;
        }
        return v;
    };
    int64_t w = int64_t(usize) + 0x100 - 1;
    while (w >= 0x100) {
        if (get(1)) {
            int64_t back = int64_t(get(13)) + 3;
            uint32_t length = 3;
            static const int lbits[4] = {2, 3, 5, 8};
            bool more = true;
            for (int lb : lbits) {
                uint32_t v = get(lb);
                length += v;
                if (v != (1u << lb) - 1) {
                    more = false;
                    break;
                }
            }
            while (more) {
                uint32_t v = get(8);
                length += v;
                more = v == 0xFF;
            }
            for (uint32_t k = 0; k < length; k++, w--) {
                if (w < 0 || w + back >= int64_t(out.size())) throw Fail("CRILAYLA: bad back reference");
                out[size_t(w)] = out[size_t(w + back)];
            }
        } else {
            out[size_t(w--)] = uint8_t(get(8));
        }
    }
    return out;
}

struct CpkFile {
    std::string path;
    uint64_t offset, size, extract;
};

std::vector<CpkFile> cpk_files(const nxi::GameImage& g, const nxi::GameImage::Entry& cpk) {
    auto block = [&](uint64_t off, const char* magic) {
        uint8_t head[16];
        if (g.read(cpk, off, head, 16) != 16 || std::memcmp(head, magic, 4) != 0)
            throw Fail(std::string("CPK: no ") + magic + " block");
        std::vector<uint8_t> d(size_t(le64(head + 8)));
        if (g.read(cpk, off + 16, d.data(), d.size()) != d.size()) throw Fail("CPK: truncated block");
        return d;
    };
    std::vector<Row> header = read_utf(block(0, "CPK "));
    if (header.empty()) throw Fail("CPK: empty header");
    uint64_t toc = header[0]["TocOffset"].u, content = header[0]["ContentOffset"].u;
    if (!toc) throw Fail("CPK: no table of contents");
    uint64_t base = content ? std::min(toc, content) : toc;
    std::vector<CpkFile> out;
    for (Row& r : read_utf(block(toc, "TOC "))) {
        std::string dir = r["DirName"].s, name = r["FileName"].s;
        uint64_t size = r["FileSize"].u, ext = r["ExtractSize"].u;
        out.push_back({dir.empty() ? name : dir + "/" + name, base + r["FileOffset"].u, size, ext ? ext : size});
    }
    return out;
}

// ---- HBH1 ----

constexpr uint32_t kCtrl = 0x98761234, kCodeGfx = 0x12345678, kCodeCompute = 0x12345679;

struct Parsed {
    uint64_t code, ctrl, size;  // absolute offsets in the file, and the code size
};

// hbh1_shaders.py parse(): section 3 = [0x20 prefix "NXGL"][code][control block, 0x880 bytes, magic 0x98761234].
bool parse(const std::vector<uint8_t>& d, Parsed& out) {
    if (d.size() < 0x40 || std::memcmp(d.data(), "HBH1", 4) != 0 || le32(d.data() + 4) != 0x40) return false;
    uint32_t s_off = le32(d.data() + 0x0c + 8 * 3), s_size = le32(d.data() + 0x0c + 8 * 3 + 4);
    if (uint64_t(s_off) + s_size > d.size() || s_size < 0x20 + 0x880) return false;
    const uint8_t* sec = d.data() + s_off;
    if (std::memcmp(sec, "NXGL", 4) != 0 || le32(sec + 4) != 1) return false;
    uint32_t co = le32(sec + 8), size = le32(sec + 0xc), c = le32(sec + 0x10);
    if (size == 0 || uint64_t(co) + size > c || uint64_t(c) + 0x880 > s_size) return false;
    if (le32(sec + c) != kCtrl || le32(sec + c + 0x704) != size) return false;
    out = {uint64_t(s_off) + co, uint64_t(s_off) + c, size};
    return true;
}

std::string stage_of(const std::vector<uint8_t>& d, uint64_t p, uint64_t c) {
    if (le32(d.data() + p) == kCodeCompute || le32(d.data() + c + 0x708) == 0) return "compute";
    if (p + 0x34 > d.size()) return "other";
    uint32_t t = (le32(d.data() + p + 0x30) >> 10) & 0xF;
    return t == 1 ? "vertex" : t == 5 ? "pixel" : "other";
}

void make_dir(const std::string& p) { mkdir(p.c_str(), 0755); }

void write_file(const std::string& path, const uint8_t* p, size_t n) {
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f || std::fwrite(p, 1, n, f) != n) {
        if (f) std::fclose(f);
        throw Fail("cannot write " + path + " (" + std::strerror(errno) + ")");
    }
    if (std::fclose(f) != 0) throw Fail("cannot write " + path);
}

struct Groups {
    std::string out;
    std::set<std::string> seen;
    std::map<std::string, std::string> manifest;  // group -> rows
    long blocks = 0;
};

void add_file(Groups& g, const std::string& group, const std::string& name, const std::vector<uint8_t>& data) {
    Parsed ps;
    if (!parse(data, ps)) return;
    const uint8_t* code = data.data() + ps.code;
    std::string h = sha1_16(code, size_t(ps.size));
    if (!g.seen.insert(h).second) return;
    std::string gdir = g.out + "/" + group;
    make_dir(gdir);
    std::string cf = "ctrl_" + sha1_16(data.data() + ps.ctrl, 0x880) + ".bin";
    write_file(gdir + "/code_" + h + ".bin", code, size_t(ps.size));
    write_file(gdir + "/" + cf, data.data() + ps.ctrl, 0x880);
    std::string stage = stage_of(data, ps.code, ps.ctrl);
    const uint8_t* c = data.data() + ps.ctrl;
    char line[768];
    std::snprintf(line, sizeof line, "%s/%s\t%s\t0x%llx\t0x%llx\t0x%llx\t0x%x\t0x%x\t0x%x\t0x%x\t0x%x\t%s\tcode_%s.bin\t%s\n",
                  group.c_str(), name.c_str(), stage.c_str(), (unsigned long long)ps.code, (unsigned long long)ps.size,
                  (unsigned long long)ps.ctrl, 0x880, le32(c + 0x708), le32(c + 0x6f8), le32(c + 0x700), le32(c + 0x6fc),
                  h.c_str(), h.c_str(), cf.c_str());
    g.manifest[group] += line;
    g.blocks++;
}

bool ieq(const std::string& a, const std::string& b) {
    if (a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); i++)
        if (std::tolower(static_cast<unsigned char>(a[i])) != std::tolower(static_cast<unsigned char>(b[i]))) return false;
    return true;
}

bool ends_with_ci(const std::string& s, const char* suffix) {
    size_t n = std::strlen(suffix);
    return s.size() >= n && ieq(s.substr(s.size() - n), suffix);
}

// The RomFS folder "data/nx/shader", whatever its case.
const nxi::GameImage::Entry* find_ci(const nxi::GameImage& game, const std::string& path) {
    if (const auto* e = game.find(path)) return e;
    std::string dir;
    size_t start = 0;
    while (start <= path.size()) {
        size_t next = path.find('/', start);
        std::string part = path.substr(start, next == std::string::npos ? std::string::npos : next - start);
        bool found = false;
        for (auto& [name, entry] : game.list(dir)) {
            std::string leaf = name.substr(name.rfind('/') == std::string::npos ? 0 : name.rfind('/') + 1);
            if (ieq(leaf, part)) {
                dir = dir.empty() ? leaf : dir + "/" + leaf;
                found = true;
                break;
            }
        }
        if (!found) return nullptr;
        if (next == std::string::npos) break;
        start = next + 1;
    }
    return game.find(dir);
}

}  // namespace

long extract_shaders(const nxi::GameImage& game, const std::string& out_dir,
                     const std::function<void(int, int)>& progress, std::string& error) {
    try {
        make_dir(out_dir);
        const std::string folder = "data/nx/shader";
        if (!find_ci(game, folder))
            throw Fail("the game file has no data/nx/shader (is it Yo-kai Watch 4?)");
        // the loose files of the folder and the CPK
        std::vector<std::pair<std::string, nxi::GameImage::Entry>> loose;
        const nxi::GameImage::Entry* cpk = nullptr;
        for (auto& [name, entry] : game.list(folder)) {
            if (entry.dir) continue;
            std::string leaf = name.substr(name.rfind('/') == std::string::npos ? 0 : name.rfind('/') + 1);
            if (ends_with_ci(leaf, ".cpk")) {
                if (ieq(leaf, "shader.cpk")) cpk = game.find(folder + "/" + leaf);
            } else {
                loose.push_back({leaf, entry});
            }
        }
        std::sort(loose.begin(), loose.end(), [](auto& a, auto& b) { return a.first < b.first; });
        std::vector<CpkFile> files;
        if (cpk) {
            files = cpk_files(game, *cpk);
            std::sort(files.begin(), files.end(), [](const CpkFile& a, const CpkFile& b) { return a.path < b.path; });
        }
        if (loose.empty() && files.empty()) throw Fail("no shader files in data/nx/shader");
        Groups g;
        g.out = out_dir;
        const int total = int(loose.size() + files.size());
        int done = 0;
        for (auto& [name, entry] : loose) {
            if (progress) progress(done++, total);
            std::vector<uint8_t> data(size_t(entry.size));
            if (game.read(entry, 0, data.data(), data.size()) != data.size()) throw Fail("cannot read " + name);
            add_file(g, "loose", name, data);
        }
        for (const CpkFile& f : files) {
            if (progress) progress(done++, total);
            std::vector<uint8_t> raw(size_t(f.size));
            if (game.read(*cpk, f.offset, raw.data(), raw.size()) != raw.size()) throw Fail("cannot read " + f.path);
            std::vector<uint8_t> data = f.extract != f.size ? crilayla(raw) : std::move(raw);
            std::string base = f.path.substr(f.path.rfind('/') == std::string::npos ? 0 : f.path.rfind('/') + 1);
            add_file(g, "shader_cpk", base, data);
        }
        for (auto& [group, rows] : g.manifest) {
            std::string m =
                "id\tstage\tcode_off\tcode_size\tctrl_off\tctrl_size\tprogram_start\tprogram_bytes\tconst_off\t"
                "const_size\tcode_sha1_16\tcode_file\tctrl_file\n" + rows;
            write_file(out_dir + "/" + group + "/manifest.tsv", reinterpret_cast<const uint8_t*>(m.data()), m.size());
        }
        if (progress) progress(total, total);
        if (g.blocks == 0) throw Fail("no HBH1 shaders found in data/nx/shader");
        return g.blocks;
    } catch (const Fail& e) {
        error = e.what();
    } catch (const std::bad_alloc&) {
        error = "out of memory";
    }
    return -1;
}

}  // namespace yokai4
