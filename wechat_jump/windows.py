"""Windows 10 (1703+)/11 client-area capture and guarded SendInput backend.

Only Win32API loads system DLLs. Importing this module is safe on Linux and
the guard layer can be tested with an injected API without moving the mouse.
"""
import ctypes as C
import sys
import time

from PIL import ImageGrab

from .control import SafetyStop, guarded_press


# Explicit Windows widths: C long is 64-bit on Linux but 32-bit on Windows.
LONG, DWORD, WORD, HANDLE = C.c_int32, C.c_uint32, C.c_uint16, C.c_void_p


class POINT(C.Structure):
    _fields_ = [('x', LONG), ('y', LONG)]


class RECT(C.Structure):
    _fields_ = [('left', LONG), ('top', LONG), ('right', LONG), ('bottom', LONG)]


class MONITORINFO(C.Structure):
    _fields_ = [('cbSize', DWORD), ('rcMonitor', RECT), ('rcWork', RECT), ('dwFlags', DWORD)]


class MOUSEINPUT(C.Structure):
    _fields_ = [('dx', LONG), ('dy', LONG), ('mouseData', DWORD),
                ('dwFlags', DWORD), ('time', DWORD), ('dwExtraInfo', C.c_size_t)]


class KEYBDINPUT(C.Structure):
    _fields_ = [('wVk', WORD), ('wScan', WORD), ('dwFlags', DWORD),
                ('time', DWORD), ('dwExtraInfo', C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [('uMsg', DWORD), ('wParamL', WORD), ('wParamH', WORD)]


class INPUTDATA(C.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', DWORD), ('data', INPUTDATA)]


def _rect_tuple(rect):
    return rect.left, rect.top, rect.right, rect.bottom


class Win32API:
    def __init__(self):
        if sys.platform != 'win32':
            raise SafetyStop('Win32 后端只能在 Windows 10/11 上运行。')
        if sys.getwindowsversion().build < 15063:
            raise SafetyStop('需要 Windows 10 1703 或更新版本（含 Windows 11）。')
        self.user32 = C.WinDLL('user32', use_last_error=True)
        self.dwm = C.WinDLL('dwmapi', use_last_error=True)
        self.enum_proc = C.WINFUNCTYPE(C.c_int, HANDLE, C.c_ssize_t)
        signatures = {
            'SetProcessDpiAwarenessContext': ([HANDLE], C.c_int),
            'GetThreadDpiAwarenessContext': ([], HANDLE),
            'GetAwarenessFromDpiAwarenessContext': ([HANDLE], C.c_int),
            'EnumWindows': ([self.enum_proc, C.c_ssize_t], C.c_int),
            'IsWindow': ([HANDLE], C.c_int),
            'IsWindowVisible': ([HANDLE], C.c_int),
            'IsIconic': ([HANDLE], C.c_int),
            'GetClientRect': ([HANDLE, C.POINTER(RECT)], C.c_int),
            'GetWindowRect': ([HANDLE, C.POINTER(RECT)], C.c_int),
            'ClientToScreen': ([HANDLE, C.POINTER(POINT)], C.c_int),
            'GetWindowTextLengthW': ([HANDLE], C.c_int),
            'GetWindowTextW': ([HANDLE, C.c_wchar_p, C.c_int], C.c_int),
            'GetClassNameW': ([HANDLE, C.c_wchar_p, C.c_int], C.c_int),
            'GetWindowThreadProcessId': ([HANDLE, C.POINTER(DWORD)], DWORD),
            'GetForegroundWindow': ([], HANDLE),
            'GetWindow': ([HANDLE, C.c_uint], HANDLE),
            'GetCursorPos': ([C.POINTER(POINT)], C.c_int),
            'SetCursorPos': ([C.c_int, C.c_int], C.c_int),
            'GetAsyncKeyState': ([C.c_int], C.c_int16),
            'GetSystemMetrics': ([C.c_int], C.c_int),
            'MonitorFromRect': ([C.POINTER(RECT), DWORD], HANDLE),
            'GetMonitorInfoW': ([HANDLE, C.POINTER(MONITORINFO)], C.c_int),
            'SendInput': ([C.c_uint, C.POINTER(INPUT), C.c_int], C.c_uint),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.user32, name)
            fn.argtypes, fn.restype = args, result
        self.dwm.DwmGetWindowAttribute.argtypes = [HANDLE, DWORD, C.c_void_p, DWORD]
        self.dwm.DwmGetWindowAttribute.restype = LONG
        # Before any coordinate-dependent API or screenshot. An existing
        # manifest may have set awareness; verify the effective context too.
        self.user32.SetProcessDpiAwarenessContext(HANDLE(-4))
        context = self.user32.GetThreadDpiAwarenessContext()
        if self.user32.GetAwarenessFromDpiAwarenessContext(context) != 2:
            raise SafetyStop('无法启用每显示器 DPI 感知，停止以避免缩放坐标偏移。')

    @staticmethod
    def require(ok, operation):
        if not ok:
            raise SafetyStop(f'{operation} 失败（Win32 错误 {C.get_last_error()}）。')

    def window_ids(self):
        ids = []
        callback = self.enum_proc(lambda hwnd, _param: (ids.append(int(hwnd)), 1)[1])
        self.require(self.user32.EnumWindows(callback, 0), 'EnumWindows')
        return ids

    def visible(self, hwnd):
        if not (self.user32.IsWindow(hwnd) and self.user32.IsWindowVisible(hwnd)) or self.user32.IsIconic(hwnd):
            return False
        cloaked = DWORD()
        result = self.dwm.DwmGetWindowAttribute(hwnd, 14, C.byref(cloaked), C.sizeof(cloaked))
        self.require(result == 0, '读取窗口可见性')
        return not cloaked.value

    def client_rect(self, hwnd):
        rect, origin = RECT(), POINT()
        self.require(self.user32.GetClientRect(hwnd, C.byref(rect)), 'GetClientRect')
        self.require(self.user32.ClientToScreen(hwnd, C.byref(origin)), 'ClientToScreen')
        return origin.x, origin.y, origin.x+rect.right, origin.y+rect.bottom

    def window_rect(self, hwnd):
        rect = RECT()
        self.require(self.user32.GetWindowRect(hwnd, C.byref(rect)), 'GetWindowRect')
        return _rect_tuple(rect)

    def identity(self, hwnd):
        self.require(self.user32.IsWindow(hwnd), '窗口身份检查')
        title = C.create_unicode_buffer(self.user32.GetWindowTextLengthW(hwnd)+1)
        self.user32.GetWindowTextW(hwnd, title, len(title))
        name, pid = C.create_unicode_buffer(256), DWORD()
        self.require(self.user32.GetClassNameW(hwnd, name, len(name)), 'GetClassNameW')
        self.require(self.user32.GetWindowThreadProcessId(hwnd, C.byref(pid)), 'GetWindowThreadProcessId')
        return {'title': title.value, 'pid': pid.value, 'wm_class': ['win32:'+name.value]}

    def screen_bounds(self):
        x, y, w, h = [self.user32.GetSystemMetrics(i) for i in (76, 77, 78, 79)]
        return x, y, x+w, y+h

    def region_visible(self, region):
        rect = RECT(*region)
        monitor = self.user32.MonitorFromRect(C.byref(rect), 0)
        if not monitor:
            return False
        info = MONITORINFO()
        info.cbSize = C.sizeof(info)
        self.require(self.user32.GetMonitorInfoW(monitor, C.byref(info)), 'GetMonitorInfoW')
        a, b, c, d = _rect_tuple(info.rcMonitor)
        l, t, r, bot = region
        return a <= l < r <= c and b <= t < bot <= d

    def foreground(self):
        return self.user32.GetForegroundWindow()

    def above(self, hwnd):
        result, seen = [], {hwnd}
        while True:
            hwnd = self.user32.GetWindow(hwnd, 3)  # GW_HWNDPREV: previous in Z order.
            if not hwnd:
                return result
            if hwnd in seen or len(result) >= 10000:
                raise SafetyStop('窗口层级变化，无法确认遮挡关系。')
            seen.add(hwnd)
            result.append(hwnd)

    def pointer(self):
        point = POINT()
        self.require(self.user32.GetCursorPos(C.byref(point)), 'GetCursorPos')
        return point.x, point.y

    def key_down(self, virtual_key):
        return bool(self.user32.GetAsyncKeyState(virtual_key) & 0x8000)

    def move_pointer(self, xy):
        self.require(self.user32.SetCursorPos(*xy), 'SetCursorPos')

    def send_button(self, down):
        event = INPUT()
        event.type = 0  # INPUT_MOUSE
        event.mi.dwFlags = 0x0002 if down else 0x0004
        if self.user32.SendInput(1, C.byref(event), C.sizeof(INPUT)) != 1:
            raise SafetyStop('SendInput 未成功发送。请确认微信和脚本均以普通用户运行，'
                             '且桌面未锁定；脚本不会自动提权。')


class Desktop:
    def __init__(self, api=None):
        self.api = Win32API() if api is None else api

    def close(self):
        pass

    def window(self, window_id):
        return window_id

    def rect(self, window):
        return self.api.client_rect(window)

    def identity(self, window):
        return self.api.identity(window)

    def screen_bounds(self):
        return self.api.screen_bounds()

    def windows(self):
        result = []
        for hwnd in self.api.window_ids():
            try:
                if self.api.visible(hwnd):
                    result.append((hwnd, self.identity(hwnd)['title'], self.rect(hwnd)))
            except SafetyStop:
                continue  # A window may disappear during enumeration.
        return result

    def select_region(self):
        raise SafetyStop('Windows 请使用 setup --auto --preview 自动选区，或 --crop x,y,width,height；不支持 --pick。')


class WindowsBackend:
    def __init__(self, desktop, config):
        self.desktop, self.api, self.config = desktop, desktop.api, config
        self.window = config['window_id']
        self.held = False
        if desktop.identity(self.window) != config['identity']:
            raise SafetyStop('窗口身份变化或配置来自其他系统，请重新 setup。')
        self.anchor = desktop.rect(self.window)
        l, t, r, b = self.anchor
        x, y, w, h = config['crop']
        if x < 0 or y < 0 or w < 180 or h < 280 or x+w > r-l or y+h > b-t:
            raise SafetyStop('裁剪区域超出游戏窗口，请重新 setup。')
        self.region = l+x, t+y, l+x+w, t+y+h
        if not self.api.region_visible(self.region):
            raise SafetyStop('游戏区域须完整位于同一显示器内，请移动后重新 setup。')
        self.click = round(l+x+.85*w), round(t+y+.85*h)

    def check(self):
        api = self.api
        if api.key_down(0x1b):
            raise SafetyStop('Esc 紧急停止。')
        pointer = api.pointer()
        sl, st, _, _ = api.screen_bounds()
        if (abs(pointer[0]) <= 5 and abs(pointer[1]) <= 5) or (
                sl <= pointer[0] <= sl+5 and st <= pointer[1] <= st+5):
            raise SafetyStop('鼠标移到屏幕左上角，已停止。')
        if self.held and max(abs(a-b) for a, b in zip(pointer, self.click)) > 6:
            raise SafetyStop('按压时检测到鼠标移动，已停止。')
        if not api.visible(self.window):
            raise SafetyStop('游戏窗口已隐藏、关闭或最小化。')
        if self.desktop.identity(self.window) != self.config['identity'] or self.desktop.rect(self.window) != self.anchor:
            raise SafetyStop('游戏窗口身份、位置或尺寸变化，已停止。')
        if not api.region_visible(self.region):
            raise SafetyStop('游戏区域不完整可见，已停止。')
        if api.foreground() != self.window:
            raise SafetyStop('游戏窗口失去焦点，已停止。')
        for hwnd in api.above(self.window):
            if api.visible(hwnd):
                a, b, c, d = api.window_rect(hwnd)
                l, t, r, bot = self.region
                if a < r and l < c and b < bot and t < d:
                    raise SafetyStop('游戏区域被其他窗口遮挡，已停止。')

    def capture(self):
        self.check()
        image = ImageGrab.grab(bbox=self.region, all_screens=True, include_layered_windows=True)
        self.check()
        if image.size != (self.region[2]-self.region[0], self.region[3]-self.region[1]):
            raise SafetyStop('截图尺寸与物理坐标不一致，请检查 DPI 设置。')
        return image

    def down(self):
        self.check()
        if any(self.api.key_down(k) for k in (1, 2, 4)):
            raise SafetyStop('用户正在按鼠标键，停止以避免干扰。')
        self.api.move_pointer(self.click)
        self.check()
        if max(abs(a-b) for a, b in zip(self.api.pointer(), self.click)) > 2:
            raise SafetyStop('鼠标未到达目标窗口内的按压位置。')
        self.held = True  # Cleanup also covers a partial/failed send.
        queued = time.monotonic()
        self.api.send_button(True)
        return queued

    def up(self):
        if self.held:
            queued = time.monotonic()
            self.api.send_button(False)
            self.held = False  # Keep True on failure so outer cleanup can retry.
            return queued

    def press(self, duration):
        return guarded_press(self, duration)
