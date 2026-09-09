# 原版帧率参照与当前优化目标

2026-09-09。按用户要求由 Luna max 研究，主线程核对原版手册和固定上游源码。

## 已确认与尚未证明

原版1997年 DOS/Windows《主题医院》的精确呈现FPS、统一上限和VSync行为，
本轮未取得可靠第一手数值。原版手册只确认五档速度，以及分辨率/阴影对游戏
速度的影响。不能把显示刷新率、DOSBox cycles或现代机器观测写成原版固定FPS。
[原版手册，第1、7、45页](https://www.retrogames.cz/manualy/DOS/Theme_Hospital_-_Manual_-_PC.pdf)。

CorsixTH固定上游 `56bd5d00f76331c7f76d7b696726a7926303ca0c` 可以提供可核对
的规则参照：[18ms基础时钟](https://github.com/CorsixTH/CorsixTH/blob/56bd5d00f76331c7f76d7b696726a7926303ca0c/CorsixTH/Src/lua_sdl.h#L43)、
[速度档](https://github.com/CorsixTH/CorsixTH/blob/56bd5d00f76331c7f76d7b696726a7926303ca0c/CorsixTH/Lua/world.lua#L716-L727)、
[实体与动画更新顺序](https://github.com/CorsixTH/CorsixTH/blob/56bd5d00f76331c7f76d7b696726a7926303ca0c/CorsixTH/Lua/world.lua#L860-L948)。

| 固定上游规则 | 名义值，非Old3DS实测 |
|---|---|
| 世界基础更新 | 18ms一次，约55.56次/秒 |
| Normal | 每3次基础更新推进1个游戏小时，约18.52次游戏/实体动画更新/秒 |
| Max speed | 每2次推进1个游戏小时，约27.78次/秒 |
| And then some more | 每次推进1个游戏小时，约55.56次/秒 |
| Speed Up `{8,1}` | 每次基础更新执行8次游戏小时/动画更新，约444.44次/秒；与第五档不同 |

单个人物还可能有意慢动画或等待。绘制可以重复显示当前离散动画帧；呈现FPS
与动画换帧率、游戏日期推进量分开计量。固定上游SDL主循环会合并积压timer
事件；当前3DS的独立SimulationClock/PresentationClock须按自己的计数判断。

## 保留30FPS+，同时验收模拟速度

30FPS+继续作为Old3DS产品目标，原版帧率还原声明保持NOT_PROVEN。
正常速度下，同时看有效呈现间隔、完成的World/游戏小时/实体更新、时钟欠账
与丢弃、输入积压。重复提交旧画布另记，不用它补足有效FPS；现有素材离散
动画重复帧本身属于正常规则。当前不增加动画插帧或自定义游戏速度。

R64有效窗口60.025475秒：925帧、2775World、925游戏小时，呈现15.410FPS。
R65有效窗口60.021092秒：936帧、2808World、936游戏小时，呈现15.595FPS。
两轮都低于30FPS及名义实时推进能力。工作量未完全锁同，不能凭两次小差异
宣称精确提速比例。[R64证据](evidence/r64-runner-20260909.json)、
[R65证据](evidence/r65-runner-20260909.json)。

下一步沿[五框架主计划](R63_PERFORMANCE_PLAN.md)减少模拟和绘制的实际成本，
同窗观察模拟时钟；不因原版FPS未知而降低用户已确定的性能目标。
