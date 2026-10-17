# -*- mode: python ; coding: utf-8 -*-
"""File Tracker 打包配置。

**这个文件以前不存在**，所以 v1.1.0 那个 exe 是怎么打出来的只存在于作者记忆里，
没人能复现。项目笔记第三节 ⑤ 记的就是这件事。

它同时解决那处"打包后反而能跑、从源码必然失败"的巧合：

    ``images/`` 被放进 ``_MEIPASS`` 的**根**，恰好与仓库根的 ``images/`` 同构，
    所以 ``sys._MEIPASS/images/...`` 能命中——**是巧合，不是设计**。

现在 ``datas`` 里显式声明了映射关系，且 :func:`file_tracker.core.resource_path`
按同一条规则解析，两边不再是"碰巧一致"。

用法::

    pyinstaller File-Tracker.spec --noconfirm
"""

import os
import subprocess
import sys

# --------------------------------------------------------------------------
# 构建期信息：让产物能自报"是哪个提交构建的"
# --------------------------------------------------------------------------

def _git(*args: str) -> str:
    """跑一条 git 命令；失败返回空串（打包环境可能没有 git）。"""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=SPECPATH,  # noqa: F821 - PyInstaller 注入的 spec 目录
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def resolve_revision() -> str:
    """确定要写进产物的提交哈希。

    优先取环境变量：构建脚本会先打一次，避免"构建过程中仓库被改"导致
    产物自报的哈希与实际代码不符。
    """
    return (
        os.environ.get("FILE_TRACKER_BUILD_REV", "").strip()
        or _git("rev-parse", "--short=7", "HEAD")
        or "unknown"
    )


def resolve_version() -> str:
    """从 ``file_tracker/__init__.py`` 读版本号，保证与源码一致。"""
    version_file = os.path.join(SPECPATH, "src", "file_tracker", "core.py")  # noqa: F821
    try:
        with open(version_file, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("APP_VERSION"):
                    return line.split("=", 1)[1].strip().strip('"\'')
    except OSError:
        pass
    return "0.0.0"


REVISION = resolve_revision()
VERSION = resolve_version()
WINDOWED = os.environ.get("FILE_TRACKER_CONSOLE", "") != "1"

# 版本资源（Explorer 属性页）。实现与理由都在 tools/version_info.py，
# 这里只把它拿进来——spec 不该塞下第二份"每个字段是什么意思"的说明。
sys.path.insert(0, os.path.join(SPECPATH, "tools"))  # noqa: F821
from version_info import build_version_info as _build_version_info  # noqa: E402

# 构建期模块：core.build_revision() 会优先读它。
# 单文件 exe 里既没有 .git 也没有构建脚本，这是唯一可靠的来源。
#
# **必须写进 `file_tracker/` 包内。**
#
# 踩过（v1.2.0 发版时才发现）：原来写在仓库根，于是它是一个**顶层模块**
# `_build_info`；而 `core.py` 读的是 `from ._build_info import ...`
# —— **包内相对导入**。路径对不上，导入永远 ImportError 被吞掉，
# 产物一律自报 `File Tracker 1.2.0+unknown`。
#
# 更糟的是它**测不出来**：`build.ps1` 把 `FILE_TRACKER_BUILD_REV`
# 设进了自己的进程环境，而那是 `build_revision()` 的**第 2 号来源**。
# 自检时跑 exe，exe 从环境变量里读到了哈希 —— 校验因此恒过。
# 也就是说「产物必须能自报哈希」这条纪律**从未真正成立**。
package_dir = os.path.join(SPECPATH, "src", "file_tracker")  # noqa: F821
build_info = os.path.join(package_dir, "_build_info.py")
with open(build_info, "w", encoding="utf-8") as handle:
    handle.write(
        "# 由 File-Tracker.spec 在打包时生成，请勿手工编辑，也不要提交。\n"
        f"BUILD_REVISION = {REVISION!r}\n"
        f"BUILD_VERSION = {VERSION!r}\n"
    )

# --------------------------------------------------------------------------
# 分析
# --------------------------------------------------------------------------

a = Analysis(  # noqa: F821
    [os.path.join(SPECPATH, "src", "main.py")],  # noqa: F821
    # `src/` 必须在路径上，`file_tracker` 包从这里解析。
    #
    # 早先还加了 `SPECPATH`，理由是"让构建期生成的 `_build_info` 找得到"——
    # **那个理由本身是错的**：`core.py` 用的是包内相对导入
    # `from ._build_info import ...`，它只会去 `file_tracker/` 里找。
    # 所以现在 `_build_info.py` 就写在包内（见上），`SPECPATH` 不再需要。
    pathex=[os.path.join(SPECPATH, "src")],  # noqa: F821
    binaries=[],
    # **只打运行时真正用的那几个资源，不再整目录塞进去。**
    #
    # 原来是 `(images 目录, "images")` —— 整目录复制。于是**文档用的截图
    # 也被打进了 exe**（两张 Overview 共 358 KB，约产物的 2%）。
    #
    # 那些图是 **README 的展示图**，**程序运行时一个字节都不读**。
    # 它们该留在仓库里，但不该进产物。
    #
    # 现状：旧的 `FileTracker_v1.0/v1.1-Overview.jpg` 都已删除
    # （v1.1 那张画的是**旧界面**——图上还有个早就删掉的「切换排序」按钮，
    # 当作 v1.2.4 的展示图会与实物不符）。README 现在用
    # `FileTracker_v1.2.4-light.jpg` / `-dark.jpg`，那两张**同样只是展示图**，
    # 所以同样不在下面的清单里。
    #
    # 逐个列出而不是"排除两个"：这样**新增资源必须显式登记**，
    # 不会因为"放进 images/ 就自动进产物"而再次混进文档文件。
    # 漏登记会立刻暴露——资源加载失败是可见的（`--selftest` 也会报）。
    datas=[
        (os.path.join(SPECPATH, "images", name), "images")  # noqa: F821
        for name in (
            "shell32_star.ico",   # 窗口/任务栏图标
            "pin_grey.png",       # 顶置按钮（未顶置）
            "pin_red.png",        # 顶置按钮（已顶置）
            "settings.png",       # 设置按钮
        )
    ],
    # `file_tracker._build_info` 是**运行时才有**的模块（打包时刚生成），
    # 静态分析看不到它被 import，所以要显式声明，否则会被漏掉。
    hiddenimports=["file_tracker._build_info"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 明确排除：这些都没有被 import，留着只会撑大体积并引入冲突风险
    excludes=[
        "pywin32", "win32api", "win32com", "pythoncom", "pywintypes",
        "numpy", "PyQt5", "PyQt6", "PySide2", "PySide6",
        "pytest", "_pytest", "unittest", "pydoc", "doctest",
        "tkinter", "test", "distutils",
        # === 体积：这几个只有 stdlib 内部才用，应用从不 import ===
        #
        # `libcrypto-3-x64.dll`（2.11 MB）的依赖链（用 PyInstaller 的 xref 查清）：
        #   libcrypto ← _hashlib ← hashlib ← tarfile / zipfile
        # 应用源码里**没有** ssl / hashlib / http / urllib / socket。
        # 排掉这三个之后 `libcrypto` 与 `_hashlib` 都不再进产物。
        #
        # ⚠️ **`ast` / `dis` 不能排**：`inspect` 依赖它们，排掉会让
        #    `pyi_rth_inspect` 在启动时抛 ModuleNotFoundError（实测：弹崩溃框）。
        # ⚠️ **`socket` 不能排**：实测进程活着但窗口起不来。
        # ⚠️ **每加一项都要跑 GUI 回归**（`tools/verify_gui.py`）——
        #    "包打得出来"与"界面能用"是两件事，本项目为此栽过跟头。
        "tarfile", "hashlib", "email",
        # === wx 的 html 子模块（0.39 MB = 产物的 2.9%）===
        #
        # `probe_bundle_size.py` 实测：
        #   wxmsw32u_html_vc140_x64.dll  0.22 MB
        #   _html.cp311-win_amd64.pyd    0.17 MB
        #
        # 源码里**一处都没有**用到（grep `wx.html` / `HtmlWindow` /
        # `wx.richtext` / `wx.xrc` 全为空）—— 它是 **PyInstaller 的
        # wx hook 默认打进来**的，不是我们引的。
        #
        # 本项目不渲染任何 HTML，排掉没有功能损失。
        "wx.html", "wx.html2", "wx.richtext", "wx.xrc",
        # === wx 的另外四块（2026-10-17，实测省 0.29 MB）===
        #
        # `wx.adv` / `wx.propgrid` / `wx.aui` / `wx.grid`
        # —— `grep src/file_tracker/*.py` 全部 **0 处引用**。
        # 本项目只用 `wx.Frame / Panel / ListCtrl / TreeCtrl / Dialog /
        # StaticText / Bitmap / DC / GraphicsContext / SplitterWindow`，
        # 全在 wx 核心里。
        #
        # ## 收益：**只有 0.29 MB**（12.99 → 12.70），不是 3.37 MB
        #
        # 四个 pyd 在解释器目录里合计 3.37 MB，但用 `CArchiveReader` 查
        # exe 内部发现 **它们本来就不在包里** —— PyInstaller 的 wx hook
        # 早就不打这些子模块了。那 0.29 MB 是别的连带效应省出来的。
        #
        # 所以这一项属于"**顺手写上、零风险、收益小**"，不是体积优化的
        # 主要手段。真正的大头（压缩前合计 33.31 MB）省不掉：
        #
        #   wx\wxmsw32u_core_vc140_x64.dll   7.99 MB   ← wx 核心
        #   wx\_core.cp311-win_amd64.pyd     7.22 MB   ← wx 绑定
        #   python311.dll                    5.74 MB   ← 运行时
        #   wx\wxbase32u_vc140_x64.dll       2.81 MB   ← wx 基础
        #   sqlite3.dll                      1.60 MB   ← 数据库
        #
        # ⇒ **12.7 MB 已是这套技术栈的地板**，再往下只能换 GUI 框架。
        #
        # ## ⚠️ 曾被误判成"是它导致 exe 起不来"
        #
        # 我一度判定"加了这四项之后窗口出不来"，回退了改动、删了 dist、
        # 还写进文档说"打包有未解问题"。**那是误判** —— 真正的错因是
        # 我的检测方法：`--onefile` 是两层进程（bootloader + 子进程），
        # 而窗口属于**子进程**，我却按 `Popen` 拿到的父进程 pid 去查。
        #
        # 修好检测（按进程树查窗口）后，带这四项的 exe **0.6 秒出窗口**。
        # 见 `tools/probes/probe_launch_check.py` 的 `descendant_pids()`。
        "wx.adv", "wx.propgrid", "wx.aui", "wx.grid",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="File Tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX 会让某些杀软误报，且对 wxPython 的 DLL 不安全
    upx_exclude=[],
    runtime_tmpdir=None,
    console=not WINDOWED,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPECPATH, "images", "shell32_star.ico"),  # noqa: F821
    # **版本资源**：Explorer「属性 → 详细信息」那一页。
    #
    # 没有它的时候那一页几乎是空的——文件说明、版权都没写，
    # 用户报障时也没法从属性里读出装的是哪一版。
    # 字段与取值对照 Roboc 的 `Directory.Build.props`，见 tools/version_info.py。
    #
    # 注意 `ProductVersion` 里**不带提交哈希**：哈希留在
    # `--version` 的输出里，属性页只显示干净的 1.2.2。
    version=_build_version_info(VERSION),  # noqa: F821
)

# 清理构建期临时模块，免得被误提交（.gitignore 里也有一条）
try:
    os.remove(build_info)
except OSError:
    pass

# 用英文输出：这个 print 会经过 PyInstaller 的 stdout，
# 而 Windows 控制台默认是 GBK，中文会变成乱码（踩过一次）
print(f"[spec] version {VERSION}  revision {REVISION}  windowed {WINDOWED}")
