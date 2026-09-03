# Old 3DS 内存预算与硬件验收门

状态：**Budget contract v1.0 / host packer and gate constants implemented / runtime pools pending**

冻结源码基线：`9fbaeb6210108e27363c2bbc39769d70f2d41ea2`

资源格式：`docs/OLD3DS_RESOURCE_ARCHITECTURE.md`

## 1. 结论

当前 v0.6.1 已经拥有 56.180736 MB（53.578125 MiB）常规堆，仍在 S70 报告 52.637 MiB
`uordblks` 后 OOM。
后续实现必须把主菜单常规堆压到 36 MiB 以内，把第一关稳定状态压到 44 MiB 以内，
始终给转换、存档、错误页和安全退出留出有证明的空间。

本文件冻结所有上限。实现可以降低上限；提高任何上限都需要新真机测量、风险说明和
本文件的新版本。

## 2. 单位和测量口径

- 1 KiB = 1,024 B；1 MiB = 1,048,576 B。
- `heap_total` 使用 `envGetHeapSize()`。
- `heap_payload` 使用 `mallinfo.uordblks`，`heap_arena` 使用 `mallinfo.arena`，
  `heap_arena_free` 使用 `mallinfo.fordblks`；三者必须来自同一次快照。
- `heap_available_estimate = min(heap_total, max(0, heap_total - heap_arena) +
  heap_arena_free)`。`heap_used_estimate = heap_total - heap_available_estimate`，包含
  allocator 已提交且不可复用的开销；连续分配能力仍由 probe 单独证明。
- `linear_total` 使用 `envGetLinearHeapSize()`，`linear_free` 使用
  `linearSpaceFree()`。
- `lua_bytes` 使用 Lua allocator 的当前值；它是 `heap_used_estimate` 的子集，禁止再次相加。
- audio、sprite、texture、language/font、metadata 和 scratch 都是 `heap_used_estimate` 或
  linear used 的分类子集，必须分别记账。
- “连续分配探针”指真实 `malloc(N)`、触碰每 4 KiB 页、立即 free；只查看总空闲值不
  能替代探针。
- 每个 gate 使用峰值和最低水位。阶段结束时的单点快照不能代表阶段峰值。

## 3. 已测基线

### 3.1 真机数据

来源：`work/hardmac-runs/20260902-174010-postlaunch-diagnosis/boot.log`。

| 阶段 | `uordblks` | `fordblks` | Lua | linear free | 时间 |
|---|---:|---:|---:|---:|---:|
| S10 | 64,104 B | 5,480 B | 0 B | 0 B（遥测初始化异常，见 3.2） | 108 ms |
| S20 | 792,544 B | 38,896 B | 705,797 B | 0 B（同上） | 8,152 ms |
| S30 | 1,594,040 B | 19,736 B | 705,797 B | 6,238,208 B | 8,306 ms |
| S40 | 3,667,264 B | 2,226,832 B | 1,543,162 B | 6,238,208 B | 20,407 ms |
| S50 | 3,964,648 B | 1,929,448 B | 1,655,543 B | 6,213,632 B | 21,060 ms |
| S60 | 10,233,488 B | 260,416 B | 7,289,530 B | 6,213,632 B | 35,164 ms |
| S70 | 55,124,320 B | 1,015,408 B | 22,295,372 B | 6,213,632 B | 88,373 ms |
| FATAL | 55,193,952 B | 945,776 B | 22,295,372 B | 6,213,632 B | S70 后 |

额外测量：

- `heap_total = 56,180,736 B = 56.180736 MB = 53.578125 MiB`。
- `linear_total = 8,388,608 B = 8 MiB`。
- `SOUND-0.DAT = 16,634,862 B = 15.864241 MiB`。
- S70 到 FATAL 没有 S80、S90、S100，主菜单和下屏适配器没有运行。

### 3.2 已知测量缺口

早期快照的 `fordblks` 和 `linear_free` 出现很小值或 0，随后才反映已建立的 allocator
arena。`fordblks` 没有包含尚未提交给 allocator arena 的普通堆空间，不能单独用于
证明真实余量。新遥测必须：

1. 记录 allocator 初始化状态和 API 返回码；
2. 同时记录 arena、uordblks、fordblks、按上式计算的 available、分类计数和探针结果；
3. 在线性后端初始化后重置有效 low-water mark；
4. 把无效样本标成 `valid=false`，禁止把 0 当成真实低水位。

现有 S70/FATAL 的 OOM 和总堆数值是有效事实。当前日志没有分类资源峰值，因此下文的
分类数字属于架构上限，未宣称为现状测量。

## 4. 冻结预算

### 4.1 硬件前提

| 项目 | 硬门槛 | 处理 |
|---|---:|---|
| 常规堆总量 | `>= 52 MiB`（54,525,952 B） | 低于此值：`E_HEAP_TOO_SMALL`，停在轻量错误页 |
| 线性堆总量 | `exactly 8 MiB`（8,388,608 B） | 不一致：构建或启动 FAIL |
| 线性堆常驻上限 | `6 MiB`（6,291,456 B） | 保留至少 2 MiB linear reserve |

当前设备的常规堆为 53.578125 MiB，满足 52 MiB 前提；这条事实没有证明下面的运行时
上限已经实现。

### 4.2 阶段总上限

所有数字都是阶段内峰值，包含 allocator overhead。这里的 `heap_used_estimate` 使用第
2 节的计算值。`heap_used_estimate` 达到上限前 512 KiB
进入预警并触发零引用缓存驱逐；达到上限的下一次非紧急分配必须失败关闭。

| 阶段/场景 | 常规堆硬上限 | 最低 `heap_available_estimate` | 必须成功的连续探针 |
|---|---:|---:|---:|
| S10–S50 boot/audio device ready | 12 MiB | 40 MiB | 8 MiB |
| S60 selected language ready | 18 MiB | 34 MiB | 8 MiB |
| S100 主菜单稳定 30 s | **36 MiB** | **16 MiB** | **8 MiB** |
| 第一关可操作且稳定 10 min | **44 MiB** | **8 MiB** | **4 MiB** |
| 第一关 20 个病人稳定 30 min | **44 MiB** | **8 MiB** | **4 MiB** |
| 转换/存档进行中 | 48 MiB 瞬时绝对上限 | 4 MiB | 2 MiB |

52 MiB 是验收允许的最小 heap total，所以表中的空闲门槛按 52 MiB 计算。当前
53.578125 MiB 设备会自然多出约 1.578 MiB，禁止把这部分写进新的缓存目标。

主菜单和第一关上限分别固定为 36 MiB、44 MiB。任何“平均低于上限、偶尔越过”的
结果都为 FAIL。

### 4.3 资源 pool 上限

这些 pool 是阶段总量的子集，不能相互借额度。一个项目同时占用两个类别时必须分别
计数，例如 indexed8 sprite 和由它产生的 texture。

| pool | 常规堆硬上限 | 线性堆硬上限 | 说明 |
|---|---:|---:|---|
| audio decoded PCM + `Mix_Chunk` metadata | **3 MiB** | 0 | 活动 channel 可 pin；超限丢弃新音效 |
| decoded sprite indexed8 | **8 MiB** | 0 | 按 64 KiB block 解码，零引用 LRU |
| texture payload + texture metadata | **6 MiB** | 若后端使用 linear，也受 6 MiB linear 总常驻约束 | 普通和替换调色板纹理合并计数 |
| selected language tables + font maps/atlases | **3 MiB** | 0 | 同时只允许一个语言；font atlas 最多 16×256×256×2 B |
| resource catalog + mounted metadata | **1 MiB** | 0 | 使用紧凑数组和 string pool |
| shared I/O/decode scratch | **1 MiB** | 0 | 单实例，禁止递归 acquire |
| boot/error UI permanent set | **512 KiB** | 256 KiB | 始终可用，计入上面的 texture/linear 总量 |

audio、sprite 和 texture 是用户点名的冻结上限：3 MiB、8 MiB、6 MiB。manifest 只能
声明更低的包级 ceiling。

### 4.4 转换与存档 reserve

常规堆固定预留 **8 MiB**，分成：

- 4 MiB operation workspace：关卡转换、语言切换准备或存档序列化可以临时使用；
- 4 MiB emergency reserve：错误页、日志、回主菜单和安全退出不得消费的底线。

规则：

1. 主菜单或关卡稳定态必须至少空闲 8 MiB，启动转换/存档前 4 MiB 连续探针成功。
2. 操作开始前先停止旧 group 的新 acquire，并驱逐旧 group 的零引用缓存。
3. operation workspace 的累计峰值不得超过 4 MiB；过程中 `heap_available_estimate` 不得低于 4 MiB，
   2 MiB 连续探针必须成功。
4. 操作结束或回滚后 1 s 内 `heap_available_estimate` 恢复到至少 8 MiB，4 MiB 连续探针再次成功。
5. 保存序列化超过 4 MiB 时改用有界流式写入；禁止扩大 reserve 或生成整份内存副本。
6. reserve gate 失败时不进入操作，返回 `E_TRANSITION_RESERVE` 或 `E_SAVE_RESERVE`。

线性堆另保留 **2 MiB**。framebuffer、DSP 和纹理 linear 分配峰值合计不得超过 6 MiB。

## 5. 预算执行机制

### 5.1 分配前

每个资源 descriptor 必须提供 stored bytes、decoded bytes、目标 pool 和临时 scratch
需求。`ResourceManager` 按以下顺序处理 acquire：

```text
检查 kind/size/阶段
  → 计算 pool 和阶段剩余额度
  → 驱逐 refcount=0 的确定性 LRU
  → 预留完整目标字节与 allocator overhead
  → 读取一个 block
  → 校验、解码、登记
  → 发布 lease
```

预留失败不得先尝试 `malloc`。实际占用超过 descriptor 预留值属于
`E_ACCOUNTING_OVERRUN`，当前 group 加载失败。

### 5.2 allocator overhead

预算计数使用实际分配大小，包含：

- allocator usable size/rounded size；
- C++ 对象、索引节点和字符串容量；
- SDL texture/Mix_Chunk 可查询或由后端 wrapper 记录的 payload；
- 对齐 padding；
- 尚未释放的旧对象和转换中的新对象。

无法查询的第三方分配通过包装 allocator 或阶段 delta 分类。任一阶段出现超过
1 MiB 的 `unclassified_delta` 为 FAIL。

### 5.3 低水位动作

| 条件 | 动作 |
|---|---|
| pool 距上限 <= 256 KiB | 驱逐该 pool 全部零引用旧 group 项 |
| 阶段总量距上限 <= 512 KiB | 驱逐 texture → sprite → audio → metadata |
| 稳定态 `heap_available_estimate < 8 MiB` | 停止预取，记录 `W_RESERVE_LOW`，尝试恢复 |
| operation 中 `heap_available_estimate < 4 MiB` | 取消并回滚操作，进入错误页/主菜单 |
| emergency reserve 或错误页分配失败 | 写最小 boot log，直接返回 Homebrew |

任何恢复动作都必须使用已有 LRU/lease 机制。运行时禁止临时关闭功能后继续给出 PASS；
静音降级只有 DSP 缺失或单个 optional 音效预算拒绝时允许，并在报告中明确记录。

## 6. 场景资源组

### 6.1 Boot

允许 pin：错误页字体、错误页 UI、bundle/core catalog、当前语言根对象。boot permanent
set 上限为 512 KiB regular + 256 KiB linear。S50 之前禁止预取 V sprites、完整声音组
或 level pack。

### 6.2 主菜单

`menu` group 只能预取首屏会实际显示的 UI、字体页和短音效。完成 S100 后：

- heap peak <= 36 MiB；
- audio <= 3 MiB、sprite <= 8 MiB、texture <= 6 MiB；
- `heap_available_estimate >= 16 MiB`；
- 8 MiB 连续探针成功；
- 非 menu group 的零引用内容全部可驱逐。

### 6.3 第一关

进入第一关时允许同时保留 boot、当前 language、level-common 和 level-1 group。menu
group 必须先降为零引用并可驱逐。第一关达到“可移动镜头、可打开建造、时间开始走”
后计为 ready；从该点预热 10 分钟再读取稳定态。

第一关及 20 个病人场景的 heap peak 均 <= 44 MiB，`heap_available_estimate >= 8 MiB`，4 MiB 连续探针
成功。资源缓存没有“关卡越玩越满”的豁免。

## 7. 遥测 schema

每个 S 阶段、group 变化、每 5 s 运行采样和每次保存都写一条 JSON line：

```json
{
  "schema": 1,
  "stage": "S100",
  "group": "menu",
  "valid": true,
  "heap": {
    "total": 0,
    "arena": 0,
    "payload": 0,
    "arena_free": 0,
    "available_estimate": 0,
    "used_estimate": 0,
    "available_estimate_low": 0
  },
  "linear": {"total": 0, "used": 0, "free": 0, "low": 0},
  "lua": {"current": 0, "peak": 0},
  "pools": {
    "audio": 0,
    "sprite": 0,
    "texture": 0,
    "language_font": 0,
    "metadata": 0,
    "scratch": 0,
    "unclassified": 0
  },
  "cache": {"entries": 0, "leases": 0, "evictions": 0, "rejects": 0},
  "probe": {"bytes": 0, "pass": true},
  "resource_error": null
}
```

`pools` 是 `ResourceManager` 的验收分类。stage-1 当前 loose-file 启动路径另输出
`diagnostic_resources`（language、sound archive、VSPR 等定位类别），不能把这些诊断值
冒充 pool accounting。C++ 已冻结同名 pool 上限和五种阶段 gate；S100 主菜单入口执行
36 MiB used / 16 MiB available estimate / 8 MiB probe / 4 MiB probe reserve。其余阶段的
runtime 调用和完整 JSONL writer 仍待 loader 任务接线。

日志还必须在文件头记录 3DSX SHA-256、bundle SHA-256、所有 mounted package
SHA-256、source-set、runtime ABI、缓存上限和 build commit。不得记录资源 payload、
用户姓名或存档内容。

## 8. 主机验收门

实现提交进入真机前必须全部 PASS：

| ID | 门 | 精确 PASS 条件 |
|---|---|---|
| RH01 | 格式 round-trip | 每个 kind 的合成 fixture pack→inspect→decode 与输入逐字节一致 |
| RH02 | 确定性 | 同一输入独立构建两次，bundle 和所有 package SHA-256 完全相同 |
| RH03 | parser 安全 | 截断、offset 溢出、区域重叠、乱序/重复 ID、未知必需特性、hash 错误全部被拒绝；ASan/UBSan 0 报错 |
| RH04 | 单语言 | 文件访问 instrumentation 证明只执行/读取选定语言及其主机端继承依赖；3DS 运行包不含其他语言 Lua chunk |
| RH05 | 音频按块 | instrumentation 证明 runtime 不读取完整 `SOUND-*.DAT`；每次 decode <= 一个 4096-frame block；模拟峰值 <= 3 MiB |
| RH06 | 精灵按块 | V sheet 首次打开只读 index；未请求 sprite 的像素分配为 0；每块普通解码 <= 65,536 B |
| RH07 | cache 规则 | refcount>0 永不驱逐；平局按 Resource ID；texture 先于依赖 sprite；10,000 次 acquire/release 后计数归零且占用回基线 |
| RH08 | 预算拒绝 | 每个 pool 在 cap-1/cap/cap+1 边界行为正确；拒绝时没有部分对象、计数漂移或二次 fallback load |
| RH09 | fault injection | core/lang/level 缺失、块损坏、save reserve 不足、linear 不足均给出规定错误码并保留错误页 |
| RH10 | game-data 排除 | `git ls-files`、源码包和无游戏数据发布包中 0 个原版文件、0 个 `.th3ds` 用户数据包、0 个转换后 atlas/audio/sprite payload |

主机模拟的内存结果只能证明预算器逻辑，不能证明 Old 3DS allocator、SDL、DSP 或真机
峰值。

## 9. Old 3DS 硬件验收门

每轮都必须记录设备身份、3DSX 和包的上传前 hash、FTPD 读回 hash、boot log、遥测和
人工观察。以下门全部使用同一 build 和同一 source-set。

| ID | 场景 | 精确 PASS 条件 |
|---|---|---|
| RD01 | 身份与安装 | Old 3DS 端点、3DSX hash、bundle hash、每个 package hash 与本地候选一致；SD 上只暴露一个当前可启动入口 |
| RD02 | 重复启动 | 冷启动 10 次全部到 S100；每次 <= 30 s；0 OOM、0 hash/format 错误、0 自动静音降级；下屏 2 s 内显示进度 |
| RD03 | 堆配置 | 每次 `heap_total >= 52 MiB`，`linear_total == 8 MiB`；无 invalid snapshot 进入 low-water 统计 |
| RD04 | 主菜单预算 | 主菜单静置 30 s：heap peak <= 36 MiB，`heap_available_estimate` low >= 16 MiB，8 MiB 探针成功；audio/sprite/texture 分别 <= 3/8/6 MiB |
| RD05 | 第一关预算 | 第一关 ready 后预热 10 min：heap peak <= 44 MiB，`heap_available_estimate` low >= 8 MiB，4 MiB 探针成功；linear used peak <= 6 MiB；unclassified delta <= 1 MiB |
| RD06 | 20 病人预算 | 第一关达到 20 个病人后运行 30 min：继续满足 RD05；cache rejects 不影响 required 资源；没有视觉占位符 |
| RD07 | 音频 | UI、环境、广播各至少 20 次并连续运行 30 min；audio peak <= 3 MiB；underrun=0；停止后零引用 PCM 可驱逐；声音名称/时长与桌面参考抽样 20 项一致 |
| RD08 | 精灵/UI/字体 | 主菜单、第一关、建造、雇员、病人、消息各检查一轮；0 缺图、0 错调色板、0 透明度错误；选定语言所有可见字符 0 tofu（玩家新输入缺字除外） |
| RD09 | 转换 | 主菜单↔第一关往返 10 次；开始前 `heap_available_estimate>=8 MiB`/4 MiB probe PASS；过程中 `heap_available_estimate>=4 MiB`/2 MiB probe PASS；结束 1 s 内 `heap_available_estimate>=8 MiB`；无旧 level 活 lease |
| RD10 | 保存 | 空医院、20 病人、建房中各保存/读取 10 次；operation workspace <=4 MiB；正式存档非零且可读；`.tmp/.bak` 故障恢复通过；每轮结束 `heap_available_estimate>=8 MiB` |
| RD11 | 损坏包 | 在回滚副本上分别破坏 bundle、index、audio block、sprite block；每次得到规定错误码、轻量错误页可见 >=10 s、B 键 3 s 内返回 HBL；当前正式目录保持可启动 |
| RD12 | 生命周期 | 主菜单和第一关各执行 HOME 往返 10 次、合盖 30 s/5 min/30 min；恢复后缓存计数一致、音频可继续或安全重启、`heap_available_estimate>=8 MiB` |
| RD13 | 2 小时稳定性 | 第一关含 20 病人连续 2 h；预热 10 min 后 heap 持续增长 <=1 MiB；Lua 不单调增长；0 OOM/崩溃/死锁/underrun/required reject；全程满足 44 MiB/8 MiB/6 MiB 门槛 |
| RD14 | 性能 | 预热 30 s、采样 60 s：主菜单平均帧 <=50 ms/P95 <=100 ms；空医院 <=70/150 ms；20 病人 <=100/200 ms；HBL→S100 <=30 s；主菜单→第一关 ready <=30 s |

### 9.1 判定规则

- 任一 RD 项缺少当前 build 的完整证据：`NOT_PROVEN`。
- 任一数字越线、一次启动失败、一次 hash 不一致或 required 资源降级：`FAIL`。
- RD01–RD14 全部 PASS 后，资源架构才得到 Old 3DS acceptance。
- 画面和听感由真机人工观察证明；hash、内存和错误原因由日志/读回证明。两类证据都要有。
- New 3DS、模拟器、桌面和交叉构建结果不能替代 Old 3DS gate。

## 10. 当前判定

| 范围 | 状态 | 原因 |
|---|---|---|
| 当前 v0.6.1 启动 | **FAIL** | 真机在 S70 OOM，最后 `fordblks` 为 945,776 B |
| 53.578125 MiB 常规堆 / 8 MiB 线性堆测量 | **PASS** | 当前 boot log 有明确数值 |
| TH3DSR1 v1.0 contract | **PASS（文档层）** | 字节布局、所有权、上限和错误行为已统一 |
| host writer/inspector/packer budgets | **PASS（合成夹具）** | 确定性、hash、对齐、损坏拒绝和原子发布有主机测试 |
| runtime loader/cache/pool accounting | **NOT_PROVEN** | 本任务明确不实现 runtime resource loader |
| RH01–RH10 全量 | **NOT_PROVEN** | packer 子集有证据；loader、ASan parser、真实数据与 runtime gates 未齐 |
| RD01–RD14 | **NOT_PROVEN** | 需要同一候选的 Old 3DS 实测 |

文档与 host packer 提交不能转化为设备可运行结论。下一依赖是依据本契约实现
runtime loader/typed adapters、中央 cache 和运行时分类遥测，然后依次通过 RH 与
RD gates。
