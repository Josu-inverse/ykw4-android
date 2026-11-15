// Yo-kai Watch 4 is built with Nintendo SDK 7.3.2. runtime/src/hle_net.cpp keeps the console offline for the
// signatures of newer SDKs (socket functions take enums there, ints here), so with this main most of its hooks never
// match and the sdk's own code would talk to bsd:u, nifm:u and ssl, services the runtime does not provide. These are
// the same fallbacks for the signatures in this game's main (symbols copied from tools/yokai_probe.py --symbols-out).
//
// Only functions that go over IPC are hooked. The pure ones (Inet*, GAIStrError, SetLastErrno, the ErrorResultVariant
// members, nn::mem allocators, nn::hid vibration classes) run natively in the sdk.
//
// Not covered yet, left for the first boot log: nn::ldn, nn::nfc, nn::swkbd, nn::web, nn::friends, nn::ec, and the
// fs functions RenameFile, DeleteDirectory, MountAddOnContent (see games/yokai4/NOTES.md).
#include <nx/runtime.h>

namespace nx {

namespace {

constexpr uint32_t kNifmNoNetwork = (3400u << 9) | 110u;  // same values as hle_net.cpp
constexpr uint32_t kGenericFail = (1u << 9) | 110u;

void ok(CPU& c) { c.x[0] = 0; }
void minus_one(CPU& c) { c.x[0] = uint64_t(-1); }
void null_ptr(CPU& c) { c.x[0] = 0; }
void result_fail(CPU& c) { c.x[0] = kGenericFail; }
void nifm_fail(CPU& c) { c.x[0] = kNifmNoNetwork; }
void enetdown(CPU& c) { c.x[0] = 50; }  // ENETDOWN, as hle_net.cpp's GetLastError
void eai_fail(CPU& c) { c.x[0] = 4; }   // EAI_FAIL
// SDK 7: u32 ProfanityFilter::GetContentVersion() (newer SDKs: Result f(u32* out), hooked in svc_misc.cpp).
void ngc_content_version(CPU& c) { c.x[0] = 1; }
void show_error_variant(CPU& c) {
    log("nn::err::ShowError(ErrorResultVariant at %#llx)", static_cast<unsigned long long>(c.x[0]));
}

}  // namespace

// nn::socket, the C++ API with the SDK 7 signatures (sockaddr and int arguments instead of SockAddr and enums).
NX_HLE("_ZN2nn6socket8FinalizeEv", ok);
NX_HLE("_ZN2nn6socket6SocketEiii", minus_one);
NX_HLE("_ZN2nn6socket7ConnectEiPK8sockaddrj", minus_one);
NX_HLE("_ZN2nn6socket4BindEiPK8sockaddrj", minus_one);
NX_HLE("_ZN2nn6socket6AcceptEiP8sockaddrPj", minus_one);
NX_HLE("_ZN2nn6socket4PollEP6pollfdmi", minus_one);
NX_HLE("_ZN2nn6socket4RecvEiPvmi", minus_one);
NX_HLE("_ZN2nn6socket4SendEiPKvmi", minus_one);
NX_HLE("_ZN2nn6socket8RecvFromEiPvmiP8sockaddrPj", minus_one);
NX_HLE("_ZN2nn6socket8RecvFromEiPvmNS0_7MsgFlagEPNS0_8SockAddrEPj", minus_one);
NX_HLE("_ZN2nn6socket6SendToEiPKvmiPK8sockaddrj", minus_one);
NX_HLE("_ZN2nn6socket6SendToEiPKvmNS0_7MsgFlagEPKNS0_8SockAddrEj", minus_one);
NX_HLE("_ZN2nn6socket5FcntlEiiz", minus_one);
NX_HLE("_ZN2nn6socket8ShutdownEii", minus_one);
NX_HLE("_ZN2nn6socket10GetSockOptEiiiPvPj", minus_one);
NX_HLE("_ZN2nn6socket10SetSockOptEiiiPKvj", minus_one);
NX_HLE("_ZN2nn6socket11GetSockNameEiP8sockaddrPj", minus_one);
NX_HLE("_ZN2nn6socket12GetLastErrnoEv", enetdown);
NX_HLE("_ZN2nn6socket11GetAddrInfoEPKcS2_PK8addrinfoPPS3_", eai_fail);
NX_HLE("_ZN2nn6socket12FreeAddrInfoEP8addrinfo", ok);

// The C API (libcurl and NEX call these directly).
NX_HLE("nnsocketSocket", minus_one);
NX_HLE("nnsocketConnect", minus_one);
NX_HLE("nnsocketBind", minus_one);
NX_HLE("nnsocketPoll", minus_one);
NX_HLE("nnsocketRecv", minus_one);
NX_HLE("nnsocketSend", minus_one);
NX_HLE("nnsocketClose", minus_one);
NX_HLE("nnsocketFcntl", minus_one);
NX_HLE("nnsocketGetSockOpt", minus_one);
NX_HLE("nnsocketSetSockOpt", minus_one);
NX_HLE("nnsocketGetSockName", minus_one);
NX_HLE("nnsocketGetPeerName", minus_one);
NX_HLE("nnsocketResolverGetOption", minus_one);
NX_HLE("nnsocketResolverSetOption", minus_one);
NX_HLE("nnsocketGetLastErrno", enetdown);
NX_HLE("nnsocketGetHostByNameWithOptions", null_ptr);  // hostent*: no host

// nn::ssl: no TLS without a network. Initialize and Create fail, so nothing after them is reached; the teardown
// calls succeed.
NX_HLE("nnsslInitialize", result_fail);
NX_HLE("nnsslFinalize", ok);
NX_HLE("nnsslConnectionCreate", result_fail);
NX_HLE("nnsslConnectionDestroy", ok);
NX_HLE("nnsslContextDestroy", ok);
NX_HLE("nnsslContextGetContextId", result_fail);
NX_HLE("nnsslConnectionGetConnectionId", result_fail);
NX_HLE("nnsslConnectionDoHandshakeWithCertBuffer", result_fail);
NX_HLE("nnsslConnectionGetVerifyCertError", result_fail);
NX_HLE("nnsslConnectionPending", result_fail);
NX_HLE("nnsslConnectionRead", result_fail);
NX_HLE("nnsslConnectionWrite", result_fail);
NX_HLE("nnsslConnectionSetHostName", result_fail);
NX_HLE("nnsslConnectionSetIoMode", result_fail);
NX_HLE("nnsslConnectionSetOption", result_fail);
NX_HLE("nnsslConnectionSetSessionCacheMode", result_fail);
NX_HLE("nnsslConnectionSetSocketDescriptor", result_fail);
NX_HLE("nnsslConnectionSetVerifyOption", result_fail);
NX_HLE("_ZN2nn3ssl7Context15ImportServerPkiEPmPKcjNS0_17CertificateFormatE", result_fail);

// nn::nifm: the two functions hle_net.cpp does not have.
NX_HLE("_ZN2nn4nifm19SetLocalNetworkModeEb", ok);
NX_HLE("_ZN2nn4nifm26GetCurrentPrimaryIpAddressEP7in_addr", nifm_fail);

// Profanity filter and error applet with the SDK 7 signatures.
NX_HLE("_ZN2nn3ngc15ProfanityFilter17GetContentVersionEv", ngc_content_version);
NX_HLE("_ZN2nn3err9ShowErrorERKNS0_18ErrorResultVariantE", show_error_variant);

// nv: the one graphics call hle_vi.cpp does not have (shutdown).
NX_HLE("_ZN2nv16FinalizeGraphicsEv", ok);

}  // namespace nx
