# Old 3DS 性能模型与 v0.5.0 的改动

本文记录 0.5.0 为什么改这些地方，以及每一项的量级依据。所有耗时都按 Old 3DS
的 ARM11 @ 268 MHz、无硬件除法器、无 SIMD、L1 D-cache 16 KB 估算。

## 硬件预算

| 项目 | Old 3DS |
|---|---|
| CPU | ARM11 MPCore，应用可用约 1 核 @ 268 MHz，ARMv6K，VFPv2，无 NEON |
| 除法 | **没有硬件除法指令**，`/` 编译成 `__aeabi_*div*` 库调用 |
| 上屏 | 400x240，帧缓冲按列存储（旋转 90°） |
| 下屏 | 320x240 |
| 显存 | 6 MB VRAM；SDL2 的 N3DS 后端把帧缓冲放在 FCRAM，走 CPU 拷贝 |

一帧要在 16.7 ms 内画完才有 60 fps。下面每一项都以「毫秒/帧」计。

## 1. 帧缓冲拷贝：约 40–60 ms → 约 3 ms

SDL2 的 N3DS 后端逐像素把窗口 surface 拷进 LCD 帧缓冲。0.4.0 的 letterbox 补丁
在这个循环里做了 64 位乘法和 **64 位除法**：

```c
const int source_x = (int)(((Sint64)x * source_dim.width) / viewport.width);
```

用 `arm-none-eabi-gcc -O2 -march=armv6k` 编译 0.4.0 的补丁块，反汇编可以看到
`bl __aeabi_ldivmod` 就在最内层循环里。上屏一次 present 是 320x240 = 76,800 个
像素，每个像素一次软件 64 位除法（ARM11 上约 100–300 周期），再加 400x240 的
全屏清屏和逐像素跨 960 字节的散写。

0.5.0 改成：

- 用增量整数步进预先算出采样表（等价于 `floor(d * span / viewport)`，无除法）；
- 外层循环走目标列、内层走行，使写入在帧缓冲里**连续**；
- 只画左右黑边，不再每帧清整屏。

同样的编译条件下，最内层循环是 4 条指令、零除法：

```
ldr r2, [r0, #4]!        ; 采样表
add r2, r8, r2
ldr r2, [r5, r2, lsl #2] ; 源像素
str r2, [r3], #-4        ; 连续写入帧缓冲
```

`scripts/check_arm_codegen.sh` 把这条约束固化成检查：present 路径里允许的除法调
用点最多 2 个（就是每帧一次的宽高比计算），超过就报错。该脚本对 0.4.0 的补丁块
会失败，对 0.5.0 通过。

`tests/test_letterbox_equivalence.py` 另外把补丁块编译出来，和独立实现逐像素比
对，覆盖 640x480、320x240 和若干奇数尺寸。

## 2. CorsixTH 每帧的中间纹理：约 30–40 ms → 0

`CorsixTH/Src/th_gfx_sdl.cpp` 的 `render_target::set_scale_factor()`：当
`direct_zoom` 为 false 且渲染器支持 render target 时，**每次调用**都会

1. `SDL_CreateTexture(TARGET, 640x480)` — 1.2 MB 分配；
2. `SDL_RenderClear` — 1.2 MB memset；
3. 帧末析构时 `SDL_RenderCopy`，且纹理是 `SDL_BLENDMODE_BLEND` — 307,200 像素的
   **全屏 alpha 混合**。

`Lua/ui.lua` 的 `UI:draw` 每帧都会 `canvas:scale(1)`，也就是每帧都触发一次。软件
渲染器上一次全屏 alpha 混合按每像素 20–30 周期算就是 6–9 M 周期。

0.4.0 的 3DS 配置写的正是 `direct_zoom = false`。0.5.0 改成 `true`。窗口用的是
`SDL_WINDOW_FULLSCREEN` 而不是 `SDL_WINDOW_FULLSCREEN_DESKTOP`，所以 direct 分支
里那个「全屏时额外开一张 buffer」的条件不成立，等于完全没有中间纹理。

代价是 direct 路径下缩放会作用到每个精灵的目标矩形上。所以适配层把缩放锁死在
1.0（`Platform:adjustZoom` 变成空操作并在下屏提示），保证所有 blit 都走
`SDL_BlitSurface` 快路径，不会落到 `SDL_BlitScaled`。

## 3. 缩放质量 hint

`SDL_HINT_RENDER_SCALE_QUALITY` 原本是 `"linear"`，任何需要缩放的 blit 都会走
SDL 的双线性软件拉伸。3DS 上改成 `"nearest"`。

注意有两处调用点：`render_target` 构造函数设默认值，`create_texture_from_pixels`
在临时切到 nearest 之后**恢复**成 linear。只改第一处的话，第一张 nearest 精灵之
后所有纹理又会被恢复成 linear。0.5.0 用一个 `CORSIXTH_3DS_SCALE_QUALITY` 宏同时
覆盖两处，集成器的测试会断言两处都被改到。

## 4. 下屏：每次重绘约 30 ms → 约 4 ms，且大部分帧不重绘

三个问题各自解决：

- `SoftwareCanvas::fill_rect` 逐像素调用带边界检查的 `pixel()`。一次全屏清屏就是
  76,800 次函数调用。改成按行填充 + `memcpy` 复制后续行，`clear()` 在单色时直接
  `memset`。
- `SDL_ConvertPixels` 每次重绘对 76,800 像素跑通用逐像素格式转换。N3DS 的显示格
  式是 `SDL_PIXELFORMAT_RGBA8888`，和画布的 RGBA 字节序只差一次字节反转，ARM 上
  就是一条 `rev`。0.5.0 走专用路径，格式不匹配时才回退到 `SDL_ConvertPixels`。
- `set_state` 以前无条件置脏，Lua 每 250 ms 同步一次就等于每 250 ms 强制重绘一
  次下屏。现在 `BottomUiState` 有 `operator==`，内容真的变了才置脏；Lua 侧也加了
  一层相同的过滤，玩家自己操作时再绕过过滤立即刷新。
- 状态同步周期 250 ms → 500 ms，系统状态 1 s → 2 s，电量 5 s → 10 s。

## 预期合计

| 阶段 | 0.4.0 | 0.5.0 |
|---|---|---|
| 上屏 present | 40–60 ms | 约 3 ms |
| 下屏 present | 40–60 ms | 约 3 ms，且多数帧跳过 |
| 下屏软件绘制 | 10–20 ms | 1–2 ms，且多数帧跳过 |
| CorsixTH 中间纹理 | 30–40 ms | 0 |
| CorsixTH 自身软件光栅化 | 30–80 ms | 30–80 ms（未改动） |

也就是说：**每帧砍掉大约 120–180 ms 的纯开销**，剩下的主要成本是 CorsixTH 自己
在 640x480 下的软件光栅化。

## 剩下的天花板（诚实说明）

CorsixTH 在 640x480 用 SDL 软件渲染器画完整个医院场景，本身就要几十毫秒。即使上
面全部生效，Old 3DS 上现实的目标是**菜单 20–30 fps、游戏内 10–20 fps**。60 fps
在这台机器上做不到。要再上一个台阶只有两条路，都还没做：

1. 把 present 换成 citro3d：把 640x480 缓冲通过 `GX_DisplayTransfer` 转成 tiled
   纹理，用 GPU 画一个全屏四边形。缩放和双线性过滤由 GPU 免费完成。风险是要接管
   SDL 的 N3DS 帧缓冲后端，且必须在真机上调。
2. 降低内部分辨率。但 CorsixTH 的全屏对话框（城镇地图、银行、研究、员工管理、
   报表、病例本）都是 640x480 的位图，降分辨率会把它们裁掉，属于功能损失。

在没有真机可测的前提下，0.5.0 只做了第 1 类里零风险的部分（CPU 拷贝优化），把
GPU 路径留给有真机反馈时再上。
