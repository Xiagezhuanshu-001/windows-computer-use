# -*- coding: utf-8 -*-
"""
低层输入注入模块（SendInput / Unicode）
=========================================
解决的问题（2026-10-03 实测发现）：
    中文输入法活动时，用 keybd_event 发字母键会被 IME 截获 ——
    实测 "abc123" 打进去变成 "ABC23"（大小写反转 + 数字丢失）。

正确做法：
    用 SendInput + KEYEVENTF_UNICODE 直接投递 Unicode 字符，
    完全绕过键盘布局、修饰键状态、输入法状态。

同时提供：
    - 硬件扫描码输入（部分游戏/特殊控件只认扫描码）
    - 修饰键状态查询（CapsLock / NumLock / ScrollLock）
    - 修饰键强制设置

作者：虾哥（DSH）  建于 2026-10-03
"""

import sys
import time
import ctypes
from ctypes import wintypes

# ══════════════════════════════════════════════════════════
# Win32 结构定义
# ══════════════════════════════════════════════════════════
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MAPVK_VK_TO_VSC = 0


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT

# ── 补全 64 位签名声明 ──
# 不声明 restype 时 ctypes 默认按 32 位 int 截断返回值，
# 而 HWND/LPARAM 都是 64 位 —— 高位非零时会静默拿到错误句柄。
# （2026-10-04 复核发现）
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetForegroundWindow.argtypes = ()
_user32.SendMessageW.restype = ctypes.c_ssize_t
_user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.MapVirtualKeyW.restype = wintypes.UINT
_user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
_user32.GetKeyState.restype = ctypes.c_short
_user32.GetKeyState.argtypes = (ctypes.c_int,)
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = (wintypes.HWND,)



def _send(inputs):
    """把 INPUT 数组投递出去，返回成功条数"""
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = _user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent != n:
        err = ctypes.get_last_error()
        raise OSError(f"SendInput 只投递了 {sent}/{n} 条（Win32 错误 {err}）")
    return sent


# ══════════════════════════════════════════════════════════
# ① Unicode 字符输入（绕过输入法与键盘布局）★ 首选
# ══════════════════════════════════════════════════════════
def send_unicode_char(ch):
    """
    投递一个 Unicode 字符。
    不经过键盘布局、不受 CapsLock/Shift 影响、不被中文输入法截获。

    注意：KEYBDINPUT.wScan 是 16 位。基本平面（BMP, <=0xFFFF）直接投递；
    辅助平面（emoji 等 >0xFFFF）必须按 UTF-16 拆成代理对分两次投递，
    否则会被 ctypes 静默截断成错误字符（0x1F600 会变成 0xF600）。
    """
    code = ord(ch)
    if code <= 0xFFFF:
        codes = (code,)
    else:
        # UTF-16 代理对拆分
        v = code - 0x10000
        high = 0xD800 + (v >> 10)
        low = 0xDC00 + (v & 0x3FF)
        codes = (high, low)

    for c in codes:
        down = INPUT(type=INPUT_KEYBOARD)
        down.union.ki = KEYBDINPUT(wVk=0, wScan=c, dwFlags=KEYEVENTF_UNICODE,
                                   time=0, dwExtraInfo=0)
        up = INPUT(type=INPUT_KEYBOARD)
        up.union.ki = KEYBDINPUT(wVk=0, wScan=c, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                                 time=0, dwExtraInfo=0)
        _send([down, up])


def send_unicode_text(text, min_gap_ms=25, max_gap_ms=110, word_pause=True):
    """
    逐字符投递 Unicode 文本（含人类打字节奏）。
    适用于任何可编辑控件，中文英文都走这条路。

    失败时抛出的异常会带上 `typed_chars` 属性，记录**已经成功发出去几个字符** ——
    调用方据此可以只补发剩余部分，避免"前缀重复输入"。
    （2026-10-04 复核发现：原实现失败后由调用方整段重发，导致前半段重复。）
    """
    import random
    sent = 0
    for i, ch in enumerate(text):
        try:
            if ch == "\n":
                tap_vk(0x0D)       # Enter：必须 down+up
            elif ch == "\t":
                tap_vk(0x09)       # Tab：必须 down+up
            else:
                send_unicode_char(ch)
        except Exception as exc:
            exc.typed_chars = sent
            raise
        sent += 1
        time.sleep(random.uniform(min_gap_ms, max_gap_ms) / 1000.0)
        if word_pause and ch == " " and random.random() < 0.12:
            time.sleep(random.uniform(0.15, 0.45))
    return sent



# ══════════════════════════════════════════════════════════
# ② 虚拟键输入（组合键、功能键用这个）
# ══════════════════════════════════════════════════════════
def send_vk(vk, up=False, extended=False):
    """
    投递虚拟键（按下或抬起）。

    【适用范围，2026-10-04 实测】只用于**功能键与修饰键**：
      F1-F12、方向键、Home/End/PgUp/PgDn、Tab、Esc、Ctrl/Shift/Alt、Win。
    不要用它输入字符（A-Z、0-9、符号）—— 在中文输入法环境下字符翻译会被拦掉，
    实测 send_vk / send_scancode / keybd_event 三种方式发的字母键都进不去，
    而 send_unicode_char 完全正常。**字符输入请用 type_text。**
    """
    flags = 0
    if up:
        flags |= KEYEVENTF_KEYUP
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.union.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    _send([inp])


def tap_vk(vk, hold_ms=30, extended=False):
    """
    按一下某个虚拟键（down + up 成对，异常也保证抬起）。

    Codex 复核（2026-10-04）指出：send_unicode_text 里换行和 Tab 只调了
    send_vk()（只有 down），隔离验证确认目标只收到 Enter-down / Tab-down。
    所有"按一下"的语义都应该走这个函数。
    """
    send_vk(vk, extended=extended)
    try:
        time.sleep(hold_ms / 1000.0)
    finally:
        send_vk(vk, up=True, extended=extended)


def send_combo(vk_list, gap_ms=45):
    """
    投递组合键（按顺序按下、逆序抬起）。
    按下与抬起之间用 try/finally 保护 ——
    中途异常也必须把已按下的键全部抬起，否则修饰键会永久卡住。
    """
    pressed = []
    try:
        for vk in vk_list:
            send_vk(vk)
            pressed.append(vk)
            time.sleep(gap_ms / 1000.0)
    finally:
        for vk in reversed(pressed):
            try:
                send_vk(vk, up=True)
            except Exception:
                pass
            time.sleep(gap_ms / 1000.0)


# ══════════════════════════════════════════════════════════
# ③ 扫描码输入（部分游戏/特殊控件只认扫描码）
# ══════════════════════════════════════════════════════════
def send_scancode(vk, up=False):
    """用硬件扫描码投递（兼容性最好，但需要开 NumLock 等条件）"""
    scan = _user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.union.ki = KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    _send([inp])


# ══════════════════════════════════════════════════════════
# ④ 修饰键状态（诊断大小写错乱等问题）
# ══════════════════════════════════════════════════════════
VK_CAPITAL = 0x14
VK_NUMLOCK = 0x90
VK_SCROLL = 0x91


def toggle_state():
    """返回三个开关锁的状态"""
    return {
        "capslock": bool(_user32.GetKeyState(VK_CAPITAL) & 0x0001),
        "numlock": bool(_user32.GetKeyState(VK_NUMLOCK) & 0x0001),
        "scrolllock": bool(_user32.GetKeyState(VK_SCROLL) & 0x0001),
    }


def is_capslock_on():
    return toggle_state()["capslock"]


def set_capslock(on):
    """强制设置 CapsLock 状态（需要时用，改完记得还原）"""
    if is_capslock_on() != bool(on):
        send_combo([VK_CAPITAL])
        time.sleep(0.12)
    return is_capslock_on()


def ime_active_window():
    """
    查询当前前台窗口是否处于"输入法打开"状态。
    返回 True/False，查不到时返回 None（不假装知道）。

    关键修正（2026-10-04 复核发现）：
      ImmGetDefaultIMEWnd 属于 imm32.dll，**不在 user32**。
      之前调 user32 上的同名函数会 AttributeError，被 except 吞掉后永远返回 None。
    """
    try:
        _imm32 = ctypes.WinDLL("imm32", use_last_error=True)
        # imm32 侧同样要声明签名 —— 不声明时 ctypes 默认 restype=c_int，
        # 会把 64 位 HWND 截断（与 user32 那批是同一类 bug，上轮漏了 imm32）
        _imm32.ImmGetDefaultIMEWnd.restype = wintypes.HWND
        _imm32.ImmGetDefaultIMEWnd.argtypes = (wintypes.HWND,)
    except Exception:
        return None
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None
        ime_hwnd = _imm32.ImmGetDefaultIMEWnd(hwnd)
        if not ime_hwnd:
            return None
        # WM_IME_CONTROL = 0x0283, IMC_GETOPENSTATUS = 0x0005
        return bool(_user32.SendMessageW(ime_hwnd, 0x0283, 0x0005, 0))
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
# 诊断
# ══════════════════════════════════════════════════════════
def doctor():
    st = toggle_state()
    print("  输入注入能力：")
    print("    [OK] send_unicode_char / send_unicode_text   绕过输入法的字符投递")
    print("    [OK] send_vk / send_combo                     虚拟键与组合键")
    print("    [OK] send_scancode                            硬件扫描码（兼容性最好）")
    print("    [OK] toggle_state / set_capslock              开关锁状态查询与设置")
    print("    [OK] ime_active_window                        输入法活动状态")
    print()
    print(f"  CapsLock  : {'ON' if st['capslock'] else 'OFF'}")
    print(f"  NumLock   : {'ON' if st['numlock'] else 'OFF'}")
    print(f"  ScrollLock: {'ON' if st['scrolllock'] else 'OFF'}")
    print(f"  IME 活动  : {ime_active_window()}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        doctor()
    else:
        print(__doc__)
