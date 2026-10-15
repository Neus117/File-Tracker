<#
.SYNOPSIS
    在真实桌面会话里验证各项 UI 改动。

.DESCRIPTION
    这个脚本会**真的开一个窗口**，大约 3-5 秒，然后自己关掉。
    **你不需要点任何东西**，也不需要看它——判据全部由程序读取控件属性并枚举
    真实窗口得出，不依赖截图或人眼。

    为什么要有这个包装而不直接跑 python：

    ① **无条件的收尾。** 无论 python 是正常退出、报错还是卡住，
       这里都会在超时后强杀进程。窗口不会留在你的屏幕上。

    ② **输出不能走管道。** 这是踩过的一个坑，代价是用户屏幕上出现一个
       "未响应"的窗口：

       ``ProcessStartInfo.RedirectStandardOutput = $true`` 建的是一根
       **容量有限的匿名管道**（约 4 KB）。而下面"先 WaitForExit、再 ReadToEnd"
       的顺序意味着**父进程在子进程退出前不读**。一旦子进程输出超过管道容量，
       它就会阻塞在 write 上；父进程则在等它退出——**双向死锁**。

       上一轮输出少，没触发；这一轮多加了十几条断言就触发了。

       所以改成**重定向到文件**：文件没有容量限制，写端永远不阻塞。
       "先等、后读"这条纪律保留（读之前进程已经结束）。

    注：本文件必须是 UTF-8 **带 BOM**。Windows PowerShell 5.1 读没有 BOM 的
    UTF-8 会按 ANSI 解码，中文变乱码甚至语法错误。用 ``tools/add_bom.py`` 修。

.PARAMETER TimeoutSeconds
    最长等待秒数，默认 120。超时即强杀并报失败。
#>
[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$Python = if ($env:FILE_TRACKER_PYTHON) {
    $env:FILE_TRACKER_PYTHON
} else {
    'C:\Users\Neus117\miniconda3\envs\ft_env\python.exe'
}
$Script = Join-Path $Root 'tools\verify_gui.py'

if (-not (Test-Path -LiteralPath $Python)) { throw "找不到 Python: $Python" }
if (-not (Test-Path -LiteralPath $Script)) { throw "找不到验证脚本: $Script" }

Write-Host "会开一个名为 'FileTracker GUI Verify' 的窗口，约 3-5 秒后自动关闭。" -ForegroundColor Yellow
Write-Host "不需要你点任何东西。最长等待 $TimeoutSeconds 秒，超时会强制结束。" -ForegroundColor Yellow
Write-Host ''

$outFile = Join-Path $env:TEMP "filetracker-verify-$PID.out.txt"
$errFile = Join-Path $env:TEMP "filetracker-verify-$PID.err.txt"
$startedAt = Get-Date

$proc = $null
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Python
    # -u 关闭缓冲：输出直接落到文件，不留半截
    $psi.Arguments = "-X utf8 -u `"$Script`""
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    # **不用 RedirectStandardOutput**：那会建一根 4 KB 的管道，
    # 而父进程要到子进程退出后才读，输出一多就双向死锁（见头部说明）。
    # 用 cmd 的重定向把输出写进文件——文件没有容量限制，写端不阻塞。
    $psi.RedirectStandardOutput = $false
    $psi.RedirectStandardError = $false
    $psi.CreateNoWindow = $true

    # 通过 cmd 做文件重定向（ProcessStartInfo 本身没有"重定向到文件"的选项）
    $psi.FileName = $env:ComSpec
    $psi.Arguments = "/c `"`"$Python`" -X utf8 -u `"$Script`" > `"$outFile`" 2> `"$errFile`"`""

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()

    $exited = $proc.WaitForExit($TimeoutSeconds * 1000)

    if (-not $exited) {
        # **超时也必须收尾**：进程可能正卡在一个模态窗口上。
        # 只用 Kill() 这个无参重载——这台机器上是 .NET Framework 的
        # PowerShell 5.1，没有 Kill(bool entireProcessTree)。
        # 注意 kill 的是 cmd；它下面的 python 还要单独收。
        try { $proc.Kill() } catch { }
        try { [void]$proc.WaitForExit(5000) } catch { }
        Get-Process -Name python -ErrorAction SilentlyContinue |
            Where-Object { $_.StartTime -ge $startedAt } |
            ForEach-Object { try { $_.Kill() } catch { } }
    }

    # 进程已结束，现在读文件是安全的
    if (Test-Path -LiteralPath $outFile) {
        Get-Content -LiteralPath $outFile | ForEach-Object { Write-Host $_ }
    }
    if (Test-Path -LiteralPath $errFile) {
        $errText = Get-Content -LiteralPath $errFile
        if ($errText) {
            Write-Host '--- stderr ---' -ForegroundColor DarkGray
            $errText | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
        }
    }

    if (-not $exited) {
        Write-Host ''
        Write-Host "超时 ${TimeoutSeconds}s，已强制结束进程（窗口应已关闭）。" -ForegroundColor Red
        exit 1
    }

    exit $proc.ExitCode
}
catch {
    Write-Host "验证脚本自身出错: $_" -ForegroundColor Red
    # 兜底：无论如何不要把一个 python 进程留在用户屏幕上
    if ($proc -ne $null) {
        try { if (-not $proc.HasExited) { $proc.Kill() } } catch { }
    }
    exit 2
}
finally {
    Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue
}
