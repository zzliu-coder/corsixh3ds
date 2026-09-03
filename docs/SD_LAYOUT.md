# SD 卡布局

执行：

```bash
./scripts/package_sd.sh --theme-hospital "/path/to/Theme Hospital"
```

运行包可以使用 `--no-data-pack`，只复制 CorsixTH 运行所需的松散原始文件；默认的 `.thp` 归档适合单独审计和校验。

生成：

```text
dist/sd-card/
└── 3ds/
    └── corsixth/
        ├── CorsixTH-3DS.3dsx
        ├── CorsixTH.lua
        ├── config.txt
        ├── sd-manifest.json
        ├── re.lua
        ├── Bitmap/
        ├── Campaigns/
        ├── Fonts/
        ├── Graphics/
        ├── Languages/
        ├── Levels/
        ├── Lua/
        └── game/
            └── 原版 Theme Hospital 数据
```

`config.txt` 固定：

```text
theme_hospital_install = "sdmc:/3ds/corsixth/game"
width = 640
height = 480
fullscreen = true
ui_scale = 1
```

`.3dsx` 和运行数据放在同一个应用目录，便于 Homebrew Launcher 启动和整体删除。保存文件仍由 CorsixTH 的保存目录逻辑管理，原子保存适配器会生成 `.tmp` 和 `.bak`。
