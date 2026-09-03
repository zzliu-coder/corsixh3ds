# CorsixTH Old 3DS Port

这是一个面向 **Old Nintendo 3DS** 的 CorsixTH 0.70.1 移植工程。工程已经移除所有裸眼 3D 路径，目标形态固定为：

- 上屏 400×240：医院主画面；CorsixTH 继续使用 640×480 逻辑画布，由 SDL2 N3DS 补丁等比缩放并留边。
- 下屏 320×240：触控管理台，负责状态、建造、员工、病人、财务和消息。
- 实体键：圆形摇杆移动镜头，十字键精确移动，A/B 确认取消，X/Y 上下文操作，L/R 缩放或切换分类，Start 暂停，Select 打开总览。
- 生命周期：HOME、合盖、休眠、恢复和退出均接入；保存采用临时文件、`fsync`、备份轮换和原子替换。
- 硬件状态：电池、音量、Wi‑Fi 强度和可用内存显示在下屏。

当前交付状态：**平台代码、CorsixTH 补丁器、Lua 适配层、资源打包器、双屏模拟器、devkitARM `.3dsx` 交叉链接和虚拟机测试已经组成可审计工程。Old 3DS 真机可玩性仍需实机验收。**

## 0.6.0 变更摘要

两块屏幕现在显示的都是游戏本身，下屏可以直接用手指操作原版界面。

- **上屏**：CorsixTH 帧的 1:1 居中裁切，医院用原始像素显示，不再缩到一半。
- **下屏**：同一帧的精确 2:1 缩略 —— 完整的 640×480 界面，工具栏和所有对话框都在，
  触摸坐标乘 2 就是游戏坐标。原来那套自制管理面板退居备用（在 SD 卡上建
  `bottom-screen-panel.txt` 即可切回）。
- **音乐显式关闭**（`play_music = false`）。原版音乐是 XMI/MIDI，这个构建没有 MIDI
  合成器；不关的话 CorsixTH 会给每条曲目各起一个加载线程去试、全部失败，白拖慢启动。
  音效不受影响。
- 游戏内容完整性写进了 `docs/GAME_COMPLETENESS.md`：12 关原版战役、23 种房间、
  34 种疾病、43 类物件全在，移植层一行游戏逻辑都没改。缺的只有过场动画、音乐、
  中文字体三项，原因逐条写明。

布局的取舍和实现见 `docs/SCREEN_LAYOUT.md`。

## 0.5.0 变更摘要

0.4.0 在真机上表现为「开机图出现后卡死、载入极慢、退出无响应」，下屏只显示一句
`STATE: 3DS ADAPTER IS NOT ATTACHED`。0.5.0 针对这四个症状：

- **present 路径**：SDL2 N3DS 帧缓冲拷贝原本在每像素循环里做一次 64 位软件除法
  （ARM11 没有硬件除法器）。改成整数采样表 + 目标内存顺序写入后，最内层循环是
  4 条指令、零除法。见 `docs/PERFORMANCE.md`。
- **每帧中间纹理**：3DS 配置里的 `direct_zoom = false` 让 CorsixTH 每帧分配、清
  空并 alpha 合成一张 640×480 render target。改为 `true`，并把缩放锁死为 1.0。
- **下屏**：按行填充替代逐像素、专用字节序转换替代 `SDL_ConvertPixels`、状态真
  正变化才重绘。
- **可诊断性**：SD 卡上的不带缓冲启动日志、下屏显示 overlay 版本与适配层来源、
  运行时自挂载适配层（含编译进二进制的兜底副本）、所有 Lua 调用进保护调用、
  `std::bad_alloc` 转成屏幕提示，不再走到 `std::terminate`。见
  `docs/BOOT_DIAGNOSTICS.md`。
- **退出**：`APTHOOK_ONEXIT` 在 APT 线程上立即推 `SDL_QUIT`，不再等主线程跑完当
  前帧。

真机验收步骤见 `docs/HARDWARE_TEST_PLAN.md`；先看下屏第二行的版本/来源标签，再取
`sdmc:/3ds/corsixth/boot.log`。

## 已实现范围

| 模块 | 实现 | 虚拟机验证 |
|---|---:|---:|
| CorsixTH 0.70.1 固定版本与 API 契约 | 完成 | 完成 |
| SDL2 N3DS 640×480 → 400×240 等比缩放 | 完成 | 补丁夹具与静态检查完成 |
| 第二 SDL 窗口与 320×240 下屏 UI | 完成 | API 桩编译、模拟器完成 |
| 圆形摇杆、十字键、A/B/X/Y/L/R/Start/Select | 完成 | 单元测试完成 |
| 触摸、拖拽建房、单击/双击/长按 | 完成 | 单元与 Lua 测试完成 |
| 上游 Lua 操作桥接 | 完成 | Lua 5.4 运行时测试完成 |
| 存档原子提交、备份和恢复 | 完成 | 文件系统故障路径测试完成 |
| 休眠、恢复、退出、周期自动保存 | 完成 | 状态机测试与 3DS 桩编译完成 |
| 双屏状态与硬件遥测 | 完成 | 模拟器与静态检查完成 |
| 音效空间声像与环形缓冲基础 | 完成 | 单元测试完成 |
| Theme Hospital 原版数据校验与 SD 卡分发 | 完成 | 打包器测试完成 |
| 裸眼 3D | 已排除 | 全仓扫描测试完成 |

## 最短使用路径

### 1. 在普通电脑上跑全部主机测试

```bash
./scripts/build_host.sh
./scripts/test_all.sh
```

结果写入：

```text
artifacts/verification/summary.json
artifacts/verification/report.md
artifacts/preview/dual-screen-preview.png
```

### 2. 使用已安装 devkitPro 的环境交叉编译

```bash
export DEVKITPRO=/opt/devkitpro
export DEVKITARM=/opt/devkitpro/devkitARM
./scripts/build_3ds.sh
```

产物目标：

```text
build-3ds/CorsixTH/CorsixTH-3DS.3dsx
```

本工程已在 macOS 上用 devkitARM 生成并校验该 `.3dsx`；这项结果仍不等同于 Old 3DS 真机验收。

### 3. 使用 Docker 或 Podman 交叉编译

```bash
./scripts/build_3ds_docker.sh
```

容器脚本会安装固定清单中的 3DS 依赖，拉取固定提交，应用补丁，构建 `.3dsx` 并生成 SD 卡目录。

### 4. 准备原版游戏数据

```bash
./scripts/package_sd.sh --theme-hospital "/path/to/Theme Hospital"
```

如果只需要运行目录，不保留额外的审计归档，可加 `--no-data-pack`。原版数据只会从你指定的本地目录复制，不随公开源码发布。

公开包不包含 EA 的原版美术、声音和关卡。用户需要自行提供合法游戏数据。

## 目录

```text
include/cth3ds/       平台无关核心接口
src/common/           输入、UI、保存、生命周期、音频、遥测
src/3ds/              libctru / SDL2 N3DS 运行时
src/host/             无窗口双屏模拟器
lua/3ds/              CorsixTH Lua 适配层
config/                固定提交与上游 Lua API 契约
tools/                 补丁器、打包器、预览与发布工具
scripts/               主机、交叉编译、容器、SD 卡、验证脚本
tests/                 C++、Python、Lua 和静态契约测试
docs/                  架构、验证与真机测试说明
```

## 关键约束

1. Old 3DS 的性能目标是稳定 30 FPS。主画面继续由 CorsixTH SDL 渲染，首版不引入 Citro2D 重写，以控制接入变量。
2. 下屏 UI 为独立 320×240 SDL 软件帧缓冲，按状态变化重绘。
3. 上游严格固定在 CorsixTH `v0.70.1` / `56bd5d00...`。补丁锚点或 Lua API 发生漂移时，构建立即失败。
4. 电影、在线更新、MIDI 设备、Tracy、AnimView 和额外工具在 3DS 构建中关闭。
5. 本仓库不包含 CorsixTH 上游源码；`scripts/bootstrap_upstream.sh` 拉取并打补丁。

详细说明见 [架构](docs/ARCHITECTURE.md)、[上游接入](docs/UPSTREAM_INTEGRATION.md)、[虚拟机验证](docs/VM_VERIFICATION.md) 和 [真机验收](docs/HARDWARE_TEST_PLAN.md)。
