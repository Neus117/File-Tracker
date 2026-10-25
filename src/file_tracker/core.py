"""纯逻辑层：不 import wx，可在无 GUI、无显示器的环境下测试。

本模块承载那些以前埋在 `FileTracker` 里、因此无法自动验证的判断：

* 资源路径解析（``resource_path``）—— v1.1 重写时丢失，导致从源码运行必然没有图标
* 路径规范化与父子关系判断 —— 路径栏要按路径逐级匹配树节点
* 窗口尺寸夹取 —— 1472×828 在 1366×768 笔记本上会超出屏幕
* 应用元信息与版本串 —— 产物必须能自报"是哪个提交构建的"

**这个模块里不允许出现 ``import wx``。** 一旦出现，上面四件事就重新变成只能靠人眼看的
东西了；``tests/test_core.py`` 里有一条测试专门守这件事。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

APP_NAME = "File Tracker"
APP_VERSION = "1.4.2"

#: 用户指定的初始窗口增量：**累计** 32.25%
#
# 1280×720 → 用户第一轮要 +15%（1472×828）→ 第五轮再要 +15%（1693×952）。
# 所以这里直接写最终倍数，而不是在代码里连乘两次：
# `1.15 * 1.15 = 1.3225`。**改这个数之前先确认用户要的是"再增"还是"总共"。**
WINDOW_SCALE = 1.3225

#: **只加高度**的额外倍数（宽度不动）。
#
# 起因：用户要求"记录窗格条目字号 +1pt、行距加大"，并要求"初始窗口高度适当增加"。
# 行变高了 ⇒ 同样高度下能看到的条数变少，所以补一点垂直空间。
#
# 取 **+10%**：1693×952 → 1693×1047（+95 像素，约两行）。
# 这是"循序渐进"的一档；不够就改这个数，**不要顺手连宽度一起动**。
#
# ⚠️ 它与 `WINDOW_SCALE` 是**两条独立的链**：那个管"用户要多大"，
# 这个管"字变大了要多留垂直空间"。混在一起以后就说不清是谁要的了。
WINDOW_EXTRA_HEIGHT = 1.10

DEFAULT_WINDOW_SIZE = (1280, 720)

#: 左上右下留出的安全边距，避免窗口标题栏贴住屏幕边缘或压住任务栏。
WINDOW_WORKAREA_MARGIN = 8


def resource_path(relative_path: str) -> str:
    """把仓库内的相对资源路径解析成绝对路径。

    从 ``File Tracker_v1.0.3.py``（L16-19）恢复。v1.1 重写时丢掉了这个函数，
    于是代码去找 ``<repo>\\src\\images\\``（不存在），兜底又是开发机上的
    ``D:\\Work\\programming\\File Tracker\\images``（也不存在），
    **从源码运行必然加载不到图标**。

    两条路径必须同时成立：

    * 源码运行 → 相对本文件向上两级 = 仓库根目录
    * 打包运行 → ``sys._MEIPASS`` 根目录（PyInstaller 单文件解包目录）

    :param relative_path: 相对资源路径，例如 ``"images/shell32_star.ico"``
    :return: 绝对路径。**不保证该路径存在**——存在性判断交给调用方，
        好让"找不到资源"能走一条可见的失败路径，而不是静默 return。
    """
    if hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        # core.py 在 <repo>/src/file_tracker/ 下，向上三级是仓库根目录
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # 资源路径一律用 '/' 书写，这里统一成平台分隔符
    return os.path.join(base, *relative_path.replace("\\", "/").split("/"))


# --------------------------------------------------------------------------
# 路径规范化
# --------------------------------------------------------------------------

def normalize_path(path: str) -> str:
    """把用户输入/数据库里的路径整理成可比较的规范形式。

    做四件事，都不改变路径指向：

    1. 去掉首尾空白（粘贴路径时最常见的污染）
    2. 去掉成对包裹的引号 —— 资源管理器"复制为路径"会带上双引号
    3. ``/`` 与 ``\\`` 混用统一成 ``\\``
    4. 消掉 ``.`` / ``..``，并去掉末尾多余的 ``\\``

    **刻意不改变大小写**：Windows 文件系统不区分大小写但保留大小写，
    ``lower()`` 会让界面上显示成用户从没输入过的样子。比较时按需 ``casefold()``。

    :param path: 任意待规范的路径字符串
    :return: 规范形式；输入为空时返回空串
    """
    if path is None:
        return ""
    text = str(path).strip()
    if not text:
        return ""

    # 资源管理器复制出来的路径是带引号的
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
        if not text:
            return ""

    text = text.replace("/", "\\")

    # ntpath 提供 Windows 语义，不依赖当前平台，便于在别处测试
    import ntpath

    # normpath 会消掉 "." 与 ".."，并把 "C:\\" 保留为 "C:\\"
    text = ntpath.normpath(text)

    return text


def paths_equal(left: str, right: str) -> bool:
    """按 Windows 语义比较两个路径是否指向同一位置。

    规范形式（大小写除外）相同即相等：``C:\\Users`` 与 ``c:/users/`` 相等。
    """
    a = normalize_path(left)
    b = normalize_path(right)
    if not a or not b:
        return False
    return a.casefold() == b.casefold()


def path_is_within(candidate: str, ancestor: str) -> bool:
    """判断 ``candidate`` 是否等于或位于 ``ancestor`` 之下。

    用分隔符边界比较，避免 ``C:\\Users2`` 被误判为 ``C:\\Users`` 的子路径。
    """
    child = normalize_path(candidate)
    parent = normalize_path(ancestor)
    if not child or not parent:
        return False

    child_fold = child.casefold()
    parent_fold = parent.casefold().rstrip("\\")
    if not parent_fold:
        return False
    if child_fold.rstrip("\\") == parent_fold:
        return True
    return child_fold.startswith(parent_fold + "\\")


def split_path_chain(path: str) -> list[str]:
    """把路径拆成从"根"到自身的逐级前缀，用于逐级匹配树节点。

    ``C:\\Users\\Neus\\Docs`` →
    ``['C:\\', 'C:\\Users', 'C:\\Users\\Neus', 'C:\\Users\\Neus\\Docs']``

    盘符根保留末尾反斜杠（``C:\\``）——那是"某个盘的根"的标准写法，
    且与 ``ntpath.splitdrive`` 的输出一致。其余各级不带末尾反斜杠。

    UNC 路径的根（``\\\\server\\share``）**不带**末尾反斜杠，因为它是由两段
    拼成的、不是单字符的盘符根；``ntpath.splitdrive`` 给出的 UNC 根本身也
    不带尾分隔符。这一处与 :func:`file_tracker.tree_nav.child_names_for_path`
    的切法刻意保持一致——两个函数描述同一件事，不一致会让路径栏在其中一条
    路径上静默失败。

    :return: 前缀列表；输入无效时返回空列表
    """
    import ntpath

    text = normalize_path(path)
    if not text:
        return []

    drive, rest = ntpath.splitdrive(text)

    chain: list[str] = []
    if drive:
        if drive.startswith("\\\\"):
            # UNC 根："\\\\server\\share" —— 去掉可能存在的尾分隔符
            chain.append(drive.rstrip("\\"))
        else:
            # 盘符根："C:" → "C:\\"
            chain.append(drive if drive.endswith("\\") else drive + "\\")

    current = chain[-1] if chain else ""
    for part in [p for p in rest.split("\\") if p and p != "."]:
        # 不用 ntpath.join：盘符根已带尾分隔符，join 会拼出 "C:\\\\Users"
        if current.endswith("\\"):
            current = current + part
        elif current:
            current = current + "\\" + part
        else:
            current = part
        chain.append(current)

    if not chain:
        # 既没有盘符也没有分段（例如裸 "\\"），退化为规范化结果本身
        chain = [text]

    return chain


# --------------------------------------------------------------------------
# 窗口尺寸
# --------------------------------------------------------------------------

def scaled_window_size(base: tuple[int, int] = DEFAULT_WINDOW_SIZE,
                       scale: float = WINDOW_SCALE,
                       extra_height: float = WINDOW_EXTRA_HEIGHT,
                       ) -> tuple[int, int]:
    """按比例放大基准窗口尺寸，四舍五入到整数。

    **宽度**只乘 :data:`WINDOW_SCALE`；**高度**再额外乘
    :data:`WINDOW_EXTRA_HEIGHT`（见那里的说明）。

    1280×720 → 宽 1280×1.3225 = 1693；高 720×1.3225×1.10 = 1047。
    """
    width = base[0] * scale
    height = base[1] * scale * extra_height
    return (int(round(width)), int(round(height)))


def fit_window_size(preferred: tuple[int, int],
                    work_area: tuple[int, int] | None,
                    margin: int = WINDOW_WORKAREA_MARGIN) -> tuple[int, int]:
    """把期望尺寸夹取到工作区内，并保证不小于一个可用下限。

    **为什么需要这一步**：1472×828 在 1920×1080 上没问题，但在 1366×768 的笔记本上
    会超出屏幕——用户只能看到窗口的一部分，且标题栏可能被推到屏幕外而无法拖动。

    :param preferred: 期望的客户区尺寸
    :param work_area: 可用的工作区尺寸（已扣除任务栏）；``None`` 表示未知，原样返回
    :param margin: 四周留出的安全边距
    :return: 夹取后的尺寸，保证两个方向都 > 0
    """
    width, height = int(preferred[0]), int(preferred[1])
    if not work_area:
        return (max(width, 1), max(height, 1))

    area_w, area_h = int(work_area[0]), int(work_area[1])
    if area_w <= 0 or area_h <= 0:
        return (max(width, 1), max(height, 1))

    limit_w = max(area_w - margin * 2, 1)
    limit_h = max(area_h - margin * 2, 1)
    return (max(min(width, limit_w), 1), max(min(height, limit_h), 1))


# --------------------------------------------------------------------------
# 版本串
# --------------------------------------------------------------------------

def build_revision() -> str:
    """返回构建时的 git 短哈希；打包或非仓库环境下返回 ``"unknown"``。

    规则二（见项目笔记第五节）：**产物必须能自报"是哪个提交构建的"。**
    用户报障时，这一行决定你能不能判断他装的是哪一个。

    三个来源，按可靠性排序：

    1. ``_build_info`` —— 打包时由 ``File-Tracker.spec`` **写进 exe** 的模块。
       单文件 exe 里既没有 ``.git`` 目录也没有构建脚本，这是唯一的可靠来源。
    2. ``FILE_TRACKER_BUILD_REV`` 环境变量 —— 构建脚本用。
    3. 直接读 ``.git/HEAD`` —— 从源码运行时用。**只读文件、不 fork git 进程**：
       启动路径上不该起子进程。
    """
    try:
        from ._build_info import BUILD_REVISION  # type: ignore[import-not-found]

        if BUILD_REVISION:
            return str(BUILD_REVISION)
    except ImportError:
        pass

    env_rev = os.environ.get("FILE_TRACKER_BUILD_REV")
    if env_rev:
        return env_rev.strip()

    try:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        head = os.path.join(repo_root, ".git", "HEAD")
        with open(head, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
        # "ref: refs/heads/main" → 去读那个 ref 文件
        if content.startswith("ref:"):
            ref_path = os.path.join(repo_root, ".git", *content[4:].strip().split("/"))
            with open(ref_path, "r", encoding="utf-8") as handle:
                content = handle.read().strip()
        return content[:7] if content else "unknown"
    except (OSError, ValueError):
        return "unknown"


def app_data_dir() -> str:
    """本程序放用户数据的地方：``%APPDATA%\\File Tracker``。

    ## 为什么不走 `wx.StandardPaths`

    **因为它在没有 `wx.App` 的时候会把人卡死。**

    踩过（用户报障时才发现）：``--version`` / ``--selftest`` 这两条命令行
    入口**没有** `wx.App`，而它们在没有 stdout 时会去
    ``wx.StandardPaths.Get().GetUserDataDir()`` 记日志。那句在没有 App 时
    触发 wx 断言，而 **wx 断言失败不是抛异常，是弹一个模态框等人点**。
    命令行场景没有人点 ⇒ **进程就停在那里**。

    外层那个 `except (OSError, ValueError)` 形同虚设：这句不抛这两种异常，
    它只是停住。实测：断言框开着 → 挂住；`wx.DisableAsserts()` 之后 → 正常返回。

    所以这条路**不依赖 wx**：`%APPDATA%` 是标准环境变量，自己拼就行。
    顺带修掉另一个缺陷——原来 `SetAppName` 只在 `OnInit` 里跑，
    命令行入口会写到 ``%APPDATA%\\<产物名>``（实测 ``-c``），
    而不是这里说的 ``File Tracker``。

    与 :func:`file_tracker.config.default_config_path` 同一个目录、
    同一个理由（"位置"要能被替换，"内容"才敢在测试里改）。
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def app_data_path(*parts: str) -> str:
    """`app_data_dir()` 下面某个文件的完整路径。"""
    return os.path.join(app_data_dir(), *parts)


def version_string() -> str:
    """形如 ``File Tracker 1.2.0+9293827`` 的自报版本串。"""
    return f"{APP_NAME} {APP_VERSION}+{build_revision()}"


# --------------------------------------------------------------------------
# 排序偏好
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SortSpec:
    """一个可排序的列：它的稳定标识、显示名、以及**默认方向**。

    ## 为什么方向要按列给默认值，而不是全局一个

    最自然的读法对每一列是不同的：

    * **频次**——"最常访问的"当然排在最前 → 降序
    * **访问日期 / 访问时间**——"最近的"排在最前 → 降序
    * **路径**——字母序，A 在前 → 升序

    只用一个全局方向的话，点"路径"会得到 Z→A，
    点"频次"会得到"最少访问的在前"——两者都不是用户想要的第一眼结果。

    ## 为什么标识用字符串而不是列号

    列号是**界面**的事（`app.COLUMN_*`）。存进配置、并在设置界面里
    与语言无关地引用时，需要一个不会因为"中间插了一列"就错位的名字。
    """

    key: str
    chinese: str
    english: str
    default_reverse: bool

    def label(self) -> str:
        """显示名（跟随当前语言）。"""
        from .lang import L

        return L(self.chinese, self.english)


#: **三个**可排序列，顺序与列表里的列一致。
#:
#: ## 从四个并成三个（用户 2026-10-17）
#:
#: > "时间和日期本身就是一类的东西，最开始就不应该分成两列。
#: >   只保留'访问时间'这一列，把日期并进去。"
#:
#: 原来 `date` 与 `clock` 是**两个排序项**，但它们的比较键**完全一样**
#: （都是 `datetime.strptime(record.last_access_time, TIME_FORMAT)`）——
#: 同一份数据支持两个"不同"的排序项，本来就没有意义。
#: 现在合并成 `time` 一个，并按访问时间排序。
SORT_SPECS: tuple[SortSpec, ...] = (
    SortSpec("path", "访问路径", "Path", default_reverse=False),
    SortSpec("count", "频次", "Count", default_reverse=True),
    SortSpec("time", "访问时间", "Time", default_reverse=True),
)

#: 旧版本用过的排序键 ⇒ 现在对应的键。
#:
#: 用户的配置里可能存着 `"date"` / `"clock"`（两列时代的偏好）。
#: 读出来时**映射到 `"time"`**，而不是当成未知值丢回默认 ——
#: 否则"我一直按时间降序"的用户升级后会莫名变成按频次排序。
LEGACY_SORT_KEYS = {"date": "time", "clock": "time"}

#: 没设过偏好时用哪一个。
#:
#: **保持"频次、降序"**——那是这个程序从 1.1 起的行为
#: （设置排序状态的那一行注释就写着 `COLUMN_COUNT / True`）。
#: 老用户升级之后第一眼看到的东西不该变。
DEFAULT_SORT_KEY = "count"


def find_sort_spec(key: str | None) -> SortSpec:
    """按标识取 :class:`SortSpec`；认不出就返回默认那一个。

    **认不出时回退而不是抛异常**：配置文件可以手改，
    写错一个字符串不该让程序起不来。

    **旧键会先映射**（`date`/`clock` → `time`），见 :data:`LEGACY_SORT_KEYS`。
    """
    if key in LEGACY_SORT_KEYS:
        key = LEGACY_SORT_KEYS[key]
    for spec in SORT_SPECS:
        if spec.key == key:
            return spec
    return find_sort_spec_by_key(DEFAULT_SORT_KEY)


def find_sort_spec_by_key(key: str) -> SortSpec:
    """:func:`find_sort_spec` 的内部查表（不再回退，避免递归）。"""
    for spec in SORT_SPECS:
        if spec.key == key:
            return spec
    return SORT_SPECS[0]


def sort_keys() -> tuple[str, ...]:
    """全部合法的排序列标识。"""
    return tuple(spec.key for spec in SORT_SPECS)
