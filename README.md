# windows-computer-use

**让 AI 像人一样操作 Windows 桌面 —— 而且不会点错窗口、不会打了个寂寞、不会撤销过头。**

这不是又一个 `pyautogui` 封装。它解决的是另一类问题：**AI 操作电脑时闯的祸**。

---

## 装之前先确认三件事

```
① 系统      必须是 Windows（依赖 pywin32，macOS / Linux 用不了）
② Python    3.9 以上，且在 PATH 里
             ⚠️ 如果你只装过 Microsoft Store 版 Python，装的其实是"占位程序"，不是真 Python
             验证方法：命令行运行 python --version，能打印 Python 3.x.y 才是真的
③ 权限      普通用户即可（不需要管理员）
```

**PowerShell 执行策略**：脚本默认可能被拦。用这条命令绕过（只对本次生效）：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

---

## 安装

```powershell
# 解压到一个目录，然后
cd windows-computer-use
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Target agents
```

`-Target` 可选 `agents`（默认）/ `claude` / `codex` / `openclaw` / `all`。

**装完重启你的 agent 客户端**（它只在启动时扫描 skills 目录），然后对它说：

> 用 windows-computer-use 打开计算器，算 1234 + 5678

**只用 Python 的话**：

```python
import sys
sys.path.insert(0, r"<技能目录>\scripts")
import locate, safe

# 按名字找控件（不用知道坐标）
el = locate.find(pid=12345, name="等于")
print(el.control_type, el.center)      # ButtonControl (1025, 1559)

# 安全点击：三重锁验证 + 拟人化轨迹
safe.safe_click(12345, *el.center, title_kw="计算器", coord_space="screen")
```

---

## 它到底有什么不一样

### ① 三重锁：动手之前先确认没搞错对象

```
锁 1  PID 是预期进程
锁 2  标题含预期关键词
锁 3  窗口确实在前台
      —— 三条全过才允许发出第一个击键
```

**对应事故**：打字打进了用户的密钥文件。**现在这种事在发键之前就被拦下。**

```
$ python -c "import safe; safe.safe_click(99999, 100, 100, title_kw='不存在')"
TargetMismatch: 锁2失败：标题「...」不含「不存在」
                ↑ 一个键都没发出去
```

### ② 操作后确认：不是「我点了」，是「界面真的变了」

```python
safe.safe_click(pid, x, y, expect_change=True)
# 点击前后比对界面指纹，没变就报 VerifyFailed
```

**对应事故**：点完就当成功，后面全错。

### ③ 精确撤销：次数必须对得上

```python
safe.undo_exact(53)     # 严格发 53 次，不多不少
```

**对应事故**：53 个字符撤了 80 次，撤进了用户原有内容。

### ④ 卡键救援：出事了能收拾

```python
keyboard.check_stuck_keys()          # 检出被卡住的修饰键
keyboard.release_all_modifiers()     # 全部释放
keyboard.safe_press("ctrl+s")        # 带 finally 保证抬起的按键
```

### ⑤ 拟人化：不是瞬间移动

```
贝塞尔曲线轨迹 + 变速（起步缓/中段快/末端减速）
+ 手抖 + 过冲回拉
移动 800px 耗时 0.67-1.1s（人类区间）
打字 45-165ms/字符
```

### ⑥ 看得见：直接读 Windows 无障碍树

```python
locate.dump_tree(pid)                  # 扫一眼界面上有什么
locate.find(pid=pid, name="保存")      # 按名字找，不用坐标
locate.click_by_name(pid, "确定")      # 看到名字就点
```

实测：**定位 0.12 秒**，对比 OCR 全屏扫描 10.7 秒 —— **快约 100 倍**，而且拿到的是
控件语义（名字/类型/可交互/当前值），不是像素。

---

## 测试

```powershell
cd scripts
python test_capabilities.py     # 18 项
python test_full_coverage.py    # 41 项
python test_extended.py         # 19 项
python test_locate.py           # 11 项
```

**⚠️ 运行测试会真实移动你的鼠标键盘、弹窗、持续 2-4 分钟。期间请勿操作。**

**作者机器上的留档结果**（本机 4K 屏 175% 缩放，Windows 11）：

| 测试套 | 项数 | 结果 |
|---|---|---|
| `test_capabilities.py` | 18 | 18 PASS |
| `test_full_coverage.py` | 41 | 38 PASS / 0 FAIL / 3 SKIP |
| `test_extended.py` | 19 | 19 PASS |
| `test_locate.py` | 11 | 11 PASS |

**这些数字是作者单次运行的留档，不是「保证你机器上也一样」。**
日志未随包发布；如果你跑出来数字不同，属于正常 —— 见下面的限制说明。

**偶发单项失败怎么办**：多为靶子窗口状态残留或焦点丢失，重跑一次通常就过。
如果某项**稳定失败**，大概率是环境差异（DPI / 权限 / 应用不暴露 UIA），见限制章节。

**3 项 SKIP 是机器限制，如实标注**，没有伪装成 PASS（滑块 / 长按修饰键 / 输入法切换）。

---

## 已知限制（重要，别踩坑）

### 🔴 DPI 缩放 —— 最容易踩

**175% 缩放的屏幕上**：

```
Win32 API  返回逻辑坐标 —— 2194×1234
PIL 截图   抓物理像素   —— 3840×2160
                       两个坐标系差 1.75 倍
```

**本技能在 `vision` 模块 import 时自动声明 `PER_MONITOR_AWARE_V2` 解决**。

**⚠️ 三件必须知道的事**：

```
① 这个声明是「进程级」的，而且不可撤销
   它会让整个 Python 进程变成 DPI-aware，不只是本技能

② 如果你的宿主程序自己也要管 DPI，设这个环境变量关掉：
      $env:GUI_AGENT_NO_DPI_FIX = "1"
   ⚠️ 必须在 import vision 之前设置，设晚了等于没设

③ 关掉之后坐标就不统一了，需要自己按 vision.dpi_scale() 换算
```

自检方法：

```python
import vision; print(vision.dpi_info())
# awareness_applied 应为 True，scale 应为 1.0
```

### 🟡 浏览器网页读不到 UIA

```
Edge / Chrome 默认不向 UI Automation 暴露 DOM
→ locate.find() 在网页里找不到「搜索框」「按钮」
→ 网页操作只能用「截图 + OCR + 坐标」路线
```

### 🟡 只支持 Windows

依赖 `pywin32`，macOS / Linux 用不了。

### 🟡 多显示器未适配

- 截图只认主屏（`ImageGrab` 默认行为）
- `_assert_on_screen` 的边界检查只按主屏算
- 跨屏拖拽 / 副屏上的窗口，坐标可能不对

### 🟡 锁屏 / 远程桌面下不可用

锁屏后没有交互桌面，SendInput 无效；远程桌面断开时同理。

### 🟡 不保证「像人一样通过验证码」

滑块轨迹做了专项优化（起步缓/中段冲/末端微调），**但不对抗专业风控**。

### ⚪ Shift + 键盘不通（作者机器实测）

```
Shift + 方向键   ✗    Shift + 点击   ✓
Shift + 滚轮     ✓    Ctrl 系列      ✓
```

**这是作者机器的环境问题（两种底层 API 表现一致，排除实现缺陷），不保证你也这样。**

### ⚪ OCR 首次使用要下载模型

`rapidocr-onnxruntime` 首次调用会下载约 15MB 模型，慢且需要联网。
不装这个包也行 —— `find_text` / `read_text` 不可用，其余功能不受影响。

---

## 和其他项目什么关系

**不是替代，是互补。** 作者调研过同类项目：

| 项目 | 亮点 | 与本技能的关系 |
|---|---|---|
| [microsoft/cua_skill](https://github.com/microsoft/cua_skill) | 技能库 RAG + 17 个应用模块 + 标准评测 | **上位框架**，本技能可做它的执行层 |
| [arpan404/bumblebee](https://github.com/arpan404/bumblebee) | **RL 生成鼠标路径**、wpm/错字率参数化 | 拟人化比本技能强，可借鉴 |
| [stevenke1981/windows-agent-skill](https://github.com/stevenke1981/windows-agent-skill) | 决策树编排（**PowerShell > COM > GUI**） | 编排层思路值得学，本技能已引入该原则 |
| [wimi321/windows-computer-use-skill](https://github.com/wimi321/windows-computer-use-skill) | 自带 MCP server | 同类，作者自述「尚未真机全链路验证」 |

**本技能独有的**：三重锁、操作后确认、精确撤销、卡键救援。

**本技能缺的**：应用领域知识（不如微软 17 个模块）、RL 路径（不如 bumblebee）。

---

## 设计原则

### 动手之前先问：这活该不该用鼠标？

```
能用命令行（PowerShell / CLI）解决  →  绝对不要动鼠标
能用 API / COM 解决                →  不要模拟点击
只剩 GUI 一条路                     →  才用本技能
```

**可靠性差一个数量级**：

| 方式 | 典型可靠性 |
|---|---|
| 命令行 / API | 极高（确定性、可断言、失败会报错） |
| COM / 脚本接口 | 高 |
| **GUI 模拟点击** | **低**（受焦点、遮挡、DPI、时序、动画影响） |

**本技能是最后一道手段，不是第一选择。**

### 看得见用系统 API，怎么动用人类方式

```python
# 定位：交给 UI Automation（和 MCP 工具底层同源，不重复造轮子）
cx, cy = locate.find(pid=pid, name="确定").center

# 操作：交给自己（拟人化 + 安全验证）
safe.safe_click(pid, cx, cy, title_kw=..., expect_change=True)
```

**刻意不用 UIA 的 `InvokePattern`** —— 那是程序化触发，没有鼠标轨迹，
还会绕过只有真实点击才触发的行为。

---

## 目录结构

```
windows-computer-use/
├── SKILL.md              技能主文档（给 agent 读的完整说明）
├── README.md             本文件（给人读）
├── requirements.txt      依赖清单（4 个必需包）
├── install.ps1           一键安装
└── scripts/
    ├── locate.py         UI Automation 定位层（看得见）
    ├── safe.py           三重锁 + 操作后确认
    ├── mouse.py          拟人化鼠标（贝塞尔轨迹）
    ├── keyboard.py       智能输入（绕过输入法）
    ├── window.py         窗口操作
    ├── vision.py         OCR / 找图 / DPI 感知
    ├── input_inject.py   底层注入（Unicode / 扫描码）
    ├── target_window.py      测试靶子（tkinter，独立进程）
    ├── target_winforms.ps1   测试靶子（WinForms，标准 Win32 控件）
    └── test_*.py         4 套测试
```

**公开 API 155 个**（98 模块级 + 57 类方法），另有 7 个 `doctor` 自检函数。

---

## 常见问题

**Q: 装完 agent 还是不知道有这个技能？**
A: 重启 agent 客户端。它只在启动时扫描 skills 目录。

**Q: 安装脚本说「找不到可用的 Python 3」？**
A: 大概率你只有 Microsoft Store 版 Python（那是占位程序）。
去 [python.org](https://www.python.org/downloads/) 装真 Python，安装时勾选
「Add python.exe to PATH」；或用 `-Python "完整路径"` 指定。

**Q: 报 `ModuleNotFoundError: win32api`？**
A: `pip install pywin32 --user`，装完可能需要重启终端。

**Q: 点击位置总是偏一点？**
A: 大概率是 DPI 缩放。跑这一行确认：
```python
import vision; print(vision.dpi_info())
```
`awareness_applied` 应该是 `True`，`scale` 应该是 `1.0`。

**Q: `locate.find()` 找不到控件？**
A: 该应用可能不暴露 UIA（浏览器、Electron、Java 常见）。
先用 `dump_tree(pid)` 看看能读到什么，读不到就改走截图路线。

**Q: 会不会把我电脑搞乱？**
A: 三重锁限制它只能操作你指定的窗口；`undo_exact` 保证撤销次数精确。
但**任何 GUI 自动化都有风险**，建议先在无关紧要的窗口上试。

**Q: 怎么卸载？**
A: 删掉 skills 目录下的 `windows-computer-use` 文件夹即可。它不写注册表、
不装服务、不改系统设置。

---

## 开发与验证记录

**这个项目经历过 9 轮独立复核**（Kimi K3 七轮 + Codex 两轮）。

**修掉的真实 bug（部分）**：

```
· 换行 / Tab 只发 down 没发 up（隔离桩证实）
· 拖拽时 down 与 try 之间有空档（异常后鼠标键永久按住）
· 兄弟模块加载产生副本（模块身份分裂）
· safe_type 用 GetFocus 跨进程恒返回 0（回读永远失效）
· DPI 缩放导致坐标系差 1.75 倍
· 8 处「恒真断言」的假测试
· install.ps1 三个沉默失败点（Store 存根 / pip 退出码 / --user）
```

**复核报告留档在作者机器上，未随包发布。**

---

## 许可

MIT
