# 启动诊断：从「卡死」到「卡在第几步」

0.4.0 在真机上只有一个信号：下屏一行 `STATE: 3DS ADAPTER IS NOT ATTACHED`。
这句话既不说明是哪一半出了问题，也不说明后面还发生了什么。0.5.0 把这条路补上。

## 1. SD 卡上的启动日志

进程一拿到控制权就打开 `sdmc:/3ds/corsixth/boot.log`，**不带缓冲**，并把 `stderr`
重定向进去。不带缓冲的意思是：卡死时文件里最后一行就是最后真正执行到的地方。

日志里至少包含：

```
CorsixTH 3DS overlay 0.5.0, embedded adapter crc XXXXXXXX
free application memory at start: N bytes
runtime: lower screen ready (320x240), free app memory N bytes
present: top viewport 320x240 at x=40, exact reduction=yes (1/2)
adapter: ...
runtime: boot complete, adapter=LUA|SD|EMB|FAIL
```

CorsixTH 自己 `fprintf(stderr, ...)` 的报错也会落在同一个文件里 —— 这些以前全部
丢失了。

取回日志：

```bash
python3 tools/old3ds_fetch_log.py --host <3DS 的 IP> --out run/device-logs
```

`scripts/old3ds_cycle.sh` 现在会在**部署之前**自动做这件事（部署会覆盖整个
`/3ds/corsixth`，之后再取就来不及了）。

## 2. 下屏显示身份

状态栏第二行现在是 `B5 W3 V63 M40 0.5.0 LUA` 这种形式，最后两段是 overlay 版本
和适配层来源：

| 标签 | 含义 | 说明 |
|---|---|---|
| `LUA` | `app.lua` 自己挂上的 | 正常路径，SD 卡上的 Lua 树是打过补丁的 |
| `SD` | 运行时自己从 SD 卡加载的 | **SD 卡上的 `app.lua` 不是打过补丁的版本**，但 `Lua/3ds/platform.lua` 在 |
| `EMB` | 用了编译进二进制的兜底副本 | SD 卡上的适配层缺失或加载失败，具体错误在 boot.log |
| `FAIL` | 完全挂不上 | Lua 错误在下屏和 boot.log 里 |

这四个状态直接回答了 0.4.0 无法回答的问题：**是二进制的问题，还是 SD 卡上 Lua
树的问题**。

## 3. 运行时自己挂载适配层

0.4.0 里挂载完全依赖 `app.lua` 中的 `CORSIXTH_3DS` 补丁：

```lua
local th3ds_ok, TH3DS = pcall(require, "th3ds")
local IS_3DS = th3ds_ok and TH3DS.is_platform()
...
if IS_3DS then self._3ds = require("3ds.platform").attach(self, TH3DS) end
```

只要 SD 卡上的 `app.lua` 是旧的（比如打包时用的不是集成过的上游树，或者部署到了
另一个目录、启动的是旧 `.3dsx`），`_3ds` 就永远是 nil，而二进制侧只会显示那句
「adapter is not attached」。

0.5.0 里 `runtime_initialize` 会自己补上：先探测 `TheApp._3ds`，没有就
`require("3ds.platform")`，再不行就用编译进二进制的 `platform.lua` 副本
（`tools/embed_platform_lua.py` 生成，`tests/test_embedded_adapter.py` 保证它和
`lua/3ds/platform.lua` 一致）。二进制和 Lua 版本再也不会静默地对不上。

## 4. 所有 Lua 调用都在保护调用里

CorsixTH 装了 `strict.lua`，它给 `_G` 挂了会 `error()` 的 `__index`。从 C 边界
上抛出 Lua 错误会走到 `lua_atpanic` 然后 `abort()` —— 在 3DS 上和死机完全一样，
而且什么都不留下。0.4.0 的 `call_platform_method` 直接 `lua_getglobal`、
`lua_getfield`，是暴露在这个风险里的。0.5.0 把这些动作全部塞进一个
`lua_pcall` 包裹的 C 函数。

另外，提示信息现在会在同步恢复正常后被清掉。0.4.0 只在失败时 `set_notice`，从不
清除，所以启动瞬间的一次失败会永久留在屏幕上，看起来像持续故障。

## 5. 内存耗尽不再等同于死机

Old 3DS 的应用内存比桌面小一个量级，CorsixTH 解码精灵时会 `new uint32_t[w*h]`。
未捕获的 `std::bad_alloc` 会走到 `std::terminate`，在 3DS 上表现就是两块屏幕同时
停住。0.5.0 在 `main()` 里包了 try/catch，转成下屏的 `FATAL: out of memory` 和
boot.log 里的一行，并保持画面几秒供阅读。

启动时和运行中的可用应用内存也会写进日志和下屏（`M<MB>` 字段）。

## 6. 退出

`APTHOOK_ONEXIT` 现在**在 APT 线程上立刻**推入 `SDL_QUIT`，不再等下一次
`runtime_tick`。主线程如果正卡在一个长帧里，等待正是「按 HOME 关闭没反应」的原
因。`tick()` 也会在退出置位后立即返回，不再做 Lua 调用和 SD 卡写入。
`shutdown()` 会先停掉混音器再让 Lua 释放音频块。

## 真机上该看什么

1. 开机后看下屏第二行的版本和适配层标签，确认跑的是哪个二进制、哪半边有问题。
2. 退出（或死机重启）后取 `boot.log`，看最后一行停在哪个阶段。
3. `present: ... exact reduction=yes (1/2)` 这行如果不是 `yes`，说明游戏窗口不是
   640x480，present 在做重采样，帧时间会异常。
