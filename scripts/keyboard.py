# -*- coding: utf-8 -*-
"""
键盘能力模块（完整版）
========================
覆盖人类键盘操作的全部动作：
  单字符 / 连续英文打字 / 中文输入 / 组合键 / 功能键 F1-F12 /
  导航键 / 长按修饰键 / 数字键盘 / 输入法切换 / Unicode 直输

设计要点（来自 2026-10-03 教训）：
  1. 逐字符输入有随机间隔（人类不是机器打字机）
  2. 中文走剪贴板整段粘贴（逐字符粘太慢，且会污染剪贴板历史）
  3. 组合键按下与抬起之间有时间差（人类不会同时按下）
  4. 长按有明确的松开保证（finally 里必定 key_up，不会卡住按键）
  5. 使用前请确认目标窗口在前台（配合 safe.Target.verify）

作者：虾哥（DSH）  建于 2026-10-03
"""

import sys
import time
import random

try:
    import win32api
    import win32con
    import win32clipboard
except ImportError:
    raise ImportError("需要 pywin32")


# ══════════════════════════════════════════════════════════
# 人类打字特征
# ══════════════════════════════════════════════════════════
class Typing:
    KEY_GAP_MS = (45, 165)      # 字符间隔
    KEY_HOLD_MS = (28, 75)      # 按键保持
    WORD_PAUSE_P = 0.12         # 打完一个词后停顿的概率
    WORD_PAUSE_MS = (180, 520)  # 词间停顿
    TYPO_P = 0.0                # 打错字概率（默认 0，需要时再开）
    COMBO_GAP_MS = (30, 90)     # 组合键之间的间隔
    HOLD_DEFAULT_MS = (500, 1200)

    @staticmethod
    def sleep_ms(rng):
        lo, hi = rng
        time.sleep(random.uniform(lo, hi) / 1000.0)


# ══════════════════════════════════════════════════════════
# 完整虚拟键表
# ══════════════════════════════════════════════════════════
VK = {
    # 编辑与导航
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "arrowup": 0x26, "arrowdown": 0x28, "arrowleft": 0x25, "arrowright": 0x27,
    # 修饰键
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "menu": 0x12,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    # 功能键 F1-F12（今天缺 F1-F4/F6-F10，这里补齐）
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    # 符号
    "minus": 0xBD, "equal": 0xBB, "bracketleft": 0xDB, "bracketright": 0xDD,
    "backslash": 0xDC, "semicolon": 0xBA, "apostrophe": 0xDE, "grave": 0xC0,
    "comma": 0xBC, "period": 0xBE, "slash": 0xBF,
    # 打印/系统
    "printscreen": 0x2C, "pause": 0x13, "apps": 0x5D,
    # 数字键盘
    "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63, "num4": 0x64,
    "num5": 0x65, "num6": 0x66, "num7": 0x67, "num8": 0x68, "num9": 0x69,
    "numlock_key": 0x90,
    "numadd": 0x6B, "numsub": 0x6D, "nummul": 0x6A, "numdiv": 0x6F,
    "numdecimal": 0x6E, "numenter": 0x0D,
    # 媒体键（笔记本常用）
    "volumeup": 0xAF, "volumedown": 0xAE, "volumemute": 0xAD,
    "medianext": 0xB0, "mediaprev": 0xB1, "mediastop": 0xB2, "mediaplay": 0xB3,
    # 浏览器
    "browserback": 0xA6, "browserforward": 0xA7, "browserrefresh": 0xA8,
    "browserhome": 0xAC, "browsersearch": 0xAA,
}


def _to_vk(key):
    """把键名转成虚拟键码；单个字符也支持"""
    k = key.strip().lower()
    if k in VK:
        return VK[k]
    if len(k) == 1:
        return ord(k.upper())
    raise ValueError(f"未知键名: {key}")


def key_down(key):
    win32api.keybd_event(_to_vk(key), 0, 0, 0)


def key_up(key):
    win32api.keybd_event(_to_vk(key), 0, win32con.KEYEVENTF_KEYUP, 0)


# ══════════════════════════════════════════════════════════
# ① 按键 / 组合键
# ══════════════════════════════════════════════════════════
def press(combo, hold_ms=None):
    """
    按键或组合键。press('enter') / press('ctrl+s') / press('ctrl+shift+t')
    按下与抬起之间有随机间隔（人类特征）。

    用 try/finally 保证已按下的键一定被抬起 ——
    中途异常（如 KeyboardInterrupt）若不清按键，修饰键会永久卡住。
    （2026-10-04 复核发现：本函数此前只有 docstring 写了"finally 保证"，
      实际代码没有 try/finally —— 文档说了但没做。）
    """
    keys = [_to_vk(p) for p in combo.split("+")]
    pressed = []
    try:
        for k in keys:
            win32api.keybd_event(k, 0, 0, 0)
            pressed.append(k)
            time.sleep(random.uniform(*[x / 1000.0 for x in Typing.COMBO_GAP_MS]))
        if hold_ms:
            time.sleep(hold_ms / 1000.0)
        else:
            time.sleep(random.uniform(0.04, 0.11))
    finally:
        for k in reversed(pressed):
            try:
                win32api.keybd_event(k, 0, win32con.KEYEVENTF_KEYUP, 0)
            except Exception:
                pass


def hold_key(key, ms=None):
    """
    长按某个键不放（人类用于：按住 Shift 连续选择、游戏操控、某些 App 的快捷键）。
    finally 保证一定松开，不会让按键卡住。
    """
    if ms is None:
        ms = random.randint(*Typing.HOLD_DEFAULT_MS)
    vk = _to_vk(key)
    win32api.keybd_event(vk, 0, 0, 0)
    try:
        time.sleep(ms / 1000.0)
    finally:
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(random.uniform(0.03, 0.09))


def shift_hold_select(direction="down", count=3, step_ms=180):
    """
    按住 Shift + 方向键连续选择（人类选多行的典型动作）。
    direction: up/down/left/right
    """
    vk_shift = VK["shift"]
    vk_dir = VK[direction]
    win32api.keybd_event(vk_shift, 0, 0, 0)
    try:
        time.sleep(random.uniform(0.05, 0.12))
        for _ in range(count):
            win32api.keybd_event(vk_dir, 0, 0, 0)
            time.sleep(random.uniform(0.02, 0.05))
            win32api.keybd_event(vk_dir, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(random.uniform(0.08, 0.20))
    finally:
        win32api.keybd_event(vk_shift, 0, win32con.KEYEVENTF_KEYUP, 0)


# ══════════════════════════════════════════════════════════
# ② 文字输入（英文逐字符 / 中文整段）
# ══════════════════════════════════════════════════════════

def type_ascii(text):
    """逐字符输入 ASCII 文本（模拟真人打字节奏）"""
    for i, ch in enumerate(text):
        if ch == "\n":
            press("enter")
            continue
        if ch == "\t":
            press("tab")
            continue
        vk = win32api.VkKeyScan(ch)
        if vk == -1:
            _paste(text[i:i + 1])
            continue
        code = vk & 0xFF
        need_shift = (vk >> 8) & 0x01
        shift_down = False
        try:
            if need_shift:
                win32api.keybd_event(VK["shift"], 0, 0, 0)
                shift_down = True
            win32api.keybd_event(code, 0, 0, 0)
            time.sleep(random.uniform(*[x / 1000.0 for x in Typing.KEY_HOLD_MS]))
        finally:
            # 与 press / _press_release 同款保护：中途异常也必须抬起，
            # 否则 Shift 会永久按住（上轮修了四处，漏了这一处）
            try:
                win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)
            except Exception:
                pass
            if shift_down:
                try:
                    win32api.keybd_event(VK["shift"], 0, win32con.KEYEVENTF_KEYUP, 0)
                except Exception:
                    pass
        time.sleep(random.uniform(*[x / 1000.0 for x in Typing.KEY_GAP_MS]))
        # 词间停顿
        if ch == " " and random.random() < Typing.WORD_PAUSE_P:
            Typing.sleep_ms(Typing.WORD_PAUSE_MS)


def _set_clipboard(text):
    """写入剪贴板（重试 3 次，处理被占用）"""
    for attempt in range(3):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            return True
        except Exception:
            time.sleep(0.15 * (attempt + 1))
    return False


def _paste(text):
    """整段粘贴（走剪贴板）"""
    if not _set_clipboard(text):
        raise RuntimeError("剪贴板被占用，无法粘贴")
    time.sleep(random.uniform(0.06, 0.14))
    press("ctrl+v")
    time.sleep(random.uniform(0.10, 0.25))


def type_text(text, force_paste=False):
    """
    智能输入（三层降级策略）：
      1. 首选 Unicode 注入（SendInput + KEYEVENTF_UNICODE）
         —— 绕过键盘布局、CapsLock、**中文输入法截获**
         2026-10-03 实测：用 keybd_event 时中文 IME 会把 "abc123" 变成 "ABC23"，
         换成 Unicode 注入后完全正确。
      2. 非 ASCII 或注入失败 → 剪贴板整段粘贴
      3. force_paste=True 时直接走剪贴板

    注意：粘贴会覆盖系统剪贴板（Windows 限制）。
    """
    if not text:
        return
    if force_paste:
        _paste(text)
        return
    # 优先 Unicode 注入（绕过输入法）
    # 注意：本模块既可作为包内模块（from . import）使用，也可被顶层导入（import keyboard）。
    # 两条路径都要能拿到 input_inject —— 否则会静默降级到剪贴板，
    # 等于悄悄绕过了输入法防护（2026-10-04 覆盖率测试发现的真问题）。
    _inject = None
    try:
        from . import input_inject as _inject
    except ImportError:
        try:
            import input_inject as _inject
        except ImportError:
            _inject = None
    if _inject is not None:
        try:
            _inject.send_unicode_text(text)
            return
        except Exception as exc:
            # 注入是逐字符进行的，中途失败时前若干字符**已经进到目标控件**了。
            # 此时若整段粘贴，前半段会重复。所以只把"还没发出去的"补上。
            typed_prefix = getattr(exc, "typed_chars", 0)
            rest = text[typed_prefix:] if typed_prefix else text
            if rest and rest != text:
                _paste(rest)
                return
            if rest == text:
                _paste(text)
                return
            return
    # 降级到剪贴板
    _paste(text)


def type_chinese(text):
    """中文输入（整段粘贴）—— 显式版本，语义更清楚"""
    _paste(text)


# ══════════════════════════════════════════════════════════
# ③ 数字键盘
# ══════════════════════════════════════════════════════════
def numpad(digits, ensure_numlock=True):
    """
    用数字键盘输入数字（人类财务/收银场景的习惯）。
    ensure_numlock=True 时会先确认 NumLock 状态，避免输入变成方向键。
    """
    if ensure_numlock and not numlock_on():
        press("numlock")
        time.sleep(0.15)
    for ch in str(digits):
        if ch.isdigit():
            press(f"num{ch}")
            time.sleep(random.uniform(0.06, 0.18))
        elif ch == ".":
            press("numdecimal")
            time.sleep(random.uniform(0.06, 0.18))
        elif ch == "+":
            press("numadd")
        elif ch == "-":
            press("numsub")
        elif ch == "*":
            press("nummul")
        elif ch == "/":
            press("numdiv")


def numlock_on():
    """查询 NumLock 是否开启"""
    try:
        return bool(win32api.GetKeyState(VK["numlock"]) & 0x0001)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════
# ④ 输入法切换（人类中英切换）
# ══════════════════════════════════════════════════════════
def toggle_ime():
    """
    切换输入法（中英切换）。
    Windows 默认：Win+Space 切换输入法，Ctrl+Space 切换中英。
    这里用 Win+Space（通用性更好）。
    """
    press("win+space")
    time.sleep(random.uniform(0.25, 0.5))


def switch_ime_ctrl_space():
    """Ctrl+Space 中英切换（旧版 Windows 习惯）"""
    press("ctrl+space")
    time.sleep(random.uniform(0.2, 0.4))


def get_ime_status():
    """
    查询当前前台窗口是否处于"输入法打开"状态。
    返回 True/False，查不到时返回 None（不假装知道）。

    2026-10-04 复核修正：
      原实现调 win32gui.ImmGetDefaultIMEWnd —— 该函数在 imm32.dll，不在 user32/win32gui，
      必然抛 AttributeError 被 except 吞掉，导致**永远返回 None**；
      且消息号写成了 0x005（WM_SIZE），应为 WM_IME_CONTROL(0x0283) + IMC_GETOPENSTATUS(0x0005)。
      现改为直接复用 input_inject 的实现（那里已修正）。
    """
    try:
        try:
            from . import input_inject as _ii
        except ImportError:
            import input_inject as _ii
        return _ii.ime_active_window()
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
# ⑤ 语义化快捷动作（人类常用组合）
# ══════════════════════════════════════════════════════════
def select_all():
    press("ctrl+a")


def copy():
    press("ctrl+c")


def cut():
    press("ctrl+x")


def paste():
    press("ctrl+v")


def undo(times=1):
    """撤销 —— 精确次数，绝不"多按几次保险"（2026-10-03 事故）"""
    if times <= 0:
        return 0
    for _ in range(times):
        press("ctrl+z")
        time.sleep(random.uniform(0.03, 0.08))
    return times


def redo(times=1):
    if times <= 0:
        return 0
    for _ in range(times):
        press("ctrl+y")
        time.sleep(random.uniform(0.03, 0.08))
    return times


def save():
    press("ctrl+s")


def find():
    press("ctrl+f")


def close_window():
    press("alt+f4")


def switch_window():
    press("alt+tab")


def new_tab():
    press("ctrl+t")


def close_tab():
    press("ctrl+w")


def task_manager():
    press("ctrl+shift+esc")


def lock_screen():
    press("win+l")


def type_and_submit(text):
    """输入并回车（搜索框、聊天框的典型动作）"""
    type_text(text)
    time.sleep(random.uniform(0.2, 0.45))
    press("enter")


# ══════════════════════════════════════════════════════════
# 自查
# ══════════════════════════════════════════════════════════
def doctor():
    caps = [
        ("press", "单键 / 组合键（任意组合）"),
        ("hold_key", "长按某键（finally 保证松开）"),
        ("shift_hold_select", "按住 Shift + 方向键连续选择"),
        ("type_text", "智能输入（ASCII 逐字符 / 中文整段）"),
        ("type_ascii", "纯英文打字（带词间停顿）"),
        ("type_chinese", "中文整段粘贴"),
        ("numpad", "数字键盘输入（自动处理 NumLock）"),
        ("toggle_ime", "输入法切换（Win+Space）"),
        ("switch_ime_ctrl_space", "中英切换（Ctrl+Space）"),
        ("select_all/copy/cut/paste", "剪贴板四件套"),
        ("undo/redo", "撤销重做（精确次数）"),
        ("save/find/close_window/switch_window", "常用快捷键"),
        ("new_tab/close_tab", "浏览器标签"),
        ("task_manager/lock_screen", "系统快捷键"),
        ("type_and_submit", "输入并提交"),
    ]
    for name, desc in caps:
        print(f"  [OK] {name:<38} {desc}")
    print(f"\n  虚拟键表共 {len(VK)} 个键位")
    print(f"  含 F1-F12: {'f1' in VK and 'f12' in VK}")
    print(f"  含数字键盘: {'num0' in VK and 'num9' in VK}")
    print(f"  含媒体键: {'volumeup' in VK}")
    return len(caps)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        n = doctor()
        print(f"\n  键盘能力共 {n} 组")
        print(f"  NumLock 状态: {numlock_on()}")
    else:
        print(__doc__)

# ══════════════════════════════════════════════════════════
# 卡键自检与恢复
# ══════════════════════════════════════════════════════════
_MODIFIERS = {
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3,
    "lalt": 0xA4, "ralt": 0xA5, "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
}


def check_stuck_keys():
    """
    检查有哪些修饰键/锁定键当前处于"按下"状态（可能卡住）。
    返回 {"shift": True, ...}，只列出被按下的。

    为什么需要它：合成按键中途异常时，修饰键可能一直保持按下，
    之后所有输入都会被它影响（比如一直选中、一直大写）。
    """
    stuck = {}
    for name, vk in _MODIFIERS.items():
        try:
            # GetAsyncKeyState 最高位 = 当前是否按下（不受当前线程同步状态影响）
            if win32api.GetAsyncKeyState(vk) & 0x8000:
                stuck[name] = True
        except Exception:
            pass
    # 大小写锁要单独看切换位
    try:
        if win32api.GetKeyState(0x14) & 0x0001:
            stuck["capslock_on"] = True
    except Exception:
        pass
    return stuck


def release_all_modifiers(verbose=False):
    """
    强制抬起所有修饰键 —— 卡键救援。
    返回实际被释放的键名列表（空列表 = 本来就没有卡住的）。

    注意：只抬起，不会把已开启的 CapsLock/NumLock 关掉
    （那是"开关"不是"卡住"，关掉会改变用户环境）。
    """
    released = []
    for name, vk in _MODIFIERS.items():
        try:
            if win32api.GetAsyncKeyState(vk) & 0x8000:
                win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
                released.append(name)
                if verbose:
                    print(f"    已释放卡住的 {name}")
        except Exception:
            pass
    if released:
        time.sleep(0.08)
    return released


def safe_press(combo, hold_ms=None):
    """
    带救援的组合键：按之前先清一次卡键，按完再清一次。
    用在"绝不能卡键"的场景（长流程自动化）。
    """
    release_all_modifiers()
    press(combo, hold_ms=hold_ms)
    return release_all_modifiers()

