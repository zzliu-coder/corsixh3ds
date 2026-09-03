# 虚拟机验证结果

- 平台：`macOS-26.5.2-arm64-arm-64bit-Mach-O`
- Python：`3.14.6`
- CMake：`cmake version 4.3.4`
- GCC：`Apple clang version 21.0.0 (clang-2100.1.1.101)`
- Clang：`Apple clang version 21.0.0 (clang-2100.1.1.101)`

## 构建矩阵

| 矩阵 | CTest 总数 | 失败 | 结果 |
|---|---:|---:|---|
| clang-debug | 3 | 0 | 通过 |
| gcc-debug | 3 | 0 | 通过 |
| gcc-release | 3 | 0 | 通过 |
| gcc-sanitized | 3 | 0 | 通过 |

## 自动化覆盖

- C++ 测试：69 项，失败 0 项。
- Python/Lua/静态测试：83 项，跳过 2 项。
- C++ 重复稳定性：50 轮。
- Shell 语法检查：12 个脚本。
- 固定提交/哈希清单：通过。
- 实际上游 Lua API 契约：通过。
- 双屏模拟器预览：`artifacts/preview/dual-screen-preview.png`。

## 交叉编译与真机边界

- devkitARM `.3dsx` 交叉链接：通过。
- 交叉编译说明：已执行。
- Old 3DS 真机测试：未执行。

3DS API 桩编译只能证明移植层使用的函数形状和 C++ 语法。最终链接、帧率、音频、合盖、HOME、SD 卡和内存稳定性仍以 Old 3DS 真机结果为准。

## 模拟器输出 SHA-256

- `bottom.ppm`：`8f5bebc5c546bdafb26cfe3c2d3351664e9d4c8eb2c7d915e34d5894d0e7061f`
- `top.ppm`：`4a80c15cd28f7683506feb125162cae3d88066499be1f060655cfd068431e8f7`
- `trace.json`：`3bef0ea12d465e634cdc2c489dfe332e1fcafc93f2a9cc2d673ed692098404c8`
