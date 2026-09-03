# Old 3DS 资源架构与 TH3DS 二进制契约

状态：**Contract v1.0 / host packer implemented / runtime loader pending**

冻结源码基线：`9fbaeb6210108e27363c2bbc39769d70f2d41ea2`

目标硬件：Old 3DS，CorsixTH 0.70.1，Lua 5.4，SDL2 软件渲染路径

配套内存契约：`docs/OLD3DS_MEMORY_BUDGET.md`

本文冻结资源文件、加载边界、缓存所有权和错误行为。本文没有授权修改
CorsixTH 规则、存档格式或原版 Theme Hospital 数据。打包器只消费用户合法持有的
本地数据，生成物只用于该用户自己的设备和备份；源码仓库、源码发布包和无游戏数据
发布包都不得包含原版数据或由原版数据转换出的资源包。

## 1. 结论

Old 3DS 的资源成功路径只有一条：在主机上把大文件拆成可独立校验、独立解码的块，
运行时只挂载当前语言和当前场景，所有二进制内存统一由一个有硬上限的资源管理器拥有。

```text
用户持有的 Theme Hospital 数据 + CorsixTH 开放资源
                 │
                 ▼
        确定性主机打包器（离线转换）
                 │
                 ├── bundle.th3ds.json
                 ├── core.th3ds
                 ├── lang/<selected-tag>.th3ds
                 └── level/<level-id>.th3ds（按需）
                              │
                              ▼
                BundleMount + ResourceCatalog
                              │
                              ▼
                 ResourceManager（唯一所有者）
                  ├── AudioLease
                  ├── SpriteLease
                  ├── TextureLease
                  ├── UiBitmapLease
                  └── Font/LanguageLease
```

运行时禁止把大资源放进 Lua 字符串，禁止子系统保留第二份原始归档，禁止 SDL_mixer
自行拥有一套无法计量的完整声音库，禁止精灵表永久持有所有解码像素，禁止纹理绕过
中央预算。

## 2. 证据分类

本文使用三类结论：

- **MEASURED**：由当前真机日志或本地文件尺寸直接得到。
- **DERIVED**：由 MEASURED 数据和源码生命周期推导，仍需实现后测量复核。
- **DECISION**：本契约冻结的设计和阈值；实现不得自行放宽。

另用 **SOURCE** 标记冻结基线中可直接检查的控制流和所有权事实。

### 2.1 当前事实

| ID | 类别 | 事实 | 证据 |
|---|---|---|---|
| E01 | MEASURED | v0.6.1 真机 `envGetHeapSize()` 为 56,180,736 B（56.180736 MB，53.578125 MiB）；显式线性堆为 8,388,608 B。 | `work/hardmac-runs/20260902-174010-postlaunch-diagnosis/boot.log` |
| E02 | MEASURED | S70 快照报告 `uordblks=55,124,320 B`、`fordblks=1,015,408 B`、Lua 22,295,372 B；随后以 `FATAL: not enough memory` 退出。 | 同上 |
| E03 | MEASURED | 致命快照报告 `uordblks=55,193,952 B`、`fordblks=945,776 B`。最后成功阶段是 S70，没有 S80、S90 或 S100。当前日志未记录 `mallinfo.arena`，所以 `fordblks` 只代表 allocator arena 内的空闲块。 | 同上 |
| E04 | MEASURED | 当前用户数据中的 `SOUND-0.DAT` 为 16,634,862 B（15.864241 MiB）。 | `work/hardmac-runs/20260902-135102/release-dist/sd-card/3ds/corsixth/game/SOUND/DATA/SOUND-0.DAT` |
| E05 | MEASURED | 冻结的 CorsixTH 树包含 24 个语言 Lua 文件，源文件总量约 3.2 MiB。 | `external/CorsixTH/CorsixTH/Lua/languages/` |
| E06 | SOURCE | `FileSystem:readContents()` 以 `f:read("*a")` 把整个声音归档放入 Lua 字符串；`sound_archive::load_from_th_file()` 再复制到 `std::vector<uint8_t>`；`sound_player::populate_from()` 对每个条目调用 `Mix_LoadWAV_RW()`。 | `Lua/filesystem.lua`、`Lua/audio.lua`、`Src/th_sound.cpp` |
| E07 | SOURCE | `Strings:init()` 遍历语言目录，对每个 `.lua` 调用 `loadfile_envcall()`，随后逐个执行到 `Language()`。 | `Lua/strings.lua` |
| E08 | SOURCE | S70 调用 `loadAnimations("Data", "V")`；`sprite_sheet::load_from_th_file()` 遍历整张表并为每个非空精灵生成解码像素。首次绘制又创建 `SDL_Texture`，普通和替换调色板纹理会保留到精灵释放。 | `Lua/app.lua`、`Lua/graphics.lua`、`Src/th_gfx_sdl.cpp` |
| E09 | SOURCE | S80 位于游戏定义加载之后；C++ 运行时在 S90 初始化并调用 `ensure_adapter()`。S70 退出时新下屏适配器尚未开始。 | `Lua/app.lua`、`Src/3ds/runtime_3ds.cpp` |
| E10 | SOURCE | 当前 `CTH3DPK1` 包只用于确定性审计，manifest 明确写着 `pack_runtime_mounted: false`；运行时仍读取 loose `game/` 树。 | `tools/th3ds_pack.py` |

### 2.2 推导

| ID | 类别 | 推导 |
|---|---|---|
| D01 | DERIVED | `SOUND-0.DAT` 载入峰值至少同时存在 Lua 和 C++ 两份完整内容，共 33,269,724 B（31.728481 MiB）；SDL_mixer 解码块另行占用内存。具体 SDL_mixer 峰值仍需新遥测量出。 |
| D02 | DERIVED | 只缩小线性堆无法让当前启动结构稳定。v0.6.1 已得到 53.58 MiB 常规堆，S70 仍用到 52.57 MiB 并退出。 |
| D03 | DERIVED | 只处理声音仍不足以形成资源上限。语言编译、V 精灵解码和纹理累积都缺少预算边界。 |
| D04 | DERIVED | 选择单语言、按声音块解码、按精灵块解码和中央纹理 LRU 可以消除已确认的无上限增长点。能节省多少必须由新实现的分类遥测证明。 |

## 3. 资源包族

**DECISION R01**：TH3DS v1 是一组可独立校验的包：

| 文件 | 必需性 | 内容 | 挂载寿命 |
|---|---|---|---|
| `bundle.th3ds.json` | 必需 | 包清单、当前语言、包 SHA-256、源数据集合指纹 | 启动至退出 |
| `core.th3ds` | 必需 | 启动页、主菜单、共享 UI、共享声音、共享精灵索引 | 启动至退出 |
| `lang/<bcp47>.th3ds` | 必需且只挂载一个 | 已解析继承的单语言字符串、该语言字形图集 | 启动至语言切换/退出 |
| `level/<level-id>.th3ds` | 按关卡必需 | 该关卡专用地图、资源块和预取组 | 关卡转换至离开关卡 |

语言切换采用保存配置后重启。运行中不得同时挂载两个完整语言包。`level` 包可以在后续
实现中合并进 `core`，但目录、索引和缓存行为仍须保持按关卡可卸载，且必须继续满足
内存契约。

包文件和 bundle manifest 都是由用户数据在本地生成的派生物，不进入 Git，也不进入
无游戏数据发布包。允许提交的只有格式实现、合成测试夹具和不含原版内容的 schema。

## 4. 容器字节序和头部

**DECISION R02**：所有整数为无符号 little-endian；有符号字形度量使用 two's
complement little-endian。文件默认对齐为 64 B，音频数据块对齐为 4096 B。所有保留
字段必须写零，读取到非零保留字段时 v1 加载器返回 `E_HEADER_RESERVED`。

魔数的 8 个字节固定为：

```text
54 48 33 44 53 52 31 00    # "TH3DSR1\0"
```

固定头部为 256 B：

| Offset | Size | 字段 | v1 值/语义 |
|---:|---:|---|---|
| `0x00` | 8 | `magic` | `TH3DSR1\0` |
| `0x08` | 2 | `header_size` | `256` |
| `0x0A` | 2 | `version_major` | `1` |
| `0x0C` | 2 | `version_minor` | `0` |
| `0x0E` | 2 | `header_flags` | v1 为 `0` |
| `0x10` | 4 | `endian_tag` | 数值 `0x01020304`；磁盘字节为 `04 03 02 01` |
| `0x14` | 4 | `default_alignment` | `64` |
| `0x18` | 4 | `package_role` | `1=core, 2=language, 3=level` |
| `0x1C` | 4 | `index_entry_size` | `128` |
| `0x20` | 8 | `manifest_offset` | 64 B 对齐的绝对偏移 |
| `0x28` | 8 | `manifest_size` | canonical JSON 字节数 |
| `0x30` | 8 | `index_offset` | 64 B 对齐的绝对偏移 |
| `0x38` | 4 | `index_count` | 最大 65,535 |
| `0x3C` | 4 | `reserved_0` | `0` |
| `0x40` | 8 | `metadata_offset` | 64 B 对齐的绝对偏移 |
| `0x48` | 8 | `metadata_size` | kind-specific metadata 总字节数 |
| `0x50` | 8 | `data_offset` | 64 B 对齐的绝对偏移 |
| `0x58` | 8 | `data_size` | data 区总字节数 |
| `0x60` | 8 | `build_epoch` | 固定为 `0`，禁止把时间写入确定性内容 |
| `0x68` | 32 | `catalog_sha256` | `index || metadata` 原始字节的 SHA-256 |
| `0x88` | 32 | `payload_sha256` | data 区原始字节的 SHA-256 |
| `0xA8` | 32 | `container_sha256` | 整个文件的 SHA-256；计算时把本字段 32 B 置零 |
| `0xC8` | 32 | `source_set_sha256` | 第 7.2 节定义的源数据集合指纹 |
| `0xE8` | 4 | `required_runtime_abi` | v1 初值 `1` |
| `0xEC` | 4 | `required_feature_bits` | v1 已知必需特性位 |
| `0xF0` | 16 | `reserved_1` | 全零 |

所有 offset/size 都必须先做无溢出范围校验，再执行 seek 或分配。各区域不得重叠，填充
字节必须为零。索引按 16 B resource ID 的字节序严格递增，重复或乱序都视为损坏。

## 5. 通用索引

每条索引固定 128 B：

| Offset | Size | 字段 | 语义 |
|---:|---:|---|---|
| `0x00` | 16 | `resource_id` | 第 7.1 节定义的稳定 ID |
| `0x10` | 2 | `kind` | 见下表 |
| `0x12` | 2 | `codec` | `0=NONE, 1=ZLIB, 2=DSP_ADPCM` |
| `0x14` | 4 | `flags` | `REQUIRED=1, PIN_ON_MOUNT=2, STREAMABLE=4` |
| `0x18` | 4 | `group_id` | manifest 中的预取/生命周期组 |
| `0x1C` | 1 | `alignment_log2` | v1 为 `6` 或音频的 `12` |
| `0x1D` | 3 | `reserved_0` | 全零 |
| `0x20` | 8 | `data_offset` | 文件内绝对偏移 |
| `0x28` | 4 | `stored_size` | 压缩后字节数，最大 64 MiB |
| `0x2C` | 4 | `decoded_size` | 完整逻辑资源大小；流式资源不得据此整块分配 |
| `0x30` | 8 | `meta_offset` | metadata 区内相对偏移 |
| `0x38` | 4 | `meta_size` | metadata 字节数，最大 1 MiB/资源 |
| `0x3C` | 2 | `dependency_count` | metadata 开头的 16 B 依赖 ID 数量 |
| `0x3E` | 2 | `reserved_1` | 全零 |
| `0x40` | 32 | `stored_sha256` | 当前资源全部存储字节的 SHA-256 |
| `0x60` | 32 | `decoded_sha256` | 逻辑解码内容的 SHA-256 |

v1 kind：

| 值 | 名称 | 内容 |
|---:|---|---|
| 1 | `AUDIO_BANK` | 带逐 clip 随机访问索引的转换后声音库 |
| 2 | `LANGUAGE_BUNDLE` | 仅含选中语言静态继承闭包的有界资源 |
| 3 | `SPRITE_SHEET` | 精灵索引和独立压缩块 |
| 4 | `UI_BITMAP` | 预转换的 RGB565/RGBA5551 位图 |
| 5 | `FONT_ATLAS` | 预栅格化字形页 |
| 6 | `FONT_MAP` | codepoint、字形度量和 kerning |
| 7 | `PALETTE` | 256 色 RGBA8888 调色板 |
| 255 | `OPAQUE_BLOB` | 仅限明确有界的小型兼容资源 |

未知 kind、codec、必需 flag 或 feature bit 返回 `E_UNSUPPORTED_FEATURE`。v1 禁止使用
`OPAQUE_BLOB` 包装大声音、整张 V 数据或完整 TTF 来绕开分类预算。

通用索引的 codec 为 `0=NONE, 1=ZLIB, 2=DSP_ADPCM`。当前 `AUDIO_BANK`、
`LANGUAGE_BUNDLE` 和 `SPRITE_SHEET` 都在各自 payload 内提供随机访问索引，外层 codec
固定为 `NONE`。kind payload 的精确布局由 `docs/TH3DS_PACKER_FORMAT.md` 冻结。

## 6. Manifest

### 6.1 包内 manifest

manifest 使用 `TH3DS_PACKER_FORMAT.md` 定义的 UTF-8 canonical JSON 子集。禁止 BOM、浮点数、绝对路径、主机名、
用户名和时间戳。以下字段全部必需：

```json
{
  "format": {"major": 1, "minor": 0},
  "package": {
    "id": "32 lowercase hex chars",
    "role": "core|language|level",
    "name": "stable logical name"
  },
  "runtime_abi": {"min": 1, "max": 1},
  "source": {
    "set_sha256": "64 lowercase hex chars",
    "file_count": 0,
    "total_bytes": 0
  },
  "toolchain": {
    "packer_contract": 1,
    "packer_git": "40 lowercase hex chars",
    "python": "3",
    "sprite_compression": "zlib-level-9",
    "font_input": "pre-rasterized"
  },
  "catalog": {
    "resource_count": 0,
    "catalog_sha256": "64 lowercase hex chars",
    "payload_sha256": "64 lowercase hex chars"
  },
  "dependencies": [
    {"package_id": "32 lowercase hex chars", "container_sha256": "64 lowercase hex chars"}
  ],
  "groups": [
    {
      "id": 1,
      "name": "boot|menu|level-common|level-<id>",
      "required": true,
      "decoded_ceiling_bytes": 0,
      "resource_ids": ["32 lowercase hex chars"]
    }
  ],
  "language": null,
  "level": null,
  "budgets": {
    "audio_bytes": 3145728,
    "sprite_bytes": 8388608,
    "texture_bytes": 6291456,
    "language_font_bytes": 3145728,
    "metadata_bytes": 1048576,
    "scratch_bytes": 1048576
  },
  "provenance": {
    "contains_user_game_data": true,
    "redistributable": false
  }
}
```

language 包把 `language` 设为对象，至少包含规范 BCP-47 tag、CorsixTH 名称、已解析的
继承链、字符串数、codepoint 数、atlas 页数和字体源 SHA-256。level 包把 `level` 设为
对象，至少包含稳定 level ID、地图源 SHA-256 和允许的依赖包 ID。

`package.id` 的 16 B 值为：

```text
first_16_bytes(SHA-256(
  "th3ds-package-id-v1\0" || role || "\0" || name || "\0" ||
  source_set_sha256 || required_runtime_abi_le32
))
```

### 6.2 Bundle manifest

`bundle.th3ds.json` 同样使用 canonical JSON，固定包含：`format`、`runtime_abi`、
`source_set_sha256`、`selected_language`、`start_level`、`packages[]` 和
`bundle_sha256`。每个 package 项包含相对路径、role、package ID、文件尺寸和
container SHA-256。路径只允许 ASCII 小写、数字、`-`、`_`、`.` 和 `/`；禁止 `..`。

`bundle_sha256` 的计算把自身值替换成 64 个字符 `0`，随后对 canonical JSON 求
SHA-256。安装器先核对 bundle，再核对每个包。运行时只接受同一个
`source_set_sha256` 的包族。

## 7. ID、路径和哈希

### 7.1 Resource ID

逻辑名先执行以下规范化：

1. `\` 改为 `/`，移除重复 `/` 和开头 `./`。
2. 拒绝绝对路径、空段、`.`、`..`、NUL 和非 UTF-8。
3. Theme Hospital 原始路径按 ASCII case-fold 后使用大写目录名和小写文件名；
   CorsixTH 开放资源使用仓库中声明的规范名。
4. BCP-47 tag 先做规范化；资源 type 使用上表大写名称。

Resource ID 为：

```text
first_16_bytes(SHA-256(
  "th3ds-resource-id-v1\0" || kind_name || "\0" || canonical_logical_name
))
```

ID 与内容解耦，所以脚本和索引能跨重打包稳定引用。打包时若两个逻辑名产生同一
16 B ID，立即返回 `P_ID_COLLISION`；运行时也必须检查，禁止覆盖。

### 7.2 源数据集合指纹

源文件按 canonical path 的 UTF-8 字节排序。每条记录为：

```text
path_length_u16 || path_bytes || file_size_u64 || file_sha256_32bytes
```

`source_set_sha256` 是全部记录连接后的 SHA-256。转换出的 core、language 和 level
包必须携带同一指纹；开放 CorsixTH 资源使用独立命名空间，但同样进入记录集合。

运行时策略：启动时验证 header、catalog、bundle 和所有 REQUIRED 资源的 stored
hash；首次解码时验证 decoded hash。音频/精灵随机块先验证块 CRC32，完整资源的
decoded hash 在主机打包测试和安装验证阶段强制执行。2 小时运行无需反复扫描整包。

`stored_sha256` 精确覆盖 `[data_offset, data_offset + stored_size)`，不含资源前的全零
对齐 padding；padding 由 package payload hash 覆盖。`decoded_sha256` 的逻辑字节流固定
如下：audio bank 为 bank 顺序的 `name_bytes_u16 || name || original_pcm`；sprite sheet
为 source index 顺序的 `source_size_u32 || Theme Hospital chunk stream`；language bundle
为依赖顺序的 `path_bytes_u16 || path || content`；UI/font atlas 和 font map 为其最终存储
字节。
`decoded_size` 是该逻辑字节流长度，streamable 资源不得按它申请一整块内存。

## 8. 音频契约

**DECISION R03**：打包器离线拆解 `SOUND-0.DAT`，生成一个 `AUDIO_BANK`。bank 只保留
转换后的逐 clip payload 和随机访问索引；运行时禁止打开或复制完整原始归档。

v1.0 保留源 PCM 的采样率、声道和 8/16-bit width，避免在缺少已固定重采样器时制造
不可复现的音频语义。codec 为 PCM U8、PCM S16LE 或调用者提供且重复运行结果一致的
DSP-ADPCM。每个 clip 4096 B 对齐、带 CRC-32 和 SHA-256，并可单独 seek。单 clip 的
decoded bytes 必须不超过 3 MiB；整个 bank 的 decoded 总量不作为驻留申请。

精确头部、entry 和 decoded-hash 串联规则见 `docs/TH3DS_PACKER_FORMAT.md`。后续 runtime
任务负责把一个 clip 解码进 `ResourceManager` 所有的 PCM buffer，并确保活动 channel
持有 lease。stage 1 没有实现或验证播放行为。

## 9. 语言契约

**DECISION R04**：打包器静态解析 `Language` 和 `Inherit`，证明选中语言的完整、无环、
dependency-first 闭包，只把这个闭包和明确引用的 `LANG-N.DAT` 写入
`LANGUAGE_BUNDLE`。动态继承、缺失依赖和路径不安全立即失败。未选语言不得进入 payload。

早期“在主机执行任意 Lua 并输出扁平表”的提案缺少安全、确定的执行器，当前 Python
实现无法忠实复现 CorsixTH 的完整 Lua 语义。v1.0 因此冻结为可验证的选中闭包；
payload 头、逐文件 hash、64 B 对齐和 decoded-hash 规则见格式文档。语言包及字体总量
必须不超过 3 MiB。

后续 typed language adapter 只能执行已挂载闭包，禁止扫描 loose 语言目录。该 adapter
的 `_S` 构造、必需 key 检查和真机行为属于下一 runtime 任务。

## 10. 精灵契约

**DECISION R05**：打包器离线解析 `.tab/.dat`，每个非空 TAB row 成为一个独立、64 B
对齐的 zlib level-9 block。解压结果是精确的 Theme Hospital chunk stream；候选位明确
该 stream 通过 simple、complex 或两种 decoder 的结构校验。两种都不通过立即失败。

单图最终 indexed8 pixels 上限 307,200 B，`compressed-source 解压结果 + indexed8
pixels` 必须不超过 1 MiB scratch。精确 `TH3DSP1` header/entry 布局、CRC/SHA 和
decoded-hash 规则见格式文档。

首次请求一个精灵时，runtime 只读取所在 block，校验、解压并把最终 indexed8 pixels
放入中央 sprite cache。首次绘制时从该 lease 建立中央 texture cache 项。原始块、像素
和 SDL texture 分别计量；runtime 解码与 sheet-specific candidate 选择属于下一任务。

## 11. UI 位图和字体图集

### 11.1 UI 位图

**DECISION R06**：主机端完成调色板展开和像素格式转换。`UI_BITMAP` 只允许：

- `RGB565=1`：完全不透明资源；bit `15..11=R, 10..5=G, 4..0=B`。
- `RGBA5551=2`：含透明像素资源；bit `15..11=R, 10..6=G, 5..1=B, 0=A`。

每个 16-bit 像素按 little-endian 存储，行紧密排列，stride 必须等于 `width*2`。
metadata 为 `width u16, height u16, stride u16, pixel_format u8, mip_count u8,
flags u16, reserved[6]=0`。v1 的 `mip_count` 固定为 1。

运行时不得保留 RGBA8888 中间副本。v1.0 UI payload 已是最终 16-bit buffer；上传完成
后，如果渲染后端已经复制，普通堆 buffer 立即释放。

### 11.2 字体

**DECISION R07**：语言包只包含该语言实际字符串的 codepoint、ASCII 错误页字符和
配置允许的玩家名字符范围。字体在主机端栅格化为 256x256 RGBA5551 atlas 页，白色
RGB 加 1-bit alpha，可用 texture color modulation 着色。每个语言最多 16 页。

`FONT_MAP` v1.0 使用 canonical JSON，glyph 按 codepoint 排序，字段固定为 `codepoint`、
`x`、`y`、`width`、`height`、`advance`、`bearing_x`、`bearing_y`。map 必须通过依赖 ID
引用对应 `FONT_ATLAS`。stage 1 只接收预栅格化输入，不运行字体渲染器；输入图必须正好
256x256、16-bit，glyph rectangle 必须全部在 atlas 内。

缺字在打包时为 `P_MISSING_GLYPH`。运行时遇到玩家输入产生的新缺字时显示内置方框，
写一次 `W_MISSING_GLYPH`，继续运行；禁止临时加载 TTF 或扩大 atlas。

## 12. 加载器 API 边界

**DECISION R08**：实现必须保持以下单向依赖：

```text
BundleMount
  open_bundle(path) -> Result<MountedBundle, ResourceError>

ResourceCatalog
  find(ResourceId, ExpectedKind) -> Result<ResourceDescriptor, ResourceError>

ResourceManager                         # 唯一 payload/texture/PCM 所有者
  acquire(ResourceId, AcquirePolicy) -> Result<ResourceLease, ResourceError>
  prefetch(GroupId, Deadline) -> PrefetchReport
  release_group(GroupId) -> void
  begin_transition(TargetGroup) -> Result<TransitionToken, ResourceError>
  snapshot() -> ResourceMemorySnapshot

Typed adapters
  AudioProvider::acquire_clip(id) -> AudioLease
  SpriteProvider::acquire_sprite(id) -> SpriteLease
  TextureProvider::acquire_texture(id, variant) -> TextureLease
  UiProvider::acquire_bitmap(id) -> UiBitmapLease
  LanguageProvider::mount_selected(tag) -> LanguageLease
  FontProvider::acquire_glyph(codepoint) -> GlyphLease
```

Lua 只能接收小型字符串、标量、Resource ID 或 opaque handle。以下接口在 3DS 资源
路径中禁止出现：

- `readContents()` 返回大二进制 Lua string；
- `std::vector<uint8_t>` 按值跨 API 返回；
- SDL_mixer 或精灵对象接管裸指针所有权；
- 子系统自建无预算 map/cache；
- 业务代码直接 seek 资源包或 loose game tree。

每次 acquire 必须在读盘前按 kind metadata 预留最终目标 bytes 和 scratch；通用
`decoded_size` 只描述 hash 的逻辑流，不能替代 sprite pixel bytes 或 audio clip bytes。
预留失败先驱逐 refcount=0 的项目；仍无法满足时返回有类型错误，不执行尝试性分配。

## 13. 中央缓存、refcount 和 LRU

**DECISION R09**：一个 `ResourceManager` 管理五个 pool：metadata、audio PCM、decoded
sprites、textures、language/font。每个 pool 有独立硬上限，同时受当前阶段总上限约束。

规则固定如下：

1. `ResourceLease` 创建时 refcount 加一，析构/显式 release 时减一；refcount 溢出或
   重复 release 为致命内部错误 `E_REFCOUNT_CORRUPT`。
2. refcount 大于零的项目不可驱逐。`PIN_ON_MOUNT` 只允许 boot/error UI 和当前语言
   根对象使用，也计入预算。
3. refcount 归零时记录单调 `last_release_tick` 并进入该 pool 的 LRU 尾部。再次 acquire
   只更新一次时钟，不分配第二份内容。
4. 驱逐顺序为：零引用替换调色板 texture、零引用普通 texture、零引用 decoded
   sprite、零引用 audio PCM、零引用非当前 group metadata。相同类别按最早释放优先，
   Resource ID 字节序用于平局，保证可复现。
5. texture 依赖 sprite 时先销毁 texture，再允许驱逐 sprite；活动 audio channel 持有
   AudioLease，channel callback 之后才能驱逐 PCM。
6. group 切换先停止旧组新 acquire，等待/取消可取消 lease，驱逐旧组零引用项，验证
   transition reserve，再挂载目标组。超时返回 `E_GROUP_BUSY`，不得叠加两关资源。
7. 解码 scratch 是一个 1 MiB 共享 workspace，任一时刻只有一个资源解码任务使用。
   音频 callback 禁止执行 I/O、解码或分配。
8. 每次分配、驱逐、拒绝和 group 切换都记录类别、Resource ID、字节数、refcount、
   pool 水位和阶段。日志不得记录原版 payload。

缓存上限和阶段上限见 `docs/OLD3DS_MEMORY_BUDGET.md`。manifest 数字只能收紧本地上限；
包内更大的值返回 `E_BUDGET_CONTRACT`。

## 14. 兼容性与失败行为

### 14.1 版本

- `version_major != 1`：`E_FORMAT_MAJOR`，停止挂载。
- `version_major == 1` 且 `version_minor > runtime_supported_minor`：只有 feature bits 全部
  已知且 header/index size 与 v1 一致时才允许；其余返回 `E_FORMAT_MINOR`。
- runtime ABI 不在 manifest 的 `[min,max]`：`E_RUNTIME_ABI`。
- `CTH3DPK1` 旧审计包：`E_LEGACY_AUDIT_PACK`，提示重新打包，禁止当作运行时包读取。

### 14.2 完整性和组合

- bundle/package/container/catalog/payload hash 错误：`E_HASH_*`，停止在轻量错误页。
- core、language、level 的 source-set 不同：`E_SOURCE_SET_MIXED`。
- package ID、Resource ID 重复：`E_ID_DUPLICATE`。
- offset 越界、整数溢出、区域重叠、非零 padding：`E_FORMAT_BOUNDS`。
- selected language 缺失：先关闭失败的 selected language mount，再尝试 bundle 明确
  声明的 `fallback_language`；bundle 没有声明或 fallback 也失败时返回
  `E_LANGUAGE_MISSING`。禁止扫描目录猜测语言。
- required 资源缺失或损坏：当前 boot/transition 失败并保留错误页。
- optional UI/音效缺失：使用内置占位图或静音，记录一次 warning；不得扩大缓存补救。

生产模式禁止静默读取 loose game files。开发模式只有显式
`resource_mode=developer-loose` 才可启用，并在每个阶段日志写 `NON_ACCEPTANCE_MODE`；该
模式的真机结果一律为 `NOT_PROVEN`。

### 14.3 低内存

预算预留失败返回 `E_BUDGET_<POOL>`，先保留 4 MiB emergency reserve 和下屏错误页。
音效 acquire 失败只丢弃新音效并记数；required sprite、language、font 或 level 数据
失败则取消转换，回到主菜单或错误页。任何路径都禁止触发整包 fallback load。

## 15. 确定性要求

**DECISION R10**：相同输入、相同工具版本和相同选项必须逐字节产生相同输出。

- 输入遍历、manifest key、resource index、language key、glyph、kerning、sprite 和
  block 全部使用本文规定的排序。
- build epoch 和 padding 固定为零；压缩器固定版本、level、block size 和线程数。
- JSON 使用 canonical form；禁止把绝对路径和时间写入包。
- 原子写入 `<name>.tmp`，完成 fsync、整包复读和 hash 校验后 rename。
- 同一输入连续构建两次，core、selected language、level 和 bundle 的 SHA-256 必须
  全部相同，否则打包失败 `P_NONDETERMINISTIC`。

## 16. 实现验收

本契约的实现只有在以下证据齐备后才可称为完成：

1. parser、hash、边界、碰撞、版本和故障注入主机测试全部 PASS。
2. 合成数据两次构建 bit-identical；真实用户数据只在受保护工作目录测试。
3. instrumentation 证明启动没有读取整个 `SOUND-*.DAT`，没有编译非选定语言，V
   sprite 只按块解码，所有 texture 都在中央 cache 登记。
4. `docs/OLD3DS_MEMORY_BUDGET.md` 的所有 host 与 hardware gates 全部 PASS。
5. 无游戏数据发布包扫描结果为 0 个原版或转换后游戏资源。

当前状态：`TH3DSR1 v1.0` host writer/inspector、确定性合成 fixtures、hash/alignment 和
fail-closed packer budget 已实现；runtime loader、typed adapters、上游接线和真机结果
仍为 `NOT_PROVEN`。
