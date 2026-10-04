# 独立进程测试靶子（WinForms 版）
#
# 为什么需要它：
#   tkinter 是自绘控件，对合成的 Shift 修饰键处理特殊
#   （2026-10-04 实测：GetKeyState 确认 Shift 已按下、方向键也送达，
#     但 Tk 里的 Shift+方向键不产生选中）。
#   真实场景用的是标准 Windows 控件，所以需要 WinForms 靶子做对照验证。
#
# 用法：powershell -NoProfile -File target_winforms.ps1 -StateFile <路径>

param(
    [string]$StateFile = "$env:TEMP\gui_agent_winforms_state.json"
)


# ── DPI 感知（必须早于任何窗口创建）──
# 注意：param() 必须是脚本第一条可执行语句，所以这段只能放在它后面。
# 教训：初版插在 param 之前，导致 param 失效、-StateFile 参数传不进来。
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class DpiHelper {
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr ctx);
    public static void Enable() { try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch {} }
}
"@ -ErrorAction SilentlyContinue
[DpiHelper]::Enable()

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# 注意：必须用 ::new() 或 -ArgumentList，
# 写成 New-Object System.Drawing.Point(20,25) 是无效的（会静默不生效）
$form = New-Object System.Windows.Forms.Form
$form.Text = "gui-agent-winforms-target"
$form.ClientSize = [System.Drawing.Size]::new(580, 440)
$form.StartPosition = "Manual"
$form.Location = [System.Drawing.Point]::new(300, 260)
$form.TopMost = $true

$textBox = New-Object System.Windows.Forms.TextBox
$textBox.Location = [System.Drawing.Point]::new(20, 25)
$textBox.Size = [System.Drawing.Size]::new(540, 90)
$textBox.Multiline = $true
$form.Controls.Add($textBox)

$listBox = New-Object System.Windows.Forms.ListBox
$listBox.Location = [System.Drawing.Point]::new(20, 130)
$listBox.Size = [System.Drawing.Size]::new(540, 120)
$listBox.SelectionMode = [System.Windows.Forms.SelectionMode]::MultiExtended
for ($i = 0; $i -lt 60; $i++) {
    [void]$listBox.Items.Add(("item_{0:d2}" -f $i))
}
$form.Controls.Add($listBox)

$button = New-Object System.Windows.Forms.Button
$button.Location = [System.Drawing.Point]::new(20, 265)
$button.Size = [System.Drawing.Size]::new(140, 36)
$button.Text = "click me"
$script:clicks = 0
$button.Add_Click({
    $script:clicks++
    $button.Text = "clicks: $script:clicks"
})
$form.Controls.Add($button)

$form.Add_Shown({ $form.Activate() })

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 250
$timer.Add_Tick({
    try {
        $sel = @()
        foreach ($i in $listBox.SelectedIndices) { $sel += [int]$i }
        $data = @{
            text           = [string]$textBox.Text
            clicks         = [int]$script:clicks
            list_selection = $sel
            hwnd           = $form.Handle.ToInt64()
            alive          = $true
        } | ConvertTo-Json -Compress
        $tmp = "$StateFile.tmp"
        [System.IO.File]::WriteAllText($tmp, $data, (New-Object System.Text.UTF8Encoding($false)))
        Move-Item -Force $tmp $StateFile
    } catch { }
    if (Test-Path "$StateFile.quit") {
        $timer.Stop()
        $form.Close()
    }
})
$timer.Start()

[void]$form.ShowDialog()
