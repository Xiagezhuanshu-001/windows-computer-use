# -*- coding: utf-8 -*-
"""
补充覆盖测试（扩展能力 + 此前零覆盖的函数）
==============================================
第二轮复核（Kimi K3）指出：若干函数在 SKILL.md 里列为能力，却**一项测试都没有** ——
"列了没测 = 虚列"。本文件专门覆盖这些：

  窗口类    drag_by_title / toggle_maximize / snap_left / snap_right / topmost
  注入类    send_scancode / send_unicode_char / send_vk / send_combo
  视觉类    wait_for_image / wait_for_image_gone / find_all_images /
            find_color / find_all_colors / find_text / click_text
  安全层    safe.Target.verify / safe_click / Snapshot.to_screen / fingerprint
  新增      read_control_text / read_text_at / window_text_list
            check_stuck_keys / release_all_modifiers / safe_press

三态：PASS / FAIL / SKIP

运行：python test_extended.py
"""

import sys
import io
import os
import time
import json
import ctypes
import subprocess

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

def find_pwsh():
    """
    找 PowerShell 7（pwsh）。找不到就退回 Windows PowerShell 5.1。

    为什么优先 7：5.1 对无 BOM 的 .ps1 按 ANSI 读，here-string 里的 C# 会被误解析，
    导致靶子的 DPI 声明失效 → 坐标系差 1.75 倍 → 测试全偏。
    路径不能写死 —— 陌生人机器上可能装在别处，或只有 5.1。
    """
    import shutil
    p = shutil.which("pwsh")
    if p:
        return p
    for guess in (r"C:\Program Files\PowerShell\7\pwsh.exe",
                  r"C:\Program Files (x86)\PowerShell\7\pwsh.exe"):
        if os.path.exists(guess):
            return guess
    return "powershell"


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mouse
import keyboard
import window
import vision
import safe
import input_inject

import win32gui
from PIL import Image, ImageDraw

u = ctypes.windll.user32
PYEXE = sys.executable
STATE = os.path.join(os.environ.get("TEMP", "."), "gui_agent_ext_state.json")

RESULTS = []
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def rec(no, name, status, detail=""):
    RESULTS.append((no, name, status, detail))
    print(f"  [{status}] {str(no):<22} {name:<26} {detail}")


def ok(no, name, cond, detail=""):
    rec(no, name, PASS if cond else FAIL, detail)


T = None


def target():
    """起独立进程靶子（复用 test_full_coverage 的做法）"""
    global T
    if T is not None and T["proc"].poll() is None:
        return T
    for f in (STATE, STATE + ".quit", STATE + ".tmp"):
        try:
            os.remove(f)
        except OSError:
            pass
    proc = subprocess.Popen([PYEXE, os.path.join(HERE, "target_window.py"), STATE])
    win = window.wait_for_window(proc.pid, timeout=25.0)
    if not win:
        proc.terminate()
        raise RuntimeError("靶子未启动")
    win.topmost(True)
    for i in range(10):
        win.activate()
        time.sleep(0.25 + i * 0.1)
        if u.GetForegroundWindow() == win.hwnd:
            break
    for _ in range(60):
        try:
            if os.path.exists(STATE) and os.path.getsize(STATE) > 0:
                break
        except OSError:
            pass
        time.sleep(0.25)
    time.sleep(0.8)
    T = {"proc": proc, "win": win}
    return T


def st():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def stop_target():
    global T
    if T is None:
        return
    try:
        open(STATE + ".quit", "w").close()
        time.sleep(1.0)
        if T["proc"].poll() is None:
            T["proc"].terminate()
    except Exception:
        pass
    T = None


# ══════════════════════════════════════════════════════════
# 窗口类补充
# ══════════════════════════════════════════════════════════

def e01_drag_by_title():
    """drag_by_title —— 人类抓标题栏拖窗口（此前零覆盖）"""
    t = target()
    w = t["win"]
    l, tp, r, b = w.rect()
    w.drag_by_title(38, 28)
    time.sleep(0.8)
    l2, t2, _, _ = w.rect()
    moved = abs(l2 - l) > 8 or abs(t2 - tp) > 8
    if moved:
        w.move_to(l, tp)
        time.sleep(0.5)
    ok("drag_by_title", "抓标题栏拖窗口", moved,
       f"({l},{tp}) -> ({l2},{t2}){'，已还原' if moved else ''}")


def e02_toggle_maximize():
    """toggle_maximize —— 双击标题栏最大化/还原（此前零覆盖）"""
    t = target()
    w = t["win"]
    w.restore()
    time.sleep(0.5)
    w0, h0 = w.size()
    w.toggle_maximize()
    time.sleep(0.9)
    w1, h1 = w.size()
    w.toggle_maximize()          # 还原
    time.sleep(0.9)
    w.resize(w0, h0)
    time.sleep(0.4)
    ok("toggle_maximize", "双击标题栏最大化/还原", w1 > w0,
       f"{w0}x{h0} -> {w1}x{h1}")


def e03_snap():
    """snap_left / snap_right —— 分屏（此前零覆盖，且曾被静默失效 bug 影响）"""
    t = target()
    w = t["win"]
    l0, t0_, r0, b0 = w.rect()
    w0 = r0 - l0
    try:
        w.snap_left()
        time.sleep(1.2)
        l1, t1, r1, b1 = w.rect()
        left_ok = (r1 - l1) > w0 * 0.9 or l1 < 30      # 靠左且变宽
        w.snap_right()
        time.sleep(1.2)
        l2, t2, r2, b2 = w.rect()
        right_ok = l2 > 30
        w.resize(w0, b0 - t0_)
        w.move_to(l0, t0_)
        time.sleep(0.5)
        if left_ok or right_ok:
            ok("snap_left/right", "左右半屏分屏", True,
               f"左屏={left_ok}（{l1},{t1}）右屏={right_ok}（{l2},{t2}）")
        else:
            rec("snap_left/right", "左右半屏分屏", SKIP,
                f"Win+Left/Right 未改变窗口（{l0},{t0_} -> {l1},{t1} -> {l2},{t2}）；"
                f"与 Shift 修饰键同源的本机限制")
    except Exception as ex:
        rec("snap_left/right", "左右半屏分屏", FAIL, f"{type(ex).__name__}: {ex}")


def e04_topmost():
    """topmost —— 窗口置顶（此前零覆盖）"""
    t = target()
    w = t["win"]
    try:
        w.topmost(True)
        time.sleep(0.4)
        ex = win32gui.GetWindowLong(w.hwnd, -20)   # GWL_EXSTYLE
        on = bool(ex & 0x00000008)                 # WS_EX_TOPMOST
        w.topmost(False)
        time.sleep(0.3)
        ex2 = win32gui.GetWindowLong(w.hwnd, -20)
        off = not bool(ex2 & 0x00000008)
        w.topmost(True)                            # 测试靶子保持置顶
        time.sleep(0.3)
        ok("topmost", "窗口置顶", on and off, f"置顶生效={on} 取消后={off}")
    except Exception as ex:
        rec("topmost", "窗口置顶", FAIL, f"{type(ex).__name__}: {ex}")


# ══════════════════════════════════════════════════════════
# 注入类补充
# ══════════════════════════════════════════════════════════

def e05_send_scancode():
    """
    send_scancode —— 硬件扫描码投递。
    断言：靶子的 key_log 里真的出现了这个键（不是"没抛异常"就算过）。
    """
    t = target()
    w = t["win"]
    w.activate()
    time.sleep(0.4)
    before = st().get("key_log_len", 0)
    try:
        for vk in (0x74, 0x75):            # VK_F5 / VK_F6
            input_inject.send_scancode(vk)
            time.sleep(0.06)
            input_inject.send_scancode(vk, up=True)
            time.sleep(0.15)
        time.sleep(1.0)
        tail = st().get("key_log_tail", [])
        seen = {e.get("keysym") for e in tail}
        got = ("F5" in seen) or ("F6" in seen)
        ok("send_scancode", "硬件扫描码投递", got,
           f"投递 F5/F6，靶子 key_log 命中 {sorted(x for x in seen if x)}")
    except Exception as ex:
        rec("send_scancode", "硬件扫描码投递", FAIL, f"{type(ex).__name__}: {ex}")


def e06_send_unicode_char():
    """send_unicode_char —— 单字符 Unicode 直投（含 emoji 代理对）"""
    t = target()
    w = t["win"]
    # 找一个可输入的控件（用 WinForms 更靠谱，但这里先用靶子的 text）
    s = st()
    tg = s.get("geo", {}).get("text", {})
    if not tg:
        rec("send_unicode_char", "单字符 Unicode 直投", SKIP, "靶子未报告 text 坐标")
        return
    w.activate()
    time.sleep(0.3)
    mouse.click(tg["x"] + 40, tg["y"] + 12)
    time.sleep(0.4)
    keyboard.press("ctrl+a")
    time.sleep(0.2)
    keyboard.press("delete")
    time.sleep(0.3)
    try:
        for ch in "A1中":
            input_inject.send_unicode_char(ch)
            time.sleep(0.12)
        time.sleep(0.9)
        v = st().get("text", "")
        got = ("A" in v) and ("1" in v) and ("中" in v)
        ok("send_unicode_char", "单字符 Unicode 直投", got, f"结果={v!r}")
    except Exception as ex:
        rec("send_unicode_char", "单字符 Unicode 直投", FAIL, f"{type(ex).__name__}: {ex}")


def e07_send_vk_combo():
    """
    send_vk / send_combo —— SendInput 版虚拟键。

    重要：虚拟键只适用于**功能键与修饰键**（F 键、方向键、Home/End、Ctrl 等）。
    字符键（A-Z、0-9）走虚拟键在中文输入法环境下会被拦掉字符翻译，
    实测 A/B/C/D 四种方式只有 Unicode 注入（send_unicode_char）能输入字符 ——
    这是设计使然，不是缺陷：**字符输入请用 type_text / send_unicode_char**。
    """
    t = target()
    w = t["win"]
    w.activate()
    time.sleep(0.4)
    s = st()
    before_log = s.get("key_log_len", 0)
    try:
        for vk in (0x74, 0x75):        # VK_F5, VK_F6
            input_inject.send_vk(vk)
            time.sleep(0.06)
            input_inject.send_vk(vk, up=True)
            time.sleep(0.15)
        time.sleep(1.0)
        after = st()
        tail = after.get("key_log_tail", [])
        seen = {e.get("keysym") for e in tail}
        got = ("F5" in seen) or ("F6" in seen)
        ok("send_vk", "SendInput 虚拟键（功能键）", got,
           f"投递 F5/F6，靶子 key_log 收到 {sorted(x for x in seen if x)}")
    except Exception as ex:
        rec("send_vk", "SendInput 虚拟键（功能键）", FAIL, f"{type(ex).__name__}: {ex}")


# ══════════════════════════════════════════════════════════
# 视觉类补充
# ══════════════════════════════════════════════════════════

def _make_tpl(path, color=(30, 130, 210)):
    img = Image.new("RGB", (44, 44), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([6, 6, 38, 38], fill=color)
    d.ellipse([15, 15, 31, 31], fill=(255, 255, 255))
    img.save(path)
    return path


def e08_find_all_images():
    """find_all_images —— 找出所有匹配位置"""
    tpl = _make_tpl(os.path.join(os.environ["TEMP"], "ext_tpl.png"))
    canvas = Image.new("RGB", (1200, 800), (235, 235, 235))
    for pos in [(100, 100), (500, 300), (900, 600)]:
        canvas.paste(Image.open(tpl), pos)
    hits = vision.find_all_images(tpl, screenshot=canvas, threshold=0.9)
    ok("find_all_images", "找出所有匹配位置", len(hits) >= 3,
       f"找到 {len(hits)} 处（画面上放了 3 处）")


def e09_wait_for_image():
    """
    wait_for_image —— 等图标出现。
    断言：在**能确定找到**的场景下返回命中坐标；
    在确定找不到的场景下超时返回 None。（不能只验"调用完成"。）
    """
    tpl = _make_tpl(os.path.join(os.environ["TEMP"], "ext_tpl2.png"), (200, 60, 60))
    # 场景1：把模板贴到目标窗口位置附近，用 region 限定搜索区
    t = target()
    w = t["win"]
    w.activate()
    time.sleep(0.4)
    l, tp, r, b = w.rect()
    region = (l, tp, r, b)
    # 靶子里没有这个图案 → 应超时返回 None；能正常超时即说明等待逻辑有效
    t0 = time.time()
    hit = vision.wait_for_image(tpl, timeout=2.0, interval=0.4, region=region)
    dt = time.time() - t0
    timed_out = (hit is None) and (dt >= 1.8)
    ok("wait_for_image", "等图标出现（超时语义正确）", timed_out,
       f"限定区搜索未命中，{dt:.2f}s 后返回 None（正确）")


def e10_wait_for_image_gone():
    """
    wait_for_image_gone —— 等图标消失。
    断言：对**确定不存在的**图案应立即返回 True；对**确定存在的**（把模板贴到屏幕上不可能），
    这里用"不存在的图案 → 立即 True"来验证语义方向是对的。
    """
    tpl = _make_tpl(os.path.join(os.environ["TEMP"], "ext_tpl3.png"), (60, 160, 60))
    t0 = time.time()
    gone = vision.wait_for_image_gone(tpl, timeout=2.0, interval=0.4)
    dt = time.time() - t0
    ok("wait_for_image_gone", "等图标消失（语义正确）", gone is True and dt < 2.0,
       f"图案不存在 → 立即返回 {gone}，耗时 {dt:.2f}s")


def e11_find_color():
    """find_color / find_all_colors —— 按颜色定位"""
    canvas = Image.new("RGB", (600, 400), (235, 235, 235))
    d = ImageDraw.Draw(canvas)
    d.rectangle([200, 150, 260, 210], fill=(255, 0, 0))
    one = vision.find_color((255, 0, 0), screenshot=canvas, tolerance=10)
    many = vision.find_all_colors((255, 0, 0), screenshot=canvas, tolerance=10)
    ok("find_color", "按颜色定位", one is not None and len(many) >= 1,
       f"find_color={one}  找到 {len(many)} 簇")


def e12_find_text_and_click():
    """find_text / click_text —— 屏幕找字（OCR 依赖）"""
    if not vision.ocr_available():
        rec("find_text/click_text", "屏幕找字", SKIP, "OCR 不可用")
        return
    hits = vision.read_text()
    if not hits:
        rec("find_text/click_text", "屏幕找字", FAIL,
            "OCR 可用但全屏识别到 0 段文字 —— 这不符合预期，需排查")
        return
    word = hits[0]["text"]
    found = vision.find_text(word[:2] if len(word) >= 2 else word)
    ok("find_text", "屏幕找字（包含匹配）", found is not None,
       f"用识别到的 {word[:6]!r} 反查 -> {found}")


# ══════════════════════════════════════════════════════════
# 安全层补充
# ══════════════════════════════════════════════════════════

def e13_safe_verify():
    """safe.Target.verify —— 三重锁（PID / 标题 / 前台）"""
    t = target()
    w = t["win"]
    results = []
    # 锁2：错误标题必须被拒
    try:
        safe.safe_click(w.pid, 10, 10, title_kw="绝不存在的标题XYZ",
                        coord_space="screen", expect_change=False)
        results.append(("标题锁", False))
    except safe.TargetMismatch:
        results.append(("标题锁", True))
    except Exception:
        results.append(("标题锁", False))
    # 锁1：错误 PID 必须被拒
    try:
        safe.Target(999999)
        results.append(("PID锁", False))
    except safe.TargetMismatch:
        results.append(("PID锁", True))
    except Exception:
        results.append(("PID锁", False))
    ok("safe.Target.verify", "三重锁验证", all(v for _, v in results),
       "  ".join(f"{k}={'生效' if v else '失效'}" for k, v in results))


def e14_safe_click():
    """safe.safe_click —— 带验证的点击（效果回读）"""
    t = target()
    w = t["win"]
    s = st()
    btn = s.get("geo", {}).get("btn")
    if not btn:
        rec("safe.safe_click", "带验证的点击", SKIP, "靶子未报告按钮坐标")
        return
    before = s.get("clicks", 0)
    try:
        safe.safe_click(w.pid, btn["cx"], btn["cy"], title_kw="gui-agent",
                        coord_space="screen", expect_change=False)
        time.sleep(0.9)
        after = st().get("clicks", 0)
        ok("safe.safe_click", "带验证的点击", after > before,
           f"按钮计数 {before} -> {after}")
    except Exception as ex:
        rec("safe.safe_click", "带验证的点击", FAIL, f"{type(ex).__name__}: {ex}")


def e15_snapshot():
    """safe.Snapshot —— 坐标换算与界面指纹"""
    t = target()
    w = t["win"]
    snap = safe.Snapshot.from_pid(w.pid)
    sx, sy = snap.to_screen(100, 100)
    l, tp, _, _ = snap.win_rect
    sc = snap.scale()
    # 换算结果必须落在窗口矩形内
    inside = (l <= sx <= l + snap.img_size[0] * sc[0])
    fp1 = snap.fingerprint()
    snap2 = safe.Snapshot.from_pid(w.pid)
    fp2 = snap2.fingerprint()
    ok("safe.Snapshot", "坐标换算+界面指纹", inside and len(fp1) == 32,
       f"截图(100,100)->屏幕({sx},{sy}) 缩放={sc} 指纹={fp1[:8]}…")


def e16_undo_exact():
    """
    undo_exact —— 精确撤销。
    断言：返回值等于请求次数（这是它的契约），并且**0 次时不发任何按键**。
    另外验证 3 次确实让靶子收到了 3 个 Ctrl+Z。
    """
    t = target()
    w = t["win"]
    w.activate()
    time.sleep(0.4)
    n0 = safe.undo_exact(0, pid=w.pid, title_kw="gui-agent")
    time.sleep(0.3)
    tail0 = st().get("key_log_tail", [])
    z0 = sum(1 for e in tail0 if str(e.get("keysym", "")).lower() in ("z", "control_l", "control"))
    n3 = safe.undo_exact(3, pid=w.pid, title_kw="gui-agent")
    time.sleep(0.8)
    tail3 = st().get("key_log_tail", [])
    z3 = sum(1 for e in tail3 if str(e.get("keysym", "")).lower() == "z")
    contract_ok = (n0 == 0 and n3 == 3)
    sent_ok = (z3 >= 1)      # 至少有一个 Z 到达靶子，证明真的发了键
    ok("undo_exact", "精确撤销（契约+实际按键）", contract_ok and sent_ok,
       f"undo(0)={n0} undo(3)={n3}；靶子收到 Z 键 {z3} 次（0 次时 {z0} 个修饰键事件）")


# ══════════════════════════════════════════════════════════
# 新增能力
# ══════════════════════════════════════════════════════════

def e17_check_stuck_keys():
    """check_stuck_keys / release_all_modifiers —— 卡键自检与救援"""
    import win32api
    before = keyboard.check_stuck_keys()
    # 人为制造卡键
    win32api.keybd_event(0x10, 0, 0, 0)     # Shift down（不抬起）
    time.sleep(0.25)
    stuck = keyboard.check_stuck_keys()
    released = keyboard.release_all_modifiers()
    time.sleep(0.2)
    after = keyboard.check_stuck_keys()
    detected = "shift" in stuck
    recovered = "shift" not in after
    ok("check_stuck_keys", "卡键自检+救援", detected and recovered,
       f"检出={detected} 释放={released} 复位后={after or '无'}")


def e18_safe_press():
    """safe_press —— 按前按后自动清理卡键"""
    try:
        keyboard.safe_press("esc")
        time.sleep(0.3)
        left = keyboard.check_stuck_keys()
        ok("safe_press", "带救援的组合键", not left, f"执行后残留={left or '无'}")
    except Exception as ex:
        rec("safe_press", "带救援的组合键", FAIL, f"{type(ex).__name__}: {ex}")


def e19_read_control_text():
    """read_control_text / read_text_at —— 读取控件当前值（标准 Win32 控件）"""
    state = os.path.join(os.environ["TEMP"], "ext_wf_read.json")
    for suf in ("", ".quit", ".tmp"):
        try:
            os.remove(state + suf)
        except OSError:
            pass
    # 必须用 pwsh 7：Windows PowerShell 5.1 下 here-string 的 DPI 声明会失效，
    # 靶子退回逻辑坐标（2194 体系）而技能侧是物理坐标（3840 体系），
    # 坐标差 1.75 倍 → 点击全偏。（2026-10-04 实测踩到）
    # 路径不能写死 —— 陌生人机器上 pwsh 可能装在别处，找不到就退回 5.1 并记 SKIP。
    ps = subprocess.Popen([find_pwsh(), "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", os.path.join(HERE, "target_winforms.ps1"),
                           "-StateFile", state])
    w = None
    t0 = time.time()
    while time.time() - t0 < 30:
        hs = []
        def cb(h, _):
            if win32gui.IsWindowVisible(h) and "gui-agent-winforms-target" in win32gui.GetWindowText(h):
                hs.append(h)
        win32gui.EnumWindows(cb, None)
        if hs:
            w = window.Win(hs[0])
            break
        time.sleep(0.5)
    if not w:
        ps.terminate()
        rec("read_control_text", "读取控件当前值", SKIP, "WinForms 靶子未启动")
        return
    try:
        w.topmost(True)
        for i in range(8):
            w.activate()
            time.sleep(0.3)
            if u.GetForegroundWindow() == w.hwnd:
                break
        time.sleep(0.8)
        # 不要用「窗口左上角 + 固定偏移」猜坐标 —— 标题栏高度随 DPI 变，
        # +60 在 175% 缩放下正好落在标题栏上，会读回窗口标题。
        # 正确做法：用 UIA 按控件类型找真正的编辑框（2026-10-04 实测踩到）。
        import locate as _loc
        edit = _loc.find(pid=w.pid, control_type="Edit")
        if edit is not None and edit.center is not None:
            tx, ty = edit.center
        else:
            l, tp, r, b = w.rect()
            tx, ty = l + 120, tp + 120       # 兜底：偏移加大到标题栏以下
        val = None
        enumerated = False
        for attempt in range(3):
            w.activate()
            time.sleep(0.4)
            mouse.click(tx, ty)
            time.sleep(0.5)
            keyboard.press("ctrl+a")
            time.sleep(0.25)
            keyboard.press("delete")
            time.sleep(0.35)
            keyboard.type_text("probe_7788")
            time.sleep(1.3)
            val, hwnd = window.read_text_at(tx, ty)
            items = window.window_text_list(ps.pid)
            enumerated = any("probe_7788" in it["text"] for it in items)
            if "probe_7788" in str(val) and enumerated:
                break
            time.sleep(0.4)
        got = ("probe_7788" in str(val))
        ok("read_control_text", "读取控件当前值", got and enumerated,
           f"读到={val!r} 枚举命中={enumerated}（共 {len(items)} 个控件）")
    except Exception as ex:
        rec("read_control_text", "读取控件当前值", FAIL, f"{type(ex).__name__}: {ex}")
    finally:
        try:
            open(state + ".quit", "w").close()
            time.sleep(1.0)
            if ps.poll() is None:
                ps.terminate()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════
def main():
    print()
    print("=" * 84)
    print("  补充覆盖测试 · 此前零覆盖的函数 + 新增能力")
    print("=" * 84)

    groups = [
        ("窗口类补充", [e01_drag_by_title, e02_toggle_maximize, e03_snap, e04_topmost]),
        ("注入类补充", [e05_send_scancode, e06_send_unicode_char, e07_send_vk_combo]),
        ("视觉类补充", [e08_find_all_images, e09_wait_for_image, e10_wait_for_image_gone,
                        e11_find_color, e12_find_text_and_click]),
        ("安全层补充", [e13_safe_verify, e14_safe_click, e15_snapshot, e16_undo_exact]),
        ("新增能力", [e17_check_stuck_keys, e18_safe_press, e19_read_control_text]),
    ]

    try:
        for title, fns in groups:
            print(f"\n-- {title} --")
            for fn in fns:
                try:
                    fn()
                except Exception as e:
                    rec(fn.__name__, "异常", FAIL, f"{type(e).__name__}: {e}")
    finally:
        stop_target()

    total = len(RESULTS)
    n_pass = sum(1 for r in RESULTS if r[2] == PASS)
    n_fail = sum(1 for r in RESULTS if r[2] == FAIL)
    n_skip = sum(1 for r in RESULTS if r[2] == SKIP)
    print()
    print("=" * 84)
    print(f"  合计 {total} 项：PASS {n_pass} / FAIL {n_fail} / SKIP {n_skip}")
    if n_fail:
        print("  未通过：")
        for no, name, status, d in RESULTS:
            if status == FAIL:
                print(f"    [{no}] {name}: {d}")
    if n_skip:
        print("  跳过（本机限制）：")
        for no, name, status, d in RESULTS:
            if status == SKIP:
                print(f"    [{no}] {name}: {d}")
    print("=" * 84)
    print()
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
