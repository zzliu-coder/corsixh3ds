# Corsixh3ds 外部审查入口 · R19 / R23-U1-SYNC

**当前优先审查产品组合 [`e3f2c4a`](https://github.com/zzliu-coder/corsixh3ds/tree/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e)。** U1/U2/U3已组合并公开：C++、本地交叉构建/loose包施工通过；完整本地Python **FAIL**，后续同head公网CI **FAIL**，设备P1/P2/P3与完整游戏仍 **NOT_PROVEN**。E0候选`48cc842`的R23正式独立验收为 **FAIL**：F01/F02未关闭，F03/F04/F05通过。先检查实际成功路径，再按既有合同核对验收阻塞；下文保留历史基点与结果时间边界。

## 1. 版本身份与目标

| 对象 | 固定身份与用途 |
|---|---|
| **当前公开产品组合** | [`e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e`](https://github.com/zzliu-coder/corsixh3ds/tree/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e)；tree `dc7469658218ea84ca2a34bdb8e9a218a3e4d7a2`；sole parent `fe569cf563ab9a01848686d3fef47c4c4b82d3bd`。分支`codex/product-u1-boot-assets-save-r20`；相对R17基点40文件，供R26独立产品验收 |
| R17历史产品诊断基点 | [`844121cd86e5905c8a53c4574fab399d11ea0849`](https://github.com/zzliu-coder/corsixh3ds/tree/844121cd86e5905c8a53c4574fab399d11ea0849)；tree `cfa70da3d4503ea9b997064fce4e75c6d65758ca`；parent `8e9df167da524c2a8bdc3296227544d559dc70dc`。本文R16/R17历史发现仍固定此快照 |
| 独立E0验证设施候选 | [`48cc842095d548f143f8674a6778fdb511292638`](https://github.com/zzliu-coder/corsixh3ds/tree/48cc842095d548f143f8674a6778fdb511292638)；tree `d826490849f228096ab822765958d236eea6ebf3`；sole parent `8e9df167da524c2a8bdc3296227544d559dc70dc`。相对844只改三个验证文件、54产品路径未变；R23正式FAIL，R24继续修F01/F02 |
| 文档修订 | `GITHUB-REVIEW-CONTEXT-PUBLISH-R19 / R23-U1-SYNC`；[`docs/review-context`](https://github.com/zzliu-coder/corsixh3ds/blob/docs/review-context/REVIEW_CONTEXT.md)，从上一资料提交`55794e7246d23df21e6b12c485125c250b8d1162`非force追加。文档历史保留；本文件永久链接的commit只标识资料，不充当产品候选 |

当前详细入口：[产品组合与证据边界](docs/review/U1-combined-product-candidate.md)、[R23正式验收](docs/review/R23-independent-acceptance.md)。[R17诊断](docs/review/R17-playable-path-diagnosis.md)与[R18施工说明](docs/review/R18-validation-repair.md)保留各自封存时状态，当前状态以本文及新说明为准。

默认分支 `main`、最新提交和文档提交各有自己的身份。引用结论时附完整**代码 head**；文档提交只标识交接内容，不能替代产品候选。

目标硬件为 **Old 3DS，无裸眼 3D**。最小成功路径：

> 冷启动 → 主菜单 → 第一关 → 建接待台和诊室 → 招聘 → 患者完成就诊 → 保存 → 退出 → 重启恢复。

实现顺序应能追踪为：固定上游 → 组装后的实际程序 → 与真实 loader 一致的 SD 目录及配置 → 初始化必要依赖 → 适配器挂接一次 → 上述游戏路径。每步说明入口、输入及所有者、成功状态、失败时可观察结果和最小验证方法。忙医院、换关与长期运行仍需后续验收。

## 2. 历史证据、R23正式验收与当前产品结果

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

以下行号和五类历史FAIL全部对应固定 `844121c`，保持R16原结论。R18已完成施工及同版本公开验证；**R23已正式验收：F03/F04/F05 PASS，F01/F02 FAIL**。下表继续记录844上的原缺陷。

| 缺陷 | 根因与最小复现 | 现有修复边界 |
|---|---|---|
| **F01 · P1** 原始行/图失真仍通过 | [`scripts/ci_diagnostics.sh:501–545`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L501-L545) 只读聚合计数；将 E01 改为 `pass=false, actual_exit=99`，保留60/60汇总并重封摘要，stage/archive仍 PASS；H2假观测、重复行、journal/DAG环同类 | 在现有消费者复算固定行集合、结果、观测差值与 journal 图；在既有测试方法扩展真实子案例，保持149个可发现 ID |
| **F02 · P1** 内部身份绑定未闭合 | [`ci_diagnostics.sh:498–582`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L498-L582)：单改 `receipt.candidate_identity.commit` 为40个0，或改内部 bundle 摘要、删 `created_at_utc`，重封后仍接受 | 交叉核对现有 candidate/bundle/session 字段和摘要，要求合法 UTC 时间，保持冻结字段合同 |
| **F03 · P2** ZIP 原始文件名 NUL 漏检 | [`ci_diagnostics.sh:734–736`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L734-L736) 检查已截断的 `ZipInfo.filename`；将 local/central 名称后缀改为 NUL 加尾串并提供正确传输摘要，可落入白名单 | 提取前检查原始名称并拒绝 NUL，要求规范化名称精确一致；追加字节级 ZIP 子案例 |
| **F04 · P2** 失败诊断遗漏、超时无独立记录 | [`ci_diagnostics.sh:647–669`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L647-L669) 只留固定文件，遗漏 journal 引用的已有 stderr；[workflow:469–503](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/.github/workflows/old3ds-validation.yml#L469-L503) 只转交 failure outcome，无法明确记录内层 timeout | 在现有有界失败包中保留安全引用的诊断字节、内层超时/退出记录；runner 丢失和整个 job 硬超时可用性仍 NOT_PROVEN |
| **F05 · P2** JSON 类型错误没有稳定失败结果 | [`ci_diagnostics.sh:570–575`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L570-L575)、[776–783](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L776-L783)：manifest 换为合法 JSON `[]` 后 `.get` 抛异常，退出1且只有 traceback | 先检查容器/字段类型，再输出既有稳定 FAIL/code。此例已经拒绝输入，缺陷在失败输出合同 |

### R23正式FAIL；真实成功证据独立复算仍PASS

新E0候选[`48cc842`](https://github.com/zzliu-coder/corsixh3ds/tree/48cc842095d548f143f8674a6778fdb511292638)的[公开运行33938765229](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33938765229) attempt1仍为10/10 success。R23独立下载Fresh与完整bundle并复算通过；原195+14回归也通过。**正式验收FAIL**：F01的H2实际argv/run-id与固定pool槽2/backend槽0计算未闭合；F02的bundle角色覆盖及candidate transport实际摘要未绑定。五个组合反例均被stage/archive误接受。F03/F04/F05的原缺陷通过独立验收，可关闭；boolean/zero观察仅NOT_PROVEN，不新增为硬条件。见[R23精简说明](docs/review/R23-independent-acceptance.md)。

R24（GPT-6 high）在原workflow、`scripts/ci_diagnostics.sh`、`tests/test_ci_diagnostics.py`三文件边界直接修完整关系，保留原成功证据及既有合同。RH07/RH09实验路径FAIL、真机运行/内存NOT_PROVEN保持。E0的旧或新10/10均不替代未来产品组合的同hash回归。

### 当前产品组合：施工封存与后续公网结果分开

**施工封存（2026-09-05T03:53:34.907863+00:00）：** [`e3f2c4a`](https://github.com/zzliu-coder/corsixh3ds/tree/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e)已整合English闭包、文件支撑有界按需音效、唯一输入位置、checked保存/暂停及实际资源/完整帧测量。C++134/134、生成代码、本地交叉构建和loose包为施工PASS；完整Python166 selected：164 PASS、1 ERROR、1允许的大小写文件系统skip，整体 **FAIL**。已定位本地错误`CANDIDATE_PARENT_MISMATCH`：产品历史直接父为`fe569cf...`，不符合保留E0合同的直接R9父要求。143 baselineCount与E0的149属于待核对的不同清单，不能只凭数字差判定丢测。

**后续根任务读回（R19于2026-09-05T04:13:30.571424+00:00复核API）：** [run33943007122](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33943007122)，attempt1、exacthead`e3f2c4a`，completed/**failure**；2成功（old3ds-cross-build、runtime-core-protocol-self-test）、7失败（verifier-authority-negative、四项host C++、两项Python）、1跳过（final seal）。各失败日志原因尚未逐项核查，不能统归为本地父提交错误。施工者封存时的`in_progress`原快照保留。

按需音效的主机已知所有者峰值3,145,539B，实际英语747索引/746可播放槽，启动PCM=0，100回收循环；不包含全部SDL、分配器及未知暂存，设备总内存仍未证明。[产品说明](docs/review/U1-combined-product-candidate.md)列明测试替身和其他限制。实际完整游戏、真机P1/P2/P3、稳定性能/内存仍 **NOT_PROVEN**，设备准入未放行。

## 3. R17历史诊断（固定844快照）

以下只描述844，不能自动套用到新e3f2组合；新实现尚待R26独立验证。[R17详细诊断](docs/review/R17-playable-path-diagnosis.md)来自已封存报告、真实固定上游组装、组件执行及源码比对。原外部AI转述仅用于提出问题；R17的独立证据支持以下限定结论。R17同步版已核对回执及107项摘要，未重跑构建或设备检查。

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

## 4. R17内存依据与沿用的完成条件

[`docs/OLD3DS_MEMORY_BUDGET.md` §3](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/docs/OLD3DS_MEMORY_BUDGET.md#3-已测基线) 保留的是**旧 v0.6.1 / `9fbaeb6` 历史真机测量**：普通堆53.578125 MiB，启动约52.6 MiB已分配后 OOM，尚未主菜单。原始 boot.log 本轮未在旧路径找到，引用仅能追溯到保留文档。R17诊断时 `844121c` 尚无同 hash 真机内存数据；Lua及音效/精灵等分类属于总堆或linear的子集，不能重复相加。文档中的分类上限、52 MiB/8 MiB配置条件与30 FPS目标均须与实测区分。

**R17冻结观察：** R17把生成后的`th_sound.cpp`、`th_sound.h`、`th_lua_sound.cpp`、`audio.lua`、`strings.lua`、`graphics.lua`与固定上游比对，六文件字节完全相同。整库音效Lua读入/native复制/全部PCM解码、全语言chunk及全sheet精灵解码仍在实际路径；既有语言/分块音效/精灵和ResourceManager预算缓存优化尚未接管这些消费者。

默认**施工路线**为loose原始目录＋English实际闭包＋文件支撑的有界按需音效，保留原地图/精灵接口。现有选择器在真实上游选出`english.lua + original_strings.lua`，还需原`DATA/LANG-0.DAT`；本轮原字符串占位也是合成数据，闭包选择成功不证明原版解码。语言、音效前置修复与启动接通由同一单元负责；第一轮设备候选必须包含完整帧及真实资源内存仪表。精灵/纹理/存读档峰值按实际观测决定最小追加修复。原始目录的读取、解码、复制与驻留决定峰值，切换mode或停用较晚创建的`RuntimeSession`不能承诺省内存。旧架构及RH问题保留在显式实验路径，隔离本身不修复它们。

先完成三道产品门槛：**P1 跑通**（真实上游结构、统一部署模式、正确初始化、第一关画面与音效）；**P2 可操作且能保留进度**（混合输入、接待/诊室/招聘/就诊、保存退出重开、合盖/HOME返回）；**P3 性能可测**（完整帧、启动/进关/解码/存读档峰值、余量、释放后基线）。保留原界面和双屏镜像方案，验证裁切、缩小后的可读性；每帧写 SD 不应成为测量负担。忙医院、换关和长期运行完成前继续单列待证明状态。

## 5. 当前任务与下一步

| 任务 | 当前状态与责任 |
|---|---|
| R17 · GPT-6 max | 诊断与施工合同已封存；历史发现固定844 |
| R18 / R23 · GPT-6 high | R18施工及公网完成；R23独立验收完成且正式FAIL，F03/F04/F05关闭、F01/F02未关闭 |
| R24 · GPT-6 high | 原三个验证文件内修F01/F02完整来源关系；沿用现有验证框架 |
| R20 / U1 · GPT-6 high | 已组合U2/U3并封存、公开e3f2；仍为唯一共享文件集成人。等待R25/R26结果后再施工 |
| R21 / U2、R22 / U3 · GPT-6 high | 组件已纳入U1当前公开组合。来源身份分别为`6ce399899b64d853ae71f88ec94de04fe0ccd64e`、`fbf8fcd4f164f93ac495f8b10389152fc1d56ecb`；当前代码审查统一指向e3f2 |
| R25 · GPT-6 max | 只查既有验收身份合同与全部公网失败，不以未经日志核对的共同原因作结论 |
| R26 · GPT-6 high | 只读独立验收实际产品组合，设备准入未放行 |

原组件主机通过与当前组合的完整本地/公网FAIL分别保留。R23与U1两份封存记录均不被后续状态覆盖；新发现和实际修复候选由根任务持回执再同步。E0与产品最终同hash合流并分层验收，长期、多关卡及完整资源架构门槛继续留账。暂缓通用框架扩张、全loader重写、额外协议、全GPU、自绘UI与复杂多线程。

请外部审查者围绕固定 head 提供：**触发输入 → 实际调用与状态/所有权变化 → 可观察失败 → 被阻断的成功路径步骤**，附精确文件/行、可复现方法及最小修复边界；分别报告主机、构建、设备的 `PASS / FAIL / NOT_PROVEN`，说明未执行项。优先找成功路径阻塞，沿用现有验证体系。

发布范围仅为本技术入口。本文提交使用 GitHub 的 `[skip ci]` 纯文档跳过方式以避免大型构建；工作流配置保持原状。产品候选继续遵守完整验收要求。公开材料不包含原版游戏资源、存档、私人路径、凭据或未经检查的本机日志。
