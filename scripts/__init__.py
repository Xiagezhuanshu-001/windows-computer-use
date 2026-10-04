# -*- coding: utf-8 -*-
"""
gui_agent —— 像人一样操作 Windows 的完整能力包
================================================

一句话：**凡是人用鼠标键盘能做到的，这个包都能做到，而且带着人的特征。**

模块划分
--------
    mouse     鼠标：移动/单击/双击/三击/右键/中键/拖拽/滑块/滚轮/悬停/长按/框选
    keyboard  键盘：打字/中文/组合键/功能键/数字键盘/长按/输入法切换
    window    窗口：激活/最大化/最小化/调整大小/拖动/分屏/截图/剪贴板
    vision    视觉：屏幕找文字（OCR）/找图标（模板匹配）  —— 需额外依赖
    safe      安全：坐标换算/三重锁验证/操作后确认/精确撤销

设计原则（来自 2026-10-03 的 6 次真实事故）
------------------------------------------
    1. **验证密度 > 动作精度**：人类稳，是因为每一步都在看
    2. **禁止标题模糊匹配窗口**：必须 PID 锁定（事故：打字打进了用户的密钥文件）
    3. **撤销次数必须精确**：绝不"多按几次保险"（事故：多撤销 27 步）
    4. **坐标换算必须由代码完成**：不靠心算（事故：点错按钮）
    5. **破坏性按键有明确的次数和后果**：能说清才允许执行

快速开始
--------
    import sys
    sys.path.insert(0, r"<技能目录>\scripts")
    import mouse, keyboard, window

    # 找到目标窗口（必须用 PID）
    w = window.Win.by_pid(12345)
    w.activate()

    # 拟人化点击
    mouse.click(500, 300)

    # 输入并提交
    keyboard.type_and_submit("hello")

安全用法（推荐）
----------------
    import safe
    safe.safe_click(pid=12345, x=100, y=50, title_kw="记事本")   # 带三重锁验证
    safe.undo_exact(3, pid=12345)                               # 精确撤销 3 次

作者：虾哥（DSH）
建立：2026-10-03
"""

__version__ = "1.0.0"
__all__ = ["mouse", "keyboard", "window", "vision", "input_inject", "safe", "locate"]

# 延迟导入：避免在缺少 pywin32 时整个包都不可用
# 注意：必须用相对导入，否则可能撞上第三方同名包（如 pip 里的 mouse/keyboard）
try:
    from . import mouse
except Exception as _e:
    import warnings
    warnings.warn(f"gui_agent.mouse 导入失败: {_e}")
    mouse = None

try:
    from . import keyboard
except Exception as _e:
    import warnings
    warnings.warn(f"gui_agent.keyboard 导入失败: {_e}")
    keyboard = None

try:
    from . import window
except Exception as _e:
    import warnings
    warnings.warn(f"gui_agent.window 导入失败: {_e}")
    window = None

try:
    from . import vision
except Exception as _e:
    import warnings
    warnings.warn(f"gui_agent.vision 导入失败: {_e}")
    vision = None

try:
    from . import input_inject
except Exception as _e:
    import warnings
    warnings.warn(f"gui_agent.input_inject 导入失败: {_e}")
    input_inject = None

try:
    from . import safe
except Exception as _e:
    import warnings
    warnings.warn(f"gui_agent.safe 导入失败: {_e}")
    safe = None

try:
    from . import locate
except Exception as _e:
    import warnings
    warnings.warn(f"gui_agent.locate 导入失败: {_e}")
    locate = None


def capabilities():
    """汇总本包的全部能力（供审计与 SKILL 文档使用）"""
    result = {}
    for name, mod in (("mouse", mouse), ("keyboard", keyboard), ("window", window), ("vision", vision), ("input_inject", input_inject), ("safe", safe), ("locate", locate)):
        if mod is None:
            result[name] = {"status": "unavailable"}
            continue
        # 列出公开函数
        fns = [n for n in dir(mod) if not n.startswith("_") and callable(getattr(mod, n, None))]
        result[name] = {"status": "ok", "functions": sorted(fns)}
    return result


def summary():
    """打印能力汇总"""
    caps = capabilities()
    total = 0
    for name, info in caps.items():
        if info["status"] != "ok":
            print(f"  [{name}] 不可用")
            continue
        fns = [f for f in info["functions"] if not f[0].isupper()]
        total += len(fns)
        print(f"  [{name}] {len(fns)} 个公开函数")
        for f in fns:
            print(f"        {f}")
    print(f"\n  合计 {total} 个公开函数")
    return total
