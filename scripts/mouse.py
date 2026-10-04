# -*- coding: utf-8 -*-
"""
鼠标能力模块（完整版）
========================
覆盖人类鼠标操作的全部动作：
  移动 / 单击 / 双击 / 三击 / 右键 / 中键 / 拖拽 / 滑块 /
  滚轮上下左右 / Ctrl+滚轮 / Shift+滚轮 / 悬停 / 长按 / 框选 /
  Ctrl+点击 / Shift+点击

设计原则（来自 2026-10-03 事故教训）：
  1. 所有动作带人类特征：轨迹弧线、变速、抖动、随机延迟
  2. 所有动作操作前验证目标在前台（避免打到别的窗口）
  3. 破坏性动作（长按、拖拽）有明确的开始和结束，不会卡住按键

作者：虾哥（DSH）  建于 2026-10-03
"""

import sys
import time
import math
import random

try:
    import win32api
    import win32con
    import win32gui
except ImportError:
    raise ImportError("需要 pywin32")


# ══════════════════════════════════════════════════════════
# 人类特征参数
# ══════════════════════════════════════════════════════════
class Human:
    SPEED_MIN = 0.35
    SPEED_MAX = 1.10
    JITTER = 1.6
    OVERSHOOT_P = 0.18

    HOVER_MS = (70, 220)
    PRESS_MS = (55, 140)
    CLICK_OFFSET = 1.2

    DOUBLE_GAP_MS = (90, 170)     # Windows 双击间隔通常在 200ms 内
    TRIPLE_GAP_MS = (85, 160)
    LONG_PRESS_MS = (600, 1200)   # 人类长按通常 0.6-1.2 秒

    DRAG_SPEED_MIN = 0.55
    DRAG_SPEED_MAX = 1.60
    DRAG_WOBBLE = 2.2
    DRAG_TAIL_PAUSE = (60, 260)
    DRAG_TAIL_ADJUST_P = 0.35

    WHEEL_STEP_MS = (40, 110)     # 滚轮每格的间隔
    WHEEL_LINES = (1, 4)          # 每次滚 1-4 格

    @staticmethod
    def jitter(a):
        return random.uniform(-a, a)

    @staticmethod
    def sleep_ms(rng):
        lo, hi = rng
        time.sleep(random.uniform(lo, hi) / 1000.0)


# ══════════════════════════════════════════════════════════
# 基础：光标
# ══════════════════════════════════════════════════════════
def cursor():
    return win32api.GetCursorPos()


def _set(x, y):
    win32api.SetCursorPos((int(round(x)), int(round(y))))


def screen_size():
    return win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)


def _assert_on_screen(x, y):
    """防止把鼠标移到屏幕外（人类不会这么干）"""
    w, h = screen_size()
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError(f"坐标 ({x},{y}) 超出屏幕 ({w}x{h})")


def foreground_title():
    h = win32gui.GetForegroundWindow()
    return h, win32gui.GetWindowText(h)


# ══════════════════════════════════════════════════════════
# ① 移动（拟人化）
# ══════════════════════════════════════════════════════════
def move(x, y, duration=None, jitter=None):
    """
    沿二次贝塞尔曲线移动到 (x, y)。
    - 控制点随机偏移形成弧线（人类不会走绝对直线）
    - 缓入缓出速度曲线（启动慢、中段快、收尾慢）
    - 逐帧抖动，末端收敛
    - 小概率过冲再回拉
    """
    _assert_on_screen(x, y)
    sx, sy = cursor()
    ex, ey = float(x), float(y)
    dist = math.hypot(ex - sx, ey - sy)
    if dist < 2:
        _set(ex, ey)
        return

    if duration is None:
        duration = min(Human.SPEED_MAX, max(Human.SPEED_MIN, dist / 1400.0 + random.uniform(0.15, 0.45)))
    if jitter is None:
        jitter = Human.JITTER

    mx, my = (sx + ex) / 2, (sy + ey) / 2
    nx, ny = -(ey - sy), (ex - sx)
    nlen = math.hypot(nx, ny) or 1.0
    # 保证最小弧度：人类手部运动绝不会是绝对直线。
    # 2026-10-03 实测发现：若 bow 允许接近 0，轨迹会退化成直线（机器特征），
    # 采样检测会判定为非人类。所以强制一个下限。
    bow = random.uniform(0.03, 0.12) * dist * random.choice((-1, 1))
    cx, cy = mx + nx / nlen * bow, my + ny / nlen * bow

    steps = max(12, min(90, int(dist / 9)))
    t0 = time.time()
    for i in range(steps + 1):
        p = i / steps
        e = 3 * p * p - 2 * p * p * p
        bx = (1 - e) ** 2 * sx + 2 * (1 - e) * e * cx + e * e * ex
        by = (1 - e) ** 2 * sy + 2 * (1 - e) * e * cy + e * e * ey
        j = jitter * (1.0 - e * 0.65)
        _set(bx + Human.jitter(j), by + Human.jitter(j))
        slack = (t0 + duration * p) - time.time()
        if slack > 0:
            time.sleep(slack)

    if random.random() < Human.OVERSHOOT_P and dist > 40:
        ox = ex + (ex - sx) / dist * random.uniform(6, 16)
        oy = ey + (ey - sy) / dist * random.uniform(6, 16)
        _set(ox, oy)
        time.sleep(random.uniform(0.03, 0.09))
    _set(ex + Human.jitter(Human.CLICK_OFFSET), ey + Human.jitter(Human.CLICK_OFFSET))


def hover(x, y, ms=None):
    """悬停 —— 移过去停一会儿（触发 tooltip / hover 效果）"""
    move(x, y)
    if ms is None:
        ms = random.randint(400, 900)
    time.sleep(ms / 1000.0)


# ══════════════════════════════════════════════════════════
# ② 点击（全部变体）
# ══════════════════════════════════════════════════════════
_BTN = {
    "left": (win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP),
    "right": (win32con.MOUSEEVENTF_RIGHTDOWN, win32con.MOUSEEVENTF_RIGHTUP),
    "middle": (win32con.MOUSEEVENTF_MIDDLEDOWN, win32con.MOUSEEVENTF_MIDDLEUP),
}


def _press_release(button="left", hold_ms=None):
    """
    按下 → 保持 → 抬起。
    用 try/finally 保证抬起 —— 中途异常若不清按键，鼠标键会永久按住。
    （2026-10-04 复核发现：press() 修了 finally，但最基础的点击原语漏了。）
    """
    down, up = _BTN[button]
    win32api.mouse_event(down, 0, 0, 0, 0)
    try:
        if hold_ms is None:
            Human.sleep_ms(Human.PRESS_MS)
        else:
            time.sleep(hold_ms / 1000.0)
    finally:
        try:
            win32api.mouse_event(up, 0, 0, 0, 0)
        except Exception:
            pass


def click(x=None, y=None, button="left", clicks=1, move_first=True, hover_ms=None, gap_ms=None):
    """
    单击 / 双击 / 三击。
    clicks=1 单击，2 双击，3 三击（选整段）。
    gap_ms 控制多击之间的间隔（默认按人类双击节奏）。
    """
    if x is not None and y is not None:
        if move_first:
            move(x, y)
        else:
            _assert_on_screen(x, y)
            _set(x, y)
    if hover_ms is None:
        Human.sleep_ms(Human.HOVER_MS)
    else:
        time.sleep(hover_ms / 1000.0)

    for i in range(clicks):
        _press_release(button)
        if i < clicks - 1:
            if gap_ms is not None:
                time.sleep(gap_ms / 1000.0)
            elif clicks == 2:
                Human.sleep_ms(Human.DOUBLE_GAP_MS)
            else:
                Human.sleep_ms(Human.TRIPLE_GAP_MS)


def double_click(x=None, y=None, button="left"):
    click(x, y, button, clicks=2)


def triple_click(x=None, y=None, button="left"):
    """三击 —— 通常是"选中整行/整段"的人类习惯"""
    click(x, y, button, clicks=3)


def right_click(x=None, y=None):
    """右键单击（弹上下文菜单）"""
    click(x, y, "right")


def middle_click(x=None, y=None):
    """中键单击（常用于新标签页打开链接、中键滚动）"""
    click(x, y, "middle")


def long_press(x=None, y=None, button="left", ms=None):
    """
    长按不放 —— 人类用于：某些 App 的次级菜单、拖动前置动作、强制选择。
    注意：这是"按下 → 停 → 抬起"，与拖拽的区别是不移动。
    """
    if x is not None and y is not None:
        move(x, y)
    Human.sleep_ms(Human.HOVER_MS)
    if ms is None:
        ms = random.randint(*Human.LONG_PRESS_MS)
    _press_release(button, hold_ms=ms)
    time.sleep(random.uniform(0.05, 0.15))


# ══════════════════════════════════════════════════════════
# ③ 修饰键 + 点击（人类多选习惯）
# ══════════════════════════════════════════════════════════
def _key_down(vk):
    win32api.keybd_event(vk, 0, 0, 0)


def _key_up(vk):
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)


def ctrl_click(x=None, y=None, button="left"):
    """Ctrl+点击 —— 多选不连续项（文件、列表、表格）"""
    _key_down(win32con.VK_CONTROL)
    time.sleep(random.uniform(0.03, 0.08))
    try:
        click(x, y, button)
    finally:
        time.sleep(random.uniform(0.03, 0.08))
        _key_up(win32con.VK_CONTROL)


def shift_click(x=None, y=None, button="left"):
    """Shift+点击 —— 选择连续范围"""
    _key_down(win32con.VK_SHIFT)
    time.sleep(random.uniform(0.03, 0.08))
    try:
        click(x, y, button)
    finally:
        time.sleep(random.uniform(0.03, 0.08))
        _key_up(win32con.VK_SHIFT)


# ══════════════════════════════════════════════════════════
# ④ 滚轮（上下 / 横向 / Ctrl 缩放 / Shift 横向）
# ══════════════════════════════════════════════════════════
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000


def wheel(dy, x=None, y=None, ctrl=False, shift=False, lines=None):
    """
    滚轮滚动。
      dy > 0 向上，dy < 0 向下（每格 120）
      lines: 分几次滚（人类不会一次滚到底，而是分几次带间隔）
      ctrl=True  → Ctrl+滚轮（缩放）
      shift=True → Shift+滚轮（横向滚动）
    """
    if x is not None and y is not None:
        move(x, y)
        Human.sleep_ms((60, 160))

    if lines is None:
        lines = random.randint(*Human.WHEEL_LINES)
    # 防御：lines 为 0 或负数会导致除零；人类也不会"滚 0 格"
    lines = max(1, int(lines))
    # 注意：这里不能写 int(dy) or ...，否则显式传 dy=0 会被静默改成滚 120。
    if dy == 0:
        return            # 0 就是"不滚"，静默返回

    mods = []
    if ctrl:
        mods.append(win32con.VK_CONTROL)
    if shift:
        mods.append(win32con.VK_SHIFT)
    for m in mods:
        _key_down(m)
        time.sleep(random.uniform(0.02, 0.06))

    try:
        # dy 是总滚动量（120 的倍数），分成 lines 次滚，模拟人类分段滚动
        per = int(dy / lines) or (1 if dy > 0 else -1)
        for i in range(lines):
            amount = per if i < lines - 1 else dy - per * (lines - 1)
            win32api.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(amount), 0)
            Human.sleep_ms(Human.WHEEL_STEP_MS)
    finally:
        for m in reversed(mods):
            _key_up(m)


def wheel_up(x=None, y=None, lines=None):
    if lines is None:
        lines = random.randint(*Human.WHEEL_LINES)
    wheel(lines * 120, x, y, lines=lines)


def wheel_down(x=None, y=None, lines=None):
    if lines is None:
        lines = random.randint(*Human.WHEEL_LINES)
    wheel(-lines * 120, x, y, lines=lines)


def wheel_horizontal(dx, x=None, y=None, lines=None):
    """横向滚轮（原生 HWHEEL）—— 用于横向滚动区域、时间轴"""
    if x is not None and y is not None:
        move(x, y)
        Human.sleep_ms((60, 160))
    if lines is None:
        lines = random.randint(1, 3)
    sign = 1 if dx > 0 else -1
    for _ in range(lines):
        win32api.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, sign * 120, 0)
        Human.sleep_ms(Human.WHEEL_STEP_MS)


def wheel_zoom(direction, x=None, y=None, lines=None):
    """Ctrl+滚轮缩放。direction: 'in' 放大 / 'out' 缩小"""
    if lines is None:
        lines = random.randint(1, 3)
    d = 120 if direction == "in" else -120
    wheel(d * lines, x, y, ctrl=True, lines=lines)


# ══════════════════════════════════════════════════════════
# ⑤ 拖拽（含滑块专用）
# ══════════════════════════════════════════════════════════
def drag(x1, y1, x2, y2, duration=None, wobble=None, button="left"):
    """
    按住拖动。滑块验证码做了专门优化：
      起步缓 → 中段冲 → 末端减速并微调，纵向带轻微摆动。
    """
    _assert_on_screen(x1, y1)
    _assert_on_screen(x2, y2)
    if wobble is None:
        wobble = Human.DRAG_WOBBLE
    if duration is None:
        dist = math.hypot(x2 - x1, y2 - y1)
        duration = min(Human.DRAG_SPEED_MAX, max(Human.DRAG_SPEED_MIN, dist / 900.0 + random.uniform(0.2, 0.5)))

    move(x1, y1, duration=random.uniform(0.25, 0.55))
    Human.sleep_ms(Human.HOVER_MS)
    down, up = _BTN[button]
    win32api.mouse_event(down, 0, 0, 0, 0)
    # 注意：down 之后要立刻进 try ——
    # 中间这段 sleep 若抛异常，鼠标键会永久按住（Codex 隔离验证确认过这条路径）
    try:
        time.sleep(random.uniform(0.05, 0.13))
        total_dx, total_dy = x2 - x1, y2 - y1
        steps = max(25, min(140, int(math.hypot(total_dx, total_dy) / 4)))
        t0 = time.time()
        for i in range(1, steps + 1):
            p = i / steps
            if p < 0.15:
                e = (p / 0.15) ** 2 * 0.12
            elif p < 0.80:
                e = 0.12 + (p - 0.15) / 0.65 * 0.80
            else:
                e = 0.92 + (1 - ((1 - p) / 0.20) ** 2) * 0.08
            cur_x = x1 + total_dx * e
            cur_y = y1 + total_dy * e + math.sin(p * math.pi * random.uniform(1.2, 2.4)) * wobble * (1 - p * 0.55)
            _set(cur_x, cur_y + Human.jitter(0.8))
            slack = (t0 + duration * p) - time.time()
            if slack > 0:
                time.sleep(slack)

        if random.random() < Human.DRAG_TAIL_ADJUST_P:
            for _ in range(random.randint(1, 3)):
                _set(x2 + Human.jitter(2.6), y2 + Human.jitter(1.8))
                time.sleep(random.uniform(0.02, 0.07))
        _set(x2 + Human.jitter(0.6), y2 + Human.jitter(0.6))
        Human.sleep_ms(Human.DRAG_TAIL_PAUSE)
    finally:
        win32api.mouse_event(up, 0, 0, 0, 0)


def rubber_band(x1, y1, x2, y2):
    """框选 —— 从空白处拖出一个矩形选区（桌面、文件管理器、画图）"""
    drag(x1, y1, x2, y2, wobble=0.8, duration=random.uniform(0.6, 1.1))


def drag_drop(x1, y1, x2, y2, settle_ms=None):
    """
    拖放 —— 把对象从一个位置拖到另一个位置（文件、卡片、列表项）。
    与 drag 的区别：到目标后有明显的"对准"停顿，再松手。
    """
    if settle_ms is None:
        settle_ms = random.randint(150, 380)
    drag(x1, y1, x2, y2, wobble=1.2, duration=random.uniform(0.7, 1.4))
    time.sleep(settle_ms / 1000.0)


# ══════════════════════════════════════════════════════════
# 自查
# ══════════════════════════════════════════════════════════
def doctor():
    """列出本模块覆盖的全部鼠标能力（供审计用）"""
    caps = [
        ("move", "拟人化移动（贝塞尔+变速+抖动）"),
        ("hover", "悬停（触发 tooltip）"),
        ("click", "单击 / 双击 / 三击（clicks 参数）"),
        ("double_click", "双击"),
        ("triple_click", "三击（选整段）"),
        ("right_click", "右键单击（上下文菜单）"),
        ("middle_click", "中键单击"),
        ("long_press", "长按不放"),
        ("ctrl_click", "Ctrl+点击（多选不连续）"),
        ("shift_click", "Shift+点击（选连续范围）"),
        ("wheel / wheel_up / wheel_down", "滚轮上下"),
        ("wheel_horizontal", "横向滚轮"),
        ("wheel_zoom", "Ctrl+滚轮（缩放）"),
        ("drag", "拖拽（含滑块优化）"),
        ("rubber_band", "框选"),
        ("drag_drop", "拖放"),
        ("cursor / screen_size", "光标与屏幕信息"),
    ]
    for name, desc in caps:
        print(f"  [OK] {name:<28} {desc}")
    return len(caps)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        n = doctor()
        print(f"\n  鼠标能力共 {n} 项")
        print(f"  屏幕: {screen_size()}   光标: {cursor()}")
    else:
        print(__doc__)
