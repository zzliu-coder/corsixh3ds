# CorsixTH 上游接入

## 固定基线

```text
tag:    v0.70.1
commit: 56bd5d00f76331c7f76d7b696726a7926303ca0c
```

所有第三方提交和下载哈希记录在 `config/upstream-pins.json`。

## 一键接入

```bash
./scripts/bootstrap_upstream.sh
```

顺序如下：

1. 克隆或更新到固定提交；
2. 检查 `config/corsixth-lua-api-v0.70.1.json`；
3. 复制公共核心、3DS 运行时、Lua 适配器和图标；
4. 对 CMake、`main.cpp`、`sdl_core.cpp`、`th_gfx_sdl.cpp` 和 `app.lua` 应用精确锚点补丁；
5. 生成 `corsixth_3ds_sources.cmake`；
6. 重新检查所有标记、文件哈希和两条 App 初始化路径。

补丁器可单独运行：

```bash
python3 tools/integrate_corsixth.py external/CorsixTH --overlay-root .
python3 tools/integrate_corsixth.py external/CorsixTH --overlay-root . --check
```

## 修改点

- 顶层 CMake 增加 `CORSIXTH_3DS` 和依赖前缀。
- 运行数据路径改为 `sdmc:/3ds/corsixth`。
- 3DS 公共代码和运行时加入 `CorsixTH_lib`。
- 静态链接 `lfs`、`lpeg`，并在 Lua 启动前预加载。
- 主 SDL 循环增加运行时初始化、每帧 tick、下屏事件过滤和关闭处理。
- 主窗口强制使用显示器 0；下屏窗口使用显示器 1。
- 3DS 渲染器固定为 SDL 软件渲染。
- App 关闭片头、演示、动量滚动和 FPS 记录，保持 640×480 逻辑画布。
- 两条 UI 初始化分支均挂载 `3ds.platform`。

## 升级上游的规则

升级版本时必须同时完成：

1. 更新固定 tag 和 commit；
2. 审查 3DS 依赖的 Lua 方法；
3. 更新 API 契约；
4. 重新生成所有补丁夹具；
5. 跑完 `scripts/test_all.sh`；
6. 完成交叉编译和真机回归。

工程故意拒绝模糊匹配和自动猜测，以免上游变更在真机点击某个按钮时才暴露。
