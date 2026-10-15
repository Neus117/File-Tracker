"""纯逻辑层的测试：路径规范化、资源路径、窗口尺寸、版本串。

**这个文件不创建任何窗口、不启动 GUI。** 原来的 ``tests/test_file_tracker.py``
真的去 ``MainWindow()``，在 CI 里会失败或挂死——而且它 import 的模块与类
**两个都不存在**。这里的每一条都能在无桌面会话的环境里跑完。
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from file_tracker import core


# --------------------------------------------------------------------------
# resource_path —— 从 v1.0.3 恢复的那个函数
# --------------------------------------------------------------------------

def test_resource_path_resolves_to_repo_root_from_source():
    """从源码运行时，资源路径必须落在**仓库根目录**下的 ``images/``。

    v1.1 丢失这个函数后找的是 ``<repo>\\src\\images\\``（不存在），
    所以从源码运行必然加载不到图标。
    """
    resolved = core.resource_path("images/shell32_star.ico")
    assert os.path.isabs(resolved)

    repo_root = os.path.dirname(core.__file__)          # <repo>/src/file_tracker
    repo_root = os.path.dirname(os.path.dirname(repo_root))  # <repo>
    assert os.path.normcase(resolved) == os.path.normcase(
        os.path.join(repo_root, "images", "shell32_star.ico")
    )


def test_resource_path_actually_finds_the_real_icon():
    """真实资源必须能被解析到。这是"从源码跑起来有图标"的充要证据。"""
    assert os.path.exists(core.resource_path("images/shell32_star.ico"))
    assert os.path.exists(core.resource_path("images/pin_grey.png"))
    assert os.path.exists(core.resource_path("images/pin_red.png"))


def test_resource_path_uses_meipass_when_frozen(monkeypatch, tmp_path):
    """打包运行时必须走 ``sys._MEIPASS``（PyInstaller 单文件解包目录）。"""
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    resolved = core.resource_path("images/shell32_star.ico")
    assert os.path.normcase(resolved) == os.path.normcase(
        os.path.join(str(tmp_path), "images", "shell32_star.ico")
    )


def test_resource_path_accepts_backslash_separators():
    """两种分隔符都要能解析——仓库里两种写法都出现过。"""
    forward = core.resource_path("images/pin_red.png")
    backward = core.resource_path("images\\pin_red.png")
    assert forward == backward


def test_resource_path_does_not_pretend_missing_files_exist():
    """阴性的检查结果必须先证明检测器真的跑了。

    这个方法**不保证路径存在**，存在性判断交给调用方——所以对不存在的资源
    它必须返回一个不存在的路径，而不是悄悄回退到别的什么。
    """
    resolved = core.resource_path("images/definitely-not-here.png")
    assert not os.path.exists(resolved)


# --------------------------------------------------------------------------
# normalize_path
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (r"C:\Users\Neus", r"C:\Users\Neus"),
    ("C:/Users/Neus", r"C:\Users\Neus"),          # 正斜杠统一
    ("C:\\Users\\Neus\\", r"C:\Users\Neus"),       # 末尾分隔符去掉
    ("  C:\\Users\\Neus  ", r"C:\Users\Neus"),     # 首尾空白
    ('"C:\\Users\\Neus"', r"C:\Users\Neus"),       # 资源管理器"复制为路径"带引号
    ("C:\\Users\\.\\Neus", r"C:\Users\Neus"),      # 当前目录段
    ("C:\\Users\\Other\\..\\Neus", r"C:\Users\Neus"),  # 上级目录段
    ("C:\\", "C:\\"),                              # 盘符根保留尾分隔符
    ("C:/", "C:\\"),
    ("", ""),
    ("   ", ""),
])
def test_normalize_path(raw, expected):
    assert core.normalize_path(raw) == expected


def test_normalize_path_preserves_case():
    """**刻意不改变大小写**：Windows 不区分大小写但保留大小写。

    ``lower()`` 会让界面显示成用户从没输入过的样子。
    """
    assert core.normalize_path(r"C:\Program Files") == r"C:\Program Files"
    assert core.normalize_path("c:/WINDOWS") == r"c:\WINDOWS"


# --------------------------------------------------------------------------
# 路径比较
# --------------------------------------------------------------------------

@pytest.mark.parametrize("left,right", [
    (r"C:\Users", r"c:\users"),
    (r"C:\Users\\", "C:/Users"),
    ('"C:\\Users"', r"C:\Users"),
])
def test_paths_equal_ignores_case_and_separators(left, right):
    assert core.paths_equal(left, right)


def test_paths_equal_rejects_different_paths():
    assert not core.paths_equal(r"C:\Users", r"C:\Windows")
    assert not core.paths_equal("", r"C:\Users")


def test_path_is_within_respects_separator_boundary():
    """``C:\\Users2`` **不是** ``C:\\Users`` 的子路径。

    用字符串前缀而不加分隔符边界判断，正是这类误匹配的来源。
    """
    assert core.path_is_within(r"C:\Users\Neus", r"C:\Users")
    assert core.path_is_within(r"C:\Users", r"C:\Users")       # 等于也算"在其下"
    assert not core.path_is_within(r"C:\Users2", r"C:\Users")  # ← 关键
    assert not core.path_is_within(r"C:\Windows", r"C:\Users")


# --------------------------------------------------------------------------
# split_path_chain —— 路径栏逐级展开用
# --------------------------------------------------------------------------

def test_split_path_chain_from_drive_root():
    # 注意：Python 的原始字符串不能以反斜杠结尾，盘符根必须写成 "C:\\"
    chain = core.split_path_chain(r"C:\Users\Neus\Docs")
    assert chain == ["C:\\", r"C:\Users", r"C:\Users\Neus", r"C:\Users\Neus\Docs"]


def test_split_path_chain_single_level():
    assert core.split_path_chain(r"C:\Users") == ["C:\\", r"C:\Users"]


def test_split_path_chain_of_drive_root_is_itself():
    assert core.split_path_chain("C:\\") == ["C:\\"]


def test_split_path_chain_of_unc():
    """UNC 路径（``\\\\server\\share\\dir``）按同样方式逐级展开。

    ``ntpath.splitdrive`` 把 ``\\\\server\\share`` 整体当作"盘符"，
    所以它自己也占一级——且**不带尾分隔符**（与盘符根 ``C:\\`` 不同）。
    """
    chain = core.split_path_chain(r"\\server\share\dir")
    assert chain == [r"\\server\share", r"\\server\share\dir"]


def test_split_path_chain_has_no_double_separators():
    """拼出来的每一级都不能出现双反斜杠。

    盘符根自带尾分隔符，用 ``os.path.join`` 拼接会得到 ``C:\\\\Users``——
    那个路径谁都不认识，逐级匹配必然失败。
    """
    for level in core.split_path_chain(r"C:\Users\Neus\Docs"):
        assert "\\\\" not in level, level


def test_split_path_chain_of_empty_input():
    assert core.split_path_chain("") == []
    assert core.split_path_chain("   ") == []


# --------------------------------------------------------------------------
# 窗口尺寸
# --------------------------------------------------------------------------

def test_scaled_window_size_is_15_percent_larger():
    """改动 ①：1280×720 增大 15% → 1472×828。"""
    assert core.scaled_window_size((1280, 720), 1.15) == (1472, 828)


def test_fit_window_size_keeps_preferred_when_it_fits():
    """屏幕够大时**必须原样保留** 1472×828，不能被"夹取"改小。"""
    assert core.fit_window_size((1472, 828), (1920, 1040)) == (1472, 828)


def test_fit_window_size_shrinks_on_small_screen():
    """1366×768 的笔记本上必须缩小到工作区内，否则标题栏会被推出屏幕。"""
    fitted = core.fit_window_size((1472, 828), (1366, 728))
    assert fitted[0] <= 1366
    assert fitted[1] <= 728
    assert fitted == (1366 - core.WINDOW_WORKAREA_MARGIN * 2,
                      728 - core.WINDOW_WORKAREA_MARGIN * 2)


def test_fit_window_size_handles_unknown_work_area():
    """取不到工作区时（远程桌面、多显示器边缘情况）原样返回，不要崩。"""
    assert core.fit_window_size((1472, 828), None) == (1472, 828)
    assert core.fit_window_size((1472, 828), (0, 0)) == (1472, 828)


# --------------------------------------------------------------------------
# 版本串
# --------------------------------------------------------------------------

def test_build_revision_reads_git_head_or_says_unknown():
    """规则二：产物必须能自报"是哪个提交构建的"。

    在仓库里跑应拿到 7 位短哈希；拿不到时必须是 ``"unknown"``
    **而不是空串或抛异常**——用户报障时这一行决定判断他装的是哪一个。
    """
    revision = core.build_revision()
    assert revision
    assert revision == "unknown" or len(revision) == 7


def test_version_string_contains_name_and_revision():
    text = core.version_string()
    assert text.startswith(core.APP_NAME)
    assert core.APP_VERSION in text
    assert "+" in text


# --------------------------------------------------------------------------
# 用户数据目录 —— 一个真实事故换来的约束
# --------------------------------------------------------------------------

def test_app_data_dir_does_not_need_wx():
    """**用户数据目录必须能不开 `wx.App` 算出来。**

    这是审计发现、用户报障时踩到的一个事故：

    ``--version`` / ``--selftest`` 两条命令行入口没有 `wx.App`，
    而它们在没有 stdout 时会去 ``wx.StandardPaths.Get().GetUserDataDir()``
    记日志（windowed 产物**永远**没有 stdout，所以这条路必然走到）。
    那句在没有 App 时触发 wx 断言，而 **wx 断言失败是弹一个模态框等人点**，
    不是抛异常——命令行场景没有人点，**进程就停死在那里**。
    外层那个 `except (OSError, ValueError)` 因此形同虚设。

    ## 为什么在**干净子进程**里测，而不是看 `sys.modules`

    早先是 `assert "wx" not in sys.modules`，结果**因测试顺序而失败**：
    同一套里别的测试 import 过 wx 之后，这条就永远不成立
    （实测 `1 failed, 178 passed`）。那验的不是实现，是执行顺序。

    放进子进程就没有这个问题：那里没有别人污染过 `sys.modules`，
    而且**万一实现退回 `wx.StandardPaths`，子进程会挂住**——
    由父进程的超时判失败，不会把整套测试拖死。
    """
    script = (
        "import sys;"
        "sys.path.insert(0, 'src');"
        "import file_tracker.core as core;"
        "assert 'wx' not in sys.modules, 'core 不该 import wx';"
        "print(core.app_data_dir())"
    )
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", script],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=root, timeout=20)
    except subprocess.TimeoutExpired:
        pytest.fail(
            "算 app_data_dir() 用了超过 20 秒还没返回——"
            "多半是又走回 wx.StandardPaths 了（没有 wx.App 时它会弹断言框，"
            "而断言框会一直等人点）")

    assert result.returncode == 0, (
        f"子进程失败（{result.returncode}）：{result.stderr}")
    directory = result.stdout.strip()
    assert os.path.isabs(directory), directory
    assert directory.endswith(core.APP_NAME), directory


def test_app_data_path_joins_under_the_same_dir():
    assert os.path.dirname(core.app_data_path("version.txt")) == \
        core.app_data_dir()
    assert core.app_data_path("a", "b.txt") == os.path.join(
        core.app_data_dir(), "a", "b.txt")


def test_config_path_lives_in_the_same_dir():
    """配置、日志、版本文件必须落在**同一个**目录。

    原来 `config.py` 自己拼了一遍 ``%APPDATA%``，而 `app.py` 用
    `wx.StandardPaths` ——两份实现。一旦漂移就会写到两个目录，
    用户看到的是"设置没保存"这种查不出原因的现象。
    """
    from file_tracker import config

    assert os.path.dirname(config.default_config_path()) == \
        core.app_data_dir()


def test_app_data_dir_honours_appdata_env(monkeypatch, tmp_path):
    """`%APPDATA%` 要说了算——否则没法在测试里把它引开。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert core.app_data_dir() == os.path.join(str(tmp_path), core.APP_NAME)


# --------------------------------------------------------------------------
# 分层边界
# --------------------------------------------------------------------------

#: 这些模块**不允许 import wx**——它们承载的判断必须能在无桌面环境测试
WX_FREE_MODULES = ("core", "store", "config", "tree_nav", "theme", "win32")


@pytest.mark.parametrize("module_name", WX_FREE_MODULES)
def test_module_does_not_import_wx(module_name):
    """守住院子里的那条边界。

    四项 UI 改动里有两项（窗口尺寸、频次列）的判断逻辑以前埋在窗口类里，
    只能靠人眼看。这条测试保证它们不会被重新塞回去。
    """
    import ast
    import file_tracker

    package_dir = os.path.dirname(file_tracker.__file__)
    source = open(os.path.join(package_dir, f"{module_name}.py"), encoding="utf-8").read()

    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "wx" not in imported, f"{module_name}.py 不允许 import wx"
