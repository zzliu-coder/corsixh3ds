# R74 私有交互验收会话

状态：源码合同已实施；真机 HOME、合盖、键盘、恢复画面和声音需一次集中人工确认。

## 配置与准备

使用 `tools/prepare_runner_benchmark.py --interactive --interactive-input HEALTHY.sav`，并提供原有 installed-tree、integration-receipt、assets-receipt-sha256、out 参数。profile 保持 `zh-on`，stress 为 0，禁用 capacity / busy-capacity / recovery。生成 `interactive=r74-v1`，旧配置生成字节保持不变。

准备只在全新本地目录生成 config.bin 和 preparation.json；JSON 中 command 是待主线程填入已验证 runner 路径、IP、artifact 与 launcher SHA 的单次 job 命令。准备过程不连接设备，不提交 job。超时 1800 秒；复用 runner 原有 timeout 行为：保留证据与锁，仅恢复后 wait，不自动重新投递或重启。

显式输入须由已有健康医院证据选定。文件扩展名或 SHA 一致只证明来源身份，不能证明医院模拟健康。

## 私有路径和正常玩法

原 runner manifest 验证 program.3dsx / config.bin / input.bin；Lua 树、安装配置和素材 receipt 延续现有校验。run ID 必须未消费，save 目录必须新建成功。原生复制逐文件哈希回读。

输入保留为 input.bin / input.sav，并复制到 `save/Acceptance.sav`。游戏从正常菜单“载入游戏”选择 Acceptance；测试保存可另起名称，例如 `Acceptance-after`，也允许正常覆盖私有 Acceptance。初始复制有原生哈希回读，后续修改单独记录；manifest 绑定的 input.bin 保持不变。

App 的存档、config / hotkeys、日志和截图都复用 runner 私有路径。互动模式不激活 Benchmark、不消费 one-shot marker，触摸、按键和生命周期走原普通游戏路径。

## 退出与判定

最终 main 的 Lua 重启循环结束后写 result.kv：`NOT_PROVEN / needs_human_confirmation`，workload 为 `corsixth-r74-interactive-v1`。内部 Lua 重启中的 Runtime::shutdown 不完成会话。已有 FAIL 保留；互动模式拒绝 PASS。

启动早退、硬崩溃或断电可能没有完整 result；原 runner 判定 INTERRUPTED / NOT_PROVEN，不会补造 PASS。正常返回 runner 的 COMPLETED 表示交接完成；实际体验仍需人工确认。

只读消费者：`python3 tools/read_interactive_result.py LOCAL_RETAINED_RUN`。保留文件布局：manifest.kv、program.3dsx、config.bin、input.bin、launch.kv、result.kv、receipt.kv、artifacts/boot.log、save/Acceptance.sav 及测试新存档。host runner 自带 fetch 后，应由现有读回流程补齐 private save 与日志；消费者本身不联网。

消费者核验 manifest/实物/结果/launcher 身份，拒绝错误 workload 和 PASS，保留原始结果及日志和保存文件哈希。`product_acceptance` 与原用户文件保护均保持 NOT_PROVEN，主线程另外核前后保护清单。它不从帧数推断模拟健康或体验。

## 一次集中操作

1. 正常载入 Acceptance，Normal 运行约 20 秒，观察人物、画面和声音。
2. 保存命名键盘先取消，再输入新名称并保存；确认取消无写入。
3. HOME 可用时进入系统界面约 10 秒后返回；若系统不支持则记录 NOT_PROVEN。
4. 无保存/加载进行时合盖约 10 秒再开盖，观察人物、音乐、上下屏和触摸恢复。
5. 保存到测试新名称并重新载入，继续约 20 秒，正常退出回 runner。

主线程读回日志、私有存档和前后用户文件保护。HOME / lid / resume_simulation / visual_input / audio / private_roundtrip 独立记录 PASS、FAIL 或 NOT_PROVEN。
