# 从源码运行 File Tracker（调试用，不构建 exe）
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
#
# 或者直接在资源管理器里右键这个文件 →「使用 PowerShell 运行」。
#
# 为什么需要这个脚本：
#   1. 必须用 ft_env 里的 Python（base 是 3.14，没有 wxPython 的 wheel）
#   2. 必须清 __pycache__，否则改完代码可能跑的还是旧字节码
#   3. 改完 .ps1 要补 BOM，否则 Windows PowerShell 5.1 按 GBK 解码会乱码

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

# -- Python 解释器 ---------------------------------------------------------
# 优先用环境变量指定的，方便你自己换
$Python = $env:FILE_TRACKER_PYTHON
if (-not $Python) {
    $Python = 'C:\Users\Neus117\miniconda3\envs\ft_env\python.exe'
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "找不到 Python: $Python`n请设置环境变量 FILE_TRACKER_PYTHON 指向你的解释器。"
}

Write-Host "Python : $Python"
& $Python -c "import wx; print('wxPython', wx.version())"
if ($LASTEXITCODE -ne 0) {
    throw "这个 Python 里没有 wxPython。base 环境是 3.14，装不了 wxPython 4.2.2。"
}

# -- 清掉字节码缓存 --------------------------------------------------------
# 不做这一步的话，改完 .py 有可能仍加载旧的 .pyc，你会以为改动没生效。
Get-ChildItem -LiteralPath $Root -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host '启动中……（关掉窗口即退出）'
Write-Host ''

# -- 启动 ------------------------------------------------------------------
# 用文件方式运行，**不要用 python -c**：-c 会让 wx 把 "-c" 当成
# 应用名，GetUserDataDir() 会变成 %APPDATA%\-c，配置就读错地方了。
& $Python -X utf8 (Join-Path $Root 'src\main.py')
exit $LASTEXITCODE
