# SD 卡启动合同

正式设备候选使用明确的 `th3ds` 资源模式：

```bash
./scripts/package_sd.sh \
  --asset-mode th3ds \
  --theme-hospital "/path/to/Theme Hospital" \
  --language English
```

脚本只接受已经提交且洁净的源码树，也只写入一个全新的应用目录。它会从用户自备的
正版数据生成 TH3DS package family；原始 `game/` 树、原版可执行文件和用户存档都不
进入设备候选。

生成的关键结构：

```text
dist/sd-card/3ds/corsixth/
├── CorsixTH-3DS.3dsx
├── CorsixTH.lua
├── boot-contract.json
├── config.txt
├── cth3ds-overlay-version.txt
├── sd-manifest.json
├── Bitmap/
├── Campaigns/
├── Graphics/
├── Levels/
├── Lua/
└── resources/
    ├── bundle.th3ds.json
    ├── core.th3ds
    └── lang/<selected-language>.th3ds
```

`boot-contract.json` 固定以下事实：

- `asset_mode`、候选 commit/tree 和是否具备产品候选资格；
- 入口 3DSX 的路径、大小和 SHA-256；
- 启动必需文件、目录和完整 TH3DS bundle/package family；
- 禁止路径以及保留给用户可变数据的目录。

`sd-manifest.json` 枚举发布树中的每个文件，并用大小和 SHA-256 绑定
`boot-contract.json`。`tools/validate_sd_tree.py` 会重新计算整个树，拒绝空目录、
符号链接、缺失或额外文件、错误哈希、伪装成 `.3dsx` 的文件、缺失 bundle/package、
混入的原始 loose 数据和用户存档。

仅需诊断历史 loose loader 时，必须显式运行：

```bash
./scripts/package_sd.sh \
  --asset-mode loose \
  --theme-hospital "/path/to/Theme Hospital"
```

该合同固定写入 `product_ready_eligible: false`。验收工具要求 `th3ds`，所以 loose 树
无法进入产品候选门。公开源码和测试 fixture 均不包含原版 Theme Hospital 数据。

## 验收输入绑定

`tools/v061_acceptance.py` 从原始 `python-tests.log` 重新提取
`passed/failed/errors/skipped`。预期跳过必须通过重复的 `--expected-python-skip` 参数按
unittest 的完整测试标签声明；未声明的跳过会使 H03 失败。

部署报告必须提供 `deploymentId`、`deviceId`、带时区的 `deployedAt`，并记录完整读回
后的 `binarySha256`、`manifestSha256`、`filesVerified` 和 `bytesVerified`。真机日志必须
包含一行 canonical JSON 身份记录：

```text
acceptance-identity: {"binary_sha256":"...","boot_started_at":"...","candidate_commit":"...","candidate_tree":"...","deployment_id":"...","device_id":"...","manifest_sha256":"...","schema":"corsixth-old3ds-boot-v1"}
```

身份必须逐字段匹配当前包与本次部署，`boot_started_at` 必须晚于 `deployedAt`。缺失、
空白、截断、旧日志、候选不一致或设备不一致均记录为 `FAIL`。当前运行时和部署工具
尚未生产全部字段时，设备门保持 `NOT_PROVEN` 或 `FAIL`，不能借历史日志放行。
