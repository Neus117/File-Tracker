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

# 构建期模块：core.build_revision() 会优先读它。
# 单文件 exe 里既没有 .git 也没有构建脚本，这是唯一可靠的来源。
build_info = os.path.join(SPECPATH, "_build_info.py")  # noqa: F821
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
    # 两个都要在路径上：
    #   src/        —— file_tracker 包
    #   SPECPATH    —— 构建期生成的 _build_info（core.build_revision 优先读它）
    # 只给 src/ 的话 _build_info 可能找不到，产物就会自报 "unknown"
    pathex=[os.path.join(SPECPATH, "src"), SPECPATH],  # noqa: F821
    binaries=[],
    # 显式声明 images/ → _MEIPASS/images，不再依赖"目录结构碰巧同构"
    datas=[(os.path.join(SPECPATH, "images"), "images")],  # noqa: F821
    hiddenimports=["_build_info"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 明确排除：这些都没有被 import，留着只会撑大体积并引入冲突风险
    excludes=[
        "pywin32", "win32api", "win32com", "pythoncom", "pywintypes",
        "numpy", "PyQt5", "PyQt6", "PySide2", "PySide6",
        "pytest", "_pytest", "unittest", "pydoc", "doctest",
        "tkinter", "test", "distutils",
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
)

# 清理构建期临时模块，免得被误提交（.gitignore 里也有一条）
try:
    os.remove(build_info)
except OSError:
    pass

# 用英文输出：这个 print 会经过 PyInstaller 的 stdout，
# 而 Windows 控制台默认是 GBK，中文会变成乱码（踩过一次）
print(f"[spec] version {VERSION}  revision {REVISION}  windowed {WINDOWED}")
