# 3DS 资源构建身份

正式玩家目标默认 `CTH3DS_BUILD_PROFILE=loose`。另一个合法值是
`resource-experiment`，供 TH3DS RuntimeSession 工具与实验验收使用。
其他值拒绝；该配置没有新增游戏界面或运行时切换入口。

| 身份 | 原生资源实现 | 打包 asset-mode |
| --- | --- | --- |
| loose | 玩家公共实现；不编译 RuntimeSession / ResourceManager / TH3DS / AllocationLedger / SHA256 | loose |
| resource-experiment | 玩家公共实现加上述五个实验实现文件 | th3ds |

`src/common/sources.cmake` 是公共源的唯一分类表。旧 ResourcePack 仅供工具与测试，
不加入任一 3DS 产品源集合。原生编译定义 `CTH3DS_RESOURCE_EXPERIMENT=0|1`
由配置生成；直接原生编译默认 0。

构建、生成和打包入口统一读取该环境变量；直接调用集成器使用
`--build-profile`，直接 CMake 配置使用 `-DCTH3DS_BUILD_PROFILE=...`。
生成收据的输入指纹包含 profile，CMake、source owner、二进制绑定与打包都校验一致。
旧的未记录 profile 的生成收据需要重新生成，已有依赖缓存可保留。

实验配置的默认 build / cross-build receipt / dist 目录带
`-resource-experiment` 后缀；已有显式目录覆盖参数保持有效。
需要共享工具链依赖时，将既有 `CTH3DS_DEPS_PREFIX` 指向已验证缓存。
上游固定源缓存可共用；生成视图由同一 owner 串行选择，跨身份视图无法复用。

正式原生初始化会在窗口、Lua owner、epoch 改变前拒绝 `th3ds`。
loose 的能力声明和 resource_event 拒绝消息、真实保存提交、输入、音频、
生命周期、runner 私有身份及恢复命名保持原合同。

`build_3ds.sh` 的最终链接门分别证明：loose archive/ELF 缺席实验符号，
实验 archive/ELF 保留会话入口及真实调用边；两者均要求玩家 ready 调用门、
禁止 whole-archive。设备行为与 ARM 净体积需要相应新产物验证。
host 平台 syntax 目标仅证明完整编译，不能代替最终 ARM 链接。

host probe、H1/H2 观察器及资源工具显式依赖实验库。
Python 夹具自行选择 profile，默认使用 loose，避免外层实验构建身份污染夹具。
历史 E0 fresh-chain 保留既有授权指纹及精确产品范围；它不代表当前产品树验收。
H1/H2 原有红观察不在本次资源分离中修复。
