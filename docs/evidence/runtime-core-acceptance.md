# Runtime Core acceptance evidence

Candidate source fingerprint: `095500bd278574938ef9094ddf6041cb319c46c1f44e69f56b198b055f925923`<br>
Git HEAD when verification ran: `f9b2919650a7a9e72640c4a09a2c75b520cdc792`

Host Runtime Core: **PASS**<br>
devkitARM cross-build: **PASS**<br>
Old 3DS device: **NOT_PROVEN**

| Gate | Result | Evidence |
|---|---|---|
| RH01 | PASS | synthetic every-kind converter and C++ mount/typed lookup tests |
| RH02 | PASS | two-root bundle and package SHA-256 equality tests |
| RH03 | PASS | mutation matrix plus AppleClang ASan/UBSan CTest |
| RH04 | PASS | selected-language dependency and unused-language exclusion tests |
| RH05 | PASS | AudioBank bounded stream spy <= 16,384 bytes and zero resident payload |
| RH06 | PASS | SpriteSheet bounded stream spy <= 65,536 bytes and zero unrequested pixels |
| RH07 | PASS | live/pin/dependency/LRU plus 10,000 owner and lifecycle cycles |
| RH08 | PASS | every-pool cap-1/cap/cap+1 arithmetic and atomic rejection tests |
| RH09 | PASS | missing/corrupt package plus save/transition/heap/linear reserve tests |
| RH10 | PASS | tracked-file scan and no-game package/release tests |

AppleClang ASan/UBSan completed with zero findings. LeakSanitizer is unavailable
in AppleClang on macOS and is recorded separately. The generated-bundle vertical
probe completed 10,000 acquire/level/menu/save/suspend/resume cycles and one
production mount/shutdown. A separate 10,000-cycle owner test repeated validated
mount adoption, transition, save and shutdown. Both ended with zero packages,
entries, leases and pins.

Final ELF SHA-256: `55fe05707129cd68edf572e2f81a721c30b19de691cdc7b214f432557a8b55f5`<br>
3DSX SHA-256: `027ce887bc3d6d26147e9a2f8228f2f4fe1ecce15e47c665415eba59939d2fd4`<br>
Linear heap proof: `8388608` bytes, strong `D` symbol<br>
Production call path: `cth3ds::runtime_initialize(lua_State*) → cth3ds::(anonymous namespace)::Runtime::initialize(lua_State*) → cth3ds::RuntimeSession::start(std::filesystem::__cxx11::path const&, cth3ds::RuntimeSessionConfig)`

Hardware boundary: RD01, RD02, RD03, RD04, RD05, RD06, RD07, RD08, RD09, RD10, RD11, RD12, RD13, RD14 remain **NOT_PROVEN**. Historical `S70 OOM` remains an
unsuperseded device **FAIL**. This run performed no device upload and used no
original game data.
