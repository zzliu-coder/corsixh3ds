# R41：实际音效消费者的初始化、失败清理与重试

当前源码[`a15a981f31bdf9264e2a296a96019f85bd36ca92`](https://github.com/zzliu-coder/corsixh3ds/tree/a15a981f31bdf9264e2a296a96019f85bd36ca92)，tree `8c5cdff92262e85011d3183b3a08cb18183b80fd`，唯一父`6bd03d56ed2679a6c5d5b2b9137dcdfd3d770e59`。R41报告SHA256 `ede9ed32d811e20c9fc4df16f2a709e91f04933b6b4592aad73b53b39721c0f5`。**施工本地PASS，独立验收及设备NOT_PROVEN。**

## 因果与所有权

原完整生成消费者中，`sound_count=747`先于指针表分配；分配异常后析构进入`populate_from(nullptr)`，逐项访问空表。R41自行复现基线退出-6，UBSan空指针及ASan调用栈记录与原R26线索分开。R26整体审查中断，没有最终结论。

[新实现](https://github.com/zzliu-coder/corsixh3ds/blob/a15a981f31bdf9264e2a296a96019f85bd36ca92/tools/integrate_corsixth.py#L1802)先准备新状态，成功后才替换旧bank：

1. 借用的旧archive、缓存、计数、pin保持；通过现有reserve检查新元数据请求。
2. `unique_ptr`准备零初始化指针表，局部vector准备使用时间/分配记账表。拒绝reserve或任一分配抛异常时，局部对象回收已分配内存，旧状态不变。
3. 全部准备成功后同步halt mixer；旧元数据仍有效时释放channel pin，再释放旧chunk与表。
4. 通过release/swap和标量赋值提交新archive/表/计数，归零缓存和时钟。按需解码和3MiB缓存规则保持。
5. 显式释放、析构无需新分配或reserve；空bank合法，同archive替换后可重新播放，同对象失败后可重试。

archive是借用关系，player不删除它；调用者须在成功替换或释放前保留旧archive，成功后保留新archive。现有Lua在native成功后更新环境中的archive。native已验证的失败不变量仍需放回Lua异常/GC整条生命周期审查。

## 已执行的施工检查

| 检查 | 结果及证明范围 |
|---|---|
| 初次和替换各4点 | reserve拒绝、指针表与两张元数据表失败；临时分配剩余0，旧内容/pin保持；8次同对象重试通过。 |
| 正常/释放路径 | 同archive替换、空bank、无分配释放通过，100次实际替换/释放循环；失败incoming archive销毁后旧播放仍有效。 |
| 完整生成消费者 | ASan与UBSan分别编译执行，零诊断；各747索引/746播放，启动PCM0，切片/独立读句柄/pin保持及正常通道循环通过。 |
| 主机记账 | 已知owner峰值3,145,539B，PCM/cache3,105,928B；三张元数据表主机请求17,928B。旧/新元数据准备时短暂共存，不展开PCM；这些数值不代表设备总堆。 |
| 相关和完整主机回归 | assets5、integrator6通过；最终HEAD绑定C++134、CTest3，Python168=166PASS+2原环境SKIP、零错误/失败。原166ID保留，新增2，baseline143不变。 |
| 组装与交叉 | 固定上游644文件与Git blob核对；前后两次完整组装只改th_sound.cpp，重复组装零变动、check拒绝旧函数。受影响ARM对象通过；封存时新最终ELF未建。 |

固定上游为CorsixTH v0.70.1 `56bd5d00f76331c7f76d7b696726a7926303ca0c` / tree `10bfcc53e260fcc68bda4201c97a45ed049f31a0`。两个Python跳过来自大小写不敏感文件系统冲突夹具、缺本地同HEAD最终ELF证明。SDL dummy和内存适配器是主机受控接口；SDL预编译库未插桩、LeakSanitizer不支持，因此不宣称全局无泄漏。设备reserve、Lua/GC失败全链、整机内存和帧率仍NOT_PROVEN。

## 小型公开复现

在已有精确源码checkout中检查身份，使用Python3、可用C++17编译器运行原相关测试；测试在自己的临时目录组装输入，不需要正版声音素材。以下是公开复现入口，本资料发布任务未重跑测试：

```sh
git rev-parse HEAD HEAD^{tree}
git rev-list --parents -n 1 HEAD
python3 -m unittest discover -s tests -p test_playable_assets.py -v
python3 -m unittest discover -s tests -p test_integrator.py -v
```

预期head为a15a981、tree为8c5cdff，唯一父为6bd03。测试应覆盖initial=4、replacement=4、retry=8、release=100以及旧函数升级、check拒绝和幂等；这些受控测试结果不能代替完整音库或真机测试。

完整实验证据来自施工者对实际生成th_sound.cpp和自有正版声音的独立ASan/UBSan执行。本页不公开原版素材或私有重放路径。外部审核可先用公开测试查所有权/失败路径，再在自己合法持有的原始资源与独立结果目录中验证完整消费者。

## 历史通过结果与下一个阻塞

R37的[E0正式运行](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33956848219)及R40复核的[R39产品回归](https://github.com/zzliu-coder/corsixh3ds/actions/runs/33968530647)各绑定自己的旧源码。R41只增加四文件，未修改E0权威/锁/协议。R41自动CI另按同HEAD观察，旧PASS不回写新身份。

下一道门槛是精确a15a981的独立验收，重点在实际Lua→native失败、archive借用、回调同步、pin释放与重复生命周期。随后再建立新最终ELF/包和同一二进制的真机完整成功链。`RH07_PRODUCT`/`RH09_PRODUCT`原FAIL保留，最小可玩、完整游戏、设备与真实内存仍NOT_PROVEN。
