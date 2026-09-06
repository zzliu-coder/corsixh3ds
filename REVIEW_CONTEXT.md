# Corsixh3ds：Old 3DS 当前源码审阅入口

**当前待审源码是 [`a15a981f31bdf9264e2a296a96019f85bd36ca92`](https://github.com/zzliu-coder/corsixh3ds/tree/a15a981f31bdf9264e2a296a96019f85bd36ca92)。R41音效初始化失败清理修复已快进合入公开产品候选；本地施工PASS，正式独立验收和真机可玩性仍为NOT_PROVEN。** 默认main仍是历史快照，审核请使用下表固定源码。本文为R41-MERGED-SYNC资料修订，文档提交与源码提交各自标识自己的内容。

## 1. 审核对象与最小目标

| 对象 | 精确身份与入口 |
|---|---|
| 当前产品候选 | 分支[`codex/product-e0-integration-r39`](https://github.com/zzliu-coder/corsixh3ds/tree/codex/product-e0-integration-r39)；源码commit `a15a981f31bdf9264e2a296a96019f85bd36ca92`；tree `8c5cdff92262e85011d3183b3a08cb18183b80fd`；唯一父 `6bd03d56ed2679a6c5d5b2b9137dcdfd3d770e59`。分支名保留R39，当前源码已包含R41。 |
| 直接前版R39 / R40 | [`6bd03d56ed2679a6c5d5b2b9137dcdfd3d770e59`](https://github.com/zzliu-coder/corsixh3ds/tree/6bd03d56ed2679a6c5d5b2b9137dcdfd3d770e59)；tree `c016e1365f91f8a2c85da7b8a3e2b00309560f97`；父 `622c60fdb268ef22a3470b228d9dda51c4741e6f`。有限整合独立验收PASS，范围见下文。 |
| 已验收E0来源 | [`357afba4570c6c337d43a993d8c53b41b2f3e5cb`](https://github.com/zzliu-coder/corsixh3ds/tree/357afba4570c6c337d43a993d8c53b41b2f3e5cb)；tree `0a92b4360d8b404ea43de753a21b3bd47be97d06`；唯一父 `8e9df167da524c2a8bdc3296227544d559dc70dc`。R37通过原E0合同验收，其证据保持此E0身份。 |
| 默认main / R17历史基点 | [`844121cd86e5905c8a53c4574fab399d11ea0849`](https://github.com/zzliu-coder/corsixh3ds/tree/844121cd86e5905c8a53c4574fab399d11ea0849)；tree `cfa70da3d4503ea9b997064fce4e75c6d65758ca`；父 `8e9df167da524c2a8bdc3296227544d559dc70dc`。本轮未改main。 |
| 文档 | 分支[`docs/review-context`](https://github.com/zzliu-coder/corsixh3ds/blob/docs/review-context/REVIEW_CONTEXT.md)，从资料提交`a83778b5ffbde03eccccbdab4dc9ddfc110e05a6`追加。本页URL中的commit只标识文档。 |

优先看[R41四文件差异](https://github.com/zzliu-coder/corsixh3ds/compare/6bd03d56ed2679a6c5d5b2b9137dcdfd3d770e59...a15a981f31bdf9264e2a296a96019f85bd36ca92)；需要全貌时看[历史844到当前源码](https://github.com/zzliu-coder/corsixh3ds/compare/844121cd86e5905c8a53c4574fab399d11ea0849...a15a981f31bdf9264e2a296a96019f85bd36ca92)。当前源码包含启动/输入/测量、回归准备、E0导入和本次音效修复；原R20二进制及私有SD包保持冻结，不能当作R41二进制。

目标：**Old 3DS、无立体3D、沿用原游戏窗口及双屏方案**。最小可玩链为：

> 冷启动 → 主菜单 → 第一关 → 建接待台和诊室 → 招聘 → 患者完成就诊 → 保存 → 退出 → 重启恢复。

这条链必须由同一最终二进制在真机上证明，并记录完整帧、启动/进关/解码/存读档峰值及释放后基线。忙医院、换关和长期稳定性仍需后续验证。

## 2. 为什么修真实加载入口

**历史数据：** 保留的[旧v0.6.1内存记录](https://github.com/zzliu-coder/corsixh3ds/blob/844121cd86e5905c8a53c4574fab399d11ea0849/docs/OLD3DS_MEMORY_BUDGET.md)记载普通堆约53.58MiB，启动分配约52.6MiB后OOM，尚未主菜单。原始日志未在后续历史位置找到，因此这里只引用该文档中的旧测量。**当前没有新的Old 3DS整机峰值或帧率实测。**

**R17已确认：** 固定上游实际组装暴露语言目录与部署目录不匹配、初始化顺序、双指针状态、保存/暂停顺序和不完整帧计时等问题。声音、语言和图形的真实加载热点此前仍沿用全量处理；架构中有预算或缓存类，并不证明实际消费者经过这些类。详细历史见[R17诊断](docs/review/R17-playable-path-diagnosis.md)。

**源码推断与施工路线：** 原始目录只是存储方式，峰值由读取、解码、复制、暂存与驻留共同决定。切换loose模式无法单独证明省内存。工作收缩到实际语言/音效/精灵入口：English实际闭包、文件支撑的有界按需音效作为启动前置；保留原地图/精灵接口，按真实加载、纹理和存读档峰值决定后续最小修复。启动和内存由同一责任单元收口，通用框架扩张继续冻结。

**已完成施工及主机证据：** U1整合语言闭包、原始资源目录、启动挂接、checked保存/加载与有界暂停恢复；U2统一触摸/方向键/UI指针及同批动作顺序；U3接入完整帧、真实资源与内存观测。这些源码进入当前候选。实际英语音库主机测试记录747索引、746可播放项、启动PCM为0和有界缓存。SDL/mixer内部暂存、分配器开销、真实Lua/GC全链及设备余量仍有未证明部分。

## 3. 已通过哪些门槛

| 版本 / 层次 | 证据与范围 |
|---|---|
| R37：E0正式独立验收 | **PASS，仅E0基础设施。** [run33956848219](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33956848219/attempts/1)，357afba、workflow_dispatch、10job成功。完整输入实有字节、候选Git对象、Fresh原始行/图/来源关系和既有缺陷回归已独立核对。原195+14通过；59组关联回归中58通过、1原外部真实性观察NOT_PROVEN。 |
| R39施工 / R40有限整合独立验收 | **PASS，仅限定整合与既有回归。** 6bd03相对R27只导入workflow和两份diagnostics；后两文件等于已验收E0，workflow等于E0加原R27尾检。[run33968530647](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33968530647/attempts/1)：9个适用job成功，Fresh按原手动入口条件跳过。两指定Python各166/166、零跳过；四C++矩阵各134、CTest各3；交叉产物/链接证明、协议和权威负控已独立复算。 |
| R41本地音效修复 | **施工PASS。** 精确a15a981的GNU Debug C++134、CTest3；Python168项完整记账：166PASS、2原环境SKIP、0失败/错误。定向完整生成消费者ASan/UBSan分别通过。交叉仅验证受影响ARM对象；封存时未建立新最终ELF。 |
| 本轮公开发布 | 精确a15a981从6bd03正常快进，未制造新产品提交。文档与源码远端身份/正文另外回读。自动CI状态见[同源码运行列表](https://github.com/zzliu-coder/corsixh3ds/actions?query=branch%3Acodex%2Fproduct-e0-integration-r39+sha%3Aa15a981f31bdf9264e2a296a96019f85bd36ca92)及下方快照；本次未等候或重做整套验证。 |
| 产品、设备和历史FAIL | R41独立验收、最小可玩链、整机内存/帧率、设备均 **NOT_PROVEN**。`RH07_PRODUCT`、`RH09_PRODUCT`原 **FAIL** 保留。R26整体审查中断且没有最终结论。旧e3f2公网FAIL、旧48cc842的R23正式FAIL按各自版本保留。 |

**本轮自动CI快照（2026-09-06T03:16:07.892833+00:00）：** [34008375371](https://github.com/zzliu-coder/corsixh3ds/actions/runs/34008375371)，attempt1，push，in_progress / None。此处仅记录运行元数据，未核验新产物或完成独立验收。

R37完整公开输入可从[原release](https://github.com/zzliu-coder/corsixh3ds/releases/tag/e0-r14-fresh-evidence-357afba4570c)追溯；阅读本文无须下载大包。R39/R40已通过的记录不能换成R41身份。新产品Formal Fresh也不能由E0成功或push任务状态自动推出。

## 4. R41根因与修复后的成功状态

**R41施工独立复现：** 旧生成音效实现先释放旧bank并把计数写成747，再分配指针表。首表分配失败时，非零计数与空指针并存，析构清理逐项访问空表。基线实际进程退出-6并出现空指针诊断；后续元数据分配失败还会留下部分状态，旧内容已经丢失。

当前实现把可能失败的工作放到局部所有者中准备：现有reserve预检 → 零初始化指针表和两张元数据表全部准备 → 同步停止mixer、用仍有效的旧元数据释放播放pin → 释放旧chunk/表 → 用release/swap/标量赋值提交完整新状态。任一准备失败时，局部所有者回收临时内容，旧archive、计数、缓存和播放pin保持；同对象可重试。显式释放和析构不分配、不要求reserve。

四文件为[integrator](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/tools/integrate_corsixth.py#L1802)、[生成消费者故障测试](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/tests/test_playable_assets.py#L70)、[升级与幂等测试](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/tests/test_integrator.py#L161)、[完整测试清单](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/tests/host-python-suite.json)。固定上游两次完整组装差异仅`CorsixTH/Src/th_sound.cpp`；生成文件由integrator产生，审查应落到实际生成函数。

初次/替换各4个失败点、8次重试、100次释放循环通过；ASan/UBSan两lane分别覆盖真实747索引/746播放及正常生命周期。受控临时表剩余分配为0。主机已知owner峰值3,145,539B、PCM/cache记账3,105,928B，只覆盖已观测所有者。LeakSanitizer不支持，预编译SDL未做本轮插桩；Lua/GC整个失败生命周期和设备reserve未证明。详见[R41修复与小型复现](docs/review/R41-sound-cleanup-review.md)。

## 5. 下一步与审核重点

**剩余第一阻塞：对精确a15a981进行独立验收。** 优先检查实际生成音效函数的借用archive、播放pin与回调同步、准备失败后的不变量、释放无分配、替换同一archive及再次重试；然后检查Lua进入native失败后的完整异常/GC生命周期。R26没有完整审查结论，局部修复不能关闭全项目审查。

| 实际入口 | 审核问题 |
|---|---|
| [Lua音效接入模板](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/tools/integrate_corsixth.py#L1497) → `audio.lua`的setSoundArchive → 生成`th_lua_sound.cpp` → `sound_player::populate_from` | native成功前后谁持有archive？失败后Lua旧环境与native旧bank是否一致？ |
| [新populate_from](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/tools/integrate_corsixth.py#L1802) → [runtime_audio_reserve](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/src/3ds/runtime_3ds.cpp#L2232) → 准备/提交/释放 | 元数据短暂共存、reserve拒绝和三个分配失败点是否都保持一致？设备上的实际余量须另测。 |
| [文件支撑音库与按需解码](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/tools/integrate_corsixth.py#L1298) | 启动PCM、切片边界、播放pin和cache上限是否沿实际消费者成立？未知暂存不能从记账表中推定为零。 |
| [部署准备](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/tools/prepare_loose_assets.py)、[Lua适配器](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/lua/3ds/platform.lua)、[运行时](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/src/3ds/runtime_3ds.cpp) | 语言闭包、挂接、混合输入、保存重启、HOME/合盖是否沿同一成功路径成立？ |

之后需要新候选最终ELF/包与同hash设备检查；自动CI若产出ELF，也须独立核对身份和构建证明。先按小型复现检查现有源码，再复核完整生成消费者和原回归；最终以同一二进制跑完第一关就诊、保存退出重开及真实内存/完整帧采样。请外部AI按“触发输入 → 调用与所有权变化 → 可观察结果 → 成功路径受阻步骤”给出精确行号及复现，分别标注**已确认事实 / 源码推断 / 历史数据 / NOT_PROVEN**。

## 6. 历史资料与公开边界

[R17诊断](docs/review/R17-playable-path-diagnosis.md)、[R18施工](docs/review/R18-validation-repair.md)、[R23正式验收](docs/review/R23-independent-acceptance.md)、[U1组合](docs/review/U1-combined-product-candidate.md)、[R24来源返修](docs/review/R24-source-binding-closure.md)、[R25诊断](docs/review/R25-product-integration-diagnosis.md)、[R27准备](docs/review/R27-regression-preparation.md)保留原封存文字。当前状态以本页固定源码及对应新证据为准。

公开内容限源码、公开运行和安全摘要；正版Theme Hospital素材/声音、存档、私有SD包、凭据、私有机器路径/地址及未脱敏日志不公开。本轮未上传大bundle/工具链，未修改main或Release，未执行设备操作。
