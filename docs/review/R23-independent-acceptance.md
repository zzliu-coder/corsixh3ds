# R23：R18独立验收正式FAIL

[返回入口](../../REVIEW_CONTEXT.md) · [被验候选](https://github.com/zzliu-coder/corsixh3ds/tree/48cc842095d548f143f8674a6778fdb511292638)

候选`48cc842095d548f143f8674a6778fdb511292638`，tree `d826490849f228096ab822765958d236eea6ebf3`，sole parent `8e9df167da524c2a8bdc3296227544d559dc70dc`。范围限既有E0验证设施合同。R19核对162项封存摘要，仅发布本说明，未重跑验收。源公开handoff SHA256：`a404a480f067313f4f08a2e646cf001fbbbc01f01118fd8489e2235a6952971c`。

| 原缺陷类 | R23独立结果 |
|---|---|
| F01 原始复算 | **FAIL**：record/observation与实际journal argv未绑定；用所有槽求和替代固定pool槽2/backend槽0，允许挪槽保持总和 |
| F02 内部绑定 | **FAIL**：checked只检查存在项，未要求既有role集合完整覆盖；candidate transport实际摘要没有绑定到对应角色 |
| F03 ZIP原始名称 | **PASS**，原NUL字节变异稳定拒绝 |
| F04 失败诊断/超时 | **PASS**，独立子进程0/23/124退出、先写诊断后终止，原始字节留存；失败包保持非接受 |
| F05 错误JSON容器 | **PASS**，原类型边界及既有组合回归通过，稳定FAIL/code |

五个正式反例均在正确封装摘要重算后，令stage和archive返回0/PASS：

1. 同时改变H2 record与observation的run-id，实际journal argv保持原值。
2. 只改变journal argv的run-id，record/observation保持原值。
3. 将64B增量从冻结pool槽2移至槽0，总和不变。
4. 同时清空preflight及final的checked角色列表，envelope仍声明13角色。
5. 将candidate_transport的source_sha256与bundle_sha256同步改为零，保留head及真实角色摘要。

[H2检查位置](https://github.com/zzliu-coder/corsixh3ds/blob/48cc842095d548f143f8674a6778fdb511292638/scripts/ci_diagnostics.sh#L764-L793)、[冻结H2生产者](https://github.com/zzliu-coder/corsixh3ds/blob/48cc842095d548f143f8674a6778fdb511292638/tests/runtime_core_v2/evidence_protocol_adversarial.py#L2290-L2308)、[角色覆盖检查](https://github.com/zzliu-coder/corsixh3ds/blob/48cc842095d548f143f8674a6778fdb511292638/scripts/ci_diagnostics.sh#L686-L695)、[transport与前后角色检查](https://github.com/zzliu-coder/corsixh3ds/blob/48cc842095d548f143f8674a6778fdb511292638/scripts/ci_diagnostics.sh#L821-L829)。

`initial_entry_count=false`代替0的观察，作为正式合同拒绝条件的依据仅 **NOT_PROVEN**；它不重开F05、不决定总FAIL、不新增为硬条件。

真实成功路径仍 **PASS**：原195/195+14/14回归通过；[run33938765229](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33938765229)同head 10/10 success；独立Fresh复算862项、完整bundle验证375项通过。Fresh artifact9961199388有58文件、56payload、57摘要行，ZIP SHA256 `73839365d81caf6b5e6e0a4e2751ad6f685389609c4232a8ae212b13ad20f258`。实际60/32/22/54行、40 H2进程及18节点20边无环DAG均吻合。两版公共Python各149通过、零skip；本地145通过、4允许skip。正确公开输入持续有效，错误输入拒绝边界决定正式FAIL。

R24（GPT-6 high）只在原workflow、ci_diagnostics.sh及参数化测试三文件内补全H2实际argv/固定槽计算、角色完整覆盖与实际摘要关系。保留149测试ID、R12权威、正确成功证据和产品边界，沿用现有协议。

RH07/RH09实验产品语义 **FAIL**；真机运行、S70内存、上游Git来源合同及runner丢失后上传仍 **NOT_PROVEN**。R23未改产品、旧证据或公开CI，E0通过项不替代e3f2组合的回归与设备验收。
