# R17：真实可玩路径诊断（公开详细版）

本文件可公开，仅包含源码结论、测试边界及待实施合同摘要。R17为只读诊断，未改产品、未提交或推送；本文件由统一资料发布任务发布。**诊断完成；当前产品PRODUCT_BLOCKED；当前Old3DS运行与内存NOT_PROVEN。**


本公开版由R19 / R17_SYNC发布，改写自封存的可公开handoff（SHA256 `4f86a858369df4fe71ef39417fb2927f63b609f25fea04c56fc2d2a490adc2de`）。对应R17正式报告SHA256 `0f94c1ac0b5d958c0980cf1772da60605cfed365027bd5dff0605473c31c9886`，实施合同SHA256 `5ff5f97acf96ba994680063037c10a5f2baf3a4090b266e076d4d94c41de3cbf`。R19校验回执及107项封存摘要；本次仅发布文档，未重跑诊断。完整本机报告、合同JSON、日志与回执继续留在本地。

[返回审查入口](../../REVIEW_CONTEXT.md)

## 待审身份

- Overlay head：`844121cd86e5905c8a53c4574fab399d11ea0849`
- Tree：`cfa70da3d4503ea9b997064fce4e75c6d65758ca`
- Sole parent：`8e9df167da524c2a8bdc3296227544d559dc70dc`
- 上游CorsixTH v0.70.1：`56bd5d00f76331c7f76d7b696726a7926303ca0c`；tree `10bfcc53e260fcc68bda4201c97a45ed049f31a0`
- [待审源码](https://github.com/zzliu-coder/corsixh3ds/tree/844121cd86e5905c8a53c4574fab399d11ea0849)

下列标注的生成上游行号指该固定commit经冻结integrator组装后的结果；overlay路径和链接直接对应待审head。上游原始文件与生成结果的行号应分别使用，本文只对已核对的相同字节热点给出上游固定链接。原版游戏内容和私人路径均未包含于本文件。

## 已确认

1. [scripts/package_sd.sh:6,107–111](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/package_sd.sh#L6)默认th3ds并要求`CorsixTH/Languages`；真实上游使用`CorsixTH/Lua/languages`。真实上游组装后的默认打包exit2。[tests/test_package_sd_script.py:24–55](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/tests/test_package_sd_script.py#L24)自造runtime/Languages并使用假Git/3DSX，未覆盖真实结构。
2. 上游`CorsixTH/Lua/filesystem.lua:93,123,164,243`仍按原始目录枚举/打开文件；`App:readDataFile/readMapDataFile`等消费原始数据。th3ds打包禁止game并提供resources；native[src/3ds/runtime_3ds.cpp:788–807](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/src/3ds/runtime_3ds.cpp#L788)仍强制创建RuntimeSession，忽略loose模式。
3. `App:init`在重资源加载、初始UI之后attach；[lua/3ds/platform.lua:523](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/lua/3ds/platform.lua#L523)立即sync并发菜单资源事件。RuntimeSession直到后续C++mainloop才创建。Lua组件复现先attach失败且留下wrapper/app._3ds、重试再次包装。互斥UI分支没有证明一次执行无条件attach两次。实际原版数据还可能在attach之前OOM。
4. native触摸/A/B用last_game_pointer_；Lua D-pad/详情用私有cursor。触摸后的UI=(200,200)，右移一步得到(336,240)，一致目标应为(216,200)。镜像模式不再定时同步bottom状态，native mapper仍读其input_context；Lua动作结尾又统计全院对象。
5. `apply_lifecycle`先session.suspend后save，真实组件begin_save_load拒绝。SaveGameFile未检查write/close；safe_call吞错误；读档兼容性拒绝nil可被标LOAD COMPLETE。native恢复优先提升未经验证tmp，实际组件复现其覆盖已知好backup的选择。现有GameUI:quit只回菜单，App:exit仅保存config/hotkeys。
6. runtime.tick计时遗漏后续事件派发、游戏逻辑、绘制、上屏present、下屏缩小/present、GC。240样本环形缓冲每60秒写日志无法代表完整一分钟。上游timer为18ms，移植层33.333ms参数不能证明整体30FPS。
7. 原图640×480、上屏400×240中心裁切、下屏320×240全画面镜像已接入。nearest/direct_zoom、关闭额外fullscreen zoom_buffer、关闭音乐/影片已经进入实际路径；可读性和帧率尚未验证。

补充入口问题：[scripts/build_3ds_docker.sh:39](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/build_3ds_docker.sh#L39)另设默认th3ds；[scripts/old3ds_cycle.sh:73–78](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/old3ds_cycle.sh#L73)full使用废弃参数，delta缺必需原数据输入；[tools/v061_acceptance.py:211](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/tools/v061_acceptance.py#L211)硬编码th3ds；上游config_finder保存配置会丢掉asset_mode。后续只调整这些直接产品调用与对应断言。

## 内存：历史事实、当前源码与推断分开

[docs/OLD3DS_MEMORY_BUDGET.md](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/docs/OLD3DS_MEMORY_BUDGET.md)保留旧head`9fbaeb6210108e27363c2bbc39769d70f2d41ea2`历史测量：regular heap总量56,180,736B（53.578125MiB），S70 uordblks55,124,320B，随后FATAL55,193,952B，主菜单前OOM；SOUND-0.DAT文件16,634,862B。原始boot.log本轮无法取得，口径为保留文档中的历史测量，其原始可复算性NOT_PROVEN。**这些数值不代表844121c当前实测。** Lua和资源分类均为总堆子集；不能重复相加。文档audio3MiB/sprite8MiB/texture6MiB等属于预算。

本轮独立核对生成后`CorsixTH/Src/th_sound.cpp`、`th_sound.h`、`th_lua_sound.cpp`、`CorsixTH/Lua/audio.lua`、`strings.lua`、`graphics.lua`与固定上游字节完全相同。仍有整库Lua读入、整库native vector复制、populate_from解码全部声音、编译全部语言、全sheet精灵解码。若选定未压缩音库仍为历史大小，两个archive副本就有33,269,724B，尚未计PCM与其他对象；这是有条件的大小推导。结合历史OOM足以确定高风险，当前峰值必须重测。

RuntimeSession创建得更晚，停用它不会消除上述启动分配。现有host packer的语言闭包、按块音效/精灵以及ResourceManager预算/lease/cache尚未接管这些游戏消费者。

现有`tools/th3ds_assets.py:110 build_language_bundle`在真实上游上本轮成功选择English闭包：24个Lua文件总3,302,661B，实际闭包`english.lua + original_strings.lua`共137,006B，另需`DATA/LANG-0.DAT`。本轮LANG-0.DAT仅用合成占位满足存在检查；这是实际Lua代码的静态闭包/部署字节事实，原版字符串解码与设备内存减少量NOT_PROVEN。


### 六个真实热点的固定源码

R17记录的生成字节与固定上游字节摘要相同；R19再次核对保留生成文件及这些摘要。按文件比较证明现有集成未改变这些消费者，加载顺序和全量行为由R17调用链分析共同支持。

| 固定上游文件 | SHA256（上游＝生成后） |
|---|---|
| [CorsixTH/Src/th_sound.cpp](https://github.com/CorsixTH/CorsixTH/blob/56bd5d00f76331c7f76d7b696726a7926303ca0c/CorsixTH/Src/th_sound.cpp) | `4b4c69c861bbcedab20c7c4a1623778fe0c92774b875101ef3f63f904441dbf9` |
| [CorsixTH/Src/th_sound.h](https://github.com/CorsixTH/CorsixTH/blob/56bd5d00f76331c7f76d7b696726a7926303ca0c/CorsixTH/Src/th_sound.h) | `baa849c935ec137560ef497d8b592b78a852012a4e019ccfc5d31c1155f3bfde` |
| [CorsixTH/Src/th_lua_sound.cpp](https://github.com/CorsixTH/CorsixTH/blob/56bd5d00f76331c7f76d7b696726a7926303ca0c/CorsixTH/Src/th_lua_sound.cpp) | `c2ba1c9f2687ea30457cdd48f7869508a9d07849ff0b6dafc3b3b2d5ce89daac` |
| [CorsixTH/Lua/audio.lua](https://github.com/CorsixTH/CorsixTH/blob/56bd5d00f76331c7f76d7b696726a7926303ca0c/CorsixTH/Lua/audio.lua) | `c8e45c5d38e0ac08528a4c7ae85ff1739e7a3a6197f821fbffaa0aced3bfdaa4` |
| [CorsixTH/Lua/strings.lua](https://github.com/CorsixTH/CorsixTH/blob/56bd5d00f76331c7f76d7b696726a7926303ca0c/CorsixTH/Lua/strings.lua) | `7f59e039fbd557df9d8951b30bcea469f782605b499d41e426bbcb5ca7b7c619` |
| [CorsixTH/Lua/graphics.lua](https://github.com/CorsixTH/CorsixTH/blob/56bd5d00f76331c7f76d7b696726a7926303ca0c/CorsixTH/Lua/graphics.lua) | `eb5726e481098b6ceacd65a1ac08845940a2b32dea00a9580419980681e7dbf4` |

## 冻结路线与最小施工

默认采用**loose + 原FileSystem + 选定语言闭包 + 文件支撑的按需音效**，保留原地图/精灵接口、原UI与现有双屏取舍。音频可在主机做有界局部预处理；无需把所有原始消费者迁入统一资源框架。

| 原方案部分 | 处理 |
|---|---|
| 原界面、mirror/crop、nearest/direct_zoom、额外buffer移除 | 复用；画面/可读性/性能真机复核 |
| 现有语言闭包选择器、sound严格parser、固定上游RNC解码器 | 复用到默认loose staging和文件音库前置检查 |
| 原保存格式、原手动/游戏日历自动保存、atomic commit | 复用；补write/close/异常结果/恢复顺序/可见状态及保存退出 |
| th3ds默认、强制session、attach与ready顺序、重复指针 | 调整为明确loose能力、提前native依赖、一次attach、UI唯一光标 |
| 全量音库读入/复制/全部PCM展开、全语言chunk | 启动前置修复；不能等到产品PASS后处理 |
| 全VSPR、纹理保留、存读档峰值 | 先取得声音/语言改动后同hash证据，命中阻断就做该消费者最小修复 |
| RuntimeSession与既有资源框架组件/RH测试 | 保留为显式实验路径；默认不mount、不发资源事件；不宣称RH问题已解决 |
| 全部typed loader接入、通用框架、多线程加载、自绘面板、GPU重写 | 暂缓；P1/P2/P3不依赖无关E0协议扩展 |

U1负责部署、语言闭包、有界音效、初始化与进度闭环。Audio:initSpeech传真实选定DAT路径；sound_archive只加载有界索引，load_sound提供限界RWops切片；populate_from不全量decode，play/play_at按需加载，3MiB PCM+Mix_Chunk上限，活动channel不可驱逐，完成回调只发标记，正常线程做I/O与释放。预检实际mixer转换大小和临时reserve；RNC整库仅在主机使用固定上游解码器规范化至staging，保存源/派生hash。不得回退设备整库解压/静音来给PASS。

native初始化在SDL/video后、重资源前返回capabilities，不attach；真实菜单后attach一次，再mark-ready；mainloop只assert-ready。loose所有resource_event调用明确关闭；实验调用误用于玩家入口报错。保留实验真实link edge，并另外验证玩家初始化链，不能以保留的RuntimeSession符号证明默认启动。

U2统一App.ui可见光标，按touch派发→轻场景→D-pad→轻场景→A/B/详情顺序处理；移除默认输入热路径中的全院统计。U3在真实游戏loop、双屏present及实际语言/音频/精灵/map/save分配位置插桩。U2/U3公共独立文件可提前准备，共享integrator/runtime/platform由一个所有者顺序集成。实施使用GPT-6 high；本次诊断要求GPT-6 max，无子代理。

保存采用手动+上游日历周期+显式保存退出；native每60秒及系统hook保存关闭。失败留在游戏且可见。读档前有world时先checked-save独立恢复文件，失败即取消；兼容性拒绝不得标成功；发布后失败给明确恢复入口。合盖/HOME只承担有界暂停恢复，无法承诺强关机/断电保存。对应libctru v2.7.0源代码把ONEXIT放在aptExit，不能依赖其提供下一tick保存时间。[APT源码](https://github.com/devkitPro/libctru/blob/36fe1ada5b7ebe53ba4decda36d764a55f8fefb6/libctru/source/services/apt.c)

最小文件范围：overlay [scripts/package_sd.sh](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/package_sd.sh)、[scripts/build_3ds.sh](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/build_3ds.sh)、直接Docker/cycle入口、[tools/validate_sd_tree.py](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/tools/validate_sd_tree.py)、[tools/v061_acceptance.py](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/tools/v061_acceptance.py)、新增局部`tools/prepare_loose_assets.py`（拟新增）、[tools/integrate_corsixth.py](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/tools/integrate_corsixth.py)、[lua/3ds/platform.lua](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/lua/3ds/platform.lua)、`src/3ds/runtime_3ds.*`、common input/lifecycle/atomic_save/telemetry及直接测试。上游改动由integrator生成，集中于app/config_finder/persistance/audio/game_ui、th_sound/th_lua_sound、sdl_core/main及真实分配点。现有host suite仅更新selected清单/哈希以纳入新增产品回归，保留baseline IDs和runner规则；149仅为历史数量。

## 当前施工分工与发布边界（根任务增量决定）

R20/U1、R21/U2、R22/U3均已指派，GPT-6 high，当前施工中。U1同时负责启动接通与English/音效内存前置，并唯一集成runtime/platform/integrator；U2直接修改独立InputMapper，桥接补丁交U1；U3直接修改公共telemetry，实际帧/资源内存插桩补丁交U1。U1按顺序合入，第一轮设备前须接齐仪表。当前被审代码仍为844121c，尚无新的已验收产品候选。

R18的五类E0返修按原三个验证文件并行推进。最终产品与已验收E0修改在同hash候选合流后分层验收；已有十项公网成功及原架构成果保留，新候选需要自己的回归。优先检查实际游戏成功路径，继续暂缓无关验证协议扩张。

施工完成的新候选可先以“施工完成、独立验收NOT_PROVEN”公开供审查，实际代码head、文档head和证据层分别列明；本次不等待施工结果。长期、多关卡、完整资源架构门槛保持未完成，首轮验收不会替代它们。

## 实际通过项与未通过项

R17门槛：**P1=FAIL、P2=FAIL、P3_instrumentation=FAIL**；Old3DS_runtime / fps / memory均为 **NOT_PROVEN**。诊断完成、组件观测成功与产品门槛分层记录。

- PASS：冻结身份、真实固定上游组装、独立Old3DS交叉构建、最终ELF静态8MiB linear及实验session调用链、显式loose结构打包、7项Lua诊断观测、原生生命周期/恢复观测、真实上游English闭包选择。
- FAIL：默认th3ds打包；已确认启动、混合输入、保存结果和帧测量代码缺陷；RH09-H1零level包仍进入LEVEL_STABLE；RH07-H2失败prepare仍留下64B及逃逸lease。
- NOT_PROVEN：原版数据完整解码、当前Old3DS冷启动/第一关/声音/操作/保存恢复/可读性、当前真实heap/linear峰值、30FPS、持续运行。原版数据夹具为7个合成文件，结构PASS只证明结构。
- R17未执行E0公开验证或更改其代码；E0独立返修由另一任务负责，产品隔离施工可依赖本合同提前进行，正式发布仍遵守根任务验收。

首轮门槛：P1三次真实冷启动到第一关；P2接待/GP/招聘/患者就诊与混合输入、三次保存退出重启、HOME/合盖复验；P3完整帧/逻辑/绘制/双屏/加载保存停顿及实际内存采样。暖机后5次菜单/第一关和5次同档读取；达到20患者后30分钟活跃观察，至少10分钟20+患者。稳定段目标30成功双屏present/s、p95≤33.34ms，与测量完成分开判定。既有阶段/资源预算保持，采样峰值说明覆盖粒度。首轮筛查不替代原资源架构的4096-frame分块音频、全sprite block规则及2小时验收。

请外部审查优先检验：文件音库与lazy PCM是否真正进入原游戏消费者；RNC/索引边界及活动channel所有权；初始化失败/重复attach是否收口；同批触摸按键的坐标与场景顺序；保存失败是否可能退出/假成功；计时是否覆盖两屏和停顿。以生成源码与实际调用为准，设备结果需要相同head/二进制/数据hash的原始证据。
