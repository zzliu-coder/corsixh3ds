# 完整生成视图与构建消费（AR3 第一批）

本批只调整装配、身份校验及调用者。产品源码、经营算法、资源预算和原始 43 个上游夹具保持原样；Staff / World 最终源码的迁移留到下一批。

## 正常路径

1. `CTH3DS_UPSTREAM_PIN` 保存固定的原始 CorsixTH 源码。原始 Git pin 用于 RNC 解码器三文件核验；生成视图不带 `.git`，不能冒充原始 Git checkout。
2. `integrate_corsixth.py PIN --dry-run` 在私有源码及 overlay 副本中执行完整生成、嵌入适配器刷新、最终检查。输入和当前生成树保持不变。
3. `--output NEW_VIEW` 执行同一内核，完成后以独占新链接发布完整视图。已存在输出一律拒绝。原地修改入口关闭，旧集成树必须保留，并从干净 pin 重新生成。
4. `source_view.py run --lock EXTERNAL/.source-owner.lock -- COMMAND` 为同一固定源码别名确定稳定 owner。`CTH3DS_SOURCE_OWNER_LOCK` 显式传给生产子脚本，cycle 的 BUILD 产物目录变化不改变 owner；子脚本继续校验继承 FD 的 inode。`select` 在锁内切换固定构建别名 `EXTERNAL/CorsixTH`，拒绝覆盖原有实体目录。
5. `build_3ds.sh` 完整校验被选视图，配置固定别名，清理游戏目标，然后重建。固定依赖安装、工具链和媒体继续复用。任何失败都会使本次构建成功收据不可用。
6. 最终 ELF 检查等原有门全部通过后，成功构建收据绑定完整生成摘要、生成输入摘要、真实源目录、二进制摘要和移植仓库 commit / tree。`package_sd.sh` 校验此绑定后消费同一视图中的运行文件；原始资源预处理通过独立原始 pin 核验 RNC 来源。

普通的新环境可继续从 `bootstrap_upstream.sh`、`build_3ds.sh`、`package_sd.sh` 进入。已有历史实体 `external/CorsixTH` 的环境必须显式选择新的 external 命名空间，旧现场留作回退。复用现有构建缓存时，CMake 记录的源码别名也必须保持一致；更换别名需要显式选择新的游戏构建目录，依赖安装目录可以继续复用。

## 身份与失败边界

`.cth3ds-view.json` 的 `files` 覆盖全部生成文件，包含所有 Lua、生成的 C++ 和原有 `integration-manifest.json`；仅排除自身和顶层 Git 元数据。旧 overlay 清单继续保留，含义不变。文件大小、内容摘要和权限组成生成身份，mtime 不参与缓存判断。

`inputs` 覆盖 overlay、`tools/*.py`、`tools/integration/*.py` 和预留的 `upstream_overrides/`。声明的工具必须与实际执行工具字节一致。预留目录目前只纳入输入闭包，不应用 Staff / World 替换。

生成视图来自 Git 原输入时记录 `origin=git:PIN`。无 `.git` 的重复生成通过完整清单与固定版本源码签名校验，保持原生成来源字段；这不会提供新的 Git 校验结果。

独占链接发布只涉及一个新链接。生成临时树在发布前失败会清理；发布完成后的中断保留已发布目标。owner 把 TERM / HUP / INT 传给实际工作进程组，等待直接子进程和仍在执行的孙进程停止，然后使显式绑定的构建成功收据失效；合作退出超时会终止该工作组。已终止的孤儿 zombie 由系统父进程回收。跨文件发布、异常断电和外部进程绕过 owner 的行为不具备原子事务保证；主动自行脱离进程组的后台守护进程不属于这条同步构建合同。SIGKILL / 断电不能保证入口执行清理。

`test_all` 的 Python / CTest 及 cycle 快速测试通过 `independent_tests` 启动：父生产 owner 继续持锁，测试进程关闭继承 FD，并移除 owner 的 FD、锁路径和取消收据环境。独立 fixture 使用自己的临时 owner，合法生产子 build 仍保持原 owner。包 fixture 入口也独立清除 owner 元数据，支持直接在生产父环境中选测。

一条同步调用链只有最外层 supervisor 建立取消 session；嵌套 `run`、`isolated` 和 fixture 私有 owner 都留在同一进程组。`CTH3DS_CANCEL_DOMAIN` 与 FD / 锁 / 收据隔离分开继承，并核对当前进程的实际 group、session 和存活外层 supervisor；格式错误、陈旧或成员不匹配时拒绝执行。嵌套等待者无独立 KILL 截止时间；外层统一转发、终止、确认工作组停止后释放生产 owner。根取消测试显式建立外部测试 session，以便单独给该根入口发送信号；普通生产及 fixture 调用保持原取消域。此标记校验用于同步调用合同，不构成防恶意进程伪造的权限边界。

## Fresh verifier 与生产视图分开

v2 的 `prepare_sources()` 三个调用点使用 `--private-output`，输出是真实私有目录，可以填入 authority 预先分配的空目录并保留 inode。源、overlay、输出链接，非空输出，重叠根及树内链接 / 硬链接继续拒绝。完整预检失败不会填入输出；最终复制异常会保留新失败工作区，由该 fresh 任务报告失败。

原始 snapshot 与生成 source_tree 各自记账。旧产品权威指纹、允许列表和 base identity 未放宽；原 v2 authority 继续拒绝新的产品身份，升级 authority 需要独立审核。新增输入闭包角色为 integrator、generated-view 和 source-view-owner。

v2 仍在所有构建和清单记录完成后将工作区设置为只读。该只读证据树由 v2 的既有源码清单验证，不作为生产可复用生成视图或原始 pin；生产 `verify_view` 严格校验生成时权限。

## 消费者对应

| 入口 | 本批消费方式 |
| --- | --- |
| bootstrap_upstream | 原始 pin → 完整生成 → owner 内选择固定别名 |
| build_3ds | 完整视图检查 → clean-first → 原 ELF 门 → 完整源码与二进制绑定 |
| test_all | owner 内检查实际生成视图；保留原主机清单入口与 cross skip 边界 |
| verify_runtime_core / old3ds_cycle | 继承同一 owner，沿生产 bootstrap / build / package |
| package_sd | 完整成功构建绑定 → 同视图 Lua / 媒体 → 原始 pin 的 RNC 三文件检查 |
| v2 policy preview / worker prepare-xbuild-source / internal_prepare | 同一 prepare_sources → 私有真实输出 → 原始与生成身份分账 |
| verifier_driver / review-policy schema / release source closure | 同步新增生成工具闭包及预留 overrides；保留原 authority 拒绝 |
| CI artifact | 旧 overlay 清单 + generated-source.json + 构建成功绑定 |
| tests/support/pinned_upstream 与实际生成测试 | 43 原始夹具不改；原输入 → 两个全生成视图 → 重复一致 / 原输入无污染 |
| 本地 run-cross / prepare_candidate / verify_assembled_candidate | 私有交付中的迁移副本；由集成人替换明确路径后启用，旧现场和 runner 不在本批自动改写 |

`prepare_candidate` 的新 `--generated-view` 为候选必填项，`--owner-lock` 或显式 owner 环境必须匹配构建所用稳定锁。从首次 build binding、复制到末次核验都在该 owner 内；末次返回绑定及已复制二进制必须等于首次绑定，拒绝 A→B 中途重建。旧 `--generated-lua` 只作路径一致性断言。候选 Lua 非语言闭包必须与生成视图完全相等，保留的已安装语言字节也必须匹配。原媒体、存档与设备保护门继续使用。

主机测试证明装配和调用合同；合入后的 ARM 构建、正式打包、设备运行仍由集成人执行。原始 RNC SOUND 全包未找到时，真实压缩精灵的 native 解码只能证明解码源码路径，不能替代 RNC 音效包或 ARM 播放验收。
