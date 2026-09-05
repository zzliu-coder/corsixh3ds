# e3f2：U1/U2/U3公开产品组合与证据边界

[返回入口](../../REVIEW_CONTEXT.md) · [当前固定代码](https://github.com/zzliu-coder/corsixh3ds/tree/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e) · [施工分支](https://github.com/zzliu-coder/corsixh3ds/tree/codex/product-u1-boot-assets-save-r20)

候选`e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e`，tree `dc7469658218ea84ca2a34bdb8e9a218a3e4d7a2`，sole parent `fe569cf563ab9a01848686d3fef47c4c4b82d3bd`。固定上游CorsixTH v0.70.1 `56bd5d00f76331c7f76d7b696726a7926303ca0c`。相对R17基点844共40文件，已组合U2/U3和共享runtime/platform/integrator。R19核对96项封存摘要及远端身份，仅发布文档；源公开handoff SHA256：`b39e2b6fb2d2e87289a36d2b1089de915430e1711030b040cdaa2e963f7f0007`。

## 已组合的施工行为

- English实际闭包与loose入口统一；窗口成立后、重资源前初始化native，菜单后一次attach及READY检查。
- 文件支撑DAT索引、独立限界RWops片段、按需解码、活动PCM保护与普通线程回收；默认路径避免整库预解码。
- App.ui拥有唯一位置，单次HID批次中先触摸同步派发，再查询场景并处理方向/face动作；失败返回停止当前批次。
- checked保存/读取覆盖write/close/fsync/备份及安装结果，失败保留旧进度；合盖/HOME有界暂停恢复。
- 已迁移U3插桩至实际lazy音效及语言/精灵/地图/存读档边界；记录成功双屏**软件提交**间隔、错误/跳过和长停顿。SDL2顶屏present返回void，不能证明物理scanout。

当前入口：[资源预处理](https://github.com/zzliu-coder/corsixh3ds/blob/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e/tools/prepare_loose_assets.py)、[上游集成](https://github.com/zzliu-coder/corsixh3ds/blob/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e/tools/integrate_corsixth.py)、[native运行时](https://github.com/zzliu-coder/corsixh3ds/blob/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e/src/3ds/runtime_3ds.cpp)、[Lua适配器](https://github.com/zzliu-coder/corsixh3ds/blob/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e/lua/3ds/platform.lua)、[公共遥测](https://github.com/zzliu-coder/corsixh3ds/blob/e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e/src/common/telemetry.cpp)。上述行为是施工交付声明，实际组合独立验收由R26执行。

## 施工封存：2026-09-05T03:53:34.907863+00:00

| 检查 | 封存结果与限制 |
|---|---|
| 本地C++ | 134/134 PASS |
| 本地完整Python | 166 selected：164 PASS、1 ERROR、1允许的大小写FS skip；整体 **FAIL** |
| 本地错误 | `CANDIDATE_PARENT_MISMATCH`：E0既有规则要求直接父R9 `8e9df167...`，实际产品直接父为`fe569cf563ab9a01848686d3fef47c4c4b82d3bd`。未绕过检查或改写既有E0文件 |
| 清单数量 | 143 baselineCount与E0的149为不同清单口径，待R25核对身份与清单关系；数字差本身不证明丢测 |
| 实际生成代码、本地交叉构建、loose包 | 施工 **PASS**；包内二进制与本次构建绑定，不授予设备准入 |
| 封存公网快照 | run33943007122为 **in_progress**，当时公共验收 **NOT_PROVEN**；原记录保持不变 |

音效主机数据：实际英语747个索引、746个可播放槽，启动PCM=0，100次结束/回收循环；已知所有者观测峰值 **3,145,539B**。计数覆盖自有缓冲/容量和已知结构，不含全部分配器、SDL/mixer内部开销及不透明暂存；采样峰值也只是检查点的峰值下界。主机SDL dummy音频证明受控解码/播放调用与所有权，设备可听输出、总内存和reserve仍 **NOT_PROVEN**。真实整库RNC输入分支未执行。

原生混合输入、实际UI方法及生成函数检查使用明确HID/SDL/引擎构造测试缝；它们不构成完整实际游戏或设备交互证明。

## 后续根任务读回（晚于上述封存）

R19于 **2026-09-05T04:13:30.571424+00:00** 复核GitHub API：[run33943007122](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33943007122)，attempt1、exacthead`e3f2c4a80f60f82aae9935f9ef5c7cb35930f03e`，**completed/failure**。

- 2成功：old3ds-cross-build、runtime-core-protocol-self-test。
- 7失败：verifier-authority-negative、host-gcc-debug、host-gcc-release、host-gcc-sanitized、host-clang-debug、host-python-3.9.25、host-python-3.14.6。
- 1跳过：official-fresh-chain-final-seal。

此处是后续终态，施工者封存的in_progress记录继续保留。各失败日志原因尚未逐项查明，不能声称七项都来自本地`CANDIDATE_PARENT_MISMATCH`。

## 下一步与未证明边界

R25（GPT-6 max）只查既有验收身份合同和全部公网失败；R26（GPT-6 high）只读独立验收实际组合产品。U1继续作为唯一共享文件集成人，两份结果出来后再施工。设备准入尚未放行。

完整游戏、第一关接待/诊室/招聘/患者就诊、真实保存退出重启、HOME/合盖、P1/P2/P3设备门槛、稳定FPS/内存及长期运行均 **NOT_PROVEN**。RH07/RH09实验路径 **FAIL**保留。E0单列候选48cc842的R23为FAIL；R24在原三文件内继续修两类来源绑定。任何旧10/10都不转移为当前或未来组合产品PASS。

可复用构建路径：干净候选 → 固定上游组装与重复组装 → 等待完整交叉构建 → 新loose staging → manifest校验 → 构建/包内二进制相等 → 完整主机清单。公开仓库只含源码与测试；本说明不发布原版素材、存档、完整SD包或本机日志。
