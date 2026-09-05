# R25：七个公网失败的诊断与产品衔接计划

只读诊断 **PASS**；当前产品整体验证 **FAIL**。R27已按本计划在独立准备分支提前施工，尚无最终封存回执。本文固定产品[e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e](https://github.com/zzliu-coder/corsixh3ds/tree/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e)，tree `dc7469658218ea84ca2a34bdb8e9a218a3e4d7a2`，唯一parent `fe569cf563ab9a01848686d3fef47c4c4b82d3bd`。R25报告SHA256 `8fd50a3b54b3cbf337871c621bf4a5250423665c4cc3e5572dfaf5271176db4f`。

## 已失败工作与尚未执行的检查

[run33943007122 / attempt1](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33943007122/attempts/1)为2成功、7失败、1跳过。R25逐一核对原始日志：

| job | 已证实原因 |
|---|---|
| host-gcc-debug / release / sanitized | [test_atomic_save.cpp:79](https://github.com/zzliu-coder/corsixh3ds/blob/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e/tests/test_atomic_save.cpp#L79)的misleading-indentation在GNU13 -Werror下停止编译。 |
| host-clang-debug、host-python-3.9.25、host-python-3.14.6 | [U3生成路径测试](https://github.com/zzliu-coder/corsixh3ds/blob/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e/tests/test_playable_path.py)缺CTH3DS_U3_UPSTREAM，影响5个ID；[E0身份正例](https://github.com/zzliu-coder/corsixh3ds/blob/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e/tests/test_verifier_python_environment.py#L148-L192)误用产品checkout，被原E0直接R9父规则拒绝。 |
| verifier-authority-negative | 同一E0正例对象错误。生产verifier按原约束拒绝了产品历史。 |

Fresh final seal跳过来自[workflow:383–386](https://github.com/zzliu-coder/corsixh3ds/blob/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e/.github/workflows/old3ds-validation.yml#L383-L386)：原workflow_dispatch及bundle输入条件在本次push下为false；该job没有needs依赖。

两Python完整runner回执各166项：160通过、6错误、0跳过。unittest的161项/2错误与runner展开class-level错误到5个ID的记账层不同。[尾检:113–119](https://github.com/zzliu-coder/corsixh3ds/blob/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e/.github/workflows/old3ds-validation.yml#L113-L119)写死149，及其[源码断言:222–235](https://github.com/zzliu-coder/corsixh3ds/blob/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e/tests/test_build_scripts.py#L222-L235)，属于尚未执行到的后继阻断。诊断未证明修复首个错误后所有矩阵必然通过。

## 清单对账与成功路径

143项冻结baseline未变；149个旧selected ID全部保留、删除0、新增17，共166。新增包括混合输入1、测量组件2、PlayableAssets4、PlayablePath5、U3GeneratedClock5。

R25独立小型复现确认：真实E0身份正例与原R12/bundle前检通过，真实产品仍被E0专用身份检查拒绝；20份固定上游源码与Git blob相符，两次实际integrator生成的72文件一致，原U3五方法随后5/5通过且0跳过。这些是固定源码与受控主机测试输入的证明，游戏完整启动仍待验收。

## 五文件施工与最终导入边界

| 现有文件 | 最小动作 |
|---|---|
| tests/test_atomic_save.cpp | 显式语句和花括号，保持行为与-Werror。 |
| tests/test_playable_path.py | 从已有original_sources导出固定源码，核对摘要并重复真实生成，使五个原ID输入自足。 |
| tests/test_verifier_python_environment.py | 用真实精确E0 checkout作身份正控，保留现有闭包/锁与负例断言及真实产品拒绝。 |
| .github/workflows/old3ds-validation.yml | 尾检绑定当前manifest数量/ID摘要、实际候选/清单身份和完整结果，零跳过；保留Fresh入口与原锁定/封存流程。 |
| tests/test_build_scripts.py | 在原测试方法的subcases验证完整149/166范围及缺失/变更ID、过期身份或清单、错误与跳过拒绝。 |

生产verifier、R12冻结权威、schema、依赖锁、历史oracle和现有完整回归入口保持原约束。正式导入已验收E0的workflow、diagnostics及其测试三文件增量，与五文件计划存在重叠，预期相对产品净七路径；这是本轮局部导入清单。

R27由原U1唯一集成人负责，已获准提前编码；正式E0导入与最终放行待相应验收。R28仅对新E0候选1a1730e按原合同独立验收。公开产品仍固定e3f2，普通进度消息不替代最终封存回执。最终组合冻结自己的head/tree/parents后执行完整同候选验证，E0 Fresh/bundle保留原E身份。

独立产品验收尚未完成、没有最终回执。RH07/RH09仍FAIL；实际第一关就诊、保存重启、完整游戏、真机内存/性能与设备均NOT_PROVEN，设备准入未放行。
