# -*- coding: utf-8 -*-
"""
定位层测试（UI Automation）
============================
这是 2026-10-04 新增的能力：让技能自己「看得见」界面结构，
不再只能靠 OCR（全屏 ~10 秒）或猜坐标。

覆盖：
  可用性判断 / 取窗口节点 / 摊平控件树 / 按名字找 / 按类型找 /
  找全部 / 等元素出现 / 读控件值 / 元素级操作 / 「看到名字就点」/
  定位速度对比（UIA vs OCR）

三态：PASS / FAIL / SKIP

运行：python test_locate.py
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

import window
import locate as loc
import vision

import win32gui

u = ctypes.windll.user32
RESULTS = []
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def rec(no, name, status, detail=""):
    RESULTS.append((no, name, status, detail))
    print(f"  [{status}] {str(no):<24} {name:<26} {detail}")


def ok(no, name, cond, detail=""):
    rec(no, name, PASS if cond else FAIL, detail)


def start_winforms():
    """起 WinForms 靶子（标准 Win32 控件，UIA 支持最好）"""
    state = os.path.join(os.environ.get("TEMP", "."), "locate_test_state.json")
    for suf in ("", ".quit", ".tmp"):
        try:
            os.remove(state + suf)
        except OSError:
            pass
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
    if w:
        w.topmost(True)
        for i in range(8):
            w.activate()
            time.sleep(0.3)
            if u.GetForegroundWindow() == w.hwnd:
                break
        time.sleep(1.0)
    return ps, w, state


def read_state(state):
    try:
        return json.loads(open(state, encoding="utf-8").read().lstrip("\ufeff"))
    except Exception:
        return {}


def l01_available():
    """UIA 可用性"""
    ok("is_available", "UIA 可用性", loc.is_available(),
       f"uiautomation 可用={loc.is_available()}")


def l02_window_node(ps, w, state):
    """取窗口 UIA 根节点"""
    t0 = time.time()
    root = loc.window_of_pid(w.pid)
    dt = time.time() - t0
    ok("window_of_pid", "取窗口 UIA 根节点", root is not None,
       f"{'拿到根节点' if root else '拿不到'} 耗时 {dt:.3f}s")


def l03_dump_tree(ps, w, state):
    """摊平控件树"""
    t0 = time.time()
    tree = loc.dump_tree(w.pid, max_depth=4)
    dt = time.time() - t0
    has_edit = any("Edit" in x["control_type"] for x in tree)
    has_btn = any("Button" in x["control_type"] for x in tree)
    ok("dump_tree", "摊平控件树", len(tree) > 5 and has_edit and has_btn,
       f"{len(tree)} 个控件（含 Edit={has_edit} Button={has_btn}）耗时 {dt:.3f}s")


def l04_find_by_name(ps, w, state):
    """按名字找控件"""
    t0 = time.time()
    el = loc.find(pid=w.pid, name="click me")
    dt = time.time() - t0
    if el is None:
        rec("find(name)", "按名字找控件", FAIL, "没找到 'click me'")
        return
    ctr = el.center
    # 断言改成真回读：名字要含 click、类型要是 Button、坐标要有效
    good = (ctr is not None and "click" in el.name.lower()
            and "Button" in el.control_type)
    ok("find(name)", "按名字找控件", good,
       f"找到 {el.control_type} {el.name!r} 中心={ctr} 耗时 {dt:.3f}s")


def l05_find_by_type(ps, w, state):
    """按类型找控件"""
    els = loc.find_all(pid=w.pid, control_type="ListItem", limit=50)
    # 靶子有 60 个 ListItem，limit=50 → 应恰好拿到 50 个（对齐 limit 而不是松阈值）
    ok("find_all(type)", "按类型找全部", len(els) == 50,
       f"找到 {len(els)} 个 ListItem（靶子 60 个，limit=50）")


def l06_read_value(ps, w, state):
    """读控件当前值"""
    # 先往编辑框写点东西
    el = loc.find(pid=w.pid, control_type="Edit")
    if el is None:
        rec("Element.value", "读控件当前值", FAIL, "找不到 Edit 控件")
        return
    el.set_value("value_probe_123")
    time.sleep(1.2)
    el2 = loc.find(pid=w.pid, control_type="Edit")
    v = el2.value if el2 else None
    ok("Element.value", "读控件当前值", "value_probe_123" in str(v),
       f"读到 {v!r}")


def l07_click_by_name(ps, w, state):
    """「看到名字就点」"""
    before = read_state(state).get("clicks", 0)
    okk, detail = loc.click_by_name(w.pid, "click me")
    time.sleep(1.0)
    after = read_state(state).get("clicks", 0)
    ok("click_by_name", "看到名字就点", okk and after > before,
       f"{detail}；计数 {before} -> {after}")


def l08_wait_for(ps, w, state):
    """等元素出现（超时语义）"""
    t0 = time.time()
    el = loc.wait_for(pid=w.pid, name="绝不存在的控件名XYZ", timeout=2.0, interval=0.4)
    dt = time.time() - t0
    ok("wait_for", "等元素出现（超时）", el is None and dt >= 1.8,
       f"{dt:.2f}s 后返回 None（正确）")

    # 存在的元素应立即返回。
    # 注意：这个按钮被点过之后名字从 'click me' 变成了 'clicks: N'，
    # 所以这里用包含匹配 'click' —— 真实界面里控件文字变化很常见，
    # 按固定全名找会失效，这也是用 UIA 定位时必须留意的点。
    t0 = time.time()
    el2 = loc.wait_for(pid=w.pid, name="click", timeout=5.0)
    dt2 = time.time() - t0
    got = el2.name if el2 is not None else None
    ok("wait_for(命中)", "等元素出现（命中）", el2 is not None and dt2 < 6.0,
       f"找到 {got!r}，耗时 {dt2:.2f}s")


def l09_speed_compare(ps, w, state):
    """速度对比：UIA 定位 vs OCR 定位（这是当初加定位层的理由）"""
    # UIA
    t0 = time.time()
    el = loc.find(pid=w.pid, name="click me")
    dt_uia = time.time() - t0
    # OCR（全屏）
    dt_ocr = None
    if vision.ocr_available():
        t0 = time.time()
        vision.read_text()
        dt_ocr = time.time() - t0
    if dt_ocr:
        ratio = dt_ocr / max(dt_uia, 1e-6)
        ok("速度对比", "UIA vs OCR 定位速度", dt_uia < dt_ocr,
           f"UIA {dt_uia:.3f}s vs OCR {dt_ocr:.2f}s → 快 {ratio:.0f} 倍")
    else:
        rec("速度对比", "UIA vs OCR 定位速度", SKIP,
            f"UIA {dt_uia:.3f}s；OCR 不可用，无法对比")


def l10_element_click(ps, w, state):
    """元素级拟人化点击（不是 UIA 的 Invoke）"""
    # 注意：这个按钮点过一次后名字会从 'click me' 变成 'clicks: N'，
    # 所以用包含匹配 'click' 才稳（真实界面里控件文字变化也很常见）
    el = loc.find(pid=w.pid, name="click", control_type="Button")
    if el is None:
        rec("Element.click", "元素级拟人化点击", FAIL, "找不到按钮")
        return
    before = read_state(state).get("clicks", 0)
    t0 = time.time()
    el.click()
    dt = time.time() - t0
    time.sleep(1.0)
    after = read_state(state).get("clicks", 0)
    ok("Element.click", "元素级拟人化点击", after > before,
       f"计数 {before} -> {after}，耗时 {dt:.2f}s（人类区间，非瞬间）")


def main():
    print()
    print("=" * 84)
    print("  定位层测试（UI Automation）—— 让技能自己「看得见」")
    print("=" * 84)

    ps = w = state = None
    try:
        ps, w, state = start_winforms()
        if not w:
            print("  [!] WinForms 靶子未启动，全部记 SKIP")
            rec("setup", "起靶子", SKIP, "WinForms 靶子启动失败")
            return 0

        print(f"\n  靶子: pid={w.pid} hwnd={w.hwnd} title={w.title!r}\n")
        l01_available()
        l02_window_node(ps, w, state)
        l03_dump_tree(ps, w, state)
        l04_find_by_name(ps, w, state)
        l05_find_by_type(ps, w, state)
        l06_read_value(ps, w, state)
        l07_click_by_name(ps, w, state)
        l08_wait_for(ps, w, state)
        l09_speed_compare(ps, w, state)
        l10_element_click(ps, w, state)
    finally:
        try:
            if state:
                open(state + ".quit", "w").close()
                time.sleep(1.0)
            if ps and ps.poll() is None:
                ps.terminate()
        except Exception:
            pass

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
        print("  跳过：")
        for no, name, status, d in RESULTS:
            if status == SKIP:
                print(f"    [{no}] {name}: {d}")
    print("=" * 84)
    print()
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
