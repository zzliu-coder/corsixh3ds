# R74-03：点选字段与系统键盘

2026-09-10。实现范围为保存名、玩家名、数字单行框。原视野/触控坐标及经营规则保持。

## 唯一成功路径

真实 Textbox 点击回调 → 当前 pen-up 范围登记一个请求 → 原 Window/App 松笔处理退出 → 检查字段及窗口仍有效 → 系统键盘 → 再检查 owner → 按原字段策略验证 → setText → 一次原 confirm。A 复用相同 editText；初始化 setActive 不触发键盘。重复松笔没有第二次请求。

保存名使用既有 1–40 ASCII 字母/数字/空格/连字符/下划线；玩家名保留 15 字节及 alpha/numbers/misc（空格、加号、连字符）规则，空值交由原回调回退。数字使用 NUMPAD，原 Apply 继续负责范围与默认值。原中文值取消后完整保留。快捷槽在简体中文界面显示“存档槽 1/2/3”。

Cancel、不支持、关闭窗口、隐藏/禁用、已注销字段、UI 替换、模态窗口覆盖、字段 owner 替换均不提交。save_prefix 继续保护原默认名及快捷槽；自定义名称沿用原显式名称语义，本批不自动改名。多行控制台及无明确字段策略的输入框保持原路径。

原生键盘保留 GPU 静止、输入队列暂停/丢弃、32 声道原暂停状态及音乐原暂停状态恢复、声效回调暂停恢复、退出时拒绝确认。新增进入/返回两次已有 operation_boundary，系统键盘等待时间从模拟追赶时钟中排除；保持原时钟算法。

## 证据及依赖

定向 8 项通过（1.001 秒）：5 项新增真实模块/原生函数测试，3 项既有桥接/槽位回归。完整 pinned strict/class/window/save/player/options 文件加载；真实 Button/Textbox/Window.onMouseUp、confirm、数字 Apply、覆盖确认/取消及 Operations 执行。图形、注册/事件运输、文件、系统 applet 为受控服务；主机用 Lua 5.4 API-check 库。

原生探针抽取实际 text_keyboard 函数，在 ASan/UBSan 下覆盖 6 组按钮/退出组合、音频原状态、输入恢复及长时间 applet 后时钟 rebase。该证据不证明真实系统 applet 外观或实际硬件服务返回。

测试与保存代理的 R74 owner 修复合并后执行，依赖其共享 `tests/support/save_ui.py`、`tests/fixtures/save_ui_modules.json`、`tests/runtime_support/save_ui_loader.lua`。共享 helper 安装固定原模块时执行正式 Textbox/player 变换并检查幂等；产品集成仍由完整生成流程统一负责。原最小 44 文件生成夹具不含完整 UI 模块。

源文件入口：`tools/handheld_ui.py`、`lua/3ds/platform.lua`、`src/3ds/runtime_3ds.cpp`。嵌入头由主线程最终合并后统一生成。本子项未执行 ARM、FTP 或装机。

## 状态

- 字段实现与定向主机测试：PASS。
- 与最终全部 R74 改动的整套测试、默认 ARM、安装/读回：待主线程合批。
- 真实键盘显示/取消/确认、HOME/合盖、声音/触控恢复、最新存档重载：NOT_PROVEN，装机后一次实机闭环。
- 系统中文输入法、全 Unicode 编辑、地图编辑器与任意分辨率功能验收：本批未承诺。
