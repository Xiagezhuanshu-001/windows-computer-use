<#
.SYNOPSIS
    windows-computer-use 一键安装脚本

.DESCRIPTION
    把技能装到指定 agent 平台的 skills 目录，并装好 Python 依赖。

    默认装到 ~\.agents\skills\（DSH 等使用），也可用 -Target 指定其他平台：
        .\install.ps1 -Target claude      # ~\.claude\skills\
        .\install.ps1 -Target codex       # ~\.codex\skills\
        .\install.ps1 -Target openclaw    # ~\.openclaw\skills\
        .\install.ps1 -Target all         # 全部

.PARAMETER Target
    安装目标：agents（默认）/ claude / codex / openclaw / all

.PARAMETER Python
    Python 解释器路径。默认自动探测。

.PARAMETER SkipDeps
    跳过 Python 依赖安装（只复制文件）。

.PARAMETER Check
    装完跑一次完整测试（会真实移动你的鼠标键盘 2-4 分钟，期间请勿操作）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Target all
#>

[CmdletBinding()]
param(
    [ValidateSet("agents", "claude", "codex", "openclaw", "all")]
    [string]$Target = "agents",

    [string]$Python = "",

    [switch]$SkipDeps,

    [switch]$Check
)

$ErrorActionPreference = "Stop"

# 汇总结果，最后据此决定横幅颜色 —— 不能"不管中间怎么失败都报绿"
$script:Problems = @()
$script:DepsOK = $false
$script:FilesOK = $false

function Write-Step($m) { Write-Host "  $m" }
function Write-OK($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn2($m){ Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host "  [X] $m" -ForegroundColor Red; $script:Problems += $m }

Write-Host ""
Write-Host "====================================================="
Write-Host "  windows-computer-use  安装程序"
Write-Host "====================================================="
Write-Host ""

# ── 0. 前置检查：Windows ──
if ($env:OS -ne "Windows_NT") {
    Write-Err "本技能只支持 Windows（依赖 pywin32）"
    exit 1
}
Write-OK "系统: Windows  PowerShell $($PSVersionTable.PSVersion)"

# ── 1. 找准源目录 ──
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $scriptDir "SKILL.md"))) {
    Write-Err "找不到 SKILL.md —— 请把本脚本和 SKILL.md 放在同一目录"
    exit 1
}
Write-OK "源目录: $scriptDir"

# ── 2. 找 Python（关键：识别 Microsoft Store 存根）──
function Test-PythonCandidate($path) {
    # 返回 @{ OK=bool; Version=str; Minor=int; Reason=str }
    # 重点识别 WindowsApps 存根：它"存在且能执行"，实际是跳转商店的占位符
    if (-not $path) { return @{ OK = $false; Reason = "空路径" } }

    if ($path -match 'WindowsApps') {
        return @{ OK = $false; Reason = "这是 Microsoft Store 的占位程序（python.exe 存根），不是真 Python" }
    }

    try {
        $out = & $path --version 2>&1 | Out-String
    } catch {
        return @{ OK = $false; Reason = "执行失败: $($_.Exception.Message)" }
    }
    $out = $out.Trim()
    if ($out -notmatch 'Python\s+3\.(\d+)') {
        return @{ OK = $false; Reason = "输出不是 Python 版本号（得到: $out）" }
    }
    return @{ OK = $true; Version = $out; Minor = [int]$Matches[1] }
}

$pyCandidates = @()
if ($Python) {
    $pyCandidates += $Python
} else {
    foreach ($cand in @("python", "python3", "py")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) { $pyCandidates += $cmd.Source }
    }
    foreach ($guess in @(
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python314\python.exe", "C:\Python313\python.exe",
        "C:\Python312\python.exe", "C:\Python311\python.exe",
        "C:\Program Files\Python314\python.exe",
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe"
    )) {
        if (Test-Path $guess) { $pyCandidates += $guess }
    }
    # 扫一遍常见根目录下的子目录（某些发行版/绿色安装用 pythoncore-* 这种目录名）
    foreach ($root in @("$env:LOCALAPPDATA\Python", "$env:LOCALAPPDATA\Programs\Python",
                        "$env:USERPROFILE\scoop\apps\python\current", "C:\Python")) {
        if (Test-Path $root) {
            Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
                ForEach-Object {
                    $p = Join-Path $_.FullName "python.exe"
                    if (Test-Path $p) { $pyCandidates += $p }
                }
        }
    }
}

$usePy = $null
$useMinor = 0
$useVer = ""
$checkResults = @()
foreach ($cand in ($pyCandidates | Select-Object -Unique)) {
    $r = Test-PythonCandidate $cand
    $checkResults += [PSCustomObject]@{ Path = $cand; OK = $r.OK; Info = "$($r.Version)$($r.Reason)" }
    if ($r.OK -and -not $usePy) { $usePy = $cand; $useMinor = $r.Minor; $useVer = $r.Version }
}

if (-not $usePy) {
    Write-Err "找不到可用的 Python 3"
    Write-Host ""
    Write-Step "探测结果："
    foreach ($r in $checkResults) {
        Write-Step ("  " + $(if ($r.OK) { "[可用]" } else { "[不可用]" }) + " " + $r.Path + "  -> " + $r.Info)
    }
    Write-Host ""
    Write-Step "怎么解决："
    Write-Step "   1. 装 Python 3.9+：https://www.python.org/downloads/"
    Write-Step "      安装时务必勾选 Add python.exe to PATH"
    Write-Step "   2. 或用 -Python 指定完整路径，例如："
    Write-Step "      .\install.ps1 -Python `"C:\Python312\python.exe`""
    Write-Host ""
    if (($checkResults | Where-Object { $_.Path -match 'WindowsApps' }).Count -gt 0) {
        Write-Warn2 "检测到 Microsoft Store 的 Python 占位程序 —— 那不是真 Python。"
        Write-Warn2 "请去 python.org 下载安装；或到 设置 → 应用 → 高级应用设置 → 应用执行别名"
        Write-Warn2 "把 python.exe / python3.exe 两个开关关掉。"
        Write-Host ""
    }
    exit 1
}

Write-OK "Python: $usePy  ($useVer)"
if ($useMinor -lt 9) { Write-Warn2 "Python 版本偏低（需 3.9+），可能有兼容问题" }
if ($useMinor -ge 13) {
    Write-Step "   （Python 3.$useMinor 较新；若 pywin32 装不上，先升级 pip：$usePy -m pip install -U pip）"
}

# ── 3. 决定安装目标 ──
$map = @{
    "agents"   = "$env:USERPROFILE\.agents\skills"
    "claude"   = "$env:USERPROFILE\.claude\skills"
    "codex"    = "$env:USERPROFILE\.codex\skills"
    "openclaw" = "$env:USERPROFILE\.openclaw\skills"
}
$targets = if ($Target -eq "all") { $map.Values } else { @($map[$Target]) }

Write-Host ""
Write-Step "将安装到："
foreach ($t in $targets) { Write-Step "   $t" }

# 发布清单：只动这些文件，用户加进 scripts/ 的其他东西不碰
$manifest = @("SKILL.md", "README.md", "requirements.txt")
$shippedScripts = @()
if (Test-Path (Join-Path $scriptDir "scripts")) {
    $shippedScripts = (Get-ChildItem (Join-Path $scriptDir "scripts") -File |
                       Where-Object { $_.Extension -in ".py", ".ps1" }).Name
}
$requiredModules = @("mouse.py", "keyboard.py", "window.py", "vision.py",
                     "input_inject.py", "safe.py", "locate.py")

# ── 4. 复制文件（失败记进 Problems，不沉默）──
Write-Host ""
Write-Step "复制技能文件..."
$destList = @()
foreach ($t in $targets) {
    $dest = Join-Path $t "windows-computer-use"
    try {
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
        $destScripts = Join-Path $dest "scripts"
        New-Item -ItemType Directory -Path $destScripts -Force | Out-Null

        # 只删发布清单内的文件（保留用户自己加的）
        foreach ($f in $manifest) {
            $fp = Join-Path $dest $f
            if (Test-Path $fp) { Remove-Item $fp -Force }
        }
        foreach ($f in $shippedScripts) {
            $fp = Join-Path $destScripts $f
            if (Test-Path $fp) { Remove-Item $fp -Force }
        }
        Get-ChildItem $dest -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

        foreach ($f in $manifest) {
            $fp = Join-Path $scriptDir $f
            if (Test-Path $fp) { Copy-Item $fp $dest -Force }
        }
        foreach ($f in $shippedScripts) {
            Copy-Item (Join-Path $scriptDir "scripts\$f") $destScripts -Force
        }

        # 校验：复制完必须验，不能"复制失败但自检绿"
        $missing = @()
        if (-not (Test-Path (Join-Path $dest "SKILL.md"))) { $missing += "SKILL.md" }
        foreach ($m in $requiredModules) {
            if (-not (Test-Path (Join-Path $destScripts $m))) { $missing += $m }
        }
        if ($missing.Count -gt 0) {
            Write-Err "$($t.Replace($env:USERPROFILE,'~'))  复制不完整，缺: $($missing -join ', ')"
        } else {
            $n = (Get-ChildItem $dest -Recurse -File | Measure-Object).Count
            Write-OK "$($t.Replace($env:USERPROFILE,'~'))  ($n 个文件)"
            $destList += $destScripts
        }
    } catch {
        Write-Err "$($t.Replace($env:USERPROFILE,'~'))  失败: $($_.Exception.Message)"
    }
}
if ($destList.Count -gt 0) { $script:FilesOK = $true }

# ── 5. 装依赖（必须检查退出码）──
if (-not $SkipDeps) {
    Write-Host ""
    Write-Step "安装 Python 依赖（首次约 1-3 分钟）..."
    $req = Join-Path $scriptDir "requirements.txt"
    if (-not (Test-Path $req)) {
        Write-Err "找不到 requirements.txt，无法安装依赖"
    } else {
        try { & $usePy -m pip install --upgrade pip --quiet --disable-pip-version-check 2>&1 | Out-Null } catch { }

        $pipArgs = @("-m", "pip", "install", "-r", $req, "--disable-pip-version-check")
        $isAdmin = ([Security.Principal.WindowsPrincipal] `
                    [Security.Principal.WindowsIdentity]::GetCurrent()
                   ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        if (-not $isAdmin) { $pipArgs += "--user" }

        $pipOut = & $usePy @pipArgs 2>&1
        $pipCode = $LASTEXITCODE
        if ($pipCode -eq 0) {
            Write-OK "依赖安装完成"
            $script:DepsOK = $true
        } else {
            $tail = ($pipOut | Select-Object -Last 6) -join " | "
            Write-Err "依赖安装失败（pip 退出码 $pipCode）"
            Write-Step "   pip 输出尾部: $tail"
            $suffix = if (-not $isAdmin) { " --user" } else { "" }
            Write-Step "   手动重试：$usePy -m pip install -r `"$req`"$suffix"
        }
    }
} else {
    Write-Step "（-SkipDeps 已指定，跳过依赖安装）"
    $script:DepsOK = $true      # 用户主动跳过，不算失败
}

# ── 6. 导入自检（在**安装目标**上跑，不是源目录）──
Write-Host ""
Write-Step "导入自检..."
if ($destList.Count -eq 0) {
    Write-Warn2 "没有成功复制的目标，跳过自检"
} else {
    $probe = $destList[0]
    $checkPy = Join-Path $env:TEMP ("wcu_check_" + $PID + ".py")
    # 路径通过 argv 传，避免路径含单引号时 here-string 断掉
    $checkSrc = @'
import sys
d = sys.argv[1]
sys.path.insert(0, d)
mods = ["mouse", "keyboard", "window", "vision", "input_inject", "safe", "locate"]
ok, fail = [], []
for m in mods:
    try:
        __import__(m)
        ok.append(m)
    except Exception as e:
        fail.append(m + " -> " + type(e).__name__ + ": " + str(e)[:60])
print("OK: " + (", ".join(ok) if ok else "(none)"))
if fail:
    print("FAIL:")
    for f in fail:
        print("  " + f)
    sys.exit(1)
'@
    Set-Content -Path $checkPy -Value $checkSrc -Encoding UTF8
    try {
        $out = & $usePy $checkPy $probe 2>&1
        $code = $LASTEXITCODE
        $out | ForEach-Object { Write-Step "   $_" }
        if ($code -eq 0) {
            Write-OK "7 个模块导入正常"
        } else {
            Write-Err "有模块导入失败 —— 通常是依赖没装好"
            Write-Step "   手动修：$usePy -m pip install -r `"$(Join-Path $scriptDir 'requirements.txt')`" --user"
        }
    } catch {
        Write-Err "自检异常: $($_.Exception.Message)"
    } finally {
        Remove-Item $checkPy -Force -ErrorAction SilentlyContinue
    }
}

# ── 7. 完整测试（可选）──
if ($Check) {
    Write-Host ""
    Write-Warn2 "即将跑完整测试：它会真实移动你的鼠标键盘、弹窗、持续 2-4 分钟"
    Write-Warn2 "期间请勿操作鼠标键盘；偶发单项失败多为靶子状态残留，重跑即可"
    Write-Step "3 秒后开始（Ctrl+C 可取消）..."
    Start-Sleep -Seconds 3
    $anyTarget = $destList | Select-Object -First 1
    foreach ($t in @("test_capabilities.py", "test_full_coverage.py", "test_extended.py", "test_locate.py")) {
        $tf = Join-Path $anyTarget $t
        if (Test-Path $tf) {
            Write-Step "   --- $t ---"
            Push-Location $anyTarget
            & $usePy $t 2>&1 | Select-String -Pattern "合计|FAIL" | ForEach-Object { Write-Step "   $_" }
            Pop-Location
        }
    }
}

# ── 8. 结论（按实际结果决定颜色，不再永远绿）──
Write-Host ""
Write-Host "====================================================="
if ($script:Problems.Count -eq 0) {
    Write-Host "  安装完成" -ForegroundColor Green
    Write-Host "====================================================="
    Write-Host ""
    Write-Step "下一步："
    Write-Step "   1. 重启你的 agent 客户端（让它重新扫描 skills 目录）"
    Write-Step "   2. 对它说：用 windows-computer-use 打开计算器算 1+1"
} else {
    Write-Host "  安装未完成 —— 有 $($script:Problems.Count) 个问题" -ForegroundColor Red
    Write-Host "====================================================="
    Write-Host ""
    Write-Step "问题清单："
    foreach ($p in $script:Problems) { Write-Step "   - $p" }
    Write-Host ""
    if ($script:FilesOK -and -not $script:DepsOK) {
        Write-Step "文件已复制到位，只差依赖。手动补一句就能用："
        Write-Step "   $usePy -m pip install -r `"$(Join-Path $scriptDir 'requirements.txt')`" --user"
    }
}
Write-Host ""
if ($script:Problems.Count -gt 0) { exit 1 } else { exit 0 }
