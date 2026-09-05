# Corsixh3ds 外部审查入口 · R19 / R18-SYNC

**当前结论：R17诊断完成，启动/操作/保存与计时代码阻断已确认；P1/P2/P3仪表代码 FAIL，Old 3DS运行与内存 NOT_PROVEN。原844快照E0正式验收 FAIL；新R18候选公开10/10 PASS，R23独立验收中（NOT_PROVEN）。** 请先审查启动、操作、保存恢复的实际阻塞，再看验证设施缺口。本文是截至 2026-09-05 的精简技术交接；状态不会随分支最新提交自动升级。

## 1. 版本身份与目标

| 对象 | 固定身份 |
|---|---|
| R17产品诊断基点（公开代码） | [`844121cd86e5905c8a53c4574fab399d11ea0849`](https://github.com/zzliu-coder/corsixh3ds/tree/844121cd86e5905c8a53c4574fab399d11ea0849)；产品与验证设施共同所在快照，尚未产品验收 |
| 新E0验证设施候选 | [48cc842095d548f143f8674a6778fdb511292638](https://github.com/zzliu-coder/corsixh3ds/tree/48cc842095d548f143f8674a6778fdb511292638)；tree `d826490849f228096ab822765958d236eea6ebf3`，sole parent `8e9df167da524c2a8bdc3296227544d559dc70dc`；54产品路径未变，产品可玩性未证明 |
| R17基点 tree / sole parent | `cfa70da3d4503ea9b997064fce4e75c6d65758ca` / `8e9df167da524c2a8bdc3296227544d559dc70dc` |
| R17定位分支 | `codex/e0-r14-fresh-evidence-retention-sibling`；本行定位R17基点，R18候选链接另列 |
| 文档发布版本 | `GITHUB-REVIEW-CONTEXT-PUBLISH-R19 / R18-SYNC`，专用分支 [`docs/review-context`](https://github.com/zzliu-coder/corsixh3ds/blob/docs/review-context/REVIEW_CONTEXT.md)，从R17诊断基点 `844121c` 派生，首版为 `45453355d118374dc827a14638e831a488f8c61f`；本次非force追加于U2/U3增量 `12af353ab5b73c6d52d87baff5332b2bd485df10`，本次更新本文并新增[R18修复说明](docs/review/R18-validation-repair.md)，既有[R17细节](docs/review/R17-playable-path-diagnosis.md)保留；文档提交身份以本文件的 GitHub 永久链接所含 commit 为准 |

默认分支 `main`、最新提交和文档提交各有自己的身份。引用结论时附完整**代码 head**；文档提交只标识交接内容，不能替代产品候选。

目标硬件为 **Old 3DS，无裸眼 3D**。最小成功路径：

> 冷启动 → 主菜单 → 第一关 → 建接待台和诊室 → 招聘 → 患者完成就诊 → 保存 → 退出 → 重启恢复。

实现顺序应能追踪为：固定上游 → 组装后的实际程序 → 与真实 loader 一致的 SD 目录及配置 → 初始化必要依赖 → 适配器挂接一次 → 上述游戏路径。每步说明入口、输入及所有者、成功状态、失败时可观察结果和最小验证方法。忙医院、换关与长期运行仍需后续验收。

## 2. R15/R16历史证据与R18施工进展

下表继承已封存的 **R16 独立验收**。R19首版已核对报告、summary 和摘要清单，与 GitHub 的代码身份、run 和 release 元数据；未重新执行 R16 的大型下载或测试。R16 原报告 SHA256：`23757ebec0ab30b78199546ac3dba6e795e837ba555d63543bbf137106e868d7`。报告原文及负面输入留在本地，以下为可公开摘要；外部审查者可从公开源码复现这些最小变异。

| 证据层 | 状态与边界 |
|---|---|
| 公网运行 | [run 33932207215 / attempt 1](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33932207215)，同一代码 head，10/10 jobs completed/success：**PASS** |
| Fresh 原始证据 | [artifact 9959080299](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33932207215/artifacts/9959080299)：58 个常规文件、56 个载荷、57 条排序 LF 摘要；内容、绑定及矩阵/H2/DAG由 R16 独立复算：**PASS**。ZIP SHA256 `e52492ac9f50ee2ba881b2ac503f6553c47dd7ab9a1077bb7d015702d0fb6a31` |
| 完整验证 bundle | [release](https://github.com/zzliu-coder/corsixh3ds/releases/tag/e0-r14-fresh-evidence-844121cd86e5) / [asset 545104307](https://github.com/zzliu-coder/corsixh3ds/releases/download/e0-r14-fresh-evidence-844121cd86e5/input-bundle-r14-fresh-evidence-linux-x86_64-844121cd86e5.tar)，813,547,520 bytes，全字节及内部小文件核对：**PASS**；SHA256 `7fbeeee50bcd8052860148698a92aa4b3b991d705cd9b7788b9315d9f97e0c6f`。阅读本文无需下载 |
| 主机 / 交叉构建 | R16 核对公开原始结果：Python 3.9.25、3.14.6 各149个固定测试 ID，protocol 33 行，ARM ELF 及链接证明：**PASS**，只证明对应主机/构建层 |
| E0 正式验收 | **FAIL**：正确输入可通过，错误输入的拒绝、诊断与绑定合同存在下列五类缺陷 |
| 产品边界 | `RH07_PRODUCT=FAIL`、`RH09_PRODUCT=FAIL`，沿用 R16 保留判定 |
| 真机 / 内存 / 来源 | `REAL_DEVICE_RUNTIME`、`S70_REAL_DEVICE_MEMORY`、`UPSTREAM_GIT_PROVENANCE` 均为 **NOT_PROVEN**。同 hash 真机运行与S70内存仍缺失；上游Git来源是R16冻结判定。R17新增固定上游身份与真实组装PASS，证据范围见下节 |

R16 负面测试共 195 项（168 PASS / 27 FAIL），追加边界14项（13 PASS / 1 FAIL）；28个失败检查归并为5个根因。有效公开包自身的完整性继续为 PASS；这些验证结果尚不足以得出“游戏已可玩”。

### 已复现的 R16-F01…F05

以下行号和五类历史FAIL全部对应固定 `844121c`，保持R16原结论。R18已完成施工及同版本公开验证；**五类缺陷在R18中的正式关闭状态待R23独立验收（NOT_PROVEN）**。

| 缺陷 | 根因与最小复现 | 现有修复边界 |
|---|---|---|
| **F01 · P1** 原始行/图失真仍通过 | [`scripts/ci_diagnostics.sh:501–545`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L501-L545) 只读聚合计数；将 E01 改为 `pass=false, actual_exit=99`，保留60/60汇总并重封摘要，stage/archive仍 PASS；H2假观测、重复行、journal/DAG环同类 | 在现有消费者复算固定行集合、结果、观测差值与 journal 图；在既有测试方法扩展真实子案例，保持149个可发现 ID |
| **F02 · P1** 内部身份绑定未闭合 | [`ci_diagnostics.sh:498–582`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L498-L582)：单改 `receipt.candidate_identity.commit` 为40个0，或改内部 bundle 摘要、删 `created_at_utc`，重封后仍接受 | 交叉核对现有 candidate/bundle/session 字段和摘要，要求合法 UTC 时间，保持冻结字段合同 |
| **F03 · P2** ZIP 原始文件名 NUL 漏检 | [`ci_diagnostics.sh:734–736`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L734-L736) 检查已截断的 `ZipInfo.filename`；将 local/central 名称后缀改为 NUL 加尾串并提供正确传输摘要，可落入白名单 | 提取前检查原始名称并拒绝 NUL，要求规范化名称精确一致；追加字节级 ZIP 子案例 |
| **F04 · P2** 失败诊断遗漏、超时无独立记录 | [`ci_diagnostics.sh:647–669`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L647-L669) 只留固定文件，遗漏 journal 引用的已有 stderr；[workflow:469–503](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/.github/workflows/old3ds-validation.yml#L469-L503) 只转交 failure outcome，无法明确记录内层 timeout | 在现有有界失败包中保留安全引用的诊断字节、内层超时/退出记录；runner 丢失和整个 job 硬超时可用性仍 NOT_PROVEN |
| **F05 · P2** JSON 类型错误没有稳定失败结果 | [`ci_diagnostics.sh:570–575`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L570-L575)、[776–783](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L776-L783)：manifest 换为合法 JSON `[]` 后 `.get` 抛异常，退出1且只有 traceback | 先检查容器/字段类型，再输出既有稳定 FAIL/code。此例已经拒绝输入，缺陷在失败输出合同 |

### R18施工完成；R23独立验收中

新E0候选[`48cc842`](https://github.com/zzliu-coder/corsixh3ds/tree/48cc842095d548f143f8674a6778fdb511292638)相对R15仅修改`.github/workflows/old3ds-validation.yml`、`scripts/ci_diagnostics.sh`和`tests/test_ci_diagnostics.py`，54产品路径指纹保持不变。[同版本公开运行33938765229](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33938765229) attempt1为10/10 success；[Fresh artifact9961199388](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33938765229/artifacts/9961199388)的ZIP SHA256为`73839365d81caf6b5e6e0a4e2751ad6f685389609c4232a8ae212b13ad20f258`。

原195+14项复验、293项公开原始复算通过，均为**施工证据**。R19核对79项封存摘要和公开身份/API，未重跑这些验证。R23（GPT-6 high）正在依据既有R14合同及五类缺陷开展独立验收，正式结果仍 **NOT_PROVEN/进行中**。修复内容与证明边界见[R18精简说明](docs/review/R18-validation-repair.md)。保留R15/R16历史成果、RH07/RH09 FAIL及真机运行/内存NOT_PROVEN。

## 3. R17 已完成的产品路径诊断

[R17详细诊断](docs/review/R17-playable-path-diagnosis.md)来自已封存报告、真实固定上游组装、组件执行及源码比对。原外部AI转述仅用于提出问题；R17的独立证据支持以下限定结论。R17同步版已核对回执及107项摘要，未重跑构建或设备检查。

| 已执行层 | R17结果与边界 |
|---|---|
| 固定上游组装 / 交叉构建 | CorsixTH v0.70.1 `56bd5d00f76331c7f76d7b696726a7926303ca0c`真实组装 **PASS**；独立Old3DS交叉构建 **PASS**，只证明构建层 |
| 默认 / loose打包 | 默认th3ds **FAIL**（真实语言目录不匹配，exit2）；loose **PASS（结构）**，仅7个合成游戏文件、308,426 bytes，原版解码及完整游戏 **NOT_PROVEN** |
| 组件诊断 / 产品门槛 | 7项Lua及原生组件观测复现；P1、P2、P3仪表代码 **FAIL**；RH09-H1、RH07-H2仍 **FAIL**；当前Old3DS运行、帧率、内存 **NOT_PROVEN** |

| 项目 | 已确认结果与限定；固定源码入口 |
|---|---|
| 语言目录 | 默认要求`CorsixTH/Languages`，真实上游使用`CorsixTH/Lua/languages`；自造测试目录未覆盖真实结构。[scripts/package_sd.sh](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/package_sd.sh)；[tests/test_package_sd_script.py](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/tests/test_package_sd_script.py) |
| 资源模式与消费者 | config/FileSystem消费game目录和原始文件；th3ds只提供resources，native initialize仍强制session、忽略loose。[scripts/package_sd.sh](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/package_sd.sh)；[src/3ds/runtime_3ds.cpp](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/src/3ds/runtime_3ds.cpp)；[tools/integrate_corsixth.py](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/tools/integrate_corsixth.py) |
| 初始化与attach | 真实组装中UI之后attach→sync→菜单事件，session到后续mainloop才创建；组件复现失败遗留wrapper/app._3ds及重试重复包装。互斥UI分支没有证明正常执行无条件attach两次；原版重资源还可能更早OOM。初始化失败继续及错误READY已确认。[tools/integrate_corsixth.py](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/tools/integrate_corsixth.py)；[lua/3ds/platform.lua](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/lua/3ds/platform.lua) |
| 唯一光标与场景 | native和Lua指针分离；触摸UI=(200,200)后D-pad右移实际到(336,240)，一致目标为(216,200)。镜像场景更新过期、动作尾部全院统计及同批触摸/按键顺序均需修复。[src/3ds/runtime_3ds.cpp](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/src/3ds/runtime_3ds.cpp)；[lua/3ds/platform.lua](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/lua/3ds/platform.lua) |
| 保存与生命周期 | suspend先于save导致begin_save_load拒绝；write/close和异常结果未闭合，兼容性拒绝可误标成功，恢复组件优先提升坏tmp。ONEXIT没有已证明的保存时机；路线采用手动/日历周期/明确保存退出，合盖与HOME有界暂停恢复。[src/common/runtime_session.cpp](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/src/common/runtime_session.cpp)；[src/common/atomic_save.cpp](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/src/common/atomic_save.cpp)；[lua/3ds/platform.lua](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/lua/3ds/platform.lua) |
| 完整帧计时 | tick计时遗漏后续逻辑、绘制、双屏present及GC；240样本环不能代表整分钟。需同一候选接入完整帧与实际加载采样。[src/3ds/runtime_3ds.cpp](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/src/3ds/runtime_3ds.cpp)；[src/common/telemetry.cpp](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/src/common/telemetry.cpp)；[tools/integrate_corsixth.py](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/tools/integrate_corsixth.py) |
| 双屏与内存 | 裁切/镜像、nearest/direct_zoom、移除额外buffer及禁音乐/影片已进入路径；设备效果仍待证明。六个声音/语言/图形热点与固定上游逐字节相同，全量声音、语言与sheet加载仍存在。见下节及详细报告 |

## 4. 内存决策与完成条件

[`docs/OLD3DS_MEMORY_BUDGET.md` §3](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/docs/OLD3DS_MEMORY_BUDGET.md#3-已测基线) 保留的是**旧 v0.6.1 / `9fbaeb6` 历史真机测量**：普通堆53.578125 MiB，启动约52.6 MiB已分配后 OOM，尚未主菜单。原始 boot.log 本轮未在旧路径找到，引用仅能追溯到保留文档。当前 `844121c` 尚无同 hash 真机内存数据；Lua及音效/精灵等分类属于总堆或linear的子集，不能重复相加。文档中的分类上限、52 MiB/8 MiB配置条件与30 FPS目标均须与实测区分。

**新事实：** R17把生成后的`th_sound.cpp`、`th_sound.h`、`th_lua_sound.cpp`、`audio.lua`、`strings.lua`、`graphics.lua`与固定上游比对，六文件字节完全相同。整库音效Lua读入/native复制/全部PCM解码、全语言chunk及全sheet精灵解码仍在实际路径；既有语言/分块音效/精灵和ResourceManager预算缓存优化尚未接管这些消费者。

默认**施工路线**为loose原始目录＋English实际闭包＋文件支撑的有界按需音效，保留原地图/精灵接口。现有选择器在真实上游选出`english.lua + original_strings.lua`，还需原`DATA/LANG-0.DAT`；本轮原字符串占位也是合成数据，闭包选择成功不证明原版解码。语言、音效前置修复与启动接通由同一单元负责；第一轮设备候选必须包含完整帧及真实资源内存仪表。精灵/纹理/存读档峰值按实际观测决定最小追加修复。原始目录的读取、解码、复制与驻留决定峰值，切换mode或停用较晚创建的`RuntimeSession`不能承诺省内存。旧架构及RH问题保留在显式实验路径，隔离本身不修复它们。

先完成三道产品门槛：**P1 跑通**（真实上游结构、统一部署模式、正确初始化、第一关画面与音效）；**P2 可操作且能保留进度**（混合输入、接待/诊室/招聘/就诊、保存退出重开、合盖/HOME返回）；**P3 性能可测**（完整帧、启动/进关/解码/存读档峰值、余量、释放后基线）。保留原界面和双屏镜像方案，验证裁切、缩小后的可读性；每帧写 SD 不应成为测量负担。忙医院、换关和长期运行完成前继续单列待证明状态。

## 5. 正在做什么，以及如何反馈

| 任务 | 当前状态与责任 |
|---|---|
| R17 · GPT-6 max | **诊断完成，合同已封存**；产品仍PRODUCT_BLOCKED。已完成本次资料同步 |
| R18 · GPT-6 high | **施工及同版本公开验证完成**；保持三个验证文件边界，正式关闭待R23 |
| R23 · GPT-6 high | **独立验收中 / NOT_PROVEN**：依据既有R14合同及R16五类缺陷重新验收R18 |
| R20 / U1 · GPT-6 high | **施工中**：启动＋English/音效内存前置＋保存/生命周期；唯一拥有共享runtime/platform/integrator及最终集成 |
| R21 / U2 · GPT-6 high | **组件完成，已交U1待实际集成**：独立InputMapper与输入回归；共享桥接补丁及接线清单由U1顺序合入 |
| R22 / U3 · GPT-6 high | **组件完成，已交U1待实际集成**：公共telemetry与独立测试；共享插桩补丁/API由U1接入实际消费者，仍是第一轮设备候选前置 |

U2本地组件身份：`6ce399899b64d853ae71f88ec94de04fe0ccd64e`，仅3文件。封存主机结果为119项C++、17项ASan/UBSan及9项带原生/引擎测试替身的Lua桥接观测通过。组件候选的共享runtime/platform仍是冻结版，旧光标偏移仍可复现；实际native/HID/SDL/GameUI接线、混合操作与P2端到端继续 **NOT_PROVEN**。

U3本地组件身份：`fbf8fcd4f164f93ac495f8b10389152fc1d56ecb`，仅6文件。119项C++、24项ASan/UBSan、10项相关Python及5项带SDL/Lua测试缝的生成函数测量检查通过。组件已实现成功双屏软件提交间隔、长停顿、阶段耗时、采样内存及未知暂存的记录；ARM检查仅语法，完整交叉链接和设备未做。新lazy音效入口的实际观测、组合候选、设备性能/内存仍 **NOT_PROVEN**。

以上两个commit仅在本地，公开仓库尚未包含其组件代码，因而不提供GitHub组件commit链接。根任务已将组件、共享补丁及API交给同一U1集成人；U1完成当前基础事务后顺序合入U2、U3，再交付同一实际生成源码/交叉构建/SD候选供独立验收。待U1推送真实集成版本后再更新代码审查链接。R17详细报告保留当时快照，施工最新状态以本节为准。

产品成功路径继续以`844121c`为R17诊断基点；`48cc842`单列为新E0验证设施候选。U1/U2/U3实际产品组合尚未封存/公开，两个本地组件身份保持原限定。U2/U3组件已交付，共享文件由U1顺序集成；E0独立验收与产品集成并行，最终同一候选hash合流并分别完成主机、构建、设备验收，旧10/10不替代新候选回归。保留原计划和已有成果，长期、多关卡及完整资源架构门槛继续留账；暂缓通用框架扩张、全loader重写、额外协议、全GPU、自绘UI与复杂多线程。

后续新候选可在“**施工完成、独立验收NOT_PROVEN**”状态提前公开供审查，文档head与产品head分别记录；验收通过再升级状态。本次不等待R23验收或U1产品组合结果，后续由根任务持封存回执驱动增量同步。

请外部审查者围绕固定 head 提供：**触发输入 → 实际调用与状态/所有权变化 → 可观察失败 → 被阻断的成功路径步骤**，附精确文件/行、可复现方法及最小修复边界；分别报告主机、构建、设备的 `PASS / FAIL / NOT_PROVEN`，说明未执行项。优先找成功路径阻塞，沿用现有验证体系。

发布范围仅为本技术入口。本文提交使用 GitHub 的 `[skip ci]` 纯文档跳过方式以避免大型构建；工作流配置保持原状。产品候选继续遵守完整验收要求。公开材料不包含原版游戏资源、存档、私人路径、凭据或未经检查的本机日志。
