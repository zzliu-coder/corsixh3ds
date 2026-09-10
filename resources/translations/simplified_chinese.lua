-- Handheld completion of the pinned upstream Simplified Chinese catalogue.
-- Appended inside the real language environment; ordinary inheritance/formatting
-- still owns these strings. Protocols, save paths and English are unchanged.
adviser.warnings.cannot_afford_machine = "更换%2%至少需要银行存款 $%1%！"
adviser.warnings.cannot_buy = "无法再购买这种物品！"
adviser.warnings.another_desk = "请为新接待员再建一个接待台。"
adviser.warnings.no_doctor_no_gp_office = "请建造诊断室并雇佣医生！"
adviser.warnings.no_gp_office = "请建造诊断室，让医生为病人诊断！"
adviser.staff_place_advice.not_enough_lecture_chairs = "每位受训医生都需要一把培训椅！"
adviser.cheats.queuejump_off_cheat = "病人不再让病危者优先就诊。"
adviser.cheats.queuejump_on_cheat = "病人会让病危者优先就诊。"
adviser.cheats.superdoctor_on_cheat = "优秀医学院推荐毕业生来应聘！请查看待聘员工。"
adviser.cheats.superdoctor_off_cheat = "医学院不再推荐毕业生来应聘。"
confirmation.restart_mapeditor = "确定重新启动地图编辑器吗？"
confirmation.quit_mapeditor = "确定退出地图编辑器吗？"
confirmation.very_old_save = "游戏在此存档创建后已有多次更新。要重新开始本关，以确保各项功能正常吗？//只要不覆盖，原存档会被保留。"
confirmation.replace_machine_extra_info = "新机器的强度为 %d（当前为 %d）。"
confirmation.remove_destroyed_room = "要花费 $%d 拆除这个房间吗？"
options_window.sound = "声音"
options_window.right_mouse_scrolling = "鼠标滚图"
options_window.right_mouse_scrolling_option_middle = "中键"
options_window.right_mouse_scrolling_option_right = "右键"
options_window.autosave_frequency = "自动存档频率"
options_window.scale_ui = "界面缩放"
autosave_frequency = {daily="每日", weekly="每周", monthly="每月"}
save_game_window.missing_filename = "请输入新存档名称，或选择要覆盖的存档。"
save_game_window.save_button = "保存"
save_map_window.save_button = "保存"
save_map_window.missing_filename = "请输入新地图名称，或选择要覆盖的地图。"
load_game_window.load_button = "载入"
load_map_window.load_button = "载入"
load_map_window.caption = "载入地图（%1%）"
customise_window.enable_screen_shake = "画面震动"
customise_window.enable_announcer_subtitles = "播报字幕"
customise_window.machine_menu_button = "机器菜单按钮"
customise_window.emergency_only = "仅急诊病人"
customise_window.male_and_female = "男性和女性"
customise_window.male_only = "仅男性"
customise_window.regular_patients = "普通病人"
adviser_history.message = "消息"
adviser_history.close = "关闭"
machine_menu.ratio = "强度比例"
machine_menu = {machine="机器",status="状态",remaining_strength="剩余",total_strength="强度",close="关闭"}
tooltip.machine_menu = {sort="点击按此项排序",machine="点击机器，打开详情并移到其所在位置",
  smoking="标记表示机器有爆炸危险。点击购买新机器。",assigned="标记表示已安排勤杂工维修。点击查看负责的勤杂工。",
  remaining_strength="机器的剩余强度",total_strength="机器的总强度",close="关闭机器列表",
  header={smoking="危险标记",assigned="维修安排标记",machine="机器名称",remaining_strength="机器剩余强度",status="机器状态",total_strength="机器总强度"}}
cheats_window.cheats = {max_reputation="最高声望",repair_all_machines="维修所有机器",reset_death_count="清零死亡人数",
  show_infected="显示或隐藏感染标记",toggle_earthquake="切换地震",toggle_epidemic="切换传染病",toggle_invulnerable_machines="切换机器无损状态"}
tooltip.cheats_window.cheats = {max_reputation="将医院声望设为最高",repair_all_machines="维修医院内的所有机器",reset_death_count="将医院死亡人数清零",
  show_infected="显示或隐藏当前已发现传染病的感染标记",toggle_earthquake="切换是否发生地震",toggle_epidemic="切换是否发生传染病",
  toggle_invulnerable_machines="切换机器使用时是否磨损"}
custom_campaign_window.duplicates_warning = "已隐藏 %d 个名称重复的战役"
hotkey_window.ingame_sellPickedUpItem = "出售拿起的物品"
hotkey_window.ingame_panel_adviserHistory = "顾问消息记录"
hotkey_window.ingame_panel_machineMenu = "机器菜单"
hotkey_window.ingame_toggleTransparent = "切换透明显示"
menu_charts.adviser_history = "  (%1%) 顾问消息记录 "
menu_charts.machine_menu = "  (%1%) 机器菜单"
menu_debug_overlay_blocking_off_areas = {choice_1="  完全禁止  ",choice_2="  部分允许  ",choice_3="  完全允许  "}
information.level_lost.patient_happiness = "病人的平均满意度已低于 %d%。"
information.level_lost.staff_happiness = "员工的平均满意度已低于 %d%。"
audio_window = {caption="声音设置", announcement_volume="播报音量", sound_volume="音效音量", music_volume="音乐音量",
  midi_port="MIDI 端口", midi_api="MIDI 接口", soundfont="音色库", soundfont_location_caption="选择音色库（%1%）",
  jukebox="音乐播放器", default_midi_port="默认", default_midi_api="默认（软件）"}
tooltip.folders_window.clear_directory = "清除当前选择的目录"
tooltip.status.under.patient_happiness = "病人的平均满意度至少应为 %d%。当前为 %d%"
tooltip.status.under.staff_happiness = "员工的平均满意度至少应为 %d%。当前为 %d%"
tooltip.status.over.patient_happiness = "病人的平均满意度应高于 %d%。当前为 %d%"
tooltip.status.over.staff_happiness = "员工的平均满意度应高于 %d%。当前为 %d%"
tooltip.options_window = {scale_ui="调整界面比例。仅显示适合当前分辨率的选项。", select_ui_scale="选择界面比例",
  ui_scale_unavailable="当前分辨率不支持界面缩放，请先提高分辨率。", sound="调整声音设置",
  right_mouse_scrolling="切换用于滚动地图的鼠标按键", language_dropdown_no_font="请先在目录设置中选择支持此语言的字体",
  autosave_frequency="设置游戏自动存档的频率", resolution_unavailable="当前界面比例不支持此分辨率"}
tooltip.autosave_frequency = {daily="每个游戏日开始时自动存档，保留一年，共 365 份。单份存档可能超过 1 MB，请预留足够空间。",
  weekly="每月的 1、7、14、21、28 日自动存档，保留一年，共 60 份。", monthly="每月第一天自动存档，保留一年，共 12 份。"}
tooltip.adviser_history = {header={message="顾问消息",delete_message="点击清空所有消息"},close="关闭顾问消息记录",
  message="顾问消息列表，最新消息排在前面",delete_message="点击删除此条消息"}
tooltip.debug_patient_window.item = "创建患有%s的测试病人"
tooltip.custom_campaign_window.duplicates_warning = "详细错误请查看日志窗口"
tooltip.toolbar.machine_menu = "机器菜单"
tooltip.machine_menu.ratio = "剩余强度占总强度的比例"
tooltip.machine_menu.header.ratio = "机器剩余强度占总强度的百分比"
tooltip.customise_window = {enable_screen_shake="地震时画面会震动。关闭此选项可保持画面稳定。",
  enable_announcer_subtitles="显示医院广播的字幕",machine_menu_button="在底部工具栏显示机器菜单按钮。低分辨率下可能无法显示。"}
tooltip.audio_window = {announcement_volume="调整播报音量",sound_volume="调整音效音量",music_volume="调整音乐音量",
  midi_api="游戏音乐使用的 MIDI 接口。自定义音乐目录不使用此选项。",midi_port="游戏音乐使用的设备端口",
  browse_soundfont="选择其他音色库文件（sf2 或 sf3）。当前位置：%1%",jukebox="打开音乐播放器",back="关闭窗口",
  browse="选择目录",no_soundfont_specified="使用默认音色库",soundfont_location="播放 MIDI 音乐使用的音色库。未指定时使用默认音色库。"}
tooltip.hotkey_window = {panel_debugKeys="设置调试快捷键",panel_scrollKeys="设置滚动地图快捷键",panel_generalInGameKeys="设置常用游戏快捷键",
  panel_toggleKeys="设置切换选项快捷键",panel_globalKeys="设置全局快捷键",panel_zoomKeys="设置缩放快捷键"}
map_editor_window.pages.paste = "粘贴区域"
map_editor_window.pages.set_parcel = "设置地块编号"
map_editor_window.pages.set_parcel_tooltip = "选择编号后按回车确认。"
map_editor_window.pages.parcel = "地块 %d"
map_editor_window.checks.spawn_points_and_path = "警告：病人无法到达医院。地图边缘需要道路或室外灰色地砖，并有路径通往医院入口。"
errors.overlay = {incorrect_difficulty="地图覆盖难度必须为 easy、full 或 hard。当前值：",
  incorrect_level_number="地图覆盖关卡编号必须为 1 至 12。当前值：",missing_setting="自定义关卡的地图覆盖设置缺少难度和关卡编号。"}
errors.cannot_restart_missing_files = "缺少文件 %s 或 %s，无法重新开始此关。"
errors.missing_level_file = "错误：找不到所选关卡文件。"
errors.missing_th_data_file = "警告：找不到文件 %s，主题医院数据不完整。"
errors.music = "部分音乐文件无法播放，已在播放器中停用。详细信息请查看日志窗口。"
errors.load_level_prefix = "载入关卡时出错："
errors.load_map_prefix = "载入地图时出错："
errors.missing_corsixth_file = "警告：找不到文件 %s，请尝试重新安装 CorsixTH。"
misc = {epidemic_no_receptionist="无法创建传染病事件：没有正在工作的接待员",epidemic_no_diseases="无法创建传染病事件：没有可用的传染病",
  epidemics_off="已禁用传染病，不会再产生新的传染病事件。",epidemics_on="已重新启用传染病。",
  invulnerable_machines_on="机器将不再磨损或损坏。",invulnerable_machines_off="机器将恢复磨损，并可能损坏。",
  earthquakes_off="已禁用地震。",earthquakes_on="已重新启用地震。",
  epidemic_no_icon_to_toggle="无法切换感染标记：没有尚未公开的传染病事件。"}
-- Subtitle event keys remain identical to the original audio-bank slots.
subtitles = {
  alien001="红色警报！外星人来袭！",alien002="外星人降落了，救命！",alien003="外星人真的存在，而且就在医院里！",
  alien004="请外星来宾不要过度干扰医院工作！",alien005="外星来宾请在访客簿上签名。",
  cheat001="医院管理者正在作弊！",cheat002="警告！有人正在作弊经营医院！",cheat003="作弊警报！作弊警报！",
  epid001="传染病警报，请做好准备！",epid002="员工请注意：传染病警报！",epid003="警告，传染病警报！",epid004="警告！",
  epid005="传染病事件已结束，解除警戒。",epid006="传染病已得到控制。",epid007="传染病已被控制。",epid008="传染病紧急状态已结束。",
  quake001="警告！收到地震报告。",quake002="警告！地震即将发生。",quake003="注意！地震警报。",quake004="注意！地震即将来袭。",
  vip001="请注意，贵宾已进入医院。",vip002="一位贵宾已进入医院。",vip003="贵宾正在参观。",vip004="贵宾正在巡视医院。",
  vip005="医院有贵宾来访。",vip008="卫生部门的官员正在医院内。",
  sorry001="对于医院里的垃圾，我们深表歉意。",sorry002="对于室温过低，我们深表歉意。",sorry003="对于室温过高，我们深表歉意。",
  sorry004="暖气发生故障，向各位病人致歉。",sorry005="有呕吐物，请小心脚下。",sorry006="清洁人员请注意：走廊有呕吐物。",
  sack001="医生已被解雇。",sack002="一位医生即将离开。",sack003="一位医生正在离开。",sack004="一位护士即将离开。",sack005="一位护士正在离开。",
  sack006="被解雇的勤杂工正在离开。",sack007="一位接待员已被解雇。",sack008="一位接待员正在离开。",sack009="一位员工被挖走了。",sack010="一位医生被挖走了。",
  reqd001="请医生立即前往心脏科。",reqd002="请医生前往扫描室。",reqd003="请医生前往精神科。",reqd004="请护士前往骨折诊所。",
  reqd005="长舌治疗室需要医生。",reqd006="血液检测室需要医生。",reqd007="超声波室需要医生。",reqd008="诊断室需要医生。",
  reqd009="病房需要护士。",reqd010="手术室需要两名外科医生。",reqd011="手术室还需要一名外科医生。",reqd012="药房需要护士。",
  reqd013="放射室需要医生。",reqd014="充气治疗室需要医生。",reqd015="基因治疗室需要医生。",reqd016="生发室需要医生。",
  reqd017="培训室需要医生。",reqd019="电解治疗室需要医生。",reqd020="果冻治疗室需要医生。",reqd021="综合诊断室需要医生。",
  reqd023="研究部门需要研究员。",reqd024="除污室需要医生。",
  maint004="请勤杂工维修切舌机。",maint005="请勤杂工维修放射机。",maint006="请勤杂工维修基因修复机。",maint007="生发机需要维修。",
  maint008="请勤杂工维修电解机。",maint009="果冻机需要维修。",maint010="请勤杂工前往心脏科维修。",maint011="请勤杂工维修诊断机。",
  maint012="除污机需要维修。",maint013="请勤杂工保养充气机。",maint014="骨折治疗机需要维修。",maint015="请勤杂工前往血液检测室。",maint016="请勤杂工前往超声波室。",
  machwarn="【机器警报】",
  rand001="请接听白色便民电话。",rand002="请杰基尔医生前往精神科。",rand003="医院内请勿吸烟。",rand005="提醒病人，请勿在走廊死亡。",
  rand006="咳嗽和喷嚏会传播疾病。",rand008="病人请注意：请携带支票簿。",rand009="病人请注意：请携带信用卡。",rand010="请保持安静，这里有病人。",
  rand012="请各位病人尽量少呕吐。",rand013="警告：这是一条警告。",rand016="病人就诊，风险自负。",rand017="请精神病人尽量保持安静。",
  rand018="请病人耐心等待。",rand019="请病人安静候诊。",rand021="请勿在医院内乱扔垃圾。",rand022="乱扔垃圾违反规定。",
  rand024="请各位病人不要传播自己的病菌。",rand025="请各位病人准备好支票簿。",rand026="请各位病人准备好信用卡。",rand027="病危患者请到队伍前方。",
  rand028="请有序排队。",rand029="请关注牛蛙公司的其他产品。",rand030="请勿闲逛。",rand031="请勿乱扔垃圾。",rand032="请勿呕吐。",
  rand033="提醒各位员工，请及时休息。",rand034="今日特惠：生发治疗半价。",rand035="请伯克和黑尔先生前往后门。",rand036="请勿喂食害虫，谢谢。",
  rand037="请各位病人尽量小声呻吟，谢谢。",rand040="垃圾炸弹警报！",rand041="我播报累了，我想回家。",rand044="请大家尽量不要在走廊呕吐。",
  rand045="请莱克特医生到保卫处报到。",rand046="您的声卡工作正常。",
  emerg001="员工请注意：痔疮病人即将抵达。",emerg002="员工请注意：腹泻病人即将抵达。",emerg003="员工请注意：电视狂病人即将抵达。",
  emerg004="员工请注意：感冒病人即将抵达。",emerg005="员工请注意：骨折病人即将抵达。",emerg006="员工请注意：隐形症病人即将抵达。",
  emerg007="员工请注意：大头症病人即将抵达。",emerg008="员工请注意：多毛症病人即将抵达。",emerg009="员工请注意：猫王综合症病人即将抵达。",
  emerg010="员工请注意：严重辐射病人即将抵达。",emerg011="员工请注意：长舌症病人即将抵达。",emerg012="员工请注意：秃头症病人即将抵达。",
  emerg013="员工请注意：瘙痒症病人即将抵达。",emerg014="员工请注意：果冻症病人即将抵达。",emerg015="员工请注意：嗜睡症病人即将抵达。",
  emerg016="员工请注意：漏气症病人即将抵达。",emerg017="员工请注意：汗手症病人即将抵达。",emerg018="员工请注意：异常肿胀病人即将抵达。",
  emerg019="员工请注意：肠腐烂病人即将抵达。",emerg020="员工请注意：外星基因病人即将抵达。",emerg021="员工请注意：产妇即将抵达。",
  emerg022="员工请注意：透明症病人即将抵达。",emerg023="员工请注意：多余肋骨病人即将抵达。",emerg024="员工请注意：肾豆病人即将抵达。",
  emerg025="员工请注意：破碎的心病人即将抵达。",emerg026="员工请注意：结节破裂病人即将抵达。",emerg027="员工请注意：狂笑症病人即将抵达。",
  emerg028="员工请注意：脚踝褶皱病人即将抵达。",emerg029="员工请注意：鼻毛过多症病人即将抵达。",emerg030="员工请注意：络腮胡子病人即将抵达。",
  emerg031="员工请注意：伪血病人即将抵达。",emerg032="员工请注意：胃喷出病人即将抵达。",emerg033="员工请注意：铁肺病人即将抵达。",emerg034="员工请注意：高尔夫症病人即将抵达。",
}
