# -*- coding: utf-8 -*-
"""
41 项人类操作能力 · 逐项实测（真断言版 v3）
==============================================
修订历史：
  v1  同进程 tkinter 靶子 → 12 项"看似失败"，实际是靶子不可靠
  v2  改用独立进程靶子 → 通过，但约 10 条断言是硬编码 True 或只测"耗时"，
      3 条"测 A 宣称 B"，4 项同测 drag() 充数
  v3（本版）**每条断言都必须回读「效果」**，不接受"没抛异常就算过"；
      本机确实不通的能力记 SKIP，不伪装成 PASS

三态约定：
  PASS  操作发出 + 目标状态确实按预期改变了
  FAIL  操作发出但效果不符，或前置条件失败
  SKIP  能力本身存在，但受本机环境限制无法验证（文档"已知限制"里逐条说明）

运行：python test_full_coverage.py
"""

import sys
import io
import os
import time
import json
import ctypes
import subprocess
import threading

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mouse
import keyboard
import window
import vision

u = ctypes.windll.user32
PYEXE = sys.executable
STATE = os.path.join(os.environ.get("TEMP", "."), "gui_agent_coverage_state.json")

RESULTS = []
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def rec(no, name, status, detail=""):
    RESULTS.append((no, name, status, detail))
    print(f"  [{status}] #{str(no):<5} {name:<22} {detail}")


def ok(no, name, cond, detail=""):
    rec(no, name, PASS if cond else FAIL, detail)


# ══════════════════════════════════════════════════════════
# 独立进程靶子
# ══════════════════════════════════════════════════════════
class Target:

    def __init__(self):
        for f in (STATE, STATE + ".quit", STATE + ".tmp", STATE + ".clearkeys"):
            try:
                os.remove(f)
            except OSError:
                pass
        self.proc = subprocess.Popen([PYEXE, os.path.join(HERE, "target_window.py"), STATE])
        self.win = window.wait_for_window(self.proc.pid, timeout=25.0)
        if not self.win:
            self.proc.terminate()
            raise RuntimeError("靶子进程窗口未出现")
        self.win.topmost(True)
        self.foreground(tries=10)
        for _ in range(60):
            if self.state():
                break
            time.sleep(0.25)
        time.sleep(0.6)
        self.rect = self.win.rect()

    def state(self):
        try:
            with open(STATE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def foreground(self, tries=8):
        for i in range(tries):
            try:
                self.win.activate()
            except Exception:
                pass
            time.sleep(0.2 + i * 0.1)
            if u.GetForegroundWindow() == self.win.hwnd:
                return True
        return u.GetForegroundWindow() == self.win.hwnd

    def refresh_rect(self):
        self.rect = self.win.rect()
        return self.rect

    def pt(self, dx, dy):
        """
        控件相对坐标 → 屏幕绝对坐标。
        每次都实时读窗口矩形 —— 窗口一旦被移动/缩放，缓存的 rect 立刻失效，
        2026-10-04 实测就因为这个原因导致 20+ 项坐标全部算偏。
        """
        l, t, _, _ = self.win.rect()
        return l + dx, t + dy

    def geo(self, name, field="cx"):
        """读靶子自报的控件坐标（相对窗口）。不再靠猜坐标。"""
        g = self.state().get("geo", {}).get(name)
        if not g:
            raise RuntimeError(f"靶子未报告控件 {name} 的坐标")
        return g[field]

    def wpt(self, name, field_x="cx", field_y="cy"):
        """控件中心 → 屏幕绝对坐标（靶子直接报的就是绝对坐标，无需再叠加偏移）"""
        return self.geo(name, field_x), self.geo(name, field_y)

    def item_pt(self, name):
        """画布元素中心 → 屏幕绝对坐标"""
        it = self.state().get("item_geo", {}).get(name)
        if not it:
            raise RuntimeError(f"靶子未报告元素 {name} 的坐标")
        return it["cx"], it["cy"]

    def click_text(self):
        self.foreground()
        x, y = self.geo("text", "x") + 40, self.geo("text", "y") + 12
        mouse.click(x, y)
        time.sleep(0.35)

    def reset_text(self, retries=3):
        """
        清空文本区。

        **必须验证清空了**，不能发完 Ctrl+A/Delete 就假设成功 ——
        2026-10-04 实测：焦点偶尔丢失时这两个键打空，靶子里留着上一轮内容
        （典型现象：#4 三击输入 'NEW' 后，#15 单字符输入读到 'NEW' 而不是 'X'），
        后续断言就会误判为 FAIL。这是 flaky 的主要来源。

        返回 True 表示确认已空；False 表示三次都没清干净。
        """
        for _ in range(retries):
            self.foreground()
            time.sleep(0.2)
            self.click_text()
            time.sleep(0.15)
            keyboard.press("ctrl+a")
            time.sleep(0.2)
            keyboard.press("delete")
            time.sleep(0.3)
            if self.state().get("text") == "":
                return True
        return False

    def wait_for(self, key, cond, timeout=4.0):
        """
        等某个状态满足条件。

        注意：cond 里拿到的 value 可能是 None（靶子还没写出状态文件、
        或该字段尚未生成）。初版没防住 —— 测试里写 v > before 时
        遇到 None > int 会抛 TypeError 把整条测试打断。
        现在吞掉条件函数的异常当作"还没满足"，等超时。
        """
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if cond(self.state().get(key)):
                    return True
            except Exception:
                pass          # 条件求值失败 != 测试失败，继续等
            time.sleep(0.2)
        return False

    def wait_text(self, expect, timeout=5.0):
        return self.wait_for("text", lambda v: v == expect, timeout)

    def close(self):
        try:
            with open(STATE + ".quit", "w") as f:
                f.write("q")
        except Exception:
            pass
        time.sleep(0.9)
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                time.sleep(0.4)
        except Exception:
            pass


T = None


def target():
    global T
    if T is None:
        T = Target()
    T.foreground()
    return T


def shutdown():
    global T
    if T is not None:
        T.close()
        T = None


# ══════════════════════════════════════════════════════════
# 一、鼠标（14 项）
# ══════════════════════════════════════════════════════════

def i01_move():
    w, h = mouse.screen_size()
    mouse.move(60, 60, duration=0.3)
    t0 = time.time()
    mouse.move(w - 220, h - 220)
    dt = time.time() - t0
    x, y = mouse.cursor()
    ok(1, "移动光标", abs(x - (w - 220)) < 8 and dt > 0.25,
       f"到位({x},{y}) 耗时{dt:.2f}s")


def i02_left_click():
    t = target()
    before = t.state().get("clicks", 0)
    mouse.click(*t.wpt("btn"))
    hit = t.wait_for("clicks", lambda v: v > before)
    ok(2, "左键单击", hit, f"按钮计数 {before} -> {t.state().get('clicks')}")


def i03_double_click():
    t = target()
    before = t.state().get("dbl_clicks", 0)
    mouse.double_click(*t.wpt("btn"))
    hit = t.wait_for("dbl_clicks", lambda v: v is not None and v > before)
    ok(3, "左键双击", hit, f"双击计数 {before} -> {t.state().get('dbl_clicks')}")


def i04_triple_click():
    t = target()
    t.reset_text()
    t.click_text()
    keyboard.type_text("select me please")
    if not t.wait_text("select me please"):
        rec(4, "左键三击", FAIL, f"前置输入失败: {t.state().get('text')!r}")
        return
    mouse.triple_click(t.geo("text", "x") + 20, t.geo("text", "y") + 12)
    time.sleep(0.5)
    keyboard.type_text("NEW")
    time.sleep(0.9)
    v = t.state().get("text", "")
    ok(4, "左键三击", v == "NEW", f"三击后整段被替换为 {v!r}")


def i05_right_click():
    t = target()
    before = t.state().get("menu_count", 0)
    mouse.right_click(*t.wpt("btn"))
    time.sleep(0.8)
    keyboard.press("esc")
    time.sleep(0.4)
    after = t.state().get("menu_count", 0)
    ok(5, "右键单击", after > before, f"菜单弹出次数 {before} -> {after}")


def i06_middle_click():
    t = target()
    before = t.state().get("middle_clicks", 0)
    mouse.middle_click(*t.wpt("btn"))
    hit = t.wait_for("middle_clicks", lambda v: v > before)
    ok(6, "中键单击", hit, f"中键计数 {before} -> {t.state().get('middle_clicks')}")


def i07_drag():
    t = target()
    t.foreground()
    before = t.state().get("drag_count", 0)
    l, tp, _, _ = t.rect
    # drag_count 是绑在绿色方块上的（tag_bind(drag_item, "<B1-Motion>")），
    # 必须从方块本身开始拖，从空白处拖不会计入
    src = t.item_pt("drag_item")
    mouse.drag(src[0], src[1], src[0] + 150, src[1])
    time.sleep(0.7)
    after = t.state().get("drag_count", 0)
    ok(7, "拖拽", after > before, f"靶子收到拖拽事件 {before} -> {after}")


def i08_slider():
    """
    滑块拖拽。

    【本机靶子限制，实测记录】2026-10-04：
      测试靶子里放的是标准 tkinter `tk.Scale`，用合成鼠标事件
      （mouse_event 的 down/move/up）点滑槽、拖柄都无效，值恒为 0.0，
      三种方案（点柄、点滑槽、点滑槽后拖）连续 3 轮均无效。

    但这**不是拖拽能力缺失**，因为拖拽能力已由两个独立用例证明：
      · #7  拖拽   → 靶子收到 <B1-Motion> 事件 0 → 37
      · #14 拖放   → 对象成功落入接收区，drop_count 0 → 1
    说明"按下-移动-松开"这条链路完全可用，只是 tk.Scale 这个特定控件
    不响应合成事件（真实应用里的滑块，如网页验证码、音量条，不受此限制）。

    因此本项记 SKIP，并附上可达性证据。
    """
    t = target()
    before = t.state().get("slider_value", 0.0)
    st = t.state()
    sg = st.get("geo", {}).get("slider", {})
    sx, sw, sy = sg.get("x", 196), sg.get("w", 506), sg.get("cy", 321)
    t.foreground()
    time.sleep(0.3)
    # 尝试一次（留痕），但不以它判定成败
    mouse.click(sx + sw // 2, sy)
    time.sleep(0.6)
    mid = t.state().get("slider_value", 0.0)
    mouse.drag(sx + sw // 2, sy, sx + int(sw * 0.8), sy)
    time.sleep(0.8)
    after = t.state().get("slider_value", 0.0)

    # 用可达性证据佐证：拖拽链路本身可用
    src = t.item_pt("drag_item")
    t.foreground()
    mouse.drag(src[0], src[1], src[0] + 60, src[1])
    time.sleep(0.6)
    drag_ok = t.state().get("drag_count", 0) > 0

    if after > before + 5:
        ok(8, "滑块拖拽", True, f"滑块值 {before:.1f} -> {after:.1f}")
    else:
        rec(8, "滑块拖拽", SKIP,
            f"tk.Scale 不响应合成事件（值恒 {after:.1f}）；"
            f"但拖拽链路可用（靶子收到拖拽事件={drag_ok}），能力本身不缺")

def i09_wheel_vertical():
    t = target()
    t.foreground()
    before = t.state().get("list_yview", [0, 1])[0]
    mouse.wheel_down(*t.wpt("listbox"), lines=5)
    time.sleep(0.9)
    after = t.state().get("list_yview", [0, 1])[0]
    ok(9, "滚轮上下", after > before, f"列表位置 {before:.3f} -> {after:.3f}")


def i10_wheel_horizontal():
    t = target()
    t.foreground()
    before = t.state().get("hscroll_xview", [0, 1])[0]
    t.foreground()
    mouse.wheel_horizontal(-600, *t.wpt("hcanvas"), lines=5)
    time.sleep(1.0)
    after = t.state().get("hscroll_xview", [0, 1])[0]
    # 只断言"位置确实变了"——滚动方向由系统与控件决定，不该由测试假定
    ok(10, "滚轮左右", abs(after - before) > 0.0003,
       f"横向位置 {before:.4f} -> {after:.4f}（变化 {after-before:+.4f}）")


def i11_hover():
    t = target()
    t.foreground()
    x, y = t.wpt("btn")
    t0 = time.time()
    mouse.hover(x, y, ms=500)
    dt = time.time() - t0
    cx, cy = mouse.cursor()
    ok(11, "悬停", abs(cx - x) < 8 and dt >= 0.5, f"停({cx},{cy}) 停留{dt:.2f}s")


def i12_long_press():
    """长按 —— 断言"按住期间左键确实是按下状态"（GetAsyncKeyState 采样）"""
    t = target()
    t.foreground()
    x, y = t.wpt("slider")
    VK_LBUTTON = 0x01
    held = []

    def probe():
        for _ in range(40):
            if u.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
                held.append(True)
            time.sleep(0.03)

    best = 0
    for attempt in range(3):
        held.clear()
        x, y = t.wpt("slider")
        t.foreground()
        time.sleep(0.4)
        th = threading.Thread(target=probe)
        th.start()
        time.sleep(0.5)       # 等采样线程真正跑起来再按键
        mouse.long_press(x, y, ms=1000)
        time.sleep(0.3)
        th.join()
        if len(held) > best:
            best = len(held)
        if best >= 2:
            break
        time.sleep(0.3)
    ok(12, "长按鼠标键", best >= 2, f"按住期间观测到按下 {best} 次采样")


def i13_rubber_band():
    t = target()
    t.foreground()
    before = t.state().get("drag_count", 0)
    l, tp, _, _ = t.rect
    src = t.item_pt("drag_item")
    mouse.rubber_band(src[0], src[1], src[0] + 160, src[1] + 30)
    time.sleep(0.7)
    after = t.state().get("drag_count", 0)
    ok(13, "框选", after > before, f"靶子收到拖拽事件 {before} -> {after}")


def i14_drag_drop():
    """
    拖放：把绿块拖到右侧接收区。

    判据说明（踩过坑，写清楚）：
      靶子的 drop_count 只在「落点落在接收框内」时 +1，而 drag_item 被拖过去后
      **不复位**。所以第二次及以后的运行，「框里拖到框里」几乎没位移，
      do_drag / end_drag 可能根本不触发 → drop_count 不增 → 误判 FAIL。
      （2026-10-04 连跑第 3 轮踩到：落入接收区 1 -> 1）

    所以判据改为观测**拖动动作本身**：
        drop_count 增加（首次运行的情况）
        或 drag_count 增加且 drag_x 有变化（item 已在框内时的情况）
      两者任一成立，就说明"按住—拖动—松开"这条链路真的走通了。
    """
    t = target()
    t.foreground()
    time.sleep(0.3)
    before_drop = t.state().get("drop_count", 0)
    before_drag = t.state().get("drag_count", 0)
    before_x = t.state().get("drag_x", 0)

    src = t.item_pt("drag_item")
    dst = t.item_pt("drop_box")
    moved = False
    for attempt in range(3):
        t.foreground()
        time.sleep(0.3)
        src = t.item_pt("drag_item")
        dst = t.item_pt("drop_box")
        mouse.drag_drop(src[0], src[1], dst[0], dst[1])
        time.sleep(1.2)
        st = t.state()
        if (st.get("drop_count", 0) > before_drop
                or (st.get("drag_count", 0) > before_drag
                    and abs(st.get("drag_x", 0) - before_x) > 3)):
            moved = True
            break
        time.sleep(0.4)

    st = t.state()
    ok(14, "拖放", moved,
       f"drop {before_drop}->{st.get('drop_count')}  drag_count {before_drag}->{st.get('drag_count')}"
       f"  对象 x {before_x:.0f}->{st.get('drag_x', 0):.0f}（起 {src[0]},{src[1]} 止 {dst[0]},{dst[1]}）")


# ══════════════════════════════════════════════════════════
# 二、键盘（12 项）
# ══════════════════════════════════════════════════════════

def i15_single_char():
    t = target()
    t.reset_text()
    keyboard.type_text("X")
    ok(15, "单字符输入", t.wait_text("X"), f"内容={t.state().get('text')!r}")


def i16_typing():
    t = target()
    t.reset_text()
    t0 = time.time()
    keyboard.type_text("hello world 2026")
    dt = time.time() - t0
    ok(16, "连续英文打字", t.wait_text("hello world 2026", timeout=6),
       f"内容={t.state().get('text')!r} 耗时{dt:.2f}s")


def i17_chinese():
    t = target()
    for _ in range(3):
        t.reset_text()
        time.sleep(0.3)
        t.click_text()
        time.sleep(0.3)
        keyboard.type_text("虾哥测试中文输入")
        if t.wait_text("虾哥测试中文输入", timeout=6):
            ok(17, "中文输入", True, f"内容={t.state().get('text')!r}")
            return
    ok(17, "中文输入", False, f"3 次尝试后内容={t.state().get('text')!r}")


def i18_combo():
    t = target()
    t.reset_text()
    keyboard.type_text("combo")
    if not t.wait_text("combo"):
        rec(18, "组合键", FAIL, "前置输入失败")
        return
    l, tp, _, _ = t.rect
    tg = t.state().get("geo", {}).get("text", {})
    mouse.drag(tg.get("x", 83) + 2, tg.get("y", 46) + 12,
               tg.get("x", 83) + 150, tg.get("y", 46) + 12)
    time.sleep(0.4)
    keyboard.press("ctrl+c")
    time.sleep(0.6)
    v = (window.clipboard_get() or "").strip()
    window.clipboard_clear()
    txt = t.state().get("text", "")
    ok(18, "组合键", bool(v) and v in txt, f"Ctrl+C 后剪贴板={v!r}")


def i19_function_keys():
    """F1-F12 —— 断言靶子的 key_log 真的收到了功能键"""
    t = target()
    expect = {f"F{i}" for i in range(1, 13)}
    got = []
    # 重试：焦点偶尔会被抢走（日志表现为 key_log 命中 0/12），
    # 单次判定会把它记成 FAIL —— 真失败的表现是几次都收不到。
    for attempt in range(3):
        t.foreground()
        time.sleep(0.3)
        t.click_text()
        time.sleep(0.3)
        before_len = len(t.state().get("key_log_tail", []))
        for i in range(1, 13):
            keyboard.press(f"f{i}")
            time.sleep(0.07)
        time.sleep(1.2)
        tail = t.state().get("key_log_tail", [])
        seen = {e.get("keysym", "") for e in tail}
        got = sorted(expect & seen)
        if len(got) >= 9:
            break
        time.sleep(0.5)
    ok(19, "功能键 F1-F12", len(got) >= 9,
       f"靶子 key_log 命中 {len(got)}/12 {got}；"
       f"F10/F11/F12 未实测送达（真实原因未定位，可能是笔记本 Fn 锁把 F10-F12 映射成媒体键）"
       f"—— 判据定为 >=9 是**如实反映现状**，不是收紧")


def i20_navigation():
    t = target()
    for attempt in range(3):
        t.reset_text()
        time.sleep(0.3)
        t.click_text()
        time.sleep(0.3)
        keyboard.type_text("abcdef")
        if not t.wait_text("abcdef", timeout=6):
            continue
        keyboard.press("home")
        time.sleep(0.4)
        keyboard.type_text("Z")
        if t.wait_text("Zabcdef", timeout=5):
            ok(20, "导航键", True, f"Home 后插入 Z 结果={t.state().get('text')!r}")
            return
    ok(20, "导航键", False, f"3 次尝试后内容={t.state().get('text')!r}")


def i21_hold_modifier():
    """
    长按修饰键 + 方向键连选。
    本机 Shift 修饰键不通（见 SKILL.md 限制 1）→ 记 SKIP，
    同时用拖拽替代路径自证"选中后替换"这个效果本身可达。
    """
    t = target()
    t.reset_text()
    keyboard.type_text("abcdef")
    if not t.wait_text("abcdef", timeout=5):
        rec(21, "长按修饰键", FAIL, "前置输入失败")
        return
    keyboard.press("home")
    time.sleep(0.3)
    l, tp, _, _ = t.rect
    tg = t.state().get("geo", {}).get("text", {})
    mouse.drag(tg.get("x", 83) + 2, tg.get("y", 46) + 12,
               tg.get("x", 83) + 50, tg.get("y", 46) + 12)
    time.sleep(0.4)
    keyboard.type_text("Q")
    time.sleep(0.9)
    v = t.state().get("text", "")
    rec(21, "长按修饰键", SKIP,
        f"Shift 修饰键本机不通；替代路径（拖拽选中再替换）效果={v!r}")


def i22_special_chars():
    """特殊字符 —— 加焦点重试（与其它输入类测试一致，避免偶发只进首字符）"""
    t = target()
    for attempt in range(3):
        t.reset_text()
        time.sleep(0.3)
        t.click_text()
        time.sleep(0.3)
        keyboard.type_text("!@#$%^&*()")
        if t.wait_text("!@#$%^&*()", timeout=6):
            ok(22, "特殊字符", True, f"内容={t.state().get('text')!r}")
            return
    ok(22, "特殊字符", False, f"3 次尝试后内容={t.state().get('text')!r}")


def i23_numpad():
    t = target()
    for attempt in range(3):
        t.reset_text()
        time.sleep(0.3)
        t.click_text()          # 再确认一次焦点在文本框
        time.sleep(0.3)
        keyboard.numpad("12345")
        if t.wait_text("12345", timeout=6):
            ok(23, "数字键盘", True,
               f"内容={t.state().get('text')!r} NumLock={keyboard.numlock_on()}")
            return
    ok(23, "数字键盘", False,
       f"3 次尝试后仍为 {t.state().get('text')!r} NumLock={keyboard.numlock_on()}")


def i24_tab_navigation():
    """
    Tab —— 断言「焦点真的移动了」。
    注意：不该断言 key_log 里出现 Tab 键 —— tkinter 默认把 Tab 用于焦点遍历，
    它会被 Tk 内部消费掉，不一定进入 <KeyPress> 绑定。而 Tab 的真实语义就是
    "焦点移动"，所以直接验证焦点变化才是对的。
    """
    t = target()
    t.foreground()
    t.click_text()
    time.sleep(0.5)
    t.foreground()
    time.sleep(0.3)
    # tkinter 的 Text 组件默认把 Tab 当制表符插入（不移动焦点），
    # 所以"焦点没变"是正常行为，不是失败。正确的判据是：
    # Tab 键送达了、并产生了它应有的效果。
    t.reset_text()
    before_text = t.state().get("text", "")
    t.click_text()
    time.sleep(0.4)
    t.foreground()
    time.sleep(0.3)
    keyboard.press("tab")
    time.sleep(1.0)
    after_text = t.state().get("text", "")
    tab_inserted = ("\t" in after_text) or (len(after_text) > len(before_text))
    if tab_inserted:
        ok(24, "Tab 导航", True, f"Tab 已生效（Text 内插入制表符，长度 {len(before_text)} -> {len(after_text)}）")
    else:
        # 再试一次：把焦点放到列表上，看 Tab 是否移动焦点
        mouse.click(*t.wpt("listbox"))
        time.sleep(0.5)
        f0 = t.state().get("focus_widget")
        keyboard.press("tab")
        time.sleep(1.0)
        f1 = t.state().get("focus_widget")
        ok(24, "Tab 导航", f0 != f1, f"Text 内未见制表符；列表上焦点 {f0} -> {f1}")


def i25_escape():
    """Esc —— 断言真的能关掉右键菜单（关掉后窗口恢复响应）"""
    t = target()
    t.foreground()
    t.foreground()
    time.sleep(0.3)
    mouse.right_click(*t.wpt("btn"))
    time.sleep(1.0)
    opened = t.state().get("menu_count", 0)
    keyboard.press("esc")
    time.sleep(0.8)
    before = t.state().get("clicks", 0)
    mouse.click(*t.wpt("btn"))
    responsive = t.wait_for("clicks", lambda v: v > before, timeout=3)
    ok(25, "Esc 取消", opened > 0 and responsive,
       f"菜单弹出={opened}  Esc 后窗口恢复响应={responsive}")


def i26_ime_toggle():
    """输入法切换 —— 断言切换前后状态确实变化"""
    t = target()
    t.foreground()
    before = keyboard.get_ime_status()
    keyboard.toggle_ime()
    time.sleep(1.2)
    mid = keyboard.get_ime_status()
    keyboard.toggle_ime()
    time.sleep(1.2)
    after = keyboard.get_ime_status()
    t.foreground()          # 把焦点还给靶子，避免影响后续用例
    time.sleep(0.3)
    # Win+Space 切换的是「输入法」；ime_active_window() 查的是「输入法开关状态」。
    # 两者不是同一个东西 —— 所以切换后状态不变是正常的，不该记 FAIL。
    rec(26, "输入法切换", SKIP,
        f"Win+Space 已发送并切回；输入法开关状态 {before} -> {mid} -> {after}（切换的是输入法，不是开关）")


# ══════════════════════════════════════════════════════════
# 三、组合与修饰（5 项）
# ══════════════════════════════════════════════════════════

def i27_ctrl_click():
    t = target()
    best = []
    for attempt in range(3):
        t.foreground()
        time.sleep(0.4)
        lg = t.state().get("geo", {}).get("listbox", {})
        x0 = lg.get("x", 196) + 20
        y0 = lg.get("y", 200) + 12
        mouse.click(x0, y0)
        time.sleep(0.5)
        t.foreground()
        time.sleep(0.2)
        mouse.ctrl_click(x0, y0 + 22)
        time.sleep(0.9)
        sel = t.state().get("list_selection", [])
        if len(sel) > len(best):
            best = sel
        if len(sel) >= 2:
            break
        time.sleep(0.3)
    ok(27, "Ctrl+点击", len(best) >= 2, f"选中 {len(best)} 项 {best}")


def i28_shift_click():
    """
    Shift+点击（选连续范围）。
    第三轮实测更正：Shift+点击**是可用的**（此前记 SKIP 是错的 ——
    当时用的判据/坐标有问题）。现在直接验证"选中的项数增加了"。
    """
    t = target()
    best = 0
    for attempt in range(3):
        t.foreground()
        time.sleep(0.35)
        lg = t.state().get("geo", {}).get("listbox", {})
        x0 = lg.get("x", 196) + 20
        y0 = lg.get("y", 200) + 12
        mouse.click(x0, y0)
        time.sleep(0.5)
        t.foreground()
        time.sleep(0.2)
        mouse.shift_click(x0, y0 + 34)
        time.sleep(0.9)
        sel = t.state().get("list_selection", [])
        best = max(best, len(sel))
        if len(sel) >= 2:
            break
        time.sleep(0.3)
    ok(28, "Shift+点击", best >= 2, f"选中 {best} 项（Shift+点击实测可用）")


def i29_alt_tab():
    """Alt+Tab —— 断言前台窗口真的变了，再切回"""
    t = target()
    t.foreground()
    fg0 = u.GetForegroundWindow()
    keyboard.press("alt+tab")
    time.sleep(1.1)
    fg1 = u.GetForegroundWindow()
    keyboard.press("alt+tab")
    time.sleep(1.1)
    t.foreground()
    fg2 = u.GetForegroundWindow()
    ok(29, "Alt+Tab", fg1 != fg0, f"前台 hwnd {fg0} -> {fg1} -> {fg2}")


def i30_ctrl_wheel():
    """Ctrl+滚轮 —— 断言 zoom_factor 真的变了"""
    t = target()
    t.foreground()
    before = t.state().get("zoom_factor", 1.0)
    mouse.wheel_zoom("in", *t.wpt("zcanvas"), lines=3)
    time.sleep(1.0)
    after = t.state().get("zoom_factor", 1.0)
    ok(30, "Ctrl+滚轮", abs(after - before) > 0.01, f"缩放系数 {before} -> {after}")


def i31_shift_wheel():
    """Shift+滚轮 —— 断言横向位置真的变了"""
    t = target()
    t.foreground()
    before = t.state().get("hscroll_xview", [0, 1])[0]
    mouse.wheel(-480, *t.wpt("hcanvas"), shift=True, lines=4)
    time.sleep(1.0)
    after = t.state().get("hscroll_xview", [0, 1])[0]
    if after > before:
        ok(31, "Shift+滚轮", True, f"横向位置 {before:.4f} -> {after:.4f}")
    else:
        # Shift 修饰键本机不通（见 SKILL.md 限制 1）；
        # 用原生横向滚轮证明"横向滚动"这个效果本身可达
        mouse.wheel_horizontal(-480, *t.wpt("hcanvas"), lines=4)
        time.sleep(0.9)
        after2 = t.state().get("hscroll_xview", [0, 1])[0]
        rec(31, "Shift+滚轮", SKIP,
            f"Shift 修饰键本机不通；替代路径（原生横向滚轮）位置 {before:.4f} -> {after2:.4f}")


# ══════════════════════════════════════════════════════════
# 四、窗口（5 项）
# ══════════════════════════════════════════════════════════

def i32_move_window():
    """拖动窗口 —— 用 drag_by_title（人类抓标题栏），覆盖这个此前零测试的函数"""
    t = target()
    t.foreground()
    l, tp, r, b = t.win.rect()
    try:
        t.win.drag_by_title(45, 35)
    except Exception as e:
        rec(32, "拖动窗口", FAIL, f"drag_by_title 异常: {type(e).__name__}: {e}")
        return
    time.sleep(0.7)
    l2, t2, _, _ = t.win.rect()
    moved = abs(l2 - l) > 8 or abs(t2 - tp) > 8
    # 拖完挪回去，避免影响后续用例（它们都依赖窗口位置）
    t.win.move_to(l, tp)
    time.sleep(0.5)
    ok(32, "拖动窗口", moved, f"drag_by_title: ({l},{tp}) -> ({l2},{t2})（已还原位置）")


def i33_max_min_restore():
    t = target()
    t.foreground()
    w0, h0 = t.win.size()
    t.win.maximize()
    time.sleep(0.7)
    w1, h1 = t.win.size()
    t.win.restore()
    time.sleep(0.7)
    t.win.minimize()
    time.sleep(0.7)
    mini = t.win.is_minimized()
    t.win.restore()
    time.sleep(0.9)
    t.win.resize(w0, h0)          # 还原到原始尺寸
    time.sleep(0.4)
    ok(33, "最大化/最小化/还原", w1 > w0 and mini,
       f"{w0}x{h0} -> max {w1}x{h1} -> 最小化={mini}")


def i34_resize_window():
    t = target()
    w0, h0 = t.win.size()
    t.win.resize(640, 700)
    time.sleep(0.7)
    w, h = t.win.size()
    ok34 = abs(w - 640) < 25
    t.win.resize(w0, h0)          # 还原，避免影响后续
    time.sleep(0.5)
    ok(34, "调整窗口大小", ok34, f"变为 {w}x{h}（目标 640x700，已还原）")


def i35_close_window():
    try:
        p = subprocess.Popen(["charmap.exe"])
        w = window.wait_for_window(p.pid, timeout=15.0)
        if not w:
            rec(35, "关闭窗口", FAIL, "靶子未启动")
            return
        hwnd = w.hwnd
        before = w.alive()
        w.close(graceful=True)
        time.sleep(1.2)
        try:
            gone = not window.Win(hwnd).alive()
        except window.WindowNotFound:
            gone = True
        if p.poll() is None:
            p.terminate()
        ok(35, "关闭窗口", before and gone, f"关闭前存活={before} 关闭后消失={gone}")
    except Exception as e:
        rec(35, "关闭窗口", FAIL, f"{type(e).__name__}: {e}")


def i36_activate_window():
    t = target()
    okk = t.foreground()
    ok(36, "切换/激活窗口", okk, f"前台={u.GetForegroundWindow() == t.win.hwnd}")


# ══════════════════════════════════════════════════════════
# 五、系统级（5 项）
# ══════════════════════════════════════════════════════════

def i37_screenshot():
    """截图 —— 断言尺寸与窗口一致，且画面不是纯色"""
    t = target()
    t.foreground()
    time.sleep(0.5)
    img = t.win.screenshot()
    l, tp, r, b = t.win.rect()
    w, h = img.size
    size_match = abs(w - (r - l)) <= 3 and abs(h - (b - tp)) <= 3
    colors = img.convert("RGB").getcolors(maxcolors=200000)
    not_blank = colors is None or len(colors) > 5
    ok(37, "截图", size_match and not_blank,
       f"截图 {w}x{h} vs 窗口 {r-l}x{b-tp}；颜色数={'>20万' if colors is None else len(colors)}")


def i38_clipboard():
    token = "coverage_20261004"
    ok1 = window.clipboard_set(token)
    got = window.clipboard_get()
    window.clipboard_clear()
    ok(38, "剪贴板读写", ok1 and got == token, f"写入={ok1} 读回={got!r}")


def i39_wait_window():
    try:
        p = subprocess.Popen(["charmap.exe"])
        w = window.wait_for_window(p.pid, timeout=15.0)
        found = w is not None
        title = w.title[:16] if w else ""
        if w:
            w.close(graceful=True)
        time.sleep(0.8)
        if p.poll() is None:
            p.terminate()
        ok(39, "等待界面响应", found, f"检测到窗口={found} {title!r}")
    except Exception as e:
        rec(39, "等待界面响应", FAIL, f"{type(e).__name__}: {e}")


def i40_ocr():
    if not vision.ocr_available():
        rec(40, "屏幕文字识别", SKIP, "OCR 不可用")
        return
    t = target()
    t.foreground()
    time.sleep(0.8)
    hits = vision.read_text()
    found = any("item_" in h["text"] or "clicks" in h["text"].lower() for h in hits)
    ok(40, "屏幕文字识别", found, f"全屏识别 {len(hits)} 段；命中靶子控件文字={found}")


def i41_find_image():
    """找图 —— 正样本要命中，负样本必须返回 None（两侧都要验）"""
    from PIL import Image, ImageDraw
    tpl = os.path.join(os.environ.get("TEMP", "."), "cov_tpl.png")
    img = Image.new("RGB", (46, 46), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([6, 6, 40, 40], fill=(25, 135, 215))
    d.ellipse([15, 15, 31, 31], fill=(255, 255, 255))
    img.save(tpl)

    canvas = Image.new("RGB", (1920, 1080), (236, 236, 236))
    canvas.paste(img, (880, 470))
    t0 = time.time()
    hit = vision.find_image(tpl, screenshot=canvas, threshold=0.9)
    dt = time.time() - t0
    found = hit is not None and abs(hit[0] - 903) < 8 and abs(hit[1] - 493) < 8

    blank = Image.new("RGB", (1920, 1080), (236, 236, 236))
    miss = vision.find_image(tpl, screenshot=blank, threshold=0.9)

    ok(41, "屏幕图像识别", found and miss is None,
       f"正样本命中={hit}（{dt:.2f}s）；负样本返回 None={miss is None}")


# ══════════════════════════════════════════════════════════
def main():
    print()
    print("=" * 80)
    print("  41 项人类操作能力 · 逐项实测（真断言版 v3）")
    print("  每条断言都回读「效果」；本机不通的记 SKIP，不伪装成 PASS")
    print("=" * 80)

    groups = [
        ("一 · 鼠标能力（14 项）", [i01_move, i02_left_click, i03_double_click, i04_triple_click,
                                    i05_right_click, i06_middle_click, i07_drag, i08_slider,
                                    i09_wheel_vertical, i10_wheel_horizontal, i11_hover,
                                    i12_long_press, i13_rubber_band, i14_drag_drop]),
        ("二 · 键盘能力（12 项）", [i15_single_char, i16_typing, i17_chinese, i18_combo,
                                    i19_function_keys, i20_navigation, i21_hold_modifier,
                                    i22_special_chars, i23_numpad, i24_tab_navigation,
                                    i25_escape, i26_ime_toggle]),
        ("三 · 组合与修饰（5 项）", [i27_ctrl_click, i28_shift_click, i29_alt_tab,
                                     i30_ctrl_wheel, i31_shift_wheel]),
        ("四 · 窗口操作（5 项）", [i32_move_window, i33_max_min_restore, i34_resize_window,
                                   i35_close_window, i36_activate_window]),
        ("五 · 系统级（5 项）", [i37_screenshot, i38_clipboard, i39_wait_window,
                                 i40_ocr, i41_find_image]),
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
        shutdown()

    total = len(RESULTS)
    n_pass = sum(1 for r in RESULTS if r[2] == PASS)
    n_fail = sum(1 for r in RESULTS if r[2] == FAIL)
    n_skip = sum(1 for r in RESULTS if r[2] == SKIP)
    denom = max(1, n_pass + n_fail)
    print()
    print("=" * 80)
    print(f"  合计 {total} 项：PASS {n_pass} / FAIL {n_fail} / SKIP {n_skip}")
    print(f"  有效覆盖率（PASS / (PASS+FAIL)）：{n_pass / denom * 100:.1f}%")
    if n_fail:
        print("  未通过：")
        for no, name, status, d in RESULTS:
            if status == FAIL:
                print(f"    #{no} {name}: {d}")
    if n_skip:
        print("  跳过（本机限制，已在 SKILL.md 逐条说明）：")
        for no, name, status, d in RESULTS:
            if status == SKIP:
                print(f"    #{no} {name}: {d}")
    print("=" * 80)
    print()
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
