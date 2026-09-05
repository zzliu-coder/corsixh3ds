# Corsixh3ds 外部审查入口 · R19

**当前结论：公开成功证据独立复算 PASS；E0 验证设施正式验收 FAIL；Old 3DS 最小可玩路径尚未证明。** 请先审查启动、操作、保存恢复的实际阻塞，再看验证设施缺口。本文是截至 2026-09-05 的精简技术交接；状态不会随分支最新提交自动升级。

## 1. 版本身份与目标

| 对象 | 固定身份 |
|---|---|
| 本轮被审代码 | [`844121cd86e5905c8a53c4574fab399d11ea0849`](https://github.com/zzliu-coder/corsixh3ds/tree/844121cd86e5905c8a53c4574fab399d11ea0849)；产品与验证设施共同所在快照，尚未产品验收 |
| 代码 tree / sole parent | `cfa70da3d4503ea9b997064fce4e75c6d65758ca` / `8e9df167da524c2a8bdc3296227544d559dc70dc` |
| 代码定位分支 | `codex/e0-r14-fresh-evidence-retention-sibling`；审查链接均固定到上述完整 head |
| 文档发布版本 | `GITHUB-REVIEW-CONTEXT-PUBLISH-R19`，专用分支 [`docs/review-context`](https://github.com/zzliu-coder/corsixh3ds/blob/docs/review-context/REVIEW_CONTEXT.md)，从上述代码 head 派生，只新增本文；文档提交身份以本文件的 GitHub 永久链接所含 commit 为准 |

默认分支 `main`、最新提交和文档提交各有自己的身份。引用结论时附完整**代码 head**；文档提交只标识交接内容，不能替代产品候选。

目标硬件为 **Old 3DS，无裸眼 3D**。最小成功路径：

> 冷启动 → 主菜单 → 第一关 → 建接待台和诊室 → 招聘 → 患者完成就诊 → 保存 → 退出 → 重启恢复。

实现顺序应能追踪为：固定上游 → 组装后的实际程序 → 与真实 loader 一致的 SD 目录及配置 → 初始化必要依赖 → 适配器挂接一次 → 上述游戏路径。每步说明入口、输入及所有者、成功状态、失败时可观察结果和最小验证方法。忙医院、换关与长期运行仍需后续验收。

## 2. 已有证据能证明什么

下表继承已封存的 **R16 独立验收**。本次文档发布核对了报告、summary 和摘要清单，与 GitHub 的代码身份、run 和 release 元数据；未重新执行 R16 的大型下载或测试。R16 原报告 SHA256：`23757ebec0ab30b78199546ac3dba6e795e837ba555d63543bbf137106e868d7`。报告原文及负面输入留在本地，以下为可公开摘要；外部审查者可从公开源码复现这些最小变异。

| 证据层 | 状态与边界 |
|---|---|
| 公网运行 | [run 33932207215 / attempt 1](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33932207215)，同一代码 head，10/10 jobs completed/success：**PASS** |
| Fresh 原始证据 | [artifact 9959080299](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33932207215/artifacts/9959080299)：58 个常规文件、56 个载荷、57 条排序 LF 摘要；内容、绑定及矩阵/H2/DAG由 R16 独立复算：**PASS**。ZIP SHA256 `e52492ac9f50ee2ba881b2ac503f6553c47dd7ab9a1077bb7d015702d0fb6a31` |
| 完整验证 bundle | [release](https://github.com/zzliu-coder/corsixh3ds/releases/tag/e0-r14-fresh-evidence-844121cd86e5) / [asset 545104307](https://github.com/zzliu-coder/corsixh3ds/releases/download/e0-r14-fresh-evidence-844121cd86e5/input-bundle-r14-fresh-evidence-linux-x86_64-844121cd86e5.tar)，813,547,520 bytes，全字节及内部小文件核对：**PASS**；SHA256 `7fbeeee50bcd8052860148698a92aa4b3b991d705cd9b7788b9315d9f97e0c6f`。阅读本文无需下载 |
| 主机 / 交叉构建 | R16 核对公开原始结果：Python 3.9.25、3.14.6 各149个固定测试 ID，protocol 33 行，ARM ELF 及链接证明：**PASS**，只证明对应主机/构建层 |
| E0 正式验收 | **FAIL**：正确输入可通过，错误输入的拒绝、诊断与绑定合同存在下列五类缺陷 |
| 产品边界 | `RH07_PRODUCT=FAIL`、`RH09_PRODUCT=FAIL`，沿用 R16 保留判定 |
| 真机 / 内存 / 来源 | `REAL_DEVICE_RUNTIME`、`S70_REAL_DEVICE_MEMORY`、`UPSTREAM_GIT_PROVENANCE` 均为 **NOT_PROVEN**。同 hash 真机运行、S70 内存及上游 Git 来源证明仍缺失 |

R16 负面测试共 195 项（168 PASS / 27 FAIL），追加边界14项（13 PASS / 1 FAIL）；28个失败检查归并为5个根因。有效公开包自身的完整性继续为 PASS；这些验证结果尚不足以得出“游戏已可玩”。

### 已复现的 R16-F01…F05

以下行号全部对应固定 `844121c`。修复正在 R18 中进行，**尚无新的已验收候选**。

| 缺陷 | 根因与最小复现 | 现有修复边界 |
|---|---|---|
| **F01 · P1** 原始行/图失真仍通过 | [`scripts/ci_diagnostics.sh:501–545`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L501-L545) 只读聚合计数；将 E01 改为 `pass=false, actual_exit=99`，保留60/60汇总并重封摘要，stage/archive仍 PASS；H2假观测、重复行、journal/DAG环同类 | 在现有消费者复算固定行集合、结果、观测差值与 journal 图；在既有测试方法扩展真实子案例，保持149个可发现 ID |
| **F02 · P1** 内部身份绑定未闭合 | [`ci_diagnostics.sh:498–582`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L498-L582)：单改 `receipt.candidate_identity.commit` 为40个0，或改内部 bundle 摘要、删 `created_at_utc`，重封后仍接受 | 交叉核对现有 candidate/bundle/session 字段和摘要，要求合法 UTC 时间，保持冻结字段合同 |
| **F03 · P2** ZIP 原始文件名 NUL 漏检 | [`ci_diagnostics.sh:734–736`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L734-L736) 检查已截断的 `ZipInfo.filename`；将 local/central 名称后缀改为 NUL 加尾串并提供正确传输摘要，可落入白名单 | 提取前检查原始名称并拒绝 NUL，要求规范化名称精确一致；追加字节级 ZIP 子案例 |
| **F04 · P2** 失败诊断遗漏、超时无独立记录 | [`ci_diagnostics.sh:647–669`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L647-L669) 只留固定文件，遗漏 journal 引用的已有 stderr；[workflow:469–503](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/.github/workflows/old3ds-validation.yml#L469-L503) 只转交 failure outcome，无法明确记录内层 timeout | 在现有有界失败包中保留安全引用的诊断字节、内层超时/退出记录；runner 丢失和整个 job 硬超时可用性仍 NOT_PROVEN |
| **F05 · P2** JSON 类型错误没有稳定失败结果 | [`ci_diagnostics.sh:570–575`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L570-L575)、[776–783](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/ci_diagnostics.sh#L776-L783)：manifest 换为合法 JSON `[]` 后 `.get` 抛异常，退出1且只有 traceback | 先检查容器/字段类型，再输出既有稳定 FAIL/code。此例已经拒绝输入，缺陷在失败输出合同 |

R18 仅允许修改 `.github/workflows/old3ds-validation.yml`、`scripts/ci_diagnostics.sh`、`tests/test_ci_diagnostics.py`；保留 R15 成果和 R16 原始证据，修复不扩张为产品代码或新验证协议。

## 3. 产品接入审查线索：逐项待核实

本节来自外部 AI 的源码审查转述，R17 正在检查真实调用链和组装结果。下列均为**待核实**，本文只核对定位路径，不将这些判断升级为当前已确认产品故障。

| 线索 | 固定源码入口与需要回答的问题 |
|---|---|
| 语言目录 | [`scripts/package_sd.sh`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/scripts/package_sd.sh)、[`tests/test_package_sd_script.py`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/tests/test_package_sd_script.py)：默认 `CorsixTH/Languages` 与固定上游可能采用的 `CorsixTH/Lua/languages` 是否一致？自造测试目录是否覆盖真实结构？ |
| 资源模式与真实 loader | 同上打包脚本、[`tools/integrate_corsixth.py`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/tools/integrate_corsixth.py)、[`src/3ds/runtime_3ds.cpp`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/src/3ds/runtime_3ds.cpp)：`th3ds` 的 resources、`loose` 的 game、配置、上游 FileSystem 的枚举/`io.open`、原生资源包挂载能否贯通？须检查实际生成程序 |
| 初始化顺序 | 上述集成脚本、runtime、[`lua/3ds/platform.lua`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/lua/3ds/platform.lua)：`App:init()`、适配器首次状态/资源事件、`runtime_initialize()` 的先后是否正确？初始化失败能否明确退出？ |
| 唯一光标与输入场景 | runtime、platform：触摸/原生 `last_game_pointer_` 与 Lua `cursor_x/cursor_y` 是否共用权威位置？触摸甲→十字键乙→A/B是否作用于乙？镜像模式下减停重型 `syncBottomState()` 后，场景是否及时更新？ |
| 休眠与保存 | runtime、platform、[`src/common/runtime_session.cpp`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/src/common/runtime_session.cpp)：Suspended 与 `begin_save_load()` 顺序、APT 退出标记/tick返回是否阻断保存？同时核实系统回调可执行时间与已有未保存数据语义 |
| 完整帧计时 | runtime、集成脚本、[`src/common/telemetry.cpp`](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/src/common/telemetry.cpp)：`record_frame()` 是否覆盖真实游戏帧和 `runtime_after_frame()` 双屏输出？需要分清完整帧间隔、逻辑、绘制/输出及加载/存档停顿 |

## 4. 内存决策与完成条件

[`docs/OLD3DS_MEMORY_BUDGET.md` §3](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/docs/OLD3DS_MEMORY_BUDGET.md#3-已测基线) 保留的是**旧 v0.6.1 / `9fbaeb6` 历史真机测量**：普通堆53.578125 MiB，启动约52.6 MiB已分配后 OOM，尚未主菜单。原始 boot.log 本轮未在旧路径找到，引用仅能追溯到保留文档。当前 `844121c` 尚无同 hash 真机内存数据；Lua及音效/精灵等分类属于总堆或linear的子集，不能重复相加。文档中的分类上限、52 MiB/8 MiB配置条件与30 FPS目标均须与实测区分。

原始目录是一种存储路线；读取、解码、复制及驻留的真实调用链决定内存峰值。保留既有优化，先核实语言、音效、精灵及复制优化是否接到游戏。`loose` 仍待验证，必要的音效/精灵热点修复可以成为启动前置；绕过 `RuntimeSession` 或写入预算配置都不足以证明内存问题已解决。

先完成三道产品门槛：**P1 跑通**（真实上游结构、统一部署模式、正确初始化、第一关画面与音效）；**P2 可操作且能保留进度**（混合输入、接待/诊室/招聘/就诊、保存退出重开、合盖/HOME返回）；**P3 性能可测**（完整帧、启动/进关/解码/存读档峰值、余量、释放后基线）。保留原界面和双屏镜像方案，验证裁切、缩小后的可读性；每帧写 SD 不应成为测量负担。忙医院、换关和长期运行完成前继续单列待证明状态。

## 5. 正在做什么，以及如何反馈

- **R17 · GPT-6 max：诊断中。** 截至本次输入核对，未取得完成且校验通过的回执；本版未采纳其变化中的报告。待正式结论和最小实现合同到齐后增量同步。
- **R18 · GPT-6 high：已指派的五类 E0 缺口修复进行中。** 限上述三个验证文件，独立工作树；新候选仍需既有公网验证及独立验收。待可公开的 `R18-REVIEW-HANDOFF.md` 和验收身份同步。
- **后续产品施工：** 按 R17 固定接口与独立性分派最小改动；启动/资源/最终设备运行按依赖集成。保留原计划目标和已完成成果，暂缓通用资源框架扩张、全 loader 重写、额外协议、全 GPU、自绘 UI 与复杂多线程。

请外部审查者围绕固定 head 提供：**触发输入 → 实际调用与状态/所有权变化 → 可观察失败 → 被阻断的成功路径步骤**，附精确文件/行、可复现方法及最小修复边界；分别报告主机、构建、设备的 `PASS / FAIL / NOT_PROVEN`，说明未执行项。优先找成功路径阻塞，沿用现有验证体系。

发布范围仅为本技术入口。本文提交使用 GitHub 的 `[skip ci]` 纯文档跳过方式以避免大型构建；工作流配置保持原状。产品候选继续遵守完整验收要求。公开材料不包含原版游戏资源、存档、私人路径、凭据或未经检查的本机日志。
