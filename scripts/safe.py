# -*- coding: utf-8 -*-
"""
安全操作层（三重锁验证）—— 技能自包含版
==========================================
2026-10-04 从原先技能目录外的 gui_safe.py 收进技能目录，
并去掉对 human_input 的外部依赖，改用本技能内的 mouse / keyboard。

本模块提供 SKILL.md 里承诺的「三重锁验证」与「操作后确认」：

  三重锁（Target.verify）
    锁1 PID   ：窗口所属进程必须是预期进程
    锁2 标题  ：标题必须含预期关键词
    锁3 前台  ：窗口必须在前台，否则拒绝输入
  三条全过才允许动手。

  操作后确认（safe_click 的 expect_change）
    点击前后各取一次界面指纹，没变化就判定失败。

  坐标换算（Snapshot.to_screen）
    截图坐标 × 缩放倍率 → 屏幕绝对坐标，不靠心算。

  精确撤销（undo_exact）
    次数必须说清楚，绝不"多按几次保险"。

作者：虾哥（DSH）
"""

import sys
import time
import hashlib
import io
from dataclasses import dataclass
from typing import Optional, Tuple, Callable

try:
    import win32api
    import win32con
    import win32gui
    import win32process
except ImportError:
    raise ImportError("需要 pywin32")

try:
    from PIL import ImageGrab, Image
except ImportError:
    raise ImportError("需要 pillow")


# ══════════════════════════════════════════════════════════
# 异常
# ══════════════════════════════════════════════════════════


def focused_control_of_window(hwnd):
    """
    取某个窗口所属线程当前的焦点控件（**跨进程可用**）。

    为什么不能用 win32gui.GetFocus()：
      GetFocus 的 Win32 契约是"只能取**调用线程**消息队列里的焦点窗口"，
      对于别的进程（我们真正要操作的目标）永远返回 0。
      2026-10-04 复核当场实测确认：前台窗口属其他进程时 GetFocus() = 0。
      而 safe_type 的前提恰恰是"目标在前台"，所以用 GetFocus 必然拿不到东西 ——
      看起来做了回读，实际永远不做。

    正解：GetGUIThreadInfo(目标线程 id) 取 gui.hwndFocus，这是跨进程 API。
    """
    import ctypes
    from ctypes import wintypes

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("hwndActive", wintypes.HWND),
                    ("hwndFocus", wintypes.HWND),
                    ("hwndCapture", wintypes.HWND),
                    ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND),
                    ("hwndCaret", wintypes.HWND),
                    ("rcCaret", wintypes.RECT)]

    try:
        import win32process
        tid = win32process.GetWindowThreadProcessId(hwnd)[0]
        if not tid:
            return None
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetGUIThreadInfo.restype = wintypes.BOOL
        u.GetGUIThreadInfo.argtypes = (wintypes.DWORD, ctypes.POINTER(GUITHREADINFO))
        gti = GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(GUITHREADINFO)
        if not u.GetGUIThreadInfo(tid, ctypes.byref(gti)):
            return None
        return int(gti.hwndFocus) or None
    except Exception:
        return None


def _sibling(name):
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


class TargetMismatch(Exception):
    """目标窗口与预期不符 —— 必须停机，不许继续操作"""
    pass


class VerifyFailed(Exception):
    """操作后验证失败"""
    pass


class StaleSnapshot(Exception):
    """快照过期"""
    pass


# ══════════════════════════════════════════════════════════
# 快照：一次抓取，含坐标换算
# ══════════════════════════════════════════════════════════
@dataclass
class Snapshot:
    pid: int
    hwnd: int
    title: str
    win_rect: Tuple[int, int, int, int]     # 屏幕绝对: left, top, right, bottom
    img: object                              # PIL Image
    img_size: Tuple[int, int]
    taken_at: float
    TTL = 3.0                                # 秒；超过就视为过期

    @classmethod
    def from_pid(cls, pid: int, hwnd: Optional[int] = None) -> "Snapshot":
        if hwnd is None:
            hwnd = find_main_hwnd(pid)
        if not hwnd:
            raise TargetMismatch(f"PID {pid} 没有可见主窗口")
        if win32gui.IsIconic(hwnd):
            raise TargetMismatch(f"窗口已最小化，无法截图（hwnd={hwnd}）")

        l, t, r, b = win32gui.GetWindowRect(hwnd)
        img = ImageGrab.grab(bbox=(l, t, r, b))
        return cls(
            pid=pid, hwnd=hwnd,
            title=win32gui.GetWindowText(hwnd),
            win_rect=(l, t, r, b),
            img=img, img_size=img.size,
            taken_at=time.time(),
        )

    # ── 坐标换算（今天犯错最多的地方） ──
    def to_screen(self, x: float, y: float) -> Tuple[int, int]:
        """
        把「截图坐标」换算成「屏幕绝对坐标」。
        截图可能被缩放（如 3840 宽截成 1920），必须先还原倍率。
        """
        l, t, r, b = self.win_rect
        win_w, win_h = r - l, b - t
        img_w, img_h = self.img_size
        sx, sy = win_w / img_w, win_h / img_h      # 缩放倍率
        return int(round(l + x * sx)), int(round(t + y * sy))

    def to_window(self, screen_x: int, screen_y: int) -> Tuple[int, int]:
        """屏幕绝对坐标 → 窗口内相对坐标"""
        l, t, _, _ = self.win_rect
        return screen_x - l, screen_y - t

    def scale(self) -> Tuple[float, float]:
        l, t, r, b = self.win_rect
        return (r - l) / self.img_size[0], (b - t) / self.img_size[1]

    def assert_fresh(self, ttl: Optional[float] = None):
        ttl = ttl or self.TTL
        age = time.time() - self.taken_at
        if age > ttl:
            raise StaleSnapshot(f"快照已过期 {age:.1f}s（上限 {ttl}s），请重新抓取")

    def fingerprint(self) -> str:
        """界面指纹：用于判断操作前后是否变化"""
        small = self.img.convert("L").resize((64, 36))
        return hashlib.md5(small.tobytes()).hexdigest()

    def save(self, path: str):
        self.img.save(path)
        return path


# ══════════════════════════════════════════════════════════
# 窗口锁定（禁止标题模糊匹配）
# ══════════════════════════════════════════════════════════
def find_main_hwnd(pid: int) -> Optional[int]:
    """按 PID 找主窗口 —— 只认 PID，不认标题"""
    result = []
    def cb(h, _):
        if not win32gui.IsWindowVisible(h):
            return
        _, wpid = win32process.GetWindowThreadProcessId(h)
        if wpid == pid and win32gui.GetWindowText(h):
            result.append(h)
    win32gui.EnumWindows(cb, None)
    return result[0] if result else None


class Target:
    """目标窗口句柄 —— 一旦锁定，后续操作都基于它"""

    def __init__(self, pid: int, hwnd: Optional[int] = None):
        self.pid = pid
        self.hwnd = hwnd or find_main_hwnd(pid)
        if not self.hwnd:
            raise TargetMismatch(f"PID {pid} 无可见主窗口")

    @property
    def title(self) -> str:
        return win32gui.GetWindowText(self.hwnd)

    def verify(self, title_kw: Optional[str] = None, must_foreground: bool = True):
        """
        三重锁验证 —— 全过才允许操作。
          锁1 PID   ：窗口属于预期进程
          锁2 标题  ：标题含预期关键词（可选，但强烈建议）
          锁3 状态  ：窗口可见、非最小化、（可选）在前台
        """
        if not win32gui.IsWindow(self.hwnd):
            raise TargetMismatch("窗口句柄已失效")
        _, wpid = win32process.GetWindowThreadProcessId(self.hwnd)
        if wpid != self.pid:
            raise TargetMismatch(f"锁1失败：窗口 PID {wpid} != 预期 {self.pid}")
        if title_kw is not None:
            t = self.title
            if title_kw not in t:
                raise TargetMismatch(f"锁2失败：标题「{t}」不含「{title_kw}」")
        if not win32gui.IsWindowVisible(self.hwnd):
            raise TargetMismatch("锁3失败：窗口不可见")
        if win32gui.IsIconic(self.hwnd):
            raise TargetMismatch("锁3失败：窗口已最小化")
        if must_foreground:
            fg = win32gui.GetForegroundWindow()
            if fg != self.hwnd:
                # 尝试激活，但不强求（有些窗口不允许 SetForegroundWindow）
                try:
                    win32gui.SetForegroundWindow(self.hwnd)
                    time.sleep(0.35)
                except Exception:
                    pass
                if win32gui.GetForegroundWindow() != self.hwnd:
                    raise TargetMismatch("锁3失败：窗口不在前台，输入会打到别处")
        return True

    def activate(self):
        try:
            if win32gui.IsIconic(self.hwnd):
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(self.hwnd)
            time.sleep(0.35)
        except Exception as e:
            raise TargetMismatch(f"无法激活窗口：{e}")

    def snapshot(self) -> Snapshot:
        return Snapshot.from_pid(self.pid, self.hwnd)

    def close(self):
        win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)


# ══════════════════════════════════════════════════════════
# 带验证的操作
# ══════════════════════════════════════════════════════════
def _click_screen(x: int, y: int, button: str = "left", clicks: int = 1, human: bool = True):
    """底层的屏幕坐标点击（可选拟人化轨迹）"""
    if human:
        try:
            _sibling("mouse").move(x, y)
            time.sleep(0.08)
            _sibling("mouse").click(x, y, button=button, clicks=clicks, move_first=False)
            return
        except Exception:
            pass
    win32api.SetCursorPos((x, y))
    time.sleep(0.06)
    down = {"left": win32con.MOUSEEVENTF_LEFTDOWN, "right": win32con.MOUSEEVENTF_RIGHTDOWN,
            "middle": win32con.MOUSEEVENTF_MIDDLEDOWN}[button]
    up = {"left": win32con.MOUSEEVENTF_LEFTUP, "right": win32con.MOUSEEVENTF_RIGHTUP,
          "middle": win32con.MOUSEEVENTF_MIDDLEUP}[button]
    for i in range(clicks):
        win32api.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.07)
        win32api.mouse_event(up, 0, 0, 0, 0)
        if i < clicks - 1:
            time.sleep(0.12)


def safe_click(pid: int, x: float, y: float,
               title_kw: Optional[str] = None,
               coord_space: str = "screenshot",
               expect_change: bool = True,
               hwnd: Optional[int] = None,
               retries: int = 0) -> dict:
    """
    安全点击：验证目标 → 快照 → 换算坐标 → 点击 → 验证结果

    coord_space: 'screenshot'（截图坐标，默认） 或 'window'（窗口相对） 或 'screen'
    expect_change: True 时要求界面指纹发生变化，否则报 VerifyFailed
    """
    tgt = Target(pid, hwnd)
    tgt.verify(title_kw)
    snap = tgt.snapshot()
    before = snap.fingerprint()

    if coord_space == "screenshot":
        sx, sy = snap.to_screen(x, y)
    elif coord_space == "window":
        l, t, _, _ = snap.win_rect
        sx, sy = l + int(x), t + int(y)
    else:
        sx, sy = int(x), int(y)

    # 越界检查
    l, t, r, b = snap.win_rect
    if not (l <= sx <= r and t <= sy <= b):
        raise TargetMismatch(f"目标坐标 ({sx},{sy}) 不在窗口内 {(l,t,r,b)}")

    _click_screen(sx, sy)

    result = {"clicked_at": (sx, sy), "before": before}
    if expect_change:
        time.sleep(0.55)
        after = Target(pid, hwnd).snapshot().fingerprint()
        result["after"] = after
        result["changed"] = (before != after)
        if not result["changed"]:
            if retries > 0:
                return safe_click(pid, x, y, title_kw, coord_space, expect_change, hwnd, retries - 1)
            raise VerifyFailed(f"点击后界面无变化（坐标 {(sx,sy)} 可能没命中）")
    return result


def safe_type(pid: int, text: str,
              title_kw: Optional[str] = None,
              expect_readback: bool = True,
              hwnd: Optional[int] = None) -> dict:
    """
    安全输入：验证目标在前台 → 输入 → 读回焦点元素的值确认

    注意：本函数绝不按标题模糊匹配窗口；必须传 PID。
    """
    tgt = Target(pid, hwnd)
    tgt.verify(title_kw, must_foreground=True)   # ← 关键：不在前台就拒绝输入
    _sibling("keyboard").type_text(text)

    result = {"typed_len": len(text)}
    if expect_readback:
        # 真正的"操作后确认"：用 WM_GETTEXT 读回控件内容，看输入有没有落地。
        # 初版这里只附了一句"请用外部工具确认"——等于没做，已改正。
        time.sleep(0.35)
        readback = None
        try:
            wnd = _sibling("window")
            # 注意：这里必须用跨进程的 GetGUIThreadInfo，
            # 不能用 win32gui.GetFocus()（它只看调用线程，跨进程恒返回 0）
            ctrl = focused_control_of_window(tgt.hwnd)
            if ctrl and wnd is not None:
                readback = wnd.read_control_text(ctrl)
        except Exception:
            readback = None
        result["readback"] = readback
        result["verified"] = (readback is not None and text[:20] in str(readback))
        if readback is None:
            result["note"] = "控件不支持 WM_GETTEXT（如自绘控件），无法回读，已如实标注"
    return result


def undo_exact(n: int, pid: int, title_kw: Optional[str] = None):
    """
    精确撤销 n 次 —— 绝不"多按几次保险"。
    2026-10-03 事故：打了 53 字符却撤销 80 次，撤销进了原有内容。
    """
    if n <= 0:
        return 0
    tgt = Target(pid)
    tgt.verify(title_kw, must_foreground=True)
    for i in range(n):
        _sibling("keyboard").press("ctrl+z")
        time.sleep(0.02)
    return n


# ══════════════════════════════════════════════════════════
# 等待界面变化（替代盲目的 sleep）
# ══════════════════════════════════════════════════════════
def wait_for_change(pid: int, before_fp: str, timeout: float = 5.0,
                    poll: float = 0.25, hwnd: Optional[int] = None) -> bool:
    """轮询等待界面指纹变化，超时返回 False（不抛异常，便于调用方决定）"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            fp = Target(pid, hwnd).snapshot().fingerprint()
            if fp != before_fp:
                return True
        except Exception:
            pass
        time.sleep(poll)
    return False


# ══════════════════════════════════════════════════════════
# 自查：环境与规则确认
# ══════════════════════════════════════════════════════════
def doctor():
    """运行前自查：确认依赖与显示器信息"""
    info = {
        "screen": (win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)),
        "cursor": win32api.GetCursorPos(),
        "fg_hwnd": win32gui.GetForegroundWindow(),
        "fg_title": win32gui.GetWindowText(win32gui.GetForegroundWindow()),
        "pywin32": True,
        "pillow": True,
    }
    return info


if __name__ == "__main__":
    import json
    cmd = sys.argv[1] if len(sys.argv) > 1 else "doctor"
    if cmd == "doctor":
        print(json.dumps(doctor(), ensure_ascii=False, indent=2, default=str))
    elif cmd == "list":
        # 列出所有可见窗口（PID + 标题），供人工挑 PID
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        rows = []
        def cb(h, _):
            if win32gui.IsWindowVisible(h):
                t = win32gui.GetWindowText(h)
                if t:
                    _, p = win32process.GetWindowThreadProcessId(h)
                    rows.append({"hwnd": h, "pid": p, "title": t})
        win32gui.EnumWindows(cb, None)
        for r in rows:
            # 清掉零宽/控制字符，避免终端编码报错
            safe_title = "".join(ch if ch.isprintable() and ch != "\u200b" else " " for ch in r["title"])
            line = f"  pid={r['pid']:<7} hwnd={r['hwnd']:<10} {safe_title[:70]}"
            try:
                print(line)
            except UnicodeEncodeError:
                print(line.encode("ascii", "replace").decode("ascii"))
    else:
        print(__doc__)

