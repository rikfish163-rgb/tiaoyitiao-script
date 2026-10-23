"""X11 capture and XTEST input. Imported only for desktop commands."""
import os
import select
import time

from PIL import ImageGrab
from Xlib import X, XK, display
from Xlib.ext import xtest

from .control import SafetyStop, guarded_press


def intersects(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class Desktop:
    def __init__(self):
        if os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland':
            raise SafetyStop('当前为 Wayland；本版仅支持完整 X11 会话，拒绝在 XWayland 上注入。')
        if not os.environ.get('DISPLAY'):
            raise SafetyStop('未设置 DISPLAY，请在当前图形桌面的终端中启动。')
        self.name = os.environ['DISPLAY']
        self.connection = display.Display(self.name)
        self.root = self.connection.screen().root
        self.escape = self.connection.keysym_to_keycode(XK.string_to_keysym('Escape'))

    def close(self):
        self.connection.close()

    def window(self, window_id):
        return self.connection.create_resource_object('window', window_id)

    def screen_bounds(self):
        screen = self.root.get_geometry()
        return (0, 0, screen.width, screen.height)

    def prop(self, window, name, kind=X.AnyPropertyType):
        result = window.get_full_property(self.connection.intern_atom(name), kind)
        return None if result is None else result.value

    def rect(self, window):
        geometry = window.get_geometry()
        pos = self.root.translate_coords(window, 0, 0)
        return (pos.x, pos.y, pos.x+geometry.width, pos.y+geometry.height)

    def identity(self, window):
        pid = self.prop(window, '_NET_WM_PID')
        return {'title': self.title(window), 'wm_class': list(window.get_wm_class() or []),
                'pid': int(pid[0]) if pid is not None and len(pid) else None}

    def title(self, window):
        text = self.prop(window, '_NET_WM_NAME')
        if isinstance(text, bytes):
            return text.decode('utf-8', errors='replace')
        return str(window.get_wm_name() or '')

    def windows(self):
        ids = self.prop(self.root, '_NET_CLIENT_LIST_STACKING')
        if ids is None:
            raise SafetyStop('窗口管理器未提供 EWMH 窗口列表。')
        result = []
        for window_id in reversed(ids):
            window = self.connection.create_resource_object('window', int(window_id))
            try:
                if window.get_attributes().map_state == X.IsViewable:
                    result.append((int(window_id), self.title(window), self.rect(window)))
            except Exception:
                continue  # A window can close while the list is being read.
        return result

    def cancelled(self):
        keys = self.connection.query_keymap()
        return bool(self.escape and keys[self.escape//8] & (1 << (self.escape % 8)))

    def select_region(self, timeout=30):
        """Consume a drag without forwarding either click to the minigame."""
        status = self.root.grab_pointer(False, X.ButtonPressMask | X.ButtonReleaseMask,
                                        X.GrabModeAsync, X.GrabModeAsync,
                                        X.NONE, X.NONE, X.CurrentTime)
        if status != X.GrabSuccess:
            raise SafetyStop('无法获取框选鼠标，可能有其他程序正在抓取。')
        start = None
        deadline = time.monotonic()+timeout
        self.connection.flush()
        try:
            while time.monotonic() < deadline:
                if self.cancelled():
                    raise SafetyStop('已按 Esc 取消框选。')
                if not self.connection.pending_events():
                    select.select([self.connection.fileno()], [], [], .05)
                    continue
                event = self.connection.next_event()
                if event.type == X.ButtonPress and event.detail == 1:
                    start = (event.root_x, event.root_y)
                elif event.type == X.ButtonRelease and event.detail == 1 and start:
                    a, b = start
                    c, d = event.root_x, event.root_y
                    return (min(a, c), min(b, d), max(a, c), max(b, d))
            raise SafetyStop('框选超时。')
        finally:
            self.connection.ungrab_pointer(X.CurrentTime)
            self.connection.sync()


class X11Backend:
    def __init__(self, desktop, config):
        self.desktop = desktop
        self.config = config
        self.window = desktop.connection.create_resource_object('window', config['window_id'])
        if desktop.identity(self.window) != config['identity']:
            raise SafetyStop('游戏窗口已重启或身份变化，请重新执行 setup。')
        self.anchor = desktop.rect(self.window)
        cx, cy, width, height = config['crop']
        left, top, right, bottom = self.anchor
        if cx < 0 or cy < 0 or width < 180 or height < 280 or cx+width > right-left or cy+height > bottom-top:
            raise SafetyStop('裁剪区域超出游戏窗口，请重新 setup。')
        self.region = (left+cx, top+cy, left+cx+width, top+cy+height)
        screen = desktop.root.get_geometry()
        if not (0 <= self.region[0] < self.region[2] <= screen.width
                and 0 <= self.region[1] < self.region[3] <= screen.height):
            raise SafetyStop('游戏区域不完整可见，请移回屏幕内。')
        # Lower right of the selected game content; must remain in that window.
        self.click = (round(left+cx+width*.85), round(top+cy+height*.85))
        self.held = False
        if not desktop.connection.has_extension('XTEST'):
            raise SafetyStop('X server 未提供 XTEST，无法发送按压。')

    def check(self):
        d = self.desktop
        if d.cancelled():
            raise SafetyStop('Esc 紧急停止。')
        pointer = d.root.query_pointer()
        if pointer.root_x <= 5 and pointer.root_y <= 5:
            raise SafetyStop('鼠标移到屏幕左上角，已停止。')
        if self.held and (abs(pointer.root_x-self.click[0]) > 6
                          or abs(pointer.root_y-self.click[1]) > 6):
            raise SafetyStop('按压时检测到鼠标移动，已停止。')
        if self.window.get_attributes().map_state != X.IsViewable:
            raise SafetyStop('游戏窗口已隐藏或最小化。')
        if d.identity(self.window) != self.config['identity'] or d.rect(self.window) != self.anchor:
            raise SafetyStop('游戏窗口身份、位置或尺寸变化，已停止。')
        active = d.prop(d.root, '_NET_ACTIVE_WINDOW')
        if active is None or not len(active) or int(active[0]) != self.config['window_id']:
            raise SafetyStop('游戏窗口失去焦点，已停止。')
        stacking = d.prop(d.root, '_NET_CLIENT_LIST_STACKING')
        if stacking is None or self.config['window_id'] not in stacking:
            raise SafetyStop('无法确认窗口遮挡关系，已停止。')
        above = list(stacking).index(self.config['window_id'])+1
        for window_id in stacking[above:]:
            other = d.connection.create_resource_object('window', int(window_id))
            if other.get_attributes().map_state == X.IsViewable and intersects(d.rect(other), self.region):
                raise SafetyStop('游戏区域被其他窗口遮挡，已停止。')

    def capture(self):
        self.check()
        image = ImageGrab.grab(bbox=self.region, xdisplay=self.desktop.name)
        self.check()
        return image

    def down(self):
        self.check()
        pointer = self.desktop.root.query_pointer()
        if pointer.mask & (X.Button1Mask | X.Button2Mask | X.Button3Mask):
            raise SafetyStop('用户正在按鼠标键，停止以避免干扰。')
        x, y = self.click
        xtest.fake_input(self.desktop.connection, X.MotionNotify, x=x, y=y)
        self.desktop.connection.sync()
        self.check()
        self.held = True
        queued_at = time.monotonic()
        xtest.fake_input(self.desktop.connection, X.ButtonPress, detail=1)
        self.desktop.connection.sync()
        return queued_at

    def up(self):
        if self.held:
            try:
                queued_at = time.monotonic()
                xtest.fake_input(self.desktop.connection, X.ButtonRelease, detail=1)
                self.desktop.connection.sync()
                return queued_at
            finally:
                self.held = False

    def press(self, duration):
        return guarded_press(self, duration)
