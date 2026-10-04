---
name: windows-computer-use
description: 像人一样操作 Windows 桌面 —— 鼠标（含双击/拖拽/滑块/滚轮）、键盘（含中文/组合键/长按）、窗口（含分屏/调整）、视觉（OCR/找图）；带三重锁验证与拟人化特征，专治"点错、打错、撤错"
triggers:
  - 控制电脑
  - 操作桌面
  - GUI 自动化
  - computer use
  - 点击按钮
  - 鼠标点击
  - 双击
  - 右键菜单
  - 拖拽
  - 滑块验证码
  - 滑动滑块
  - 键盘输入
  - 打字
  - 输入中文
  - 组合键
  - 快捷键
  - 滚动页面
  - 滚轮
  - 窗口最大化
  - 窗口分屏
  - 调整窗口大小
  - 截图
  - 剪贴板
  - 模拟人工操作
  - 自动化点击
  - gui_agent
  - 拟人化
---

# windows-computer-use

> **凡是人用鼠标键盘能做到的，这个技能都能做到 —— 而且带着人的特征。**
>
> **2026-10-04 重大升级**：新增 UI Automation 定位层（`locate.py`），
> 技能从此**自己「看得见」界面结构**，不再只能靠 OCR 猜像素。
> 实测定位速度：**UIA 0.12s vs OCR 10.7s，快约 100 倍**（四次留档实测 88-101 倍），且拿到的是控件语义而非像素。
>
> 建立于 2026-10-03，起因是虾哥在一天内操作电脑失误 6 次，涛哥要求"提升到人一样的高度"。

---

## 一、为什么需要这个技能

**2026-10-03 的 6 次真实事故**（全部有据可查）：

| # | 事故 | 根因 | 本技能的防护 |
|---|---|---|---|
| 1 | 点「插件」点成了「新会话」 | 截图坐标未按缩放倍率换算 | `Snapshot.to_screen()` 自动换算 |
| 2 | **打字打进了用户的 API 密钥文件** | 按标题模糊匹配窗口 | `Win.by_pid()` **只认 PID**，禁止标题匹配 |
| 3 | Ctrl+Z 撤销 80 次但只打了 53 字符 | 多撤销 27 步，撤销进了原有内容 | `undo(times)` **精确次数** |
| 4 | 坐标点击点偏 | 用了过期 3 秒以上的 ax tree | `assert_fresh(ttl=3.0)` |
| 5 | 点击对 Chromium 渲染器无效 | 不知道后端兼容性差异 | 多层降级 + 操作后验证 |
| 6 | 反复重算窗口坐标 | 没有统一换算规范 | 换算由代码完成，不靠心算 |

**还有一个只有实测才能发现的 bug**：

```
中文输入法活动时，用 keybd_event 发字母键会被 IME 截获
  实测：输入 "abc123" → 界面收到 "ABC23"（大小写反转 + 数字丢失）
  解法：SendInput + KEYEVENTF_UNICODE 直接投递 Unicode，绕过 IME
```

---

## 二、核心原则

```
验证密度 > 动作精度
```

**人类操作电脑之所以稳，不是因为手稳，是因为每一步都在看**：

```
人类：看半天 → 移过去 → 停下再看 → 点 → 立刻看结果 → 不对就退回来
机器：算坐标 → 直接点 → 不看结果 →（错了）→ 重试
```

**这个技能把"看"变成了强制步骤。**

### 五步法 SOP

```
【看】截图 + 取窗口信息
【认】坐标换算 + 三重锁验证（PID / 标题 / 前台）
【动】拟人化执行（带轨迹、变速、抖动、随机延迟）
【验】操作后对比界面指纹，没变就是失败
【记】成功路径复用，失败路径避免重蹈
```

---

## 三、动手前的第一问：**这个活该不该用鼠标？**

**这条原则来自 2026-10-04 的全网调研**（stevenke1981/windows-agent-skill 的决策树），
它比我此前所有优化都更根本：

```
能用命令行（PowerShell / CLI）解决  →  绝对不要动鼠标
能用 API / COM 解决                →  不要模拟点击
只剩 GUI 一条路                     →  才用本技能
```

**可靠性差一个数量级**：

| 方式 | 典型可靠性 | 说明 |
|---|---|---|
| 命令行 / API | 极高 | 确定性、可断言、失败会报错 |
| COM / 脚本接口 | 高 | 结构化，但仍受应用状态影响 |
| **GUI 模拟点击** | **低** | 受焦点、遮挡、DPI、时序、动画影响 |

**为什么把这条写在这里**：我此前一直在琢磨「怎么把鼠标操作做稳」，
但正确的顺序是**先问「该不该用鼠标」** ——
如果一个任务能用 `Get-ChildItem` 解决，我却去截图找文件夹图标点开，
那是**自己给自己制造失败机会**。

**本技能的定位因此明确**：
> 它是**最后一道手段**，不是第一选择。
> 当确实没有命令行/API 路径时（比如操作一个只有图形界面的第三方软件），
> 才由它来保证「点得准、动得像人、做完能确认」。

## 四、能力清单（7 个模块 / **98 个模块级函数 + 57 个类方法 = 155 个公开 API**，另有 7 个 doctor）

> **口径校验命令**（数字以此为准，文档数字与它不一致就是文档错）：
> ```bash
> # 只统计 7 个能力模块，排除 test_*/target_*/__init__
> python -c "
> import ast, os
> MODS = ['mouse','keyboard','window','vision','input_inject','safe','locate']
> t = 0
> for m in MODS:
>     p = os.path.join('scripts', m + '.py')
>     n = len([x for x in ast.parse(open(p, encoding='utf-8').read()).body
>              if isinstance(x, ast.FunctionDef) and not x.name.startswith('_') and x.name != 'doctor'])
>     t += n
>     print(f'{m:<14}{n:>3}')
> print('模块级合计', t, '（文档应写', t, '）')
> "
> ```

> **表格说明**：下面各表**按「人类动作」分组**，一个动作可能合并列出多个函数
> （例如 `double_click / triple_click` 是同一行）。因此**表格行数少于标题里的函数数**，
> 这是刻意的分组呈现，不是漏列。

### 鼠标 `mouse.py` — 21 个模块级函数（+ `Human` 类 2 个）

| 函数 | 人类动作 |
|---|---|
| `move(x, y)` | 移动光标（贝塞尔弧线 + 缓入缓出 + 抖动 + 过冲回拉） |
| `hover(x, y, ms)` | 悬停（触发 tooltip） |
| `click(x, y, button, clicks)` | 单击 / 双击 / 三击 |
| `double_click` / `triple_click` | 双击 / 三击（选整段） |
| `right_click` / `middle_click` | 右键 / 中键 |
| `long_press(x, y, ms)` | 长按不放 |
| `ctrl_click` / `shift_click` | Ctrl+点击（多选） / Shift+点击（范围选） |
| `wheel_up` / `wheel_down` | 滚轮上下（分段滚，不是一次到底） |
| `wheel_horizontal` | 横向滚轮 |
| `wheel_zoom` | Ctrl+滚轮缩放 |
| `drag(x1,y1,x2,y2)` | 拖拽（**滑块验证码专用**：起步缓/中段冲/末端微调） |
| `rubber_band` | 框选 |
| `drag_drop` | 拖放（带对准停顿） |

### 键盘 `keyboard.py` — 31 个模块级函数（+ `Typing` 类 1 个）

| 函数 | 人类动作 |
|---|---|
| `type_text(text)` | **智能输入**：Unicode 注入绕过输入法，失败降级剪贴板 |
| `press("ctrl+s")` | 任意组合键 |
| `hold_key(key, ms)` | 长按（finally 保证松开，不会卡键） |
| `shift_hold_select` | 按住 Shift + 方向键连续选择 |
| `numpad("123")` | 数字键盘（自动处理 NumLock） |
| `toggle_ime()` | 输入法切换（Win+Space） |
| `select_all/copy/cut/paste` | 剪贴板四件套 |
| `undo(n)` / `redo(n)` | 撤销重做（**精确次数**） |
| `type_and_submit(text)` | 输入并回车 |
| 另含 89 个键位 | F1-F12 全、导航键、数字键盘、媒体键、浏览器键 |

### 窗口 `window.py` — 12 个模块级函数 + `Win` 类 26 个方法

**计数口径说明**（初版口径未声明，经三轮复核修正）：
- **模块级函数**：98 个（mouse 21 / keyboard 31 / window 12 / vision 11 / input_inject 10 / safe 6 / locate 7）
- **类方法**：57 个（`Win` 26 / `Element` 16 / `Snapshot` 7 / `Target` 5 / `Human` 2 / `Typing` 1）
- **公开 API 总计**：**155 个**
- 另有 **7 个** `doctor` 自查函数（每个模块一个），不计入能力。
- **口径唯一来源**：`ast` 静态分析（不导入、不碰 GUI），见下方校验命令。

下面这 12 个是 window 的**模块级函数**；`Win` 类的 26 个方法见后。

**模块级函数 12 个**：

| 函数 | 人类动作 |
|---|---|
| `list_windows()` | 列出所有可见窗口（挑 PID 用） |
| `windows_of_pid(pid)` | 按 PID 枚举窗口 |
| `main_hwnd(pid)` | 取该 PID 的主窗口句柄 |
| `wait_for_window(pid, timeout)` | 等窗口出现 |
| `wait_until_foreground(pid)` | 等窗口变前台 |
| `clipboard_get/set/clear` | 剪贴板读写清 |
| `screenshot_full()` | 全屏截图 |
| `read_control_text(hwnd)` | **读控件文本**（WM_GETTEXT） |
| `read_text_at(x, y)` / `window_text_list(pid)` | **按坐标读控件文本 / 枚举窗口内所有控件文本** |

**`Win` 类的 26 个方法**：

| 分类 | 方法 |
|---|---|
| 构造与存活 | `by_pid(pid)` · `alive()` · `assert_alive()` |
| 查询 | `title` · `pid` · `rect()` · `size()` · `is_minimized()` · `is_maximized()` · `is_foreground()` |
| 激活与状态 | `activate()` · `maximize()` · `minimize()` · `restore()` · `topmost(on)` |
| 几何 | `resize(w, h)` · `move_to(x, y)` · `set_bounds(...)` |
| 拟人化 | `drag_by_title(dx, dy)` · `toggle_maximize()` · `snap_left()` · `snap_right()` |
| 生命周期 | `close(graceful)` · `force_close()` |
| 影像 | `screenshot(path)` · `snapshot()` |



| 函数 | 人类动作 |
|---|---|
| `Win.by_pid(pid)` | **按 PID 锁定窗口**（禁止标题模糊匹配） |
| `activate()` / `maximize()` / `minimize()` / `restore()` | 激活 / 最大化 / 最小化 / 还原 |
| `resize(w, h)` / `move_to(x, y)` / `set_bounds(...)` | 调整大小 / 移动 |
| `drag_by_title(dx, dy)` | 抓标题栏拖动窗口 |
| `snap_left()` / `snap_right()` | 左右半屏分屏 |
| `clipboard_get/set/clear` | 剪贴板读写清 |
| `wait_for_window` / `wait_until_foreground` | 等待窗口出现 / 变前台 |

### 视觉 `vision.py` — 11 个模块级函数

| 函数 | 人类动作 |
|---|---|
| `grab(region)` | 截屏（全屏或指定区域） |
| `find_image(tpl)` | **找图**（归一化互相关 + 粗扫精修），返回中心坐标与相似度 |
| `find_all_images(tpl)` | 找出所有匹配位置（邻域去重） |
| `wait_for_image(tpl, timeout)` | 等图标出现 |
| `wait_for_image_gone(tpl)` | 等图标消失（等加载完成） |
| `find_color(rgb)` | 按颜色找像素 |
| `find_all_colors(rgb)` | 找出所有同色位置（聚类） |
| `read_text(region)` | **OCR 读屏幕文字**（rapidocr，纯 CPU） |
| `find_text(s)` | 找文字（支持包含匹配） |
| `click_text(s)` | **找到文字并点击** —— 最接近"看到按钮就按" |

### 定位层 `locate.py` — 7 个模块级函数 + `Element` 类 16 个方法 ★ 让技能自己看得见

**这是 2026-10-04 新增的能力，补上了本技能此前最大的短板。**

在此之前，技能不知道界面上有什么按钮，只知道「在坐标 (100,200) 按下鼠标」；
定位只能靠 OCR（全屏扫描 ~10 秒）或模板匹配，拿到的是「像素像文字」。

现在直接读 Windows UI Automation 无障碍树：

| 函数 | 作用 |
|---|---|
| `is_available()` | UIA 是否可用 |
| `window_of_pid(pid)` | 取某进程窗口的 UIA 根节点 |
| `dump_tree(pid)` | **摊平整棵控件树** —— 「扫一眼界面上有什么」 |
| `find(pid, name=/control_type=/automation_id=)` | **按名字/类型/ID 定位控件** |
| `find_all(...)` | 找出所有匹配控件 |
| `wait_for(...)` | 等控件出现 |
| `click_by_name(pid, name)` | **「看到名字就点」** —— 定位 + 拟人化点击 + 三重锁 |
| `Element.center` / `rect` | 元素坐标（可直接喂给 `mouse`） |
| `Element.value` | **读控件当前值**（动手前先看清输入框里有什么） |
| `Element.click` / `set_value` | 元素级操作（**走技能的拟人化层，不用 UIA 的 Invoke**） |

**实测数据**：

```
取窗口根节点      : 0.041s
摊平 74 个控件     : 0.263s
按名字找按钮       : 0.116s
OCR 全屏扫描       : 10.69s
                    → UIA 快约 100 倍（留档实测 88-101 倍）

dump_tree 输出示例（真实靶子）:
  [EditControl]
  [ListControl]
    [ScrollBarControl] '垂直滚动条'
      [ButtonControl] '上一行'
      [ThumbControl] '位置'
      [ButtonControl] '下一行'
    [ListItemControl] 'item_00'
    [ListItemControl] 'item_01'
```

**设计取舍**：`Element.click()` **刻意不用 UIA 的 `InvokePattern`** ——
那是"程序化触发"，没有鼠标轨迹、没有人类节奏，还会绕过一些只有真实点击才触发的行为。
这里的做法是：**用 UIA 拿到坐标，再交给 `mouse` 做拟人化点击**。
**"看得见"用 UIA，"怎么动"用人类的方式。**

### 安全层 `safe.py` — 6 个模块级函数 + `Snapshot` 7 方法 + `Target` 5 方法 ★ 技能自包含

**这就是本文档反复强调的「三重锁验证」与「操作后确认」的实现 —— 它就在技能目录里，不是外部依赖。**

| 函数/类 | 作用 |
|---|---|
| `Target.verify(pid, title_kw)` | **三重锁**：锁1 PID 属于预期进程 / 锁2 标题含预期关键词 / 锁3 窗口在前台 |
| `safe_click(pid, x, y, ...)` | 带验证的点击：三重锁 → 快照 → 坐标换算 → 越界检查 → 点击 → **指纹对比确认** |
| `safe_type(pid, text, ...)` | 带验证的输入：不在前台就**拒绝输入** |
| `undo_exact(n, pid)` | **精确撤销 n 次**，绝不"多按几次保险" |
| `Snapshot.from_pid(pid)` | 抓窗口快照（截图 + 窗口矩形 + 缩放倍率） |
| `Snapshot.to_screen(x, y)` | **截图坐标 → 屏幕绝对坐标**，自动换算，不靠心算 |
| `Snapshot.assert_fresh(ttl)` | 快照过期检查（默认 3 秒） |
| `Snapshot.fingerprint()` | 界面指纹，用于"操作后确认" |
| `wait_for_change(pid, before_fp)` | 轮询等界面变化 |
| `find_main_hwnd(pid)` | 按 PID 找主窗口（**只认 PID，禁止标题模糊匹配**） |
| `TargetMismatch` / `VerifyFailed` / `StaleSnapshot` | 三种异常，让失败**显式暴露**而不是静默 |

### 低层注入 `input_inject.py` — 10 个模块级函数

| 函数 | 用途 |
|---|---|
| `send_unicode_char(ch)` | **绕过输入法**投递单个字符 |
| `send_unicode_text(text)` | 逐字符注入 + 人类打字节奏 |
| `send_vk(vk)` / `send_combo([vk])` | 虚拟键 / 组合键（SendInput 版） |
| `send_scancode(vk)` | 硬件扫描码（游戏等只认扫描码的控件） |
| `toggle_state()` / `set_capslock(on)` | 开关锁状态查询与设置 |
| `ime_active_window()` | 判断当前是否处于中文输入状态 |

---

## 五、快速开始

```python
import sys
sys.path.insert(0, r"<你的技能目录>\scripts")   # 例如 %USERPROFILE%\.agents\skills\windows-computer-use\scripts

import mouse, keyboard, window

# ① 先按 PID 锁定窗口（绝不用标题模糊匹配）
w = window.Win.by_pid(12345)      # 12345 换成目标进程 PID
w.activate()                       # 激活到前台并确认

# ② 拟人化点击
mouse.click(500, 300)              # 左键单击
mouse.double_click(500, 300)       # 双击
mouse.right_click(500, 300)        # 右键

# ③ 输入（自动绕过输入法）
keyboard.type_text("你好 hello 123")
keyboard.press("ctrl+s")

# ④ 滑块验证码
mouse.drag(600, 400, 1100, 400)    # 专用的变速+微调轨迹

# ⑤ 窗口操作
w.snap_left()                      # 左半屏
w.resize(1200, 800)
```

**拿到 PID 的方法**：

```python
import window
for r in window.list_windows():
    print(r["pid"], r["title"])
```

---

## 六、与 MCP 工具的关系（重要）

本技能与 `kimi-cu` / `windows-mcp` **不是替代关系，而是互补**：

| 能力 | MCP 工具 | 本技能 |
|---|---|---|
| 看懂界面结构 | ✅ 无障碍树 | ✅ **现在也有了**（`locate.py`，底层同为 UIA） |
| 拟人化操作 | ❌ 瞬间移动 | ✅ 贝塞尔轨迹 + 人类节奏 |
| 三重锁验证 | ❌ | ✅ PID + 标题 + 前台 |
| 操作后确认 | 要手动再截图 | ✅ 界面指纹自动比对 |
| 精确撤销 / 卡键救援 | ❌ | ✅ |
| 调用开销 | MCP 协议往返 | 本地函数调用 |

**推荐用法**：
- **单纯"点某个名字的按钮"** → 用 `locate.click_by_name()` 一把做完（定位+操作+验证）
- **复杂界面探索** → 用 MCP 的 `get_app_state` 看完整树（它的输出更适合 agent 阅读）
- **要像人一样动** → 走本技能的 `mouse` / `keyboard`
- **做完要确认没搞砸** → 走本技能的 `safe.*`

## 七、安全用法（推荐）

**当目标是"已经存在的、有内容的窗口"时，必须用带验证的路径**：

```python
import sys
sys.path.insert(0, r"<你的技能目录>\scripts")   # 例如 %USERPROFILE%\.agents\skills\windows-computer-use\scripts
import safe          # ← 就在技能目录里，不用去找外部模块

# 三重锁：PID 属于预期进程 + 标题含关键词 + 窗口在前台
safe.safe_click(pid=12345, x=100, y=50, title_kw="记事本")

# 精确撤销（绝不"多按几次保险"）
safe.undo_exact(3, pid=12345, title_kw="记事本")
```

**三条不可违反的规则**：

```
❌ 禁止按标题模糊匹配窗口        → 必须 PID
❌ 禁止在未确认前台窗口时输入     → 会打进别的窗口
❌ 禁止"多按几次保险"            → 撤销/删除次数必须精确
```

---

## 八、自测

### ① 41 项人类操作能力 · 逐项实测（覆盖度验收）

```bash
python scripts/test_full_coverage.py
```

**这是"凡是人能做到的都必须做到"这句话的验收方式** —— 每一项都真实操作 + 效果回读，
不接受"代码里有这个函数"就算数。

```
分组            项数    内容
一 · 鼠标        14    移动/单击/双击/三击/右键/中键/拖拽/滑块/滚轮上下左右/
                       悬停/长按/框选/拖放
二 · 键盘        12+1  单字符/连续打字/中文/组合键/F1-F12/导航键/长按修饰键/
                       特殊字符/数字键盘/Tab/Esc/输入法切换
三 · 组合修饰     5    Ctrl+点击/Shift+点击/Alt+Tab/Ctrl+滚轮/Shift+滚轮
四 · 窗口         5    拖动/最大化最小化还原/调整大小/关闭/激活
五 · 系统级       5    截图/剪贴板/等待窗口/OCR/模板匹配

结果：41 项 → **38 PASS / 0 FAIL / 3 SKIP**（SKIP 项在第八章逐条说明）。
本数字与 `logs/coverage-*.log` 一一对应；**不做「连跑 N 次全绿」这类无留档的宣称**。
```

**靶子设计（这一条很关键）**：测试靶子是**独立进程**（`target_window.py`），
不是同进程内的 tkinter 窗口。原因见下方"已知限制"里的第 6 条 ——
同进程靶子会让 12 项"看似失败"，实际是靶子不可靠。

### ② 定位层测试（11 项）

```bash
python scripts/test_locate.py
```

```
UIA 可用性 / 取窗口节点 / 摊平控件树 / 按名字找 / 按类型找 /
找全部 / 读控件值 / 等元素出现（超时+命中）/ 「看到名字就点」/
元素级拟人化点击 / 速度对比（UIA vs OCR）
结果：11/11 PASS
```

### ③ 18 项基础与安全测试

```bash
python scripts/test_capabilities.py
```

```
A 组 静态检查（8 项）：键位表完整、无中文引号、无死代码、undo(0) 安全、
                      屏幕信息、越界保护、窗口枚举、错误 PID 拒绝
B 组 人类特征（3 项）：移动耗时在人类区间、轨迹偏离直线>3px、打字间隔有随机性
C 组 临时窗口（7 项）：自建窗口的点击/打字/最大化/截图/剪贴板/前台等待
```

**测试安全性**：所有动态测试都在**自己创建的窗口**里做，用完销毁，**绝不碰用户的任何文件**。

### 稳定性验证记录

```
2026-10-03 18 项测试曾连跑 10 次通过（当时尚无留档机制，该数字无日志佐证，如实标注）
2026-10-03 自查审计：发现并修复 4 处缺陷（见下表）
```

**过程中修掉的 7 个真问题**（全部是实测/审计发现的，不是理论推测）：

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 输入 `abc123` 得到 `ABC23` | 中文输入法截获键盘事件 | 改用 `SendInput + KEYEVENTF_UNICODE` 直投 |
| 2 | 轨迹偶被判为"绝对直线" | `bow` 允许接近 0，退化成正直线 | 强制最小弧度 `≥0.03×距离` |
| 3 | 轨迹仍偶被判为直线 | **测试判据本身错了** —— 弓形轨迹的 X/Y 仍可单调 | 改用「偏离起终点连线的最大距离 > 3px」 |
| 4 | `wheel(lines=0)` 崩溃 | 除零 | `lines = max(1, int(lines))` |
| 5 | **`find_image` 要 44 秒** | 全像素暴力双重循环 | 图像金字塔（4 倍降采样粗搜 + 原图精修） |
| 6 | 找不到目标时反而更慢（9.9s） | 金字塔失败后回退暴力全扫 | 去掉回退 —— 金字塔已覆盖全图 |
| 7 | 失效窗口句柄静默返回空标题 | 没有有效性校验 | `Win.__post_init__` 校验 + `alive()` / `assert_alive()` |

### 独立复核记录（2026-10-04）

**复核方**：Kimi Code（K3-256k），受虾哥委派逐行复核本包全部代码。

**复核方式**：六文件逐行通读 + 对可疑点在本机实测验证（不靠推测）。

**复核发现 7 项，经虾哥逐条核实：6 项属实，1 项误报。**

| # | 发现 | 核实结果 | 处理 |
|---|---|---|---|
| 1 | `input_inject.send_combo()` 无 try/finally，异常会卡住修饰键 | ✅ 属实 | 已修：按下序列记入 `pressed` 列表，finally 里逆序抬起 |
| 2 | emoji 等辅助平面字符被 `wScan` 截断（`0x1F600`→`0xF600`） | ✅ 属实 | 已修：拆 UTF-16 代理对分两次投递 |
| 3 | `window.close(confirm)` 两个分支代码完全相同，参数无效 | ✅ 属实 | 已修：改名 `graceful`，False 时走 `force_close()` 强杀 |
| 4 | 各模块 `sys.exit(2)` 抛 `SystemExit`，**不被 `except Exception` 捕获**，缺依赖时会杀掉宿主进程 | ✅ 属实 | 已修：4 个文件共 6 处改为 `raise ImportError(...)` |
| 5 | `ImmGetDefaultIMEWnd` 属 imm32.dll，不在 user32；调用必然 AttributeError 被吞 → IME 查询永远返回 None | ✅ 属实（复核方本机实测 `user32: MISSING` / `imm32: 存在`） | 已修：改调 imm32 + 正确消息号 `SendMessage(hwnd,0x0283,0x0005,0)`；实测现已能返回 True |
| 6 | `keyboard._is_ascii` 定义后从未使用（死代码） | ✅ 属实 | 已删 |
| 7 | `keyboard.press()` 无 try/finally | ✅ **属实（我上轮判成"误报"是错的）** | 已修：见下方"审核失误记录" |

**这次复核的价值**：第 4、5 两项是**只有逐行通读 + 实测才能发现的静默失效** —— 它们不会报错、不会崩溃，只是**永远不做那件事**，自测用例（正常路径）100% 覆盖不到。

### ⚠️ 审核失误记录：我把一项真 bug 判成了"误报"

**第 7 项 `press()` 无 try/finally —— Kimi 报的是对的，是我核实错了。**

```
我的核实方法：用 inspect.getsource() 取源码，然后判断 "finally" in src
结果        ：True  → 判定"有 finally，Kimi 误报"
真相        ：命中的是 docstring 里那句「确保松开（finally 保证）」
              实际代码里既没有 try 也没有 finally
```

**危险在于**：`press()` 是使用频率最高的函数之一，
它和已修的 `send_combo()` 是同款风险 —— **异常时修饰键会永久卡住**。
我却因为关键词匹配到了注释就结案了。

**已修**：按下序列记入 `pressed` 列表，`finally` 里逆序抬起。

**教训（写进这里以免再犯）**：
> **核实"有没有某个结构"时，要匹配语法结构，不能匹配字符串。**
> `"finally" in src` 会命中注释和文档字符串；
> 正确做法是 `re.search(r'\bfinally\s*:', src)`。

### 第二轮复核：Kimi K3 全面审查（含对上一轮结论的复查）

第二轮我明确要求复核方**怀疑我的声明**，重点查"有没有自欺欺人"。

**结果：它抓到了我 6 项不实声明 + 10 条假 PASS + 6 个新代码问题。**

已处理的关键项：

| 类别 | 问题 | 处理 |
|---|---|---|
| 🔴 声明不实 | `press()` 确实无 finally（见上） | ✅ 已修 |
| 🔴 声明不实 | **"Ctrl+A 无效"与自己的测试自相矛盾** —— 测试每个用例都靠 Ctrl+A 清场且全部通过 | ✅ 实测确认 Ctrl+A **有效**，限制描述已收窄为"Shift 专用" |
| 🔴 声明不实 | "三重锁验证"不在交付代码里，指向技能目录外的文件 | ⏳ 未解决（见下方"待办"） |
| 🔴 声明不实 | "83 个公开函数"口径未声明；按"公开 API"常规定义应约 101（含 `Win` 的 23 个方法） | ✅ **已解决**：最终精确数字（ast 静态分析）为 **98 个模块级函数 + 57 个类方法 = 155 个公开 API**（`Win` 实为 26 个方法，非 23）；7 个 doctor 不计入 |
| 🔴 声明不实 | "已修掉 11 个 bug"与文档里的 7+6 对不上 | ✅ 已改为准确表述 |
| 🟡 测试缺陷 | 10 条硬编码 `True` 或只测耗时；3 条"测 A 宣称 B"；4 项同测 `drag()` 充数 | ⏳ 未解决（见下方"待办"） |
| 🔵 代码 | `get_ime_status` 是 IME bug 的孪生副本（同样查错 API） | ✅ 已修：改为复用 `input_inject.ime_active_window()` |
| 🔵 代码 | `window.py` 三处相对导入 → **按文档用法（顶层导入）时 `snap_left/right`、`drag_by_title` 静默失效** | ✅ 已修：加 `_load_sibling()` 双路径加载 |
| 🔵 代码 | `window.py` 三处硬编码技能外路径的 `sys.path.insert` | ✅ 已删 |

**这一轮最该记住的**：
> 上一轮我判 Kimi 一项"误报"，结果是我自己错。
> **审核别人时，我的核实手段本身也要经得起复核。**

**结论：派活与复核都不能省。做的人看不到自己缺的那块，审的人也可能看错 —— 两边都做，才叫闭环。**

## 九、性能数据（实测）

```
find_image  1920x1080 全屏搜索
  ├─ 找到目标   ：0.17s      （优化前 44.27s，提速 265 倍）
  └─ 找不到目标 ：0.15s      （优化前 44.27s；中间版本因回退逻辑反而 9.92s）

mouse.move  800 像素移动     ：0.67-0.99s（人类区间）
mouse.drag  200 像素拖拽     ：1.53s
keyboard.type_text 53 字符   ：10.2s（每字符约 0.19s，人类节奏）
```

## 十、已知限制（诚实标注）

| # | 限制 | 影响 | 说明 |
|---|---|---|---|
| 1 | **Shift + 键盘不通**（Shift + 鼠标正常） | `Shift+方向键` 无效；**`Shift+点击`、`Shift+滚轮` 实测可用**；`Ctrl` 系列全部正常 | 见下方专项说明。**有替代路径，功能不缺** |
| 2 | 剪贴板是全局资源 | 多线程同时粘贴会互相覆盖 | 单线程使用无影响；并发场景需自行串行化 |
| 3 | 多显示器未特别处理 | 当前机器是单屏（实测确认） | 多屏环境下坐标基于主屏，副屏需额外适配 |
| 4 | DPI 缩放 | 当前系统 DPI=96（100%） | 高 DPI（150%/200%）下坐标可能需要缩放系数 |
| 5 | 锁屏 / 远程桌面 | 无法截图与操作 | 系统限制，非代码问题 |
| 6 | **同进程 tkinter 靶子不可靠** | 影响的是"怎么测"，不是"能不能用" | 见下方专项说明 |
| 7 | OCR 首次运行 | 会下载模型（约 15MB） | 之后离线可用 |

**这份限制清单是刻意保留的** —— 把边界说清楚，比假装万能更有用。

### 限制 1 专项：Shift + 键盘不通（Shift + 鼠标正常）

**2026-10-04 第三轮实测矩阵**（在独立进程靶子上逐个验证）：

```
Shift + 方向键   → 不通 ✗   在 Text 里选不中文字（'abcdef' 输 Q 后成 'abcQdef'）
Shift + 点击     → 通   ✓   列表真的选中了 2 项 [0, 1]
Shift + 滚轮     → 通   ✓   横向位置 0.0007 -> 0.0833
Shift + Tab      → 判据无效    tkinter 的 Text 组件里 Tab 本就插入制表符，不移动焦点
Ctrl  + 键盘     → 通   ✓   Ctrl+A / Ctrl+C 有效
Ctrl  + 点击     → 通   ✓   多选 2 项
```

**所以问题是「Shift + 键盘」这一条路径**，不是 Shift 整体，也不是所有修饰键。

**这个结论修正过两次，记录在此以免再错**：
1. 最初写成"修饰键 + 键盘的组合不通"，并把 `Ctrl+A` 也列进去 —— **错**（Ctrl 正常）
2. 第二轮改成"Shift 修饰键不通（不是所有修饰键）" —— **仍不准确**（Shift+鼠标是通的）
3. 第三轮实测矩阵后定为现在的表述 —— **以实测为准**

**排查过程**（排除实现层面的怀疑）：

```
用 keybd_event 发送 Shift     → 与 SendInput 结果一致
用 SendInput 发送 Shift       → 同上（两种底层 API 一致 → 排除实现缺陷）
tkinter 靶子上测              → Shift+方向键无效、Shift+点击有效
WinForms 标准控件上测          → Shift+方向键同样无效
GetKeyState(VK_SHIFT) 查询    → 返回 -127，Shift 确实处于按下状态
同路径的单键（Home/方向键）     → 完全有效
同路径的 Unicode 注入          → 完全有效
Ctrl 组合（键盘+鼠标）         → 完全有效
Shift + 鼠标                   → 完全有效
```

**结论**：**事实**是 Shift 能被按下、也能被鼠标事件正确携带（Shift+点击/滚轮都通），
但**键盘事件里的 Shift 状态不被目标应用识别**。两种底层 API 表现一致 → **排除实现缺陷**。
**推断**是本机环境层面有东西专门影响了"键盘事件的修饰键状态"（**这是推断，未定位到来源**）。

**替代路径（全部实测通过）**：

| 想做的事 | 替代做法 |
|---|---|
| Shift+方向键选中 | 鼠标拖拽选择（已验证） |
| Shift+点击选范围 | **直接可用**（第三轮实测已通，无需替代） |

### 限制 6 专项：测试靶子必须独立进程

初版测试套件在**同一个 Python 进程内**反复创建/销毁 tkinter 窗口当靶子，结果：

```
连续创建第 3 个窗口起，前台就丢
单一窗口重复输入，键盘焦点正常但内容为空
12 项能力"看似失败"，实际实现完全正常
```

**更根本的问题**：真实使用场景就是**操作另一个进程的窗口**，
同进程内建窗口**根本测不到真实情况**。

**改正**：靶子改为独立进程（`target_window.py`），通过状态文件回读结果。
改完之后同一批代码立刻全部通过。

**教训**：**测出失败时，先怀疑测试，再怀疑实现。**

---

## 十一、历史遗留与已解决项（全部已解决，留档备查）

第二轮复核（Kimi K3）指出的问题，**截至 2026-10-04 全部已解决**。保留在此备查：

| # | 未解决项 | 具体内容 | 影响 |
|---|---|---|---|
| 1 | ~~**测试质量**~~ | ~~10 条硬编码 True / 只测耗时；3 条测 A 宣称 B；4 项同测 drag()~~ | ✅ **已解决（2026-10-04）**：全部改为**效果回读**断言，新增 SKIP 三态。当前 **38 PASS / 0 FAIL / 3 SKIP**（与 `logs/` 留档一致） |
| 2 | ~~**三重锁不在交付内**~~ | ~~实现在技能目录之外~~ | ✅ **已解决（2026-10-04）**：已收进技能目录为 `scripts/safe.py`（6 个模块级函数 + 12 个类方法），去掉全部外部依赖，实测"错误 PID 被拒 / 错误标题被拒 / safe_click 生效"三项全通 |
| 3 | ~~**能力零覆盖**~~ | ~~11 个函数零测试~~ | ✅ **已解决（2026-10-04）**：新建 `test_extended.py`（19 项），全部覆盖并 **19/19 PASS** |
| 4 | ~~**`Win` 类方法未单列**~~ | ~~计数口径未声明~~ | ✅ **已解决（2026-10-04）**：已单列 **26** 个方法并写明口径。最终口径：98（模块级）+ 57（类方法）= **155 个公开 API** |
| 5 | ~~**缺"读取控件当前内容"**~~ | ~~只能靠 OCR 迂回~~ | ✅ **已解决（2026-10-04）**：新增 `read_control_text` / `read_text_at` / `window_text_list`；在标准 Win32 控件上实测读回 `probe_7788`，枚举出 3 个控件 |
| 6 | ~~**无卡键自检/恢复**~~ | ~~没有复位函数~~ | ✅ **已解决（2026-10-04）**：新增 `check_stuck_keys` / `release_all_modifiers` / `safe_press`；实测能检出人为制造的卡键并复位 |

**这份待办是刻意保留的** —— 修好的写修好，没修的写没修，不含糊。

## 十二、依赖

**与 `requirements.txt` 完全一致**（那里是唯一真相源，本节只是说明）。

### 必需（4 个）

```
pywin32>=306           Win32 API（窗口 / 键鼠底层）—— mouse/keyboard/window/safe/input_inject 都靠它
pillow>=10.0.0         截图与图像处理 —— vision 模块硬依赖（不装直接 ImportError）
numpy>=1.24.0          模板匹配的数组运算 —— vision 模块硬依赖
uiautomation>=2.0.18   UI Automation —— locate 定位层硬依赖
```

**注意**：`numpy` 和 `uiautomation` 是**硬依赖**，不是可选项。
（此前本节误把它们写成"可选"，与 requirements.txt 口径打架，已更正。）

### Python 版本

```
最低 3.9（代码语法核实兼容 3.9，无 3.10+ 独有语法）
推荐 3.11 - 3.13
3.14 也可以，但 pywin32 需要 >= 311 才有对应 wheel；装不上时先升级 pip
```

### 可选

```
rapidocr-onnxruntime>=1.3.0   OCR 找文字（find_text / read_text / click_text）
                               不装则这几个函数不可用，其余功能照常
                               注意：首次调用会下载约 15MB 模型，需要联网
comtypes>=1.2.0               uiautomation 某些场景需要；通常随它自动装上，不用单独装
```

### 安装

```powershell
python -m pip install -r requirements.txt
```

或直接用一键脚本（会自动处理 Python 探测、--user、退出码检查）：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### 缺依赖时的行为

7 个模块各自独立，**缺哪个只影响对应模块**：

| 缺什么 | 后果 |
|---|---|
| pywin32 | mouse / keyboard / window / safe / input_inject 全不可用（等于残废） |
| pillow 或 numpy | vision 不可用（截图、找图、OCR 全没） |
| uiautomation | locate 不可用（回到"只能靠坐标"的老状态） |
| rapidocr | 只影响 find_text / read_text，其余照常 |

`__init__.py` 对每个模块做优雅降级（`raise ImportError` 而非 `sys.exit`，**不会杀掉宿主进程**）。

## 十三、设计决策记录

| 决策 | 原因 |
|---|---|
| 为什么禁止标题匹配窗口 | 一次事故：标题含"记事本"匹配到了用户的密钥文件，打字打了进去 |
| 为什么用 Unicode 注入而非 keybd_event | 实测：中文输入法会把 "abc123" 变成 "ABC23" |
| 为什么轨迹要非直线 | 人类手部运动是弧线，绝对直线是机器特征 |
| 为什么移动不能瞬间完成 | 人类移动 800 像素需 0.3-1.5 秒，瞬间完成是机器特征 |
| 为什么撤销要精确次数 | 一次事故：80 次 Ctrl+Z 撤销进了用户原有内容 |
| 为什么用 PID 锁定 | 标题会变、会重复、会模糊匹配到错误目标 |

---

*作者：虾哥（DSH） · 建立：2026-10-03 · 最近更新：2026-10-04（Kimi K3 三轮独立复核）*
