<#
.SYNOPSIS
    File Tracker 构建脚本：检查 → 测试 → 打包 → 自检 → 报告哈希。

.DESCRIPTION
    Roboc 的 build.ps1 是这个脚本的骨架来源。两条经验直接照搬：

    ① **每一步都要能在失败时停下来并说清楚原因。** 构建脚本最坏的行为是
       "看起来成功了，产物其实是旧的"。

    ② **产物必须自报身份。** 最后一步真的去跑 exe 的 --version，
       而不是相信 spec 里那个变量——"我以为我写进去了"和"它真的在里面"
       是两件事。

    这个脚本**不发版**。发版是单独的一步，见 docs/RELEASING.md。

.PARAMETER SkipTests
    跳过 pytest。只在你已经单独跑过测试时用。

.PARAMETER Console
    打出带控制台的版本，用于排查启动期问题。

.EXAMPLE
    pwsh -File build.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$Console
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
Set-Location $Root

# 项目钉的是 Python 3.11：wxPython 4.2.2 没有 3.14 的 wheel（PyPI 上最高到 cp313）。
$Python = if ($env:FILE_TRACKER_PYTHON) {
    $env:FILE_TRACKER_PYTHON
} else {
    'C:\Users\Neus117\miniconda3\envs\ft_env\python.exe'
}

function Write-Step {
    param([string]$Text)
    Write-Host ''
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Assert-Success {
    param([string]$What)
    if ($LASTEXITCODE -ne 0) {
        throw "$What 失败（退出码 $LASTEXITCODE）"
    }
}

# --------------------------------------------------------------------------
Write-Step '0. 环境检查'
# --------------------------------------------------------------------------

if (-not (Test-Path -LiteralPath $Python)) {
    throw "找不到 Python: $Python`n请先建环境：conda env create -f environment_v1.1+.yml"
}

$version = & $Python -c "import sys; print(sys.version.split()[0])"
Assert-Success '读取 Python 版本'
Write-Host "Python : $Python ($version)"

& $Python -c "import wx, sys; print('wxPython', wx.version())"
if ($LASTEXITCODE -ne 0) { throw "wx 不可用——请确认用的是 ft_env，而不是 base（base 是 3.14，没有 wx wheel）" }

& $Python -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)"
Assert-Success '读取 PyInstaller 版本'

# --------------------------------------------------------------------------
Write-Step '1. 测试'
# --------------------------------------------------------------------------

if ($SkipTests) {
    Write-Host '已按要求跳过。' -ForegroundColor Yellow
} else {
    & $Python -X utf8 -m pytest $Root
    Assert-Success 'pytest'
}

# **对话框调用点检查。**
#
# 用户报过："失效删除确认弹窗有两个按钮，功能完全一致——关闭窗口。"
# 那一类是**静态就能查出来**的：给了两个按钮却没读 `ShowModal()` 的返回值。
#
# 它不进 pytest 是因为它检查的是**源码形状**，不是运行时行为；
# 放在构建里能让每次发版都过一遍（pytest 只覆盖被写成测试的东西）。
& $Python -X utf8 (Join-Path $Root 'tools\check_dialogs.py')
Assert-Success '对话框调用点检查'

# **同名方法定义了两次。**
#
# 审计发现 `FileTracker._remember_sort` 被定义了两次（函数体完全相同）。
# Python 只用后一个，于是"改前一个"**不会有任何效果**，而且不报错——
# 而 `app.py` 开头的模块文档就记着同一类教训，它**又长出来了一次**。
# 人工审查看不出来（两份相隔一千多行），AST 一眼就能判。
& $Python -X utf8 (Join-Path $Root 'tools\check_duplicate_methods.py')
Assert-Success '重复方法检查'

# **审计条目清账。**
#
# 这一轮的输入是一次系统性审计（功能 / 健壮性 / 体积 / 仓库卫生），
# 列了 C1-C3、M1-M5、m1-m10 共 18 项。这个脚本把每一项写成一条**可执行判据**，
# 跑通才算"处理完了"——"我记得都改完了"不是证据。
& $Python -X utf8 (Join-Path $Root 'tools\check_audit_items.py')
Assert-Success '审计条目清账'

# --------------------------------------------------------------------------
Write-Step '2. 确定构建身份'
# --------------------------------------------------------------------------

$revision = (& git rev-parse --short=7 HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $revision) { $revision = 'unknown' }
$revision = $revision.Trim()

$dirty = (& git status --porcelain)
if ($dirty) {
    Write-Host '工作区有未提交改动——产物自报的哈希会对应最后一次提交，不是当前磁盘内容。' -ForegroundColor Yellow
}

# 把哈希固定下来再打包，避免"构建过程中仓库被改"导致产物自报的哈希与实际代码不符
$env:FILE_TRACKER_BUILD_REV = $revision
if ($Console) { $env:FILE_TRACKER_CONSOLE = '1' } else { Remove-Item Env:\FILE_TRACKER_CONSOLE -ErrorAction SilentlyContinue }

Write-Host "提交   : $revision"

# --------------------------------------------------------------------------
Write-Step '3. 打包'
# --------------------------------------------------------------------------

foreach ($stale in @('build', 'dist')) {
    if (Test-Path -LiteralPath $stale) {
        # 必须清掉：PyInstaller 会复用 build/ 里的缓存，
        # 改过 .spec 之后不复用旧缓存就不会生效
        try {
            Remove-Item -LiteralPath $stale -Recurse -Force -ErrorAction Stop
        }
        catch {
            # 最常见的原因：产物正在运行，文件被占用。
            # 直接抛原始异常的话只有一行英文的 "Access is denied"，
            # 看不出"程序还开着"——这里说清楚要做什么。
            $running = @(Get-Process -Name 'File Tracker' -ErrorAction SilentlyContinue)
            if ($running.Count -gt 0) {
                throw ("无法重建：产物正在运行（当前 $($running.Count) 个实例）。" +
                       "请先关闭 File Tracker 窗口，然后重新运行 build.ps1。")
            }
            throw "无法清理 ${stale}：$($_.Exception.Message)"
        }
    }
}

& $Python -m PyInstaller 'File-Tracker.spec' --noconfirm --log-level WARN
Assert-Success 'PyInstaller'

$exe = Join-Path $Root 'dist\File Tracker.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    # PyInstaller 在不带 console 时会把 exe 放在 dist/ 下，名字取自 spec 的 name
    $candidate = Get-ChildItem -LiteralPath (Join-Path $Root 'dist') -Filter '*.exe' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $candidate) { throw "dist/ 下没有产物" }
    $exe = $candidate.FullName
}

$sizeMb = [math]::Round((Get-Item -LiteralPath $exe).Length / 1MB, 2)
Write-Host "产物   : $exe ($sizeMb MB)"

# --------------------------------------------------------------------------
Write-Step '4. 产物自检'
# --------------------------------------------------------------------------

<#
.SYNOPSIS
    运行产物并把它的标准输出抓回来（windowed 程序也适用）。

.DESCRIPTION
    **不能直接用 `& $exe --version` 赋值。** 这个 exe 是 windowed 子系统，
    没有控制台；PowerShell 对"无控制台的 GUI 子进程"的输出捕获不可靠，
    **实测拿到的是空字符串，而脚本当时没有断言输出非空**——于是一次"成功"
    的构建掩盖了"产物不会自报版本"这个事实。

    顺带守一条纪律：**读操作要排在等待之后**，否则一次读就能把脚本永久卡住
    （见 `01-反复犯的错.md` 错误六）。

    **也不能用 `Start-Process`**：它在 Windows PowerShell 5.1 上会因为环境里
    同时存在 `NO_PROXY` 与 `no_proxy` 而抛「已添加项。字典中的关键字」——
    它构造子进程环境块时用的是大小写敏感的容器。用 `ProcessStartInfo` 绕开。

    **输出也不能走管道。** 这也是踩过的坑，代价是用户屏幕上出现一个"未响应"
    的窗口：`RedirectStandardOutput = $true` 建的是一根**容量有限的匿名管道**
    （约 4 KB），而"先 WaitForExit、再 ReadToEnd"的顺序意味着父进程在子进程
    退出前不读。子进程输出一超过管道容量就阻塞在 write 上，父进程在等它退出
    ——**双向死锁**。所以走 cmd 的文件重定向，文件没有容量限制。
#>
function Get-ExeOutput {
    param(
        [Parameter(Mandatory)][string]$Exe,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $outFile = Join-Path $env:TEMP "filetracker-exe-out-$PID.txt"
    $errFile = Join-Path $env:TEMP "filetracker-exe-err-$PID.txt"
    Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    # **把 `FILE_TRACKER_BUILD_REV` 从子进程环境里删掉。**
    #
    # 这个变量是本脚本自己设的（见前面 `$env:FILE_TRACKER_BUILD_REV`），
    # 而它是 `core.build_revision()` 的**第 2 号来源**。
    # 不清掉的话，自检时 exe 会从环境变量读到哈希——
    # **即使包里根本没写进去，校验也会通过**。
    #
    # v1.2.0 就是这么发出去的：产物自报 `unknown`，而构建全绿。
    # 测"它自己能不能说清楚自己是谁"，就必须在**没有外援**的条件下测。
    $psi.Arguments = "/c `"`"$Exe`" $($Arguments -join ' ') > `"$outFile`" 2> `"$errFile`"`""
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $false
    $psi.RedirectStandardError = $false
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()

    $finished = $proc.WaitForExit(60000)
    if (-not $finished) {
        try { $proc.Kill() } catch { }
        try { [void]$proc.WaitForExit(5000) } catch { }
        throw "产物 $Exe $($Arguments -join ' ') 超过 60 秒没有退出，已强制结束。"
    }

    $text = ''
    if (Test-Path -LiteralPath $outFile) {
        $text = (Get-Content -LiteralPath $outFile -Raw -ErrorAction SilentlyContinue)
    }
    $errText = ''
    if (Test-Path -LiteralPath $errFile) {
        $errText = (Get-Content -LiteralPath $errFile -Raw -ErrorAction SilentlyContinue)
    }
    Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue

    return [pscustomobject]@{
        ExitCode = $proc.ExitCode
        StdOut   = if ($text) { $text.Trim() } else { '' }
        StdErr   = if ($errText) { $errText.Trim() } else { '' }
    }
}

# **直接跑 exe，而不是相信 spec 里的变量。**
# 这一步问的是"它真的把哈希写进自己了吗"，答案是它自己说出来的才算。
#
# **必须先把这个变量从环境里摘掉。**
#
# `$env:FILE_TRACKER_BUILD_REV` 是本脚本自己设的（见前面），而它是
# `core.build_revision()` 的**第 2 号来源**。挂着它跑自检，exe 会从
# 环境变量读到哈希 —— **即使包里根本没写进去，校验也会通过**。
#
# v1.2.0 就是这么发出去的：产物自报 `unknown`，构建却全绿。
# 测"它自己能不能说清楚自己是谁"，就必须在**没有外援**的条件下测。
#
# 用"从当前进程摘掉再放回"而不是 `$psi.Environment*.Remove(...)`：
# 那个属性在 Windows PowerShell 5.1 与 PowerShell 7 上不通用，
# 实测其中一边会得到 `$null`，报"不能对 Null 值表达式调用方法"。
$savedRevisionVar = $env:FILE_TRACKER_BUILD_REV
try {
    Remove-Item Env:\FILE_TRACKER_BUILD_REV -ErrorAction SilentlyContinue
    $versionRun = Get-ExeOutput -Exe $exe -Arguments @('--version')
} finally {
    if ($savedRevisionVar) { $env:FILE_TRACKER_BUILD_REV = $savedRevisionVar }
}
$reported = $versionRun.StdOut

if ($versionRun.ExitCode -ne 0) {
    throw "产物 --version 退出码为 $($versionRun.ExitCode)：$($versionRun.StdErr)"
}
# 没有这一条断言，上面那次"输出为空但没报错"就会一路走到发版
if ([string]::IsNullOrWhiteSpace($reported)) {
    # 注意：这条 throw 必须写成**单个字符串、单行**。
    # 写成跨行的 '(' + '...' 拼接时，Windows PowerShell 5.1 会在中文行尾报
    # "Missing closing ')' in expression"——解析器把行尾的中文标点当成了 token。
    throw "产物 --version 没有输出任何内容。它是 windowed 程序，stdout 可能不可用；它必须能自报版本，否则用户报障时无法判断装的是哪一个。"
}
Write-Host "自报   : $reported"

if ($reported -notmatch [regex]::Escape($revision)) {
    throw "产物自报的版本串里没有构建提交 $revision —— 它无法说明自己是哪一个版本"
}

# **版本资源必须真的在产物里。**
#
# 用户要求"参照 Roboc.exe 的版本信息构建"——那是 Explorer
# 「属性 → 详细信息」看到的一页。它由 `tools/version_info.py` 生成、
# 经 spec 的 `version=` 传给 PyInstaller。
#
# 这一步是**读回产物**而不是相信 spec 里的变量：spec 里那行写对了，
# 但 PyInstaller 没吃进去的情况是存在的（`--version` 那个缺陷就是这么来的）。
# 读回来还顺带确认了四个字段的值，而不只是"有资源"。
# **检查逻辑放在一个 Python 脚本里，不内联。**
# 内联时要穿过 PowerShell 的引号、cmd 的重定向、Python 的字符串三层转义，
# 写对一次、改坏一次几乎是必然的。
# 期望值取自**产物自己刚报出来的版本串**（`$reported`，形如
# "File Tracker 1.2.2+5c031de"），不另外去 core.py 解析一遍。
#
# 这样这一步比较的是**产物说的两件事**：`--version` 报的版本，
# 与版本资源里的产品版本。两者必须一致，否则「属性」页会骗人。
# （另：`$version` 是 **Python 的版本** 3.11.9，不是本程序的，别用错。）
$appVersion = ($reported -split '\+')[0].Trim().Split(' ')[-1]
# **带空格的参数必须自己加引号。**
# `Get-ExeOutput` 是把参数用空格拼进 cmd 命令行的，而产物叫
# `File Tracker.exe` —— 不加引号就成了三个参数，检查脚本会报
# "用法: check_exe_version.py <exe> <期望的产品版本>"（退出码 2）。
$script = Join-Path $Root 'tools\check_exe_version.py'
$versionCheck = Get-ExeOutput -Exe $Python -Arguments @(
    "`"$script`"", "`"$exe`"", "`"$appVersion`""
)
Write-Host "版本资源: $($versionCheck.StdOut.Trim())"
if ($versionCheck.ExitCode -ne 0) {
    throw "产物的版本资源不合格（退出码 $($versionCheck.ExitCode)）：$($versionCheck.StdErr)$($versionCheck.StdOut)"
}

$selfTest = Get-ExeOutput -Exe $exe -Arguments @('--selftest')
if ($selfTest.ExitCode -ne 0) {
    throw "产物 --selftest 失败（退出码 $($selfTest.ExitCode)）：$($selfTest.StdOut) $($selfTest.StdErr)"
}
Write-Host "自检   : $($selfTest.StdOut)"

# --------------------------------------------------------------------------
Write-Step '5. 报告'
# --------------------------------------------------------------------------

# **不要假设 `Get-FileHash` 一定可用。**
#
# 实测：本机在 `powershell -NoProfile` 里（也就是从 cmd 启动 build.ps1 时）
# `Get-FileHash` **不在 PATH 上**——它属于 `Microsoft.PowerShell.Utility`，
# 而那个模块在当前环境的 -NoProfile 会话里没被加载。
# 结果构建跑到最后一步才炸，前面 4 步全部白做。
#
# 所以退回 .NET 的 SHA256：任何 PowerShell 版本、任何 profile 下都能用。
$hash = $null
try {
    $hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
} catch {
    $hash = $null
}
if (-not $hash) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($exe)
        try {
            $hash = ([System.BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '')
        } finally {
            $stream.Dispose()
        }
    } finally {
        $sha.Dispose()
    }
}
Write-Host "SHA256 : $hash"
Write-Host ''
Write-Host '构建完成。发版见 docs/RELEASING.md（标签必须指向代码提交）。' -ForegroundColor Green

[pscustomobject]@{
    Exe      = $exe
    Version  = $reported
    Revision = $revision
    SizeMB   = $sizeMb
    SHA256   = $hash
}
