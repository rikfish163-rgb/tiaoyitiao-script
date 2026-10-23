# Windows 10 / 11 使用说明

版本 0.3.0 增加 Windows 10 1703+ / Windows 11 后端。该支持已实现，Windows 微信小游戏实机效果仍待验收；Linux 的实测成绩不能作为 Windows 成绩。

## 安装与首次运行

安装 Python 3.11+（建议 64 位 Python 3.12），关闭并重开终端。将项目解压到可写目录，在该目录的 PowerShell 中执行：

```powershell
.\install.cmd
.\start.cmd windows
.\start.cmd setup --auto --preview --delay 8
```

倒计时内切到独立的「跳一跳」窗口。检查 `runs/latest.png` 的目标点，然后单步：

```powershell
.\start.cmd run --max-jumps 1 --delay 8
```

正常落地后再增加有限次数。命令提示符中也可运行 `install.cmd`、`start.cmd`。不需要修改 PowerShell 执行策略；这两个文件是批处理脚本。

## 系统与输入边界

- 使用 Win32 枚举顶层窗口，按标题、窗口类和 PID 记录身份；截图/按压前检查身份、客户区位置及尺寸。
- 客户区坐标转换为屏幕物理像素。初始化时启用并验证每显示器 DPI 感知；失败时拒绝运行。
- 支持副屏负坐标，但游戏区域必须完整位于同一显示器内；跨屏或缩放后需重新 setup。
- 截图使用 Pillow 的屏幕捕获，包含分层窗口。游戏须保持在前台且无遮挡；不做后台点击。
- 前台窗口变化、遮挡、Esc、按压中移动鼠标或窗口、截图尺寸不符时停止。
- 鼠标可移到主屏坐标 `(0,0)` 或虚拟桌面的左上角停止。终端 `Ctrl+C` 也会清理脚本持有的鼠标键。
- 用 SendInput 发送按下/松开，检查发送数量；失败或中断后尝试释放。锁屏、UAC 安全桌面、系统冻结等情况不保证释放成功。
- 微信和脚本都以普通用户运行。SendInput 受 Windows UIPI 限制，不能向更高完整性级别的程序注入；脚本不会自动提权或关闭系统保护。
- Windows 不提供 Linux 的拖动框选功能；默认自动使用客户区，必要时用 `--crop x,y,width,height`。
- 跨系统请重新安装并 setup，重新校准。配置中的窗口编号、PID、缩放及本机按压参数不能移植。

## 验证范围

自动测试覆盖后端分派、Windows INPUT 结构布局、输入数据包、DPI 初始化的原生 API 检查、窗口状态模拟、负坐标选区、发送失败后的释放、安装和命令行入口。原生 API 检查只在 Windows 执行，不点击桌面。

GitHub Actions 的 `windows-2022` 是 Windows Server 2022 CI，不是 Windows 10/11 微信实机。CI 成功只能证明对应安装和测试通过。

## 官方接口依据

- [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)：发送数量返回值、输入结构大小和 UIPI 限制。
- [INPUT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-input)：含鼠标、键盘和硬件输入的联合体。
- [DPI awareness](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setprocessdpiawarenesscontext)：在坐标相关 API 前设置 DPI 模式。
- [GetClientRect](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getclientrect)、[ClientToScreen](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-clienttoscreen)：客户区及屏幕坐标。
- [Pillow ImageGrab](https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html)：多显示器、负坐标及分层窗口截图参数。
