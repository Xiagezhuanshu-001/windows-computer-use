# -*- coding: utf-8 -*-
"""
定位层（UI Automation）—— 让技能自己「看得见」
================================================
2026-10-04 新增。此前本技能的短板很明确：

    它不知道界面上有什么按钮，只知道「在坐标 (100,200) 按下鼠标」。
    定位只能靠 OCR（全屏扫描 ~10 秒）或模板匹配，拿到的是「像素像文字」，
    而不是「这是什么控件、能不能点、当前值是什么」。

这一层补上这个短板：直接调 Windows UI Automation（UIA）读无障碍树。

实测对比（同一台机器）：
    取窗口根节点      : 0.046s
    按控件类型查找     : 0.000-0.002s
    OCR 全屏扫描       : 9.93s
    → 快约 100 倍（多次留档实测 88-101 倍），而且拿到的是**结构化信息**（名字/角色/可交互性/当前值）

与 MCP（kimi-cu / windows-mcp）的关系：
    它们底层也是 UIA，能力和本模块等价。区别是：
      · 本模块在技能内，本地调用无协议往返开销
      · 拿到坐标后可直连本技能的拟人化操作与三重锁验证
      · 不需要 agent 层的工具调用参与，可组合、可循环

依赖：uiautomation（已装 2.0.29）；没有时优雅降级（is_available() 返回 False）

作者：虾哥（DSH）
"""

import os
import sys
import time

try:
    import uiautomation as auto
    _UIA_OK = True
except Exception:
    auto = None
    _UIA_OK = False

from typing import Optional, List, Tuple


def is_available() -> bool:
    """UIA 是否可用"""
    return _UIA_OK


def _require():
    if not _UIA_OK:
        raise RuntimeError("uiautomation 不可用，请 pip install uiautomation")


# ══════════════════════════════════════════════════════════
# 元素包装
# ══════════════════════════════════════════════════════════
class Element:
    """对 UIA 控件的轻量包装：给出人类关心的那些字段"""

    def __init__(self, ctrl):
        self._c = ctrl

    # ── 基本信息 ──
    @property
    def name(self) -> str:
        try:
            return self._c.Name or ""
        except Exception:
            return ""

    @property
    def control_type(self) -> str:
        try:
            return self._c.ControlTypeName or ""
        except Exception:
            return ""

    @property
    def class_name(self) -> str:
        try:
            return self._c.ClassName or ""
        except Exception:
            return ""

    @property
    def automation_id(self) -> str:
        try:
            return self._c.AutomationId or ""
        except Exception:
            return ""

    @property
    def rect(self) -> Optional[Tuple[int, int, int, int]]:
        """
        (left, top, width, height)；取不到时返回 **None**（不是 (0,0,0,0)）。

        为什么不能用 (0,0,0,0) 兜底：Kimi 第四轮复核指出 ——
        元素已销毁、offscreen、或 BoundingRectangle 取异常时都会得到空矩形，
        center 于是算出 (0,0)，调用方会**真的去点屏幕左上角**。
        宁可返回 None 让调用方显式处理，也不要给出一个"看起来合法"的假坐标。
        """
        try:
            r = self._c.BoundingRectangle
            w, h = r.right - r.left, r.bottom - r.top
            if w <= 0 or h <= 0:
                return None
            return (r.left, r.top, w, h)
        except Exception:
            return None

    @property
    def center(self) -> Optional[Tuple[int, int]]:
        """元素中心的屏幕坐标；矩形无效时返回 None（调用方必须判空）"""
        rc = self.rect
        if rc is None:
            return None
        l, t, w, h = rc
        return (l + w // 2, t + h // 2)

    def is_actionable(self) -> Tuple[bool, str]:
        """能不能安全地点它 —— 落键前的最后一道检查"""
        if not self.enabled:
            return False, "控件已禁用"
        if self.offscreen:
            return False, "控件在屏幕外"
        if self.rect is None:
            return False, "控件矩形无效（可能已销毁）"
        return True, ""

    @property
    def enabled(self) -> bool:
        try:
            return bool(self._c.IsEnabled)
        except Exception:
            return False

    @property
    def offscreen(self) -> bool:
        try:
            return bool(self._c.IsOffscreen)
        except Exception:
            return True

    @property
    def value(self) -> Optional[str]:
        """控件的当前值（输入框内容等）—— 人类动手前会先看一眼"""
        try:
            vp = self._c.GetValuePattern()
            if vp:
                return vp.Value
        except Exception:
            pass
        try:
            tp = self._c.GetTextPattern()
            if tp:
                return tp.DocumentRange.GetText(200)
        except Exception:
            pass
        try:
            return self._c.Name or ""
        except Exception:
            return None

    def to_dict(self) -> dict:
        rc = self.rect
        ctr = self.center
        return {"name": self.name, "control_type": self.control_type,
                "class": self.class_name, "automation_id": self.automation_id,
                "rect": rc, "center": ctr,          # 无效时是 None，调用方须判空
                "enabled": self.enabled, "offscreen": self.offscreen,
                "value": self.value}

    def __repr__(self):
        rc = self.rect
        where = f"@({rc[0]},{rc[1]},{rc[2]},{rc[3]})" if rc else "@(无效矩形)"
        return f"<{self.control_type} {self.name!r} {where}>"

    # ── 操作（走本技能的拟人化层，不是 UIA 的 Invoke） ──
    def click(self, human: bool = True, verify: bool = False):
        """
        点击这个元素。

        刻意**不用** UIA 的 InvokePattern：那是"程序化触发"，
        没有鼠标轨迹、没有人类节奏，而且绕过了一些只有真实点击才会触发的行为。
        这里取到坐标后交给 mouse 模块做拟人化点击。

        `human=False` 时用裸鼠标事件（不做轨迹，且 down/up 用 try/finally 保证成对）。
        `verify=True` 时点击后多等 0.35s 让界面稳定 —— **注意：它不做指纹比对**，
        只提供缓冲时间；真正要验证"界面确实变了"请用 `safe.safe_click(expect_change=True)`。
        （第六轮复核指出：此处 docstring 原先写"比对界面指纹"，
          而代码只 sleep，属"声明与实现不符"，本项目一直在清这类问题。）
        """
        m = _sibling("mouse")
        if m is None:
            raise RuntimeError("mouse 模块不可用（依赖缺失或导入失败）")
        okk, why = self.is_actionable()
        if not okk:
            raise RuntimeError(f"控件不可点击：{why}")
        # 重新取一次坐标并判空 —— is_actionable 通过 ≠ 下一次读取有效
        # （两次读取之间控件可能被销毁/移出屏幕，Codex 隔离桩已复现 TypeError）
        ctr = self.center
        if ctr is None:
            raise RuntimeError("控件矩形在检查后变为无效（可能已被销毁），已停手")
        cx, cy = ctr
        if human:
            m.click(cx, cy)
        else:
            import win32api
            import win32con
            win32api.SetCursorPos((cx, cy))
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            try:
                time.sleep(0.06)
            finally:
                # Codex #5：down 之后必须有 finally ——
                # 否则这段 sleep 抛异常会让鼠标键永久按住
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        if verify:
            time.sleep(0.35)
        return (cx, cy)

    def double_click(self):
        m = _sibling("mouse")
        if m is None:
            raise RuntimeError("mouse 模块不可用（依赖缺失或导入失败）")
        okk, why = self.is_actionable()
        if not okk:
            raise RuntimeError(f"控件不可双击：{why}")
        ctr = self.center
        if ctr is None:
            raise RuntimeError("控件矩形在检查后变为无效（可能已被销毁），已停手")
        cx, cy = ctr
        m.double_click(cx, cy)
        return (cx, cy)

    def set_value(self, text: str, mode: str = "replace", pid: int = None,
                  title_kw: str = None):
        """
        往这个控件里输入文字。

        **验证必须在任何击键之前** —— 这条是两个独立复核（Kimi R5-1 / Codex #7）共同
        指出的：初版虽然把"输入"接进了 safe.safe_type，但 replace 模式下的
        「全选 + 删除」却发生在三重锁验证**之前**。清空比输入更具破坏性 ——
        若点击落点偏了（元素在 is_actionable 与 click 之间移动、弹窗抢焦点），
        ctrl+a + delete 会打在用户的前台窗口里，从「打字打错地方」变成「删除删错地方」，
        与原事故同族。

        现在的执行序：
          ① pid 非空 → 先做锁1(PID) + 锁2(标题) 校验（**点击之前**）
          ② 点击拿焦点
          ③ 复查锁3（前台）—— 不在前台就停手，一个键都不发
          ④ 清空（replace 模式）
          ⑤ 输入
          ⑥ 回读验证

        mode:
          "replace" —— 全选清空后输入（默认）
          "append"  —— 移到内容末尾再输入（Ctrl+End），不清空
          "insert"  —— 只把光标点过去就输入，不清空也不定位
        """
        # ── 参数校验（非法 mode 直接拒绝，不静默接受）──
        if mode not in ("replace", "append", "insert"):
            raise ValueError(f"未知 mode: {mode!r}（只支持 replace / append / insert）")

        kb = _sibling("keyboard")
        safe = _sibling("safe")
        w = _sibling("window")
        m = _sibling("mouse")
        if kb is None or m is None:
            raise RuntimeError("keyboard / mouse 模块不可用（依赖缺失或导入失败）")

        okk, why = self.is_actionable()
        if not okk:
            raise RuntimeError(f"控件不可输入：{why}")

        # ① 点击之前先验锁 1 / 锁 2（Kimi R5-1 的修法）
        if pid is not None and safe is not None:
            try:
                tgt = safe.Target(pid)
                # 只验 PID 与标题，不要求前台（此刻还没点击，窗口未必在前台）
                tgt.verify(title_kw, must_foreground=False)
            except Exception as exc:
                return {"ok": False, "mode": mode, "verified": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "note": "锁1/锁2 未通过，**一个键都没有发出**"}

        # ② 点击拿焦点（坐标在这次读取时取，避免与 is_actionable 的读取之间产生竞态）
        ctr = self.center
        if ctr is None:
            raise RuntimeError("控件矩形在检查后变为无效（可能已被销毁），已停手")
        cx, cy = ctr
        m.click(cx, cy)
        time.sleep(0.3)

        # ③ 点击之后复查锁 3（前台）—— 不通过就停手，绝不发键
        if pid is not None and safe is not None:
            try:
                tgt2 = safe.Target(pid)
                tgt2.verify(title_kw, must_foreground=True)
            except Exception as exc:
                return {"ok": False, "mode": mode, "verified": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "note": "锁3（前台）未通过，**清空与输入都没有执行**"}

        # ④ 清空 / 定位
        if mode == "replace":
            kb.press("ctrl+a")
            time.sleep(0.2)
            kb.press("delete")
            time.sleep(0.25)
        elif mode == "append":
            kb.press("ctrl+end")      # 移到末尾，与 insert 区分开
            time.sleep(0.2)

        # ⑤ 输入（走 safe_type 时它会再验一次并回读）
        if pid is not None and safe is not None:
            res = safe.safe_type(pid, text, title_kw=title_kw, expect_readback=True)
            return {"ok": bool(res.get("verified")), "mode": mode,
                    "verified": res.get("verified"), "readback": res.get("readback"),
                    "note": res.get("note")}
        kb.type_text(text)
        time.sleep(0.3)
        note = ("未传 pid，无法做三重锁验证与回读；建议传 pid"
                if pid is None else
                "safe 模块不可用，已退化为普通输入（无三重锁、无回读）")
        return {"ok": None, "mode": mode, "verified": None, "note": note}

    def read_value(self):
        """读这个控件当前的文本（WM_GETTEXT；自绘控件可能读不到，返回 None）"""
        w = _sibling("window")
        if w is None:
            return None
        try:
            return w.read_control_text(self._c.NativeWindowHandle)
        except Exception:
            return None

    def exists(self, timeout: float = 1.0) -> bool:
        try:
            return bool(self._c.Exists(maxSearchSeconds=timeout))
        except Exception:
            return False


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
        # 有包上下文时**只走包内导入**：
        # 失败就返回 None，绝不回退顶层 ——
        # 否则会拿到同名的顶层模块（第三方 mouse/keyboard 包），造成身份分裂。
        # （Codex 复核指出：初版失败后仍回退顶层，三份实现都复现了这个问题）
        try:
            return importlib.import_module("." + name, pkg)
        except Exception:
            return None
    try:
        return importlib.import_module(name)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
# 定位
# ══════════════════════════════════════════════════════════
def window_of_pid(pid: int):
    """取某进程的主窗口 UIA 节点"""
    _require()
    import win32gui
    w = _sibling("window")
    hwnd = w.main_hwnd(pid) if w else None
    if not hwnd:
        # 退化：枚举该进程任意可见窗口
        found = []
        def cb(h, _):
            try:
                if not win32gui.IsWindowVisible(h):
                    return
                import win32process
                _, wp = win32process.GetWindowThreadProcessId(h)
                if wp == pid:
                    found.append(h)
            except Exception:
                pass
        win32gui.EnumWindows(cb, None)
        hwnd = found[0] if found else None
    if not hwnd:
        return None
    try:
        return auto.ControlFromHandle(hwnd)
    except Exception:
        return None


def dump_tree(pid: int, max_depth: int = 4, limit: int = 200) -> List[dict]:
    """
    把某进程的控件树摊平成列表（人类「扫一眼界面上有什么」的等价物）。

    返回 [{"depth":.., "name":.., "control_type":.., "rect":.., "center":..}, ...]
    """
    _require()
    root = window_of_pid(pid)
    if root is None:
        return []
    out = []

    def walk(ctrl, depth):
        if depth > max_depth or len(out) >= limit:
            return
        try:
            children = ctrl.GetChildren()
        except Exception:
            return
        for ch in children:
            if len(out) >= limit:
                return
            try:
                el = Element(ch)
                d = el.to_dict()
                d["depth"] = depth
                out.append(d)
            except Exception:
                continue
            walk(ch, depth + 1)

    walk(root, 1)
    return out


def _match(el: Element, name=None, control_type=None, automation_id=None,
           contains=True, enabled_only=False) -> bool:
    if name is not None:
        n = el.name
        if contains:
            if name not in n:
                return False
        else:
            if n != name:
                return False
    if control_type is not None and control_type.lower() not in el.control_type.lower():
        return False
    if automation_id is not None and el.automation_id != automation_id:
        return False
    if enabled_only and not el.enabled:
        return False
    return True


def find(pid: int = None, name: str = None, control_type: str = None,
         automation_id: str = None, contains: bool = True,
         enabled_only: bool = False, max_depth: int = 8,
         hwnd: int = None) -> Optional[Element]:
    """
    找一个控件。三种定位方式可单用也可组合：
        find(pid=123, name="确定")                    → 按名字
        find(pid=123, control_type="Button")          → 按类型
        find(hwnd=456, automation_id="btnOk")         → 按 AutomationId

    返回 Element，找不到返回 None。
    """
    _require()
    if hwnd:
        root = auto.ControlFromHandle(hwnd)
    elif pid is not None:
        root = window_of_pid(pid)
    else:
        raise ValueError("必须给 pid 或 hwnd")
    if root is None:
        return None
    try:
        ctrl = root.Control(searchDepth=max_depth,
                            Name=name if (name and not contains) else None)
        if ctrl and ctrl.Exists(0.5):
            el = Element(ctrl)
            if _match(el, name, control_type, automation_id, contains, enabled_only):
                return el
    except Exception:
        pass

    # 退化为整棵树遍历（支持"包含匹配"和组合条件）
    for d in _walk(root, max_depth):
        el = Element(d)
        if _match(el, name, control_type, automation_id, contains, enabled_only):
            return el
    return None


def find_all(pid: int = None, name: str = None, control_type: str = None,
             contains: bool = True, enabled_only: bool = False,
             max_depth: int = 8, limit: int = 50, hwnd: int = None) -> List[Element]:
    """找出所有匹配的控件"""
    _require()
    root = auto.ControlFromHandle(hwnd) if hwnd else window_of_pid(pid)
    if root is None:
        return []
    out = []
    for ctrl in _walk(root, max_depth):
        el = Element(ctrl)
        if _match(el, name, control_type, None, contains, enabled_only):
            out.append(el)
            if len(out) >= limit:
                break
    return out


def _walk(ctrl, max_depth, depth=1, max_nodes=2000):
    """
    深度优先遍历所有后代控件。

    加 max_nodes 上限：Kimi 第四轮指出 ——
    对浏览器/IDE 这类上万节点的窗口，「找一个不存在的名字」会遍历整棵树，
    可能耗时数十秒。dump_tree 本来就有 limit=200，_walk 却没有上限。
    """
    if depth > max_depth:
        return
    try:
        children = ctrl.GetChildren()
    except Exception:
        return
    count = 0
    for ch in children:
        if count >= max_nodes:
            return
        count += 1
        yield ch
        for sub in _walk(ch, max_depth, depth + 1, max_nodes - count):
            yield sub
            count += 1
            if count >= max_nodes:
                return


def wait_for(pid: int = None, name: str = None, control_type: str = None,
             timeout: float = 10.0, interval: float = 0.4,
             hwnd: int = None) -> Optional[Element]:
    """
    等某个控件出现（人类等界面加载的等价物）。
    超时返回 None。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        el = find(pid=pid, name=name, control_type=control_type, hwnd=hwnd)
        if el is not None and not el.offscreen:
            return el
        time.sleep(interval)
    return None


def click_by_name(pid: int, name: str, verify_foreground: bool = True):
    """
    「看到名字就点」—— 最接近人类的一句话操作。

    定位走 UIA，点击走技能内的拟人化 + 三重锁。
    返回 (成功, 详情)。
    """
    w = _sibling("window")
    safe = _sibling("safe")
    try:
        el = find(pid=pid, name=name)
    except Exception as exc:
        # find 在 UIA 不可用时抛 RuntimeError；这里保持"返回 (成功, 详情)"的契约
        return False, f"{type(exc).__name__}: {exc}"
    if el is None:
        return False, f"界面上找不到名字含 {name!r} 的控件"
    okk, why = el.is_actionable()
    if not okk:
        return False, f"找到控件但不可操作：{why}"
    ctr = el.center
    if ctr is None:
        return False, "控件矩形无效，无法定位"
    cx, cy = ctr
    try:
        if safe is not None and verify_foreground:
            # 用三重锁路径点击（PID + 标题 + 前台）
            title = w.Win.by_pid(pid).title if w else None
            kw = title[:6] if title else None
            safe.safe_click(pid, cx, cy, title_kw=kw, coord_space="screen",
                            expect_change=False)
        else:
            el.click()
        return True, f"点了 {el.control_type} {el.name!r} @{cx},{cy}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ══════════════════════════════════════════════════════════
# 自查
# ══════════════════════════════════════════════════════════
def doctor():
    caps = [
        ("is_available()", "UIA 是否可用"),
        ("window_of_pid(pid)", "取某进程窗口的 UIA 根节点"),
        ("dump_tree(pid)", "摊平整棵控件树（扫一眼界面上有什么）"),
        ("find(...)", "按名字/类型/AutomationId 定位控件"),
        ("find_all(...)", "找出所有匹配控件"),
        ("wait_for(...)", "等控件出现"),
        ("click_by_name(pid, name)", "「看到名字就点」——定位+拟人化点击"),
        ("Element.center / rect", "元素坐标（可直接喂给 mouse）"),
        ("Element.value", "读控件当前值（动手前先看清）"),
        ("Element.click / set_value", "元素级操作（走技能的拟人化层）"),
    ]
    for n, d in caps:
        print(f"  [OK] {n:<28} {d}")
    print()
    print(f"  uiautomation 可用: {_UIA_OK}")
    if _UIA_OK:
        try:
            import uiautomation as _a
            print(f"  版本: {getattr(_a, 'VERSION', '?')}")
        except Exception:
            pass
    return len(caps)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        doctor()
    else:
        print(__doc__)
