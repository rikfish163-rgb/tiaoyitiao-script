# 跳一跳脚本

面向 **Linux X11 / Windows 10、11 桌面微信小程序**。使用本机截图、图像识别和系统鼠标输入，不需要安卓手机或 ADB。Linux 使用 XTEST，Windows 使用 Win32 SendInput。

**0.3.0 为实验版本。** 新增 Windows 后端、安装/启动脚本及跨系统测试；修复细长底座圆台被提前过滤的问题。遮挡严重、无法验证完整顶面的平台仍会停止。
没有当前设备的校准样本时仍使用未校准公式，不保证默认精准，也没有经过受控试验的命中率数据。
完整原因、参考项目对照与剩余不足见 [准确性复盘](docs/accuracy-review.md)。

**验证边界：Linux 已有用户实际运行记录；Windows 微信小游戏尚未实机验收。** 自动测试、Windows API 检查和截图回归不代表已完成受控实机校准。第一次请先预览，再单步校准。

## 安装

### Windows 10 / 11

需要 Windows 10 1703+ 或 Windows 11、Python 3.11+（推荐 64 位 Python 3.12），并能在桌面微信中打开独立的「跳一跳」窗口。解压源码后，在项目目录打开 PowerShell：

```powershell
.\install.cmd
.\start.cmd setup --auto --preview --delay 8
.\start.cmd run --max-jumps 1 --delay 8
```

倒计时内切换到游戏窗口。自动选区使用客户区，不包含系统窗口边框；自绘的微信标题栏可能仍在其中。
无需拖动框选，不需要安装 X11、OpenCV 或 pywin32。`install.cmd` 只在本目录创建 `.venv`。
微信与脚本均使用普通用户权限。Windows 使用 DPI 感知的物理像素坐标；窗口须完整位于同一显示器内。
窗口重启、移动、缩放或跨显示器后重新 setup。不要复制 Linux 的 `config.json`、虚拟环境或校准参数到 Windows。

其余命令将 `bash start.sh` 换成 `.\start.cmd` 即可。Windows 不支持 `--pick`，可用自动选区或 `--crop`。
详细限制及 Win32 API 来源见 [Windows 使用说明](docs/windows.md)。

### Linux X11

需要 Python 3.11+，以及可正常启动小程序的 Linux 微信。以下操作只在本目录创建 `.venv`，不修改全局 Python 包：

```bash
bash install.sh
```

如果提示缺少 `venv`，Ubuntu 可用系统包管理器安装 `python3-venv` 后重试。项目不需要 Tkinter、OpenCV、管理员运行、浏览器插件或修改微信文件。

`requirements.txt` 固定了测试依赖：Pillow 13.0.0、NumPy 2.4.4；仅 Linux 安装 python-xlib 0.33、six 1.17.0。Pillow 12.2.0 的漏洞审计存在已知记录，因此启动入口要求至少 Pillow 13。

## 首次使用

1. 在微信中打开跳一跳，点击开始游戏，使棋子和下一跳台完整可见。
2. 确保游戏窗口完整位于屏幕内，然后在项目目录运行以下命令，自动选择唯一的「跳一跳」独立窗口、保存区域并生成预览：

   ```bash
   bash start.sh setup --auto --preview --delay 8
   ```

   如果打开了多个同名窗口，去掉 `--auto` 手动选择。列表会标记游戏窗口；只有一个游戏窗口时回车即可选择它。**应选「跳一跳」，不要选「微信」主窗口。序号随窗口排列变化。**

3. 在 8 秒倒计时内把游戏切到前台，然后等待截图。**无需拖鼠标、框选或输入窗口序号。** 默认直接使用窗口客户区；如果有不超过 8px 的边框超出屏幕，会裁到可见边缘。更大范围越界仍会停止，要求先移动窗口。
4. 终端显示「配置已保存」及「预览完成」后，打开 `runs/latest.png`。以后要再次预览，可以单独运行：

   ```bash
   bash start.sh preview
   ```

   预览只截图和分析，**不会按鼠标**。红点应位于棋子底座中心，绿点应位于下一跳台顶面中心，黄框是目标物体范围。JSON 中 `method=white_marker` 表示采用白色中心点，`platform_geometry` 表示根据平台外形估计。若截图成功但识别失败，`runs/latest-capture.png` 仍保留未标注的游戏区域，便于诊断。

5. 标注正确后试跳一次：

   ```bash
   bash start.sh run
   ```

   默认只发送 **1 次**按压，5 秒倒计时内把游戏置前。日志表示已发送的按压，不代表已确认落地或得分。

6. 按压距离合适后，有限次连续运行：

   ```bash
   bash start.sh run --max-jumps 20
   ```

窗口在倒计时和运行期间应保持原位置、尺寸，且不要被终端或其他窗口遮挡。只要移动了窗口或程序停止，就应核对状态再重新启动。微信/小程序重启后请重新 `setup --auto --preview`，窗口身份信息会失效。

### 设置失败怎么办

- 提示「无法获取框选鼠标」或尺寸 `0×0`：使用上面的 `setup --auto --preview --delay 8`，直接读取窗口区域，避免使用鼠标框选。
- 提示「微信主窗口」或选到 QQ 等其他窗口：重新运行 `bash start.sh setup --auto --preview`，使用独立的「跳一跳」窗口。
- 提示「框选区域不在所选窗口内」：核对选择的窗口标题；不能选择微信主窗口后再去框选另一个独立游戏窗口。
- 提示尺寸太小：通常是只单击了一次，或切换窗口的点击被当作选区。倒计时结束后再按住左键拖动，松开时结束。
- 提示区域不完整可见：把游戏窗口向屏幕中央移动，使四边均完整可见，再重新设置。
- 没有显示「配置已保存」：本次设置没有成功，不会生成 `config.json`；先完成设置，再运行 `preview`。
- 提示「游戏窗口失去焦点」：使用 `bash start.sh run --max-jumps 1 --delay 8`，在倒计时内用 Alt+Tab 切换到「跳一跳」独立窗口；运行期间保持前台。失焦停止不表示游戏结束，也不需要重做框选。

## 校准

默认系数是 `1.0`，不能保证适合每个微信版本或缩放比例。

### 根据实测样本拟合

0.2.0 新增 `calibrate` 命令，参考水平距离归一化及样本拟合思路。
准备一个 JSON 数组，每条样本包含以下字段：

| 字段 | 类型与含义 |
|---|---|
| `actual_dx` | 正数，本次跳跃的**实际水平位移**，单位为原图像素 |
| `width` | 采样时游戏画面宽度，180–2400px |
| `press_ms` | 本次客户端记录的按压时间，60–1500ms |
| `confirmed` | 必须为 `true`，表示已核对这条实测数据 |

至少 3 条样本、3 个不同距离，距离跨度至少达到画面宽度的 15%。不要把跳过头或未到达时的
**目标距离**写成实际位移，也不能直接相减相机移动前后的屏幕坐标。
当前未实现可靠的相机运动补偿和自动成功判定，因此没有自动在线学习。

```bash
bash start.sh calibrate measured-samples.json
```

这会生成本地 `calibration.json`。之后 `run`、`preview` 和 `analyze` 自动加载该文件，
使用 `press_ms = slope × (水平位移 / 画面宽度) + intercept`，不再依赖头部尺寸估计时长。
预测明显超出样本范围或拟合误差过大时会拒绝使用。
如需指定其他模型文件，`--calibration 路径` 放在子命令之前。

校准文件和实测样本默认不会提交到 GitHub。回归测试中的模拟数据只用于验证拟合计算，不能作为本机参数。

### 临时调整系数

```bash
# 跳近了：小幅增加按压系数，再单步试跳
bash start.sh run --coefficient 1.05

# 跳远了：小幅降低按压系数
bash start.sh run --coefficient 0.95

# 识别的头部直径受光影影响时，手动指定直径（选区原始像素）
bash start.sh run --head-diameter 20 --coefficient 1.0
```

`--coefficient` 和 `--head-diameter` 是本次覆盖值。稳定后可在本目录 `config.json` 保存对应字段，或重新运行 `setup --auto --coefficient 1.05`。

若标注位置本身错误，应先调整选区；增加按压系数无法修复定位错误。连续运行不含自动重开、复活或点击菜单，也没有排行榜接口和反检测逻辑。

## 停止与保护

- 运行中按住 **Esc**，或把鼠标移到整个 X11 屏幕左上角 `(0,0)` 附近。
- 回到终端按 `Ctrl+C`，或通过正常 `SIGTERM` 终止，也会尝试释放脚本按下的左键。
- 默认每次只跳一次，连续次数须显式指定，最大 1000。
- 窗口失焦、移动、变形、最小化、身份变化，或被 EWMH 窗口列表中更高层的窗口遮挡时停止。
- 棋子/跳台缺失或歧义时不按压；连续画面和检测结果稳定后才起跳。
- 上一次按压后画面没有足够变化时，停止重复按压；单次等待起跳条件默认超时 10 秒。
- 单次按压须在 60–1500ms 内；从按下事件提交时间计算截止时刻，避免额外加上 X server 同步等待。
  按压期间约每 10ms 检查停止条件，并用 `finally` 尝试释放左键。客户端计时仍不等于游戏引擎的精确接收时刻。

这些检查不能覆盖 X server 崩溃、`SIGKILL`、系统冻结，或未出现在窗口管理器列表中的所有覆盖层。运行时不要操作其他应用。脚本没有请求额外系统权限；只使用当前 X11 会话已有的访问能力。

## 其他命令

```bash
# 依赖和会话信息，不连接桌面
bash start.sh doctor

# 仅列出可见窗口，不发送输入
bash start.sh windows

# 指定窗口 ID 和相对客户区裁剪 x,y,width,height
bash start.sh setup --window 0x123456 --crop 0,32,360,640

# 仅在默认窗口区域确实不合适时，尝试可选的手动框选
bash start.sh setup --auto --pick

# 图片离线识别，不连接桌面
bash start.sh analyze tests/fixtures/reference-game.png --output runs/reference.png

# 自动测试，不连接桌面、截图或点击
.venv/bin/python -m unittest discover -s tests -v
```

自定义配置路径须放在子命令之前，例如 `bash start.sh --config custom.json preview`。可通过子命令的 `--delay 10` 延长切换窗口的倒计时。

## 支持范围与限制

- `method=platform_edges` 表示经过两条上边缘斜率、转角、对称性和内部前景检查的菱形顶面估计；只适用于通过这些检查的形状，不是任意平台的通用识别。

- Linux 仅支持完整 X11 会话。Wayland/XWayland 会明确拒绝启动。Windows 10 1703+/11 使用独立 Win32 后端，无需 DISPLAY；macOS 不支持。
- 裁剪区域必须是竖屏游戏内容，宽 180–2400px，高 280–4000px，纵横比约 1.05–2.6。
- 使用颜色、连通域、背景差分、白点和平台外形估计，不是通用视觉模型。主题变化、特殊平台、遮挡、强抗锯齿和游戏规则变化均可能需要后续适配。
- 连续模式判断画面已变化并稳定，没有 OCR 确认分数，也没有证明每次跳跃成功。
- 每次 `run` 在 `runs/UTC时间戳/` 中保存每跳的原始起跳图、计划 JSON、等待落地后的原图与客户端时长。
  即使只运行 1 跳也会保存跳后画面；识别失败时保存 `rejected.png` 和拒绝原因。记录不自动等于成功判定。
- 截图只保存所选游戏区域。程序运行不联网、不上传截图，也不读取微信聊天数据。
- 安装脚本需要访问 PyPI。项目源码未依赖 Windows 控制模块、ADB、OpenCV 或 Tkinter。

## 文件

- `wechat_jump/vision.py`：独立图像识别、标注和距离换算。
- `wechat_jump/control.py`：稳定性检查、有限次循环、释放鼠标的逻辑。
- `wechat_jump/calibration.py`：实测样本拟合与校准模型验证。
- `wechat_jump/x11.py`：X11 窗口、框选、截图和 XTEST 输入。
- `wechat_jump/windows.py`：Win32 窗口、DPI、截图、SendInput 和输入保护。
- `install.cmd`、`start.cmd`：Windows 安装与运行入口。
- `wechat_jump/cli.py`：配置验证和命令行入口。
- `tests/`：合成画面、真实截图和模拟桌面状态测试。
- `examples/reference-annotated.png`：原开源演示截图的识别示例，**不是当前用户游戏截图**。
- `VALIDATION.md`：实际测试记录和未验证项。
- `audit/dependency-audit.json`：固定依赖的 OSV 查询结果。

## 来源

实现参考了 [wangshub/wechat_jump_game](https://github.com/wangshub/wechat_jump_game) 的颜色定位及非线性距离/时长模型，以及 [da-p3/wechat-jump-pc](https://github.com/da-p3/wechat-jump-pc) 的桌面窗口工作流。Linux 控制、检测实现和运行保护为本项目重新编写，没有复制 Windows 控制代码。

来源、测试图和许可说明见 `NOTICES.md`。
