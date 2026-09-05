# R18：公开 Fresh 证据的有界验证修复

施工状态：COMPLETE。公开十项：10/10 PASS。原始证据施工复算：293/293 PASS。**R23（GPT-6 high）独立验收进行中，正式结果NOT_PROVEN；五类缺陷正式关闭待验收。**

本说明由R19 / R18-SYNC从已封存公开handoff整理（源SHA256 `5714d0e787746e70858059492846021440d1d82bd662e0b2185fd4d6ea8d56b5`）。R19核对79项封存摘要和公网身份/API，仅发布文档，未重跑施工复验或独立验收。[返回审查入口](../../REVIEW_CONTEXT.md)

## 代码身份与范围

- R15 输入：844121cd86e5905c8a53c4574fab399d11ea0849，原提交、分支及公开证据保留。
- R18 HEAD：48cc842095d548f143f8674a6778fdb511292638。
- R18 tree：d826490849f228096ab822765958d236eea6ebf3。
- 唯一 parent / R9：8e9df167da524c2a8bdc3296227544d559dc70dc。
- 分支：codex/e0-r18-retention-verifier-sibling。
- 相对 R15 只修改 workflow、scripts/ci_diagnostics.sh 和 tests/test_ci_diagnostics.py。相对 R9 仍为冻结的 13 文件；54 个产品路径的指纹保持 4b027341762b902c75c10b522a8edc15330e0723b73512e9fcdc9e24841f0ca6。

[完整代码](https://github.com/zzliu-coder/corsixh3ds/tree/48cc842095d548f143f8674a6778fdb511292638)；[R18 原子提交](https://github.com/zzliu-coder/corsixh3ds/commit/48cc842095d548f143f8674a6778fdb511292638)。

## 五类问题的因果链与修复

| 原问题 | 输入如何造成错误结果 | R18 的检查与回归 |
|---|---|---|
| R16-F01 | 修改矩阵或验收行、H2 观测、journal/DAG，同时保留汇总数字并重算文件封装摘要，旧验证器仍可接受。 | 按冻结 case ID 和结果重新计算 60/32/22，再派生 54；核对实际 H2 数值、40 个进程身份及 journal；重建 18 节点、20 边的依赖关系。覆盖失败行、重复 ID、篡改预期和实际值、错误观测及环。 |
| R16-F02 | 修改 receipt 候选、内部 bundle 摘要或移除 manifest 时间，外层文件校验仍可通过。 | 连接候选、session、bundle、receipt、case-set、matrix summary、fixture 和 invocation 摘要；验证已有必填 UTC 时间。覆盖各内部绑定和非 UTC 时间。 |
| R16-F03 | 在 ZIP 原始名称中加入 NUL 后，解析库提供的截断名称可能恰好匹配允许路径。 | 检查 orig_filename，要求原始名称、解析名称及规范名称完全相同。测试实际修改 ZIP local/central 名称字节。 |
| R16-F04 | 失败或超时 journal 指向诊断文件，旧失败包只复制固定文件，遗漏诊断字节；仅有 workflow failure 无法辨认超时。 | 在既有路径和大小限制内保存可用的被引用诊断、摘要和映射；记录不可用引用。命令包装器记录起止 UTC、退出码和 timed_out；149 分钟内层限制位于 150 分钟 step 和 180 分钟 job 限制内。实际执行成功、退出 23 和超时退出 124 的回归。 |
| R16-F05 | 有效 JSON 使用错误容器或字段类型，解引用、算术或集合操作可能抛出 traceback。 | 在使用前检查所需对象、数组、字符串和整数；输入问题进入稳定 FAIL/code。保留真实程序错误，不用总括异常吞掉它们。新增 84 组类型组合。 |

实现位置：[行/观测及绑定验证](https://github.com/zzliu-coder/corsixh3ds/blob/48cc842095d548f143f8674a6778fdb511292638/scripts/ci_diagnostics.sh#L599)、[命令退出记录](https://github.com/zzliu-coder/corsixh3ds/blob/48cc842095d548f143f8674a6778fdb511292638/scripts/ci_diagnostics.sh#L338)、[失败诊断保留](https://github.com/zzliu-coder/corsixh3ds/blob/48cc842095d548f143f8674a6778fdb511292638/scripts/ci_diagnostics.sh#L957)、[ZIP 原始名称检查](https://github.com/zzliu-coder/corsixh3ds/blob/48cc842095d548f143f8674a6778fdb511292638/scripts/ci_diagnostics.sh#L1118)、[回归测试](https://github.com/zzliu-coder/corsixh3ds/blob/48cc842095d548f143f8674a6778fdb511292638/tests/test_ci_diagnostics.py#L830)。

## 已执行的验证

- 原 R16 复验：修复前 168/195 + 13/14，修复后 195/195 + 14/14。复验工具仅调整路径，保留原预期判定。
- 主机可发现测试 ID 仍为 149。macOS Python 3.9.25、3.14.6 各记账 149：145 passed、4 个清单允许的环境限制 skip，0 failed/errors。
- 公网 Python 3.9.25、3.14.6 的已下载原始回执均为 149/149 passed，0 failed/errors/skipped；代码 HEAD/tree/parent 和 149 个测试 ID 摘要一致。
- 当前候选的 C++ 构建、核心运行测试和模拟器冒烟测试通过。
- 原版 R12 staged、postcommit 和 postpush 检查通过，产品路径指纹未变。
- 新 Fresh 公网任务通过。下载 ZIP 的候选验证器检查为 PASS：58 文件、56 载荷、57 条 SHA256SUMS。
- 完整 bundle 本机字节回读通过：813,557,760 bytes 和 SHA-256 与新 release 一致，237 个内部成员摘要及候选、Fresh 和 R12 DAG 绑定通过。
- 最终 attempt 1 的十个任务全部 success，全部绑定同一 R18 HEAD。下载原始 ZIP 后，使用外部冻结定义且不导入候选代码的施工复算通过 293/293：矩阵 60/60、base 32/32、R4 22/22、组合 54/54、H2 20/20+20/20，DAG 18 节点、20 边、0 环。

验证成功路径：完整输入绑定 → Fresh 执行 → 原始文件映射 → 逐行/观测/依赖复算 → 封装和摘要检查 → 上传完成 → 最终执行状态检查。失败包保持非接受状态。

## 公共代码与证据

- [公开十项运行 33938765229](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33938765229)。
- [Fresh 原始证据 artifact 9961199388](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33938765229/artifacts/9961199388)。
- ZIP SHA-256：73839365d81caf6b5e6e0a4e2751ad6f685389609c4232a8ae212b13ad20f258。
- manifest SHA-256：0c676a40f8e39cf7a78392879a7e56ffd6f7484d7f0e24e7158b39970e39bb7a。
- SHA256SUMS SHA-256：2c6fb3b03fe1de738570329bf569861cfb05dd1f6a9a81eb422abe98a69bf0d1。
- [bundle 构建运行 33938522916](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33938522916)；[独立的新 release](https://github.com/zzliu-coder/corsixh3ds/releases/tag/e0-r14-fresh-evidence-48cc842095d5)。
- bundle：813,557,760 bytes，SHA-256 a3e2cfc05a6c7102a3d870034c37128d1cfe94b6b3c438807f949e728da4130a，asset ID 545228830。

## 未证明项与剩余产品问题

本工作提供施工证据；R23已依据现有R14合同及R16-F01至F05开展独立验收，状态仍为NOT_PROVEN。旧844快照的五类历史FAIL保持原判定，R18的正式关闭状态须等待该验收。

RH07_PRODUCT=FAIL、RH09_PRODUCT=FAIL；真实设备运行、S70 真机内存和上游 Git 来源证明仍为 NOT_PROVEN。facts_checks=18/18 是保留的最终结果字段，本轮未添加新的原始 facts 协议。公开 CI 成功的证明范围限于这些实际执行的检查。

失败/超时留证依赖 runner 仍在运行；runner 消失或硬 job timeout 后的上传可用性未证明。本轮没有制造公网配额、网络中断或 runner 丢失。

产品的启动、输入坐标、存档和完整帧性能路径由独立产品工作推进，本候选没有修改这些代码。此说明可由资料发布任务同步到 GitHub；它未被加入冻结的候选文件集合。

R17产品诊断基点仍为`844121cd86e5905c8a53c4574fab399d11ea0849`。本页`48cc842`是仅改验证设施的新候选，54产品路径未变，不代表新可玩版本。U2/U3仍是已交U1待实际集成的本地组件；U1/U2/U3实际产品组合尚未封存或公开。历史与本次E0的10/10均不能替代未来组合候选的同hash回归和设备验收。
