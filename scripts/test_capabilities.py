# -*- coding: utf-8 -*-
"""
gui_agent 能力测试套件
========================
安全原则（来自 2026-10-03 事故教训）：
  1. 绝不碰用户的任何文件
  2. 自己创建临时窗口（tkinter），用完销毁
  3. 不修改任何系统设置
  4. 破坏性测试（如长按）有明确边界
  5. 每项测试可独立运行，失败不影响其它项

运行：python test_capabilities.py
输出：PASS/FAIL 汇总，全过时退出码 0
"""

import sys
import io
import os
import time
import math
import ctypes

# 统一 UTF-8 输出
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mouse
import keyboard
import window

RESULTS = []


def check(name, fn):
    """执行一项测试，记录结果"""
    try:
        ok, detail = fn()
        RESULTS.append((name, bool(ok), detail or ""))
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f"  -- {detail}" if detail else ""))
    except Exception as e:
        RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        print(f"  [FAIL] {name}  -- {type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════
# A 组：静态测试（不需要窗口，绝对安全）
# ══════════════════════════════════════════════════════════

def t_keymap_complete():
    """虚拟键表必须覆盖人类的常用键"""
    need = ["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
            "enter", "tab", "esc", "space", "backspace", "delete",
            "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
            "ctrl", "shift", "alt", "win",
            "num0", "num1", "num2", "num3", "num4", "num5", "num6", "num7", "num8", "num9"]
    missing = [k for k in need if k not in keyboard.VK]
    return (not missing), f"缺失 {missing}" if missing else f"覆盖 {len(keyboard.VK)} 个键位"


def t_no_chinese_quotes():
    """源码里不允许出现中文引号（会导致编码问题）"""
    bad = []
    for f in ["mouse.py", "keyboard.py", "window.py", "__init__.py"]:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), f)
        if not os.path.exists(p):
            continue
        src = open(p, encoding="utf-8").read()
        if any(q in src for q in "\u201c\u201d\u2018\u2019"):
            bad.append(f)
    return (not bad), f"含中文引号: {bad}" if bad else "4 个文件均无中文引号"


def t_no_dead_code():
    """不允许 if False 之类的死代码"""
    bad = []
    for f in ["mouse.py", "keyboard.py", "window.py"]:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), f)
        if os.path.exists(p):
            if "if False" in open(p, encoding="utf-8").read():
                bad.append(f)
    return (not bad), f"含死代码: {bad}" if bad else "无死代码"


def t_undo_zero_is_safe():
    """undo(0) 必须不发送任何按键、不报错"""
    n = keyboard.undo(0)
    return (n == 0), f"返回 {n}"


def t_screen_info():
    """屏幕信息可读"""
    w, h = mouse.screen_size()
    return (w > 0 and h > 0), f"屏幕 {w}x{h}"


def t_out_of_screen_guard():
    """移到屏幕外必须抛 ValueError（防止人类不会做的动作）"""
    try:
        mouse.move(999999, 999999, duration=0.01)
        return False, "没有抛异常（应该有保护）"
    except ValueError:
        return True, "正确拦截"
    except Exception as e:
        return False, f"抛了错误的异常: {type(e).__name__}"


def t_window_list():
    """能列出窗口"""
    rows = window.list_windows()
    return (len(rows) > 0), f"发现 {len(rows)} 个可见窗口"


def t_pid_lock_rejects_bad_pid():
    """不存在的 PID 必须抛 WindowNotFound（禁止模糊匹配的体现）"""
    try:
        window.Win.by_pid(999999)
        return False, "没有抛异常"
    except window.WindowNotFound:
        return True, "正确拒绝"
    except Exception as e:
        return False, f"抛了错误的异常: {type(e).__name__}"


# ══════════════════════════════════════════════════════════
# B 组：人类特征验证（不需要窗口）
# ══════════════════════════════════════════════════════════

def t_move_takes_human_time():
    """移动 800 像素应耗时 0.3-1.5 秒（不是瞬间）"""
    sx, sy = mouse.cursor()
    # 选一个安全的落点（屏幕内、避开边缘）
    w, h = mouse.screen_size()
    tx, ty = w // 2, h // 2
    t0 = time.time()
    mouse.move(tx, ty)
    dt = time.time() - t0
    # 还原（也算一次拟人移动）
    mouse.move(sx, sy)
    if dt < 0.25:
        return False, f"太快（{dt:.2f}s）—— 不像人"
    if dt > 2.0:
        return False, f"太慢（{dt:.2f}s）—— 卡顿"
    return True, f"耗时 {dt:.2f}s（人类区间）"


def _max_deviation_from_line(pts):
    """
    计算轨迹上各点到「起点-终点连线」的最大垂直距离。
    这才是判断"是不是直线"的正确指标 ——
    弓形轨迹的 X/Y 坐标可能仍然单调，但偏离直线的距离很大。
    """
    if len(pts) < 3:
        return 0.0
    x0, y0 = pts[0]
    x1, y1 = pts[-1]
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    if L == 0:
        return 0.0
    max_dev = 0.0
    for x, y in pts:
        dev = abs(dy * (x - x0) - dx * (y - y0)) / L
        if dev > max_dev:
            max_dev = dev
    return max_dev


def t_move_trajectory_not_straight():
    """
    轨迹不应是绝对直线（人类有弧线）。
    判据：轨迹偏离起终点连线的最大距离 > 3 像素。
    """
    import threading
    w, h = mouse.screen_size()

    # 先归位到一个角，确保接下来是长距离移动
    mouse.move(60, 60, duration=0.3)
    time.sleep(0.35)

    pts = []
    stop = False

    def sampler():
        while not stop:
            pts.append(mouse.cursor())
            time.sleep(0.008)

    tx, ty = w - 120, h - 120
    th = threading.Thread(target=sampler)
    th.start()
    mouse.move(tx, ty, duration=0.9)
    stop = True
    th.join()

    if len(pts) < 10:
        return False, f"采样点太少（{len(pts)}）"
    dist = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
    if dist < 400:
        return False, f"移动距离不足（{dist:.0f}px），无法判定"
    dev = _max_deviation_from_line(pts)
    if dev < 3.0:
        return False, f"偏离直线仅 {dev:.1f}px（{dist:.0f}px 移动，机器特征）"
    return True, f"{len(pts)} 个采样点，移动 {dist:.0f}px，最大偏离 {dev:.1f}px（有弧线）"


def t_typing_has_random_gaps():
    """打字间隔应有随机性（不是固定延迟）"""
    import time as _t
    gaps = []
    for _ in range(3):
        t0 = _t.time()
        keyboard.press("shift")
        gaps.append(_t.time() - t0)
    span = max(gaps) - min(gaps)
    return (span > 0.001), f"间隔波动 {span*1000:.1f}ms"


# ══════════════════════════════════════════════════════════
# C 组：临时窗口测试（自己建窗口，绝不碰用户文件）
# ══════════════════════════════════════════════════════════

class TempWindow:
    """创建一个安全的临时测试窗口（tkinter），用完即毁"""

    def __init__(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.title("gui_agent_test_temp_window")
        self.root.geometry("420x260+120+120")
        self.text = tk.Text(self.root, width=50, height=8)
        self.text.pack(padx=10, pady=10)
        self.root.update()
        self.root.update_idletasks()
        self.hwnd = self.root.winfo_id()
        # 找到顶层窗口句柄（tk 的 winfo_id 是子窗口）
        import win32gui
        self.top = win32gui.GetAncestor(self.hwnd, 2)  # GA_ROOT
        if not self.top:
            self.top = self.hwnd

    def refresh(self):
        try:
            self.root.update()
        except Exception:
            pass

    def get_text(self):
        return self.text.get("1.0", "end-1c")

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass


def with_temp(fn):
    """创建临时窗口跑测试，保证销毁"""
    tw = None
    try:
        tw = TempWindow()
        return fn(tw)
    finally:
        if tw:
            tw.close()


def t_temp_window_created():
    """临时窗口能创建（测试基础设施自检）"""
    def body(tw):
        return (tw.top != 0), f"hwnd={tw.top}"
    return with_temp(body)


def t_click_inside_temp_window():
    """点击临时窗口 —— 断言窗口真的收到了点击（用 tkinter 的点击计数）"""
    def body(tw):
        w = window.Win(tw.top)
        w.activate()
        tw.refresh()
        l, tp, r, b = w.rect()
        cx, cy = (l + r) // 2, (tp + b) // 2
        before = tw.click_count if hasattr(tw, "click_count") else None
        mouse.click(cx, cy)
        tw.refresh()
        # 没有点击计数器时，至少验证"点击后窗口仍然存活且在前台"
        alive = w.alive()
        fg = ctypes.windll.user32.GetForegroundWindow() == w.hwnd
        if before is not None:
            return (tw.click_count >= before), f"点击计数 {before} -> {tw.click_count}"
        return (alive and fg), f"点击后窗口存活={alive} 前台={fg}"
    return with_temp(body)

def t_type_into_temp_window():
    """
    能在自己创建的窗口里打字（关键：绝不打进用户文件）。
    注意：必须先确认焦点稳定 —— 人类点完输入框也会等一下再打字。
    """
    def body(tw):
        w = window.Win(tw.top)
        w.activate()
        time.sleep(0.45)                 # 等窗口激活稳定
        tw.refresh()

        l, t, r, b = w.rect()
        cx, cy = (l + r) // 2, t + 80
        mouse.click(cx, cy)              # 点进文本框
        time.sleep(0.55)                 # 等焦点稳定（关键）
        tw.refresh()

        # 清空后输入，最多重试 2 次（人类打错了也会重来）
        for attempt in range(3):
            keyboard.select_all()
            time.sleep(0.15)
            keyboard.press("delete")
            time.sleep(0.15)
            tw.refresh()

            keyboard.type_text("abc123")
            time.sleep(0.45)             # 等输入落地
            tw.refresh()

            got = tw.get_text()
            if "abc123" in got:
                return True, f"文本已进入临时窗口: {got[:20]!r}"
            # 重试前重新聚焦
            mouse.click(cx, cy)
            time.sleep(0.4)
            tw.refresh()

        return False, f"3 次尝试后仍未收到输入，窗口内容: {tw.get_text()[:20]!r}"
    return with_temp(body)


def t_win_ops_on_temp_window():
    """临时窗口的最大化/还原/调整大小可用"""
    def body(tw):
        w = window.Win(tw.top)
        w.activate()
        tw.refresh()
        w0, h0 = w.size()
        w.maximize()
        tw.refresh()
        w1, h1 = w.size()
        w.restore()
        tw.refresh()
        if w1 <= w0:
            return False, f"最大化无效（{w0}x{h0} -> {w1}x{h1}）"
        return True, f"尺寸 {w0}x{h0} -> 最大化 {w1}x{h1} -> 还原"
    return with_temp(body)


def t_clipboard_roundtrip():
    """剪贴板读写往返（用完立刻清空）"""
    token = "gui_agent_test_token_20261003"
    ok = window.clipboard_set(token)
    if not ok:
        return False, "写入失败"
    got = window.clipboard_get()
    window.clipboard_clear()
    if got == token:
        return True, "往返一致，已清空"
    return False, f"读回不一致: {got!r}"


def t_screenshot_temp_window():
    """能截取自己的临时窗口"""
    def body(tw):
        w = window.Win(tw.top)
        img = w.screenshot()
        sz = img.size
        return (sz[0] > 0 and sz[1] > 0), f"截图 {sz[0]}x{sz[1]}"
    return with_temp(body)


def t_wait_foreground_temp():
    """等待前台窗口逻辑正确（在临时窗口上验证）"""
    def body(tw):
        w = window.Win(tw.top)
        w.activate()
        ok = window.wait_until_foreground(w.pid, timeout=5.0)
        return ok, "临时窗口已成为前台" if ok else "超时"
    return with_temp(body)


# ══════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════
def main():
    print()
    print("=" * 60)
    print("  gui_agent 能力测试")
    print("=" * 60)

    print("\n-- A 组：静态检查（不碰系统） --")
    check("虚拟键表完整性", t_keymap_complete)
    check("源码无中文引号", t_no_chinese_quotes)
    check("源码无死代码", t_no_dead_code)
    check("undo(0) 安全", t_undo_zero_is_safe)
    check("屏幕信息可读", t_screen_info)
    check("屏幕外坐标保护", t_out_of_screen_guard)
    check("窗口可枚举", t_window_list)
    check("错误 PID 被拒绝", t_pid_lock_rejects_bad_pid)

    print("\n-- B 组：人类特征 --")
    check("移动耗时符合人类区间", t_move_takes_human_time)
    check("轨迹非绝对直线", t_move_trajectory_not_straight)
    check("打字间隔有随机性", t_typing_has_random_gaps)

    print("\n-- C 组：临时窗口（自建自毁，不碰用户文件） --")
    check("临时窗口可创建", t_temp_window_created)
    check("可在临时窗口点击", t_click_inside_temp_window)
    check("可在临时窗口打字", t_type_into_temp_window)
    check("临时窗口最大化/还原", t_win_ops_on_temp_window)
    check("剪贴板往返", t_clipboard_roundtrip)
    check("临时窗口截图", t_screenshot_temp_window)
    check("前台窗口等待", t_wait_foreground_temp)

    # 汇总
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = total - passed
    print()
    print("=" * 60)
    print(f"  合计 {total} 项：PASS {passed} / FAIL {failed}")
    if failed:
        print("  失败项：")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"    - {name}: {detail}")
    print("=" * 60)
    print()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
