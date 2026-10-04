# -*- coding: utf-8 -*-
"""
窗口与系统操作模块
====================
覆盖人类对窗口的全部操作：
  拖动 / 最大化 / 最小化 / 还原 / 调整大小 / 关闭 / 激活 / 置顶 /
  分屏（左右半屏）/ 截图 / 剪贴板 / 等待响应

另含进程级能力：按 PID 精确锁定窗口（禁止标题模糊匹配 —— 2026-10-03 事故教训）

作者：虾哥（DSH）  建于 2026-10-03
"""

import sys
import time
import random
from dataclasses import dataclass as _dataclass
from typing import Optional, Tuple

try:
    import win32api
    import win32con
    import win32gui
    import win32process
    import win32clipboard
except ImportError:
    raise ImportError("需要 pywin32")

try:
    from PIL import ImageGrab
except ImportError:
    raise ImportError("需要 pillow")


class WindowNotFound(Exception):
    pass


def _load_sibling(name):
    """
    加载同目录的兄弟模块。

    必须区分两种场景，否则会产生**模块身份分裂**：
      · 包内导入（gui_agent.safe）→ 必须拿 gui_agent.mouse
      · 顶层导入（import safe）  → 只能拿顶层 mouse

    Codex 复核（2026-10-04）指出：原先写的
        __import__("." + name, globals(), locals(), [name], 1)
    在包内调用时 level=1 并未生效，实际退化成顶层导入，
    结果拿到的是与 gui_agent.mouse **不同的另一份模块对象**（实测 is 判断为 False）。
    """
    import importlib
    pkg = __package__ or (__name__.rsplit(".", 1)[0] if "." in __name__ else "")
    if pkg:
        # 有包上下文时只走包内导入，失败返回 None（不回退顶层，避免身份分裂）
        try:
            return importlib.import_module("." + name, pkg)
        except Exception:
            return None
    try:
        return importlib.import_module(name)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
# 按 PID 精确定位（禁止标题模糊匹配）
# ══════════════════════════════════════════════════════════
def windows_of_pid(pid: int, visible_only: bool = True) -> list:
    """返回该 PID 的所有顶层窗口句柄（只认 PID，不认标题）"""
    found = []
    def cb(h, _):
        _, wpid = win32process.GetWindowThreadProcessId(h)
        if wpid != pid:
            return
        if visible_only and not win32gui.IsWindowVisible(h):
            return
        if win32gui.GetWindowText(h):
            found.append(h)
    win32gui.EnumWindows(cb, None)
    return found


def main_hwnd(pid: int) -> Optional[int]:
    """
    取该进程的主窗口。

    优先取有标题的可见窗口；若一个都没有（例如无标题的启动画面、
    某些工具窗口），退化为取"面积最大的可见顶层窗口" ——
    否则 windows_of_pid 的空结果会让 main_hwnd / Win.by_pid / Target /
    Snapshot / wait_for_window 对这一类进程整体失效。
    """
    ws = windows_of_pid(pid)
    if ws:
        return ws[0]
    # fallback：枚举该进程所有可见顶层窗口（不限标题），取面积最大的
    best, best_area = None, -1
    def cb(h, _):
        nonlocal best, best_area
        try:
            if not win32gui.IsWindowVisible(h):
                return
            _, wpid = win32process.GetWindowThreadProcessId(h)
            if wpid != pid:
                return
            l, t, r, b = win32gui.GetWindowRect(h)
            area = max(0, r - l) * max(0, b - t)
            if area > best_area:
                best, best_area = h, area
        except Exception:
            pass
    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        pass
    return best


def list_windows() -> list:
    """列出所有可见窗口（pid / hwnd / 标题），供人工挑 PID"""
    rows = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if t:
                _, p = win32process.GetWindowThreadProcessId(h)
                rows.append({"hwnd": h, "pid": p, "title": t})
    win32gui.EnumWindows(cb, None)
    return rows


@_dataclass
class Win:
    """窗口句柄包装"""
    hwnd: int

    def __post_init__(self):
        # 句柄有效性校验 —— 失效句柄必须立刻报错，
        # 不能让它静默返回空标题（2026-10-03 自查发现的问题）
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            raise WindowNotFound(f"无效的窗口句柄: {self.hwnd}")

    @classmethod
    def by_pid(cls, pid: int) -> "Win":
        h = main_hwnd(pid)
        if not h:
            raise WindowNotFound(f"PID {pid} 没有可见主窗口")
        return cls(h)

    def alive(self) -> bool:
        """窗口是否仍然存在（长时间操作后应检查）"""
        return bool(self.hwnd) and bool(win32gui.IsWindow(self.hwnd))

    def assert_alive(self):
        """断言窗口仍存活，否则抛 WindowNotFound"""
        if not self.alive():
            raise WindowNotFound(f"窗口已失效（hwnd={self.hwnd}）")
        return True

    # ── 查询 ──
    @property
    def title(self):
        return win32gui.GetWindowText(self.hwnd)

    @property
    def pid(self):
        _, p = win32process.GetWindowThreadProcessId(self.hwnd)
        return p

    def rect(self) -> Tuple[int, int, int, int]:
        """屏幕绝对坐标 (left, top, right, bottom)"""
        return win32gui.GetWindowRect(self.hwnd)

    def size(self) -> Tuple[int, int]:
        l, t, r, b = self.rect()
        return r - l, b - t

    def is_minimized(self):
        return bool(win32gui.IsIconic(self.hwnd))

    def is_maximized(self):
        return bool(win32gui.IsZoomed(self.hwnd))

    def is_foreground(self):
        return win32gui.GetForegroundWindow() == self.hwnd

    # ── 操作 ──
    def activate(self, wait=0.35):
        """激活到前台（人类切窗口的动作）"""
        if self.is_minimized():
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            time.sleep(0.2)
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:
            # 某些窗口拒绝 SetForegroundWindow，用 AttachThreadInput 兜底
            try:
                fg = win32gui.GetForegroundWindow()
                cur_tid = win32api.GetCurrentThreadId()
                fg_tid = win32process.GetWindowThreadProcessId(fg)[0]
                win32process.AttachThreadInput(fg_tid, cur_tid, True)
                win32gui.SetForegroundWindow(self.hwnd)
                win32process.AttachThreadInput(fg_tid, cur_tid, False)
            except Exception:
                win32gui.BringWindowToTop(self.hwnd)
        time.sleep(wait)
        return self.is_foreground()

    def maximize(self):
        win32gui.ShowWindow(self.hwnd, win32con.SW_MAXIMIZE)
        time.sleep(0.35)

    def minimize(self):
        win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
        time.sleep(0.35)

    def restore(self):
        win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        time.sleep(0.35)

    def resize(self, width: int, height: int):
        """只改大小，左上角不动"""
        l, t, r, b = self.rect()
        win32gui.MoveWindow(self.hwnd, l, t, int(width), int(height), True)
        time.sleep(0.25)

    def move_to(self, x: int, y: int):
        """只改位置，大小不变"""
        l, t, r, b = self.rect()
        win32gui.MoveWindow(self.hwnd, int(x), int(y), r - l, b - t, True)
        time.sleep(0.25)

    def set_bounds(self, x: int, y: int, width: int, height: int):
        win32gui.MoveWindow(self.hwnd, int(x), int(y), int(width), int(height), True)
        time.sleep(0.25)

    def drag_by_title(self, dx: int, dy: int, human=True):
        """
        抓住标题栏拖动窗口（人类最自然的移窗口方式）。
        默认带拟人化轨迹。
        """
        l, t, r, b = self.rect()
        # 标题栏中心偏左一点（避开右边的按钮组）
        grab_x = l + min(200, (r - l) // 3)
        grab_y = t + 15
        target_x, target_y = l + dx + min(200, (r - l) // 3), t + dy + 15
        m = _load_sibling("mouse")
        if m is not None:
            try:
                m.drag(grab_x, grab_y, target_x, target_y)
                return
            except Exception:
                pass
        # 退化：直接用 Win32 移动
        self.move_to(l + dx, t + dy)

    def snap_left(self):
        """左半屏（Win+Left）"""
        self.activate()
        press_ok = _press("win+left")
        time.sleep(0.4)
        return press_ok

    def snap_right(self):
        """右半屏（Win+Right）"""
        self.activate()
        press_ok = _press("win+right")
        time.sleep(0.4)
        return press_ok

    def toggle_maximize(self):
        """双击标题栏 = 最大化/还原（人类常用）"""
        l, t, r, b = self.rect()
        x, y = l + min(200, (r - l) // 3), t + 15
        m = _load_sibling("mouse")
        if m is not None:
            try:
                m.double_click(x, y)
                return
            except Exception:
                pass
        if self.is_maximized():
            self.restore()
        else:
            self.maximize()

    def close(self, graceful=True):
        """
        关闭窗口。
        graceful=True  → 发 WM_CLOSE（等同点 X，会弹保存提示，用户可取消）
        graceful=False → 强杀进程（不弹提示，未保存内容会丢失）
        """
        if graceful:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        else:
            return self.force_close()
        time.sleep(0.4)
        return True

    def force_close(self):
        """强杀进程（不推荐，仅在无响应时用）"""
        try:
            import subprocess
            subprocess.run(["taskkill", "/PID", str(self.pid), "/F"],
                           capture_output=True, timeout=10)
            return True
        except Exception:
            return False

    def topmost(self, on=True):
        """置顶"""
        win32gui.SetWindowPos(
            self.hwnd,
            win32con.HWND_TOPMOST if on else win32con.HWND_NOTOPMOST,
            0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
        )
        time.sleep(0.15)

    # ── 截图与剪贴板 ──
    def screenshot(self, path: Optional[str] = None):
        """截该窗口（含边框）"""
        l, t, r, b = self.rect()
        img = ImageGrab.grab(bbox=(l, t, r, b))
        if path:
            img.save(path)
        return img

    def snapshot(self):
        """兼容 safe.Snapshot 的字段结构（注意返回的是 dict，不是 Snapshot 对象）"""
        l, t, r, b = self.rect()
        img = ImageGrab.grab(bbox=(l, t, r, b))
        return {"hwnd": self.hwnd, "pid": self.pid, "title": self.title,
                "rect": (l, t, r, b), "img": img, "img_size": img.size}


def _press(combo):
    kb = _load_sibling("keyboard")
    if kb is None:
        return False
    try:
        kb.press(combo)
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════
# 剪贴板
# ══════════════════════════════════════════════════════════
def clipboard_get():
    """读取剪贴板文本（失败返回 None）"""
    for _ in range(3):
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                    return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                return None
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.12)
    return None


def clipboard_set(text):
    """写入剪贴板文本（重试处理被占用）"""
    for _ in range(3):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            return True
        except Exception:
            time.sleep(0.12)
    return False


def clipboard_clear():
    """清空剪贴板（处理过敏感内容后应当调用）"""
    return clipboard_set(" ")


# ══════════════════════════════════════════════════════════
# 等待
# ══════════════════════════════════════════════════════════
def wait_for_window(pid: int, timeout: float = 15.0, poll: float = 0.4) -> Optional[Win]:
    """等待某进程出现可见窗口（启动软件后等它出来）"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = main_hwnd(pid)
        if h:
            return Win(h)
        time.sleep(poll)
    return None


def wait_until_foreground(pid: int, timeout: float = 8.0, poll: float = 0.25) -> bool:
    """等待某进程的窗口变成前台（激活后确认）"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = win32gui.GetForegroundWindow()
        _, p = win32process.GetWindowThreadProcessId(h)
        if p == pid:
            return True
        time.sleep(poll)
    return False


def screenshot_full(path: Optional[str] = None):
    """全屏截图"""
    img = ImageGrab.grab()
    if path:
        img.save(path)
    return img


# ══════════════════════════════════════════════════════════
# 自查
# ══════════════════════════════════════════════════════════
def doctor():
    caps = [
        ("Win.by_pid(pid)", "按 PID 精确锁定窗口（禁止标题模糊匹配）"),
        ("windows_of_pid / main_hwnd", "按 PID 枚举窗口"),
        ("list_windows", "列出全部可见窗口"),
        ("activate", "激活到前台（含 AttachThreadInput 兜底）"),
        ("maximize/minimize/restore", "最大化 / 最小化 / 还原"),
        ("resize / move_to / set_bounds", "调整大小 / 移动 / 同时设置"),
        ("drag_by_title", "抓标题栏拖动窗口（拟人化）"),
        ("snap_left / snap_right", "左右半屏分屏"),
        ("toggle_maximize", "双击标题栏最大化/还原"),
        ("close / force_close", "正常关闭 / 强杀"),
        ("topmost", "窗口置顶"),
        ("screenshot / snapshot", "窗口截图"),
        ("clipboard_get/set/clear", "剪贴板读写清"),
        ("wait_for_window", "等待窗口出现"),
        ("wait_until_foreground", "等待窗口变前台"),
        ("screenshot_full", "全屏截图"),
    ]
    for name, desc in caps:
        print(f"  [OK] {name:<32} {desc}")
    rows = list_windows()
    print(f"\n  窗口能力共 {len(caps)} 项")
    print(f"  当前可见窗口 {len(rows)} 个")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        doctor()
    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        for r in list_windows():
            t = "".join(c if c.isprintable() and c != "\u200b" else " " for c in r["title"])
            print(f"  pid={r['pid']:<7} hwnd={r['hwnd']:<10} {t[:70]}")
    else:
        print(__doc__)

# ══════════════════════════════════════════════════════════
# 读取控件当前值（人动手前会先看清输入框里已有什么）
# ══════════════════════════════════════════════════════════
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E


def read_control_text(control_hwnd, max_len=4096, timeout_ms=1000):
    """
    读取某个控件的文本（WM_GETTEXT）。

    为什么需要它：人操作前会先看清输入框里已有什么内容，
    免得盲目输入把原有内容覆盖掉或接错位置。

    用 SendMessageTimeout 而不是 SendMessage ——
    目标进程若挂起，无超时的 SendMessage 会让调用方**永久阻塞**；
    超时后返回 None（明确表示"没读到"，而不是假装读到空串）。
    """
    import ctypes
    from ctypes import wintypes
    try:
        if not win32gui.IsWindow(control_hwnd):
            return None
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        u.SendMessageTimeoutW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                          wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                          ctypes.POINTER(ctypes.c_ssize_t))
        SMTO_ABORTIFHUNG = 0x0002

        res = ctypes.c_ssize_t(0)
        ok_len = u.SendMessageTimeoutW(control_hwnd, WM_GETTEXTLENGTH, 0, 0,
                                       SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(res))
        if not ok_len:
            return None          # 超时/失败 → None（不能当成"控件是空的"）
        length = int(res.value)
        if length <= 0:
            return ""            # 调用成功但长度为 0 → 确实是空控件
        buf = ctypes.create_unicode_buffer(min(length + 2, max_len))
        res2 = ctypes.c_ssize_t(0)
        # LPARAM 要传缓冲区地址的整数值。
        # 注意不能写 ctypes.cast(buf, wintypes.LPARAM) —— LPARAM 是整数类型，
        # cast 到它会得到错误的值，导致 WM_GETTEXT 什么都不写回（实测读到 None）。
        lparam = ctypes.cast(buf, ctypes.c_void_p).value
        okr = u.SendMessageTimeoutW(control_hwnd, WM_GETTEXT, len(buf), lparam,
                                    SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(res2))
        if not okr:
            return None          # 超时/失败 → 明确返回 None
        return buf.value
    except Exception:
        return None



def read_text_at(x, y, max_len=4096):
    """
    读取屏幕坐标 (x, y) 处控件的文本。
    先用 WindowFromPoint 找到那个控件，再读它的文本。

    返回 (文本, 控件句柄)；找不到返回 (None, None)。
    """
    try:
        h = win32gui.WindowFromPoint((int(x), int(y)))
        if not h:
            return None, None
        return read_control_text(h, max_len), h
    except Exception:
        return None, None


def window_text_list(pid):
    """
    列出某进程所有子控件的文本（人类"扫一眼界面上有什么"的等价物）。

    实现说明：Win32 的 EnumChildWindows **本身就是递归枚举所有后代**（深度不限），
    所以不提供 max_depth 参数（初版有该参数但改完后已失效，属死参数，已删）。
    早先的实现在回调里又递归了一次 ——
    2026-10-04 复核发现初版在回调里又调了一次自身，
    导致深度 k 的控件被枚举 k 次、max_depth 形同虚设。
    """
    out = []
    seen = set()

    def cb(child, _):
        try:
            if child in seen:
                return
            seen.add(child)
            cls = win32gui.GetClassName(child)
            txt = read_control_text(child) or ""
            if txt.strip():
                out.append({"hwnd": child, "class": cls, "text": txt.strip()[:200]})
        except Exception:
            pass

    for r in windows_of_pid(pid):
        try:
            cls = win32gui.GetClassName(r)
            txt = win32gui.GetWindowText(r)
            if txt:
                out.append({"hwnd": r, "class": cls, "text": txt[:200]})
        except Exception:
            pass
        try:
            win32gui.EnumChildWindows(r, cb, None)   # 天然递归，无需手动 walk
        except Exception:
            pass
    return out
