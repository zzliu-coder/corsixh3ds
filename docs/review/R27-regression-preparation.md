# R27：回归准备完成，E0导入与产品验收仍待完成

**PREPARED_PUBLIC_9_PASS_PENDING_E0_IMPORT**。最新准备源码[622c60fdb268ef22a3470b228d9dda51c4741e6f](https://github.com/zzliu-coder/corsixh3ds/tree/622c60fdb268ef22a3470b228d9dda51c4741e6f)，tree `cf8c1949105848c198bfa9f363449a673e247c3c`，唯一parent `e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e`，分支`codex/product-regression-entry-closure-r27`。R27报告SHA256 `7e435d4b2cd852e7203525cfec2520928e411835c2f3e7e0f4924659b0c7a4b8`；封存608项摘要已核对。

| 对象 | 当前边界 |
|---|---|
| 最新回归准备源码622c60f | 五个测试/工作流文件增量，9个适用job成功。 |
| 运行时组合和原R20包e3f2c4a | R27运行时代码与此相同；原二进制和私有SD包保持冻结，未由本轮重建或替换。旧run33943007122的FAIL保留。 |
| 独立受审E0来源1a1730e | 尚未导入R27；R28仅按原E0合同独立验收，正式结论仍待完成。旧48cc842的R23正式FAIL保留。 |

## 五文件改动

- [tests/test_atomic_save.cpp](https://github.com/zzliu-coder/corsixh3ds/blob/622c60fdb268ef22a3470b228d9dda51c4741e6f/tests/test_atomic_save.cpp)：明确保存测试lambda语句和花括号，保留原行为与-Werror。
- [tests/test_playable_path.py](https://github.com/zzliu-coder/corsixh3ds/blob/622c60fdb268ef22a3470b228d9dda51c4741e6f/tests/test_playable_path.py)：两个生成路径测试类提供自己的固定输入，核对20个上游源码摘要、两次72文件生成一致，执行原ID，摆脱环境目录变量依赖。
- [tests/test_verifier_python_environment.py](https://github.com/zzliu-coder/corsixh3ds/blob/622c60fdb268ef22a3470b228d9dda51c4741e6f/tests/test_verifier_python_environment.py)：保留当前闭包/锁检查，真实历史844121c/cfa70da作为身份正控；错误head/tree/parent/parent-tree与真实产品拒绝仍受检，生产身份规则未放宽。
- [workflow](https://github.com/zzliu-coder/corsixh3ds/blob/622c60fdb268ef22a3470b228d9dda51c4741e6f/.github/workflows/old3ds-validation.yml)及[tests/test_build_scripts.py](https://github.com/zzliu-coder/corsixh3ds/blob/622c60fdb268ef22a3470b228d9dda51c4741e6f/tests/test_build_scripts.py)：尾检绑定实际head/tree/完整parents、manifest身份、解释器、发现/选择/执行集合及逐项结果，要求当前N项全通过且零跳过。原测试方法执行149/166正控及每范围30种拒绝输入；合成控制回执只证明尾检行为。

清单保持166 selected、原149全部保留、143 baseline不变，无新增或移除顶层ID。生产verifier、wrapper、producer/consumer、schema、权威、锁、diagnostics两文件和历史oracle保持原样；workflow尾检以外的Fresh入口及封存流程字节不变。

## 新版本公网结果

[run33946473666 / attempt1](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33946473666/attempts/1)，push、同head622c60f：**9个适用job success；official-fresh-chain-final-seal skipped**。Fresh仍要求原workflow_dispatch及非空bundle URL/hash，本次push不满足入口条件。

Python3.9.25和3.14.6实际回执各166唯一ID全部PASS，0失败、0错误、0跳过；6类mismatch列表均空，候选身份和清单绑定一致。四个公网C++矩阵各134通过，交叉构建绑定当前准备候选。主机/CI通过的范围限于回归准备验证。

## 后续成功路径与验收边界

正式导入时以获独立验收的E0 workflow为基底，只迁移R27已封存的尾检增量；E0证据保持自己的E身份，最终组合冻结自己的候选身份后验证。当前E0未导入，产品独立验收尚未完成、没有最终回执。RH07/RH09仍FAIL，完整游戏、P1/P2/P3、真实内存、性能和设备仍NOT_PROVEN。

启动与内存由同一责任单元负责；实际语言闭包和文件支撑的有界按需音效是前置。首个真机候选必须带完整帧与真实加载峰值测量，并以同一二进制证明：冷启动 → 主菜单 → 第一关 → 接待/诊室/招聘 → 患者完成就诊 → 保存 → 退出 → 重启恢复。通用框架扩张继续冻结。
