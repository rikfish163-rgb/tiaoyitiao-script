# 参考来源与素材说明

本项目独立实现。以下项目提供了算法思路和工作流参考：

1. `wangshub/wechat_jump_game`，Apache-2.0：
   - https://github.com/wangshub/wechat_jump_game
   - https://github.com/wangshub/wechat_jump_game/blob/master/wechat_jump_auto.py
   - 参考棋子颜色定位、头部直径归一化、非线性运动公式。
2. `da-p3/wechat-jump-pc`：
   - https://github.com/da-p3/wechat-jump-pc
   - 参考桌面窗口选择、截图预览和鼠标按压的工作流。
   - 其 README 仅注明学习交流；本项目没有复制其源代码。
3. python-xlib：
   - https://github.com/python-xlib/python-xlib
   - 通过安装的官方库提供 X11 和 XTEST 协议接口。
4. `wangshub/wechat_jump_game` 的 slim、AI 版和 `common/ai.py`：参考水平距离归一化、实测样本拟合和跳后记录思路。
5. `shenfe/wechat-jump-game`：参考模板、双帧、边界识别和设备实测时长的工作方式。
   本项目没有复制其代码，也没有沿用其设备系数。具体比较见 `docs/accuracy-review.md`。

`tests/fixtures/reference-game.png` 为以下开源演示 GIF 的第一帧，`examples/reference-annotated.png` 在该帧上添加检测标记：

https://github.com/wangshub/wechat_jump_game/blob/master/resource/image/jump.gif

原项目许可： https://github.com/wangshub/wechat_jump_game/blob/master/LICENSE

测试图中的游戏界面和商标归相应权利人；此处用于图像识别测试和结果说明，不表示获得微信或游戏官方认可。参考项目的作者权益、素材权益不因本项目源码许可而改变。

`tests/fixtures/desktop-start.png` 为本次任务中本地生成的跳一跳游戏区域截图，
`examples/desktop-start-corrected.png` 为其检测标注版本，用于回归验证平台阴影误判。
画面仅包含游戏窗口，不包含微信聊天内容；游戏界面权利仍归相应权利人。

`tests/fixtures/desktop-failed-annotated.png` 是一次错误定位留下的游戏标注图，仅作误判回归素材。
它带有旧算法的黄框和连线，不是原始未标注画面，也不是正确识别示例。

`tests/fixtures/desktop-green-marker.png` 与 `desktop-striped-platform.png` 是本地一次运行的
第 8 跳前后原始游戏窗口截图，分别用于验证顶面侧面分离、阴影触边时的平台识别。
`examples/green-marker-corrected.png` 与 `striped-platform-corrected.png` 是离线标注结果。
这些图只含游戏窗口；素材权利说明与上述游戏截图相同。

`desktop-marble.png`、`desktop-striped-roof.png`、`desktop-occluded-turntable.png` 位于
`tests/fixtures/`，来源为后续本地运行的游戏窗口原图，分别用于纹理顶面、装饰条与头径、遮挡拒绝回归。
`examples/desktop-marble-corrected.png` 与 `desktop-striped-roof-corrected.png` 为离线标注版本。
没有收录用户提交的整张桌面截图；上述游戏素材权利说明继续适用。

`tests/fixtures/desktop-green-pedestal.png` 为分数显示 456 时的游戏区域原图，用于细长底座圆台回归；
`examples/desktop-green-pedestal-corrected.png` 为离线标注结果。游戏素材权利说明同上。
Windows 后端依据 Microsoft Win32 与 Pillow 官方文档独立编写，未复制其他项目的 Windows 控制代码；接口来源见 `docs/windows.md`。

`tests/fixtures/desktop-small-white-pedestal.png` 为分数显示 666 时停止识别的游戏区域原图，
`examples/desktop-small-white-pedestal-corrected.png` 与同名 JSON 为离线识别结果。
用于小尺寸、顶面与底座分离的白色圆台回归；游戏素材权利说明同上，不包含整张桌面截图。
