# R24：来源关系返修施工完成，正式独立验收待R28

R24施工 **COMPLETE**；同head正式公网10/10 **PASS**；正式独立验收 **NOT_PROVEN，待R28**。R23对旧候选48cc842的正式FAIL历史保留。本文是封存材料公开摘要；R24报告SHA256为`6872f012cf8e0b6ca759e0881377adc4d7628af08071fc4719ab559bb4ebc1c5`。

## 精确候选与源码

- [HEAD 1a1730e8ad12a8dce37e7d2c4432f0d22ee4ddf0](https://github.com/zzliu-coder/corsixh3ds/tree/1a1730e8ad12a8dce37e7d2c4432f0d22ee4ddf0)；tree `71a8418edbe70af132358301e29201dc0c8eb1f0`；唯一parent/R9 `8e9df167da524c2a8bdc3296227544d559dc70dc`。
- 分支`codex/e0-r24-source-binding-sibling`；相对R18仅diagnostics和其测试2文件，287新增/16删除，workflow不变。相对R9仍13路径，54产品指纹与149个可发现ID未变。
- [共享角色检查](https://github.com/zzliu-coder/corsixh3ds/blob/1a1730e8ad12a8dce37e7d2c4432f0d22ee4ddf0/scripts/ci_diagnostics.sh#L628)、[H2来源](https://github.com/zzliu-coder/corsixh3ds/blob/1a1730e8ad12a8dce37e7d2c4432f0d22ee4ddf0/scripts/ci_diagnostics.sh#L813)、[transport/DAG](https://github.com/zzliu-coder/corsixh3ds/blob/1a1730e8ad12a8dce37e7d2c4432f0d22ee4ddf0/scripts/ci_diagnostics.sh#L895)、[两入口关系测试](https://github.com/zzliu-coder/corsixh3ds/blob/1a1730e8ad12a8dce37e7d2c4432f0d22ee4ddf0/tests/test_ci_diagnostics.py#L916)。

## 修复关系与施工验证

| 类别 | 已有来源 → 当前检查 → 回归 |
|---|---|
| F01 | H2每profile/index的record/observation接回实际journal argv、run-id、fault、执行角色与session路径；差值按producer固定pool槽2/backend槽0计算。同步/反向ID变更、重复身份、首尾索引、错角色、总和不变的错槽均受检，整体路径搬迁正控仍接受。 |
| F02 | 前后checked与envelope精确覆盖已有13角色；接回inputs同角色路径/readonly、transport两个文件摘要和冻结matrix/base/R4/DAG原字节摘要。同步清空/删除/重复、路径错配及同步/反向摘要变更受检。 |

R24记录原195+14回归通过；R23五正式最小ZIP在archive/stage合计10次全部拒绝；真实R15/R18正控两入口共4次接受，新head正控两入口接受。每Python新增113组关系测试、226次两入口调用符合预期；本地两版各149记账（145通过/4允许跳过），公网两版各149通过/0跳过。F03/F04/F05既有回归保留；boolean/zero观察仍NOT_PROVEN，不重开F05。

## 公网与来源证据

[正式run33945842159 / attempt1](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33945842159/attempts/1)绑定1a1730e，workflow_dispatch，10job全success。R19实时API回读确认该身份和终态。

[Fresh artifact9963410659](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33945842159/artifacts/9963410659)：95,565字节；ZIP/API SHA256 `22c797538860afd7ead7296f830aae6d60646e24f78cc67ad21b8c0479b9c0a4`。R24记录58项、56payload、57行SHA及293项原始数据施工复算通过。

[完整bundle release](https://github.com/zzliu-coder/corsixh3ds/releases/tag/e0-r14-fresh-evidence-1a1730e8ad12)由[builder run33945734585](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33945734585)生成；813,557,760字节，SHA256 `85453155d6152ae70232186828fe60147dea256fcf9a5174cc77608c44ebb15a`。R24记录237成员核对、candidate.bundle实际Git对象与597项来源细查通过。这些是施工者复算；根已交R28独立重验，本文未重新下载完整包或执行验收。

成功路径：冻结定义与真实正控 → 共享来源关系规则 → 两入口正式反例拒绝 → 不变测试和产品边界 → 同head完整bundle与公网执行 → 原始字节和来源复算 → 独立验收。

## 必须保留的证明上限

成功ZIP没有完整bundle manifest及所有动态资源字节。跨文档字段互等仅证明已检查关系；完整来源需要exact-head bundle字节、成员和角色核对。一组动态字段被一致伪造后的真实性不能由互等证明。R28按原合同判断这个上限，新增豁免不自动成立；不增加自签权威、字段或通用协议。

RH07/RH09仍FAIL；第一关就诊、保存重启、完整游戏、设备运行和S70真实内存仍NOT_PROVEN。R28仅验E0既有合同，产品验收尚未完成、没有最终回执；最终产品证据绑定自己的候选身份，E0证据保持E身份。
