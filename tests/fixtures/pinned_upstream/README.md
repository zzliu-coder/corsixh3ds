# 固定上游测试资料

来源：CorsixTH v0.70.1，提交 `56bd5d00f76331c7f76d7b696726a7926303ca0c`。
这些是保留原版权声明的 MIT 引擎源码，不含原版游戏数据或存档。

`sources.zlib.b64` 为原20个文件的 JSON 经 zlib/base64 编码，沿用原测试字节；
另两个文件继续使用上一级的 `th_gfx_sdl.h.pinned` 与 `save_game.lua.pinned`。
另含 R51 的 `th_pathfind.cpp.pinned`，来自同一固定提交的原始字节。
`sha256.json` 列出全部23个文件的展开后摘要。

`tests/support/pinned_upstream.py` 在使用前逐文件校验，并验证二次组装内容一致。
更新资料必须来自明确的上游提交，同时更新摘要；不可用已经打补丁的产物替换原始输入。
