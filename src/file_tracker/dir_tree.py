"""导航窗格的目录树：**32×32 图标**，可直接替换 `wx.GenericDirCtrl`。

## 为什么要换掉 `GenericDirCtrl`

用户："对比 Explorer，我们的导航窗格中这些磁盘、文件夹的**标识太小了**，
看着真的很费劲。"

实测：

===========  ==========  ==============  ==========
控件          图标尺寸     行高            图标 ÷ 行高
===========  ==========  ==============  ==========
本程序        16 × 16     **50 px**       **0.32**
Explorer     16 × 16     ≈ 22 px         ≈ 0.73
===========  ==========  ==============  ==========

**一半原因是我们自己造成的**：行高从 30px 调到 50px（为了"呼吸感"），
图标没变，比例就掉了一半。

而 `GenericDirCtrl` **没有暴露任何图列表 API**（实测 `dir()` 里一个都没有），
换不了图标尺寸 —— 所以只能换控件。

## 关键设计：**做成"可直接替换"的**

`app.py` 里有约 35 处、`verify_gui.py` 里约 20 处依赖 `dir_ctrl`
（`GetTreeCtrl()` / `GetPath()` / `GetPaths()` / `ShowHidden()` / `Freeze()` …）。

**如果换成一个接口不同的控件，那几十处全要改** —— 那是这一批里最大的风险。

所以本类**继承 `wx.TreeCtrl`**，并补上 `GenericDirCtrl` 被用到的那几个方法。
于是：

* `dir_ctrl.GetTreeCtrl()` → 返回 `self`（它就是树）
* `dir_ctrl.GetPath()` / `GetPaths()` / `ShowHidden()` → 本类实现
* `app.py` 里那几十处调用**一行都不用改**

**唯一的替换点是构造那一行。**

## 图标怎么来

用 Windows 外壳自己的大图标（`SHGetFileInfo` + `SHGFI_LARGEICON`），
所以**看起来就是 Explorer 的样子**，只是尺寸对了。
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import string
import sys

import wx

from .tree_nav import needs_trim, should_skip_files, too_many_to_expand

# --------------------------------------------------------------------------
# Windows 外壳图标
# --------------------------------------------------------------------------

SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_USEFILEATTRIBUTES = 0x000000010
SHGFI_OPENICON = 0x000000002
SHGFI_DISPLAYNAME = 0x000000200
#: `DrawIconEx` 的画法：图标 + 遮罩
DI_NORMAL = 0x000000003

FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_NORMAL = 0x00000080


class _SHFILEINFO(ctypes.Structure):
    _fields_ = [
        ("hIcon", ctypes.c_void_p),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", ctypes.c_uint),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


def _drive_label(root: str) -> str:
    """盘符显示名：``SYSTEM (C:)`` 这种（卷标 + 盘符）。

    **必须用外壳给的名字，不要自己拼。** 用户现有的界面上就是
    `SYSTEM (C:)` / `ACTIVE (D:)` / `LIBRARY (E:)` —— 那是
    `wx.GenericDirCtrl` 调外壳拿到的。我们自己拼成 `C:\` 的话，
    **换控件会顺带改掉用户看惯的观感**，而这一次的需求只是"图标放大"。

    取不到就退回 ``C:\`` —— 不能因为拿不到卷标就让盘符不显示。
    """
    try:
        shell32 = ctypes.windll.shell32
        info = _SHFILEINFO()
        shell32.SHGetFileInfoW(
            ctypes.c_wchar_p(root), 0,
            ctypes.byref(info), ctypes.sizeof(info),
            SHGFI_DISPLAYNAME | SHGFI_USEFILEATTRIBUTES)
        name = (info.szDisplayName or "").strip()
        return name or root
    except (OSError, AttributeError, TypeError):
        return root


def _icon_query_path(name: str, is_dir: bool) -> str:
    """给外壳的**假路径** —— 它按扩展名返回图标，不碰磁盘。

    `SHGFI_USEFILEATTRIBUTES` 会告诉外壳"别去看文件，就按我给的属性判断"，
    所以这里拼的路径**不需要真实存在**。

    * 目录 → `C:\\folder`
    * 文件 → `C:\\x` + 它自己的扩展名（**这是关键**：
      原来写死成 `.txt`，于是所有文件都拿到"文本文件"图标）
    """
    if is_dir:
        return "C:" + os.sep + "folder"
    ext = os.path.splitext(name)[1]
    return "C:" + os.sep + "x" + ext


def _shell_icon(path: str, *, directory: bool, size: int,
                open_icon: bool = False) -> wx.Bitmap | None:
    """取 Windows 外壳给这个路径的**大图标**（32×32 @96dpi，按 DPI 放大）。

    `SHGFI_USEFILEATTRIBUTES` 让它在**路径不存在时也返回图标** ——
    建树时我们只需要"文件夹长什么样"，不必真的去 stat 每一个盘符。
    """
    try:
        shell32 = ctypes.windll.shell32
        user32 = ctypes.windll.user32
        info = _SHFILEINFO()
        flags = SHGFI_ICON | SHGFI_LARGEICON | SHGFI_USEFILEATTRIBUTES
        if open_icon:
            flags |= SHGFI_OPENICON
        attributes = (FILE_ATTRIBUTE_DIRECTORY if directory
                      else FILE_ATTRIBUTE_NORMAL)
        shell32.SHGetFileInfoW(
            ctypes.c_wchar_p(path), attributes,
            ctypes.byref(info), ctypes.sizeof(info), flags)
        if not info.hIcon:
            return None
        try:
            # ⚠️ **不用 wx 那套图标转换接口，直接用 `DrawIconEx` 画。**
            #
            # 这个构建（4.2.2 / wxWidgets 3.2.6）实测：
            #
            # * `wx.IconFromHICON(hicon)` —— **模块级函数不存在**
            # * `wx.Bitmap(icon)` —— `TypeError: Expected a list of bytes objects`
            #
            # 第一个错被下面那个 `except` 静默吞掉 ⇒ `_shell_icon`
            # **从写下那天起就一直返回 None**，所有图标都在退回
            # `wx.ArtProvider`。**用户看到的"文件图标全是空白纸"就是这么来的。**
            #
            # 与其再试第三种转换写法，不如**根本不做转换**：
            # `wx.MemoryDC.GetHandle()` 拿到 HDC（**不是已废弃的 `GetHDC()`**，
            # 后者会在启动时打 `wxPyDeprecationWarning` —— 用户看到过），
            # `DrawIconEx` 把 HICON 直接画到位图上，一步到位。
            bitmap = wx.Bitmap(size, size)
            memory = wx.MemoryDC(bitmap)
            try:
                # 先填**遮罩色**（洋红）——
                # 加进图列表时把它声明为遮罩，图标背景就透明了。
                # **用洋红不用黑**：黑色是真实内容里也会出现的颜色，
                # 拿它当遮罩会把图标自身的黑像素一起挖空。
                memory.SetBackground(wx.Brush(wx.Colour(255, 0, 255)))
                memory.Clear()
                drawn = user32.DrawIconEx(
                    ctypes.c_void_p(memory.GetHandle()), 0, 0,
                    ctypes.c_void_p(info.hIcon), size, size, 0, None,
                    DI_NORMAL)
            finally:
                memory.SelectObject(wx.NullBitmap)
        finally:
            # 无论成功与否都要**销毁外壳给的 HICON**，否则每次建树漏一个
            user32.DestroyIcon(ctypes.c_void_p(info.hIcon))
        if not drawn:
            return None
        return bitmap if bitmap.IsOk() else None
    except OSError:
        # **只兜"环境不支持"**（非 Windows、外壳调用失败）。
        #
        # `AttributeError` / `TypeError` 这类**编程错误必须冒出来** ——
        # 正是它们让上面那两个写错的接口藏了这么久。
        return None



def _as_drive_root(text: str) -> str:
    """标签是盘符根的话返回它的路径，否则空串。

    **两种写法都要认**：

    * ``C:\\`` —— 本类用的（标签就是根路径）
    * ``SYSTEM (C:)`` —— `wx.GenericDirCtrl` / Explorer 用的，
      靠 `tree_nav.drive_in_label` 解析

    踩过：一开始两处都直接用 `drive_in_label`，而它**只认第二种**，
    于是 ``C:\\`` 既列不出子目录、`GetPath()` 也永远返回空。
    """
    from .tree_nav import drive_in_label
    drive = drive_in_label(text)
    if drive:
        # ⚠️ **必须补上结尾的反斜杠。**
        #
        # `drive_in_label` 返回的是 `C:`（不带斜杠），而
        # `os.path.join("C:", "Users")` == **`C:Users`** ——
        # 那在 Windows 上不是 `C:\\Users`，
        # 而是「C 盘当前目录下的 Users」——**一个完全不同的路径**。
        #
        # 实测症状：导航选中显示成 `C:Users`，
        # 于是「选中目标路径」那条断言报了 0 项匹配。
        # 用 os.sep 而不是字面反斜杠 —— 少一层转义，也不会写坏。
        return drive if drive.endswith(os.sep) else drive + os.sep
    if len(text) == 3 and text[1:] == ":" + chr(92):
        return text
    return ""


def _is_hidden_entry(entry) -> bool:
    """`DirEntry` 指向的是不是隐藏项 —— **读已缓存的属性，不发系统调用**。

    隐藏位来自 `dwFileAttributes & FILE_ATTRIBUTE_HIDDEN (0x2)`。
    `entry.stat()` 在 Windows 上取自 `FindNextFile` 已经填好的数据，
    不会再开一次文件。

    **非 Windows 上退回"点开头"**：那个平台上没有隐藏属性这回事，
    而 `st_file_attributes` 也不存在。
    """
    try:
        attributes = getattr(entry.stat(), "st_file_attributes", None)
    except OSError:
        return False
    if attributes is None:
        return entry.name.startswith(".")
    return bool(attributes & 0x2)




#: 图标槽位。**顺序即索引**，树里存的就是这些下标。
#:
#: **必须有"文件"这一格。** 我一度把它当死代码删掉了，理由是
#: "导航树只列目录" —— 而那个限制是**我自己加的**，不是用户要的。
#: 用户报："现在它只展示文件夹，不展示文件。这样用户看不到文件夹下
#: 有什么东西，会很困惑。" 原来的 `wx.GenericDirCtrl` **默认两者都显示**。
ICON_DRIVE = 0
ICON_FOLDER = 1
ICON_FILE = 2


# --------------------------------------------------------------------------
# 目录树
# --------------------------------------------------------------------------

class DirectoryTree(wx.TreeCtrl):
    """导航窗格用的目录树。**接口对齐 `GenericDirCtrl` 中被用到的那几个方法。**

    :param show_hidden: 是否显示隐藏文件夹（对应 `GenericDirCtrl.ShowHidden`）
    """

    def __init__(self, parent, *, show_hidden: bool = False, **kwargs):
        super().__init__(parent, style=wx.BORDER_NONE | wx.TR_HAS_BUTTONS
                         | wx.TR_LINES_AT_ROOT | wx.TR_HIDE_ROOT
                         | wx.TR_SINGLE, **kwargs)
        self._show_hidden = show_hidden
        #: 建树时把子节点推迟到"展开时"再加 —— 盘符下的目录可能上千个。
        #:
        #: **值不再是 `True`，而是"建到哪一步了"**：
        #:
        #: * ``"dirs"`` —— 只建了子文件夹（沿路径展开时，大目录走这一条）
        #: * ``"full"`` —— 连文件一起建了
        #:
        #: 为什么必须区分：只有知道了当前状态，才能决定"要不要**追加**文件"；
        #: 而追加是唯一的升级方式 —— `DeleteChildren()` 会让调用方手里的 item
        #: 变成悬空句柄（见 `_append_missing` 的说明）。
        self._populated: dict = {}
        #: `quiet_expand()` 的嵌套计数；>0 表示**程序**在展开（不是用户点的）。
        self._quiet_expand_depth = 0
        #: 当前树里**由本类建出来的节点总数**（不含隐藏根；盘符节点算在内）。
        #:
        #: 为什么要自己数：`wx.TreeCtrl.GetCount()` 是 O(N) 且会走一遍原生接口，
        #: 而"要不要重建"这个判断每次导航都要做一次。自己数就放在建节点的两处
        #: （`_build_children` / `_append_missing`）累加、`populate()` 归零。
        self._node_count = 0
        #: 上一次**由程序**沿路径展开的那条链（从盘符到目标）。
        #:
        #: 下次导航时把它收起来 —— 否则"每一次打开的目录在导航窗格里全部都是
        #: 展开的状态"（用户 2026-10-25 原话），开着用几小时之后：
        #: 6k 节点关闭 0.35 秒、**45k 节点关闭 11 秒**（实测 `probe_tree_inflate.py`）。
        self._revealed_chain: list = []
        #: 已知"太大、程序态不该展开"的节点（`too_many_to_expand` 的判断结果）。
        #:
        #: 一次导航里同一个节点会被问好几次（`expand_to` / `_on_expanding` /
        #: `_refresh_item` / `TreeWalker`），而每问一次都要扫一遍目录 ——
        #: `WinSxS`（19727 条）一次 40 ms，问六次就是 240 ms。
        self._too_big: set = set()
        self._images = self._build_images()
        self.AssignImageList(self._images)
        #: 扩展名（小写）→ 图列表下标。**一个扩展名只取一次图标。**
        self._icon_cache: dict = {}
        #: 出错时的上报回调（**由 `app.py` 注入**，避免本模块反向依赖它）。
        #:
        #: 接上之前默认打 stderr —— 审计查出的那条"展开失败后目录
        #: 永久空着、且毫无提示"必须至少留下痕迹。
        self.on_error = None

        self._root = self.AddRoot("root")
        self.Bind(wx.EVT_TREE_ITEM_EXPANDING, self._on_expanding)

    # -- 图标 -------------------------------------------------------------

    def _build_images(self) -> wx.ImageList:
        """建图列表，边长 = `round(树文字高 × METRICS.tree_icon_ratio)`。

        取不到外壳图标时退回 `wx.ArtProvider` —— **不能因为取不到图标就
        让整个导航窗格空着**。
        """
        from .theme import METRICS

        # **锚定到"树文字高"，不是 DPI。**
        #
        # 行高是 `round(文字高 × row_ratio)` 算出来的，**不按 DPI 缩放**；
        # 图标若按 DPI 缩放，两者就不同源 —— 实测 @168dpi 得到 56px 图标
        # 配 56px 行高（比例 1.00），图标会把整行占满而被裁。
        text_height = self.GetTextExtent("Ag").height or 1
        size = max(int(round(text_height * METRICS.tree_icon_ratio)), 8)
        images = wx.ImageList(size, size)
        # 占满全部槽位，**保证下标与常量一一对应**（缺一个就会整体错位）
        sources = [
            (_shell_icon("C:" + os.sep, directory=True, size=size), wx.ART_HARDDISK),
            (_shell_icon("C:" + os.sep + "folder", directory=True, size=size),
             wx.ART_FOLDER),
            (_shell_icon("C:" + os.sep + "file.txt", directory=False, size=size),
             wx.ART_NORMAL_FILE),
        ]
        for bitmap, fallback in sources:  # noqa: B007
            if bitmap is None or not bitmap.IsOk():
                bitmap = wx.ArtProvider.GetBitmap(
                    fallback, wx.ART_OTHER, wx.Size(size, size))
            if bitmap.GetWidth() != size or bitmap.GetHeight() != size:
                image = bitmap.ConvertToImage()
                image = image.Scale(size, size, wx.IMAGE_QUALITY_HIGH)
                bitmap = wx.Bitmap(image)
            images.Add(bitmap)
        return images

    def _icon_for(self, name: str, is_dir: bool) -> int:
        """这个子项该用哪张图标 —— **文件按扩展名取**。

        ## 为什么必须按扩展名

        原来所有文件共用一张写死的 `file.txt` 图标，于是
        `.exe` / `.dll` / `.txt` 全长一样。用户报：
        "所有文件图标**全部是空白纸**，没有我在 Explorer 里面看到的这种图标。"

        ## 缓存

        键是**小写扩展名**。`wx.ImageList.Add()` 返回新下标，
        所以图列表可以按需增长。取不到图标时退回 `ICON_FILE`。
        """
        if is_dir:
            return ICON_FOLDER
        ext = os.path.splitext(name)[1].lower()
        hit = self._icon_cache.get(ext)
        if hit is not None:
            return hit
        size = self._icon_size()
        bitmap = _shell_icon(_icon_query_path(name, False), directory=False,
                        size=size)
        if bitmap is None or not bitmap.IsOk():
            self._icon_cache[ext] = ICON_FILE
            return ICON_FILE
        if bitmap.GetWidth() != size or bitmap.GetHeight() != size:
            bitmap = wx.Bitmap(
                bitmap.ConvertToImage().Scale(size, size, wx.IMAGE_QUALITY_HIGH))
        index = self._images.Add(bitmap)
        self._icon_cache[ext] = index
        return index

    def _icon_size(self) -> int:
        """图标边长 = `round(树文字高 × METRICS.tree_icon_ratio)`（与建图列表同源）。"""
        from .theme import METRICS
        text_height = self.GetTextExtent("Ag").height or 1
        return max(int(round(text_height * METRICS.tree_icon_ratio)), 8)

    # -- 建树 -------------------------------------------------------------

    def populate(self, expand_path: str = "") -> None:
        """列出所有盘符；`expand_path` 指向的那条链**自动展开并选中**。

        这也是**唯一的"整体重建"入口**：`DeleteChildren(root)` 之后所有旧节点
        都作废，所以 `_populated`（按节点记账）与 `_revealed_chain` 必须一起清掉。
        节点数超上限时（`tree_nav.needs_trim`）由 `app.reveal_in_tree` 调它来
        "只保留当前路径" —— 见 `MAX_TREE_NODES` 里的实测曲线。
        """
        self.DeleteChildren(self._root)
        self._populated.clear()
        self._revealed_chain = []
        self._too_big.clear()
        self._node_count = 0
        for drive in self._drives():
            # 标签用外壳给的名字（`SYSTEM (C:)`），路径反查由
            # `_as_drive_root` 里的 `drive_in_label` 负责 —— 它认的正是这种。
            item = self.AppendItem(self._root, _drive_label(drive), ICON_DRIVE)
            self._add_placeholder(item)
            self._node_count += 1
        if expand_path:
            self.expand_to(expand_path)

    @staticmethod
    def _drives() -> list[str]:
        """所有存在的盘符，**标签就是根路径本身**（``C:\``）。

        标签由 `_drive_label` 取外壳的显示名（``SYSTEM (C:)``）——
        与用户现有的观感一致，换控件不该顺带改掉它。
        """
        found = []
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                found.append(root)
        return found

    def _add_placeholder(self, item) -> None:
        """**必须先放一个假子节点**，否则 `wx.TreeCtrl` 不画展开箭头。

        真子节点留到 `EVT_TREE_ITEM_EXPANDING` 再加（懒加载）。
        """
        if not self.ItemHasChildren(item):
            self.AppendItem(item, "", -1)

    def _populate_item(self, item, *, files: bool | None = None) -> None:
        """把某个节点的子项**同步**建出来（懒加载的唯一实现处）。

        **抽出来是因为有两条路要走它**：

        * `_on_expanding` —— 用户点开箭头时（事件驱动）
        * `expand_to` —— 程序沿路径展开时（**必须同步**）

        踩过：`expand_to` 里只用 `self.Expand(item)`，紧接着就迭代
        `GetFirstChild` —— 什么也拿不到，于是路径**只展开一层就停**
        （实测只到 `C:\\Users`）。所以"先同步把子项建出来、再展开"这个顺序不能反。

        > ⚠️ **2026-10-25 更正一条旧说法**：这里原来写着"`Expand()` **投递事件**，
        > 处理函数要到下一轮事件循环才跑"。实测（`tools/probes/probe_pathbar_populate.py`）
        > 对 `EVT_TREE_ITEM_EXPANDING` **不成立** —— 每次 `Expand()` 都会**同步**
        > 把 `_on_expanding` 跑完，且发生在 `Expand()` 返回之前
        > （见 `quiet_expand()` 的说明；第 4 版"增量填充没效果"就是被这个同步回调
        > 推翻的）。上面那个"只展开一层"的现象另有原因（当时那次填充确实没发生），
        > 但**结论不变**：子项必须在 `Expand()` 之前建好。

        ## `files`：这个节点的**文件**子项要不要建

        ==============  ==========================================================
        值              含义
        ==============  ==========================================================
        ``None``        自动：条目多于 `tree_nav.DIRS_ONLY_ENTRY_THRESHOLD` 就只建文件夹
        ``True``        全量（用户点的展开、以及**目标目录**它自己）
        ``False``       只要文件夹
        ==============  ==========================================================

        **为什么"自动"这一档必须存在**（2026-10-25 实测）：

        用户报"地址栏回车非常慢、关程序也慢"。实测
        （`tools/probes/probe_pathbar_populate.py`，路径
        ``C:\\Windows\\System32\\drivers\\etc``）：

        树节点 49 → 5838，其中 ``C:\\Windows\\System32`` 一个目录就 **4907 个
        子项、4708 个是文件**、耗时 192 ms —— 而它**只是为了把下面三级的
        ``etc`` 显示出来**，那 4708 个文件对"找到下一级"毫无用处，
        却要在关闭时逐个 `Destroy()`（关闭 58 → 367 ms）。

        所以沿路径展开时，大目录只建子文件夹；真要看文件，用户点开它
        时再**追加**（`files=True` → :meth:`_append_missing`）。
        """
        if not item.IsOk():
            return
        state = self._populated.get(item)
        if state == "full":
            return
        # 已经建过"只含文件夹"的版本：
        # **只有明确要文件时才升级**。`None`（自动）按定义就是"别补" ——
        # 能走到 `"dirs"` 的目录都是因为大，再问一次条目数只会白扫一遍。
        if state == "dirs" and files is not True:
            return

        if self._quiet_expand_depth > 0 and item in self._too_big:
            return
        entries = self._entries_of(item)
        # **程序态的第二道闸：这么大的目录这次干脆不展开。**
        #
        # `should_skip_files` 只挡住"文件多"的目录；`WinSxS` 那种是
        # **子目录多**（19727 个），挡住文件也救不了 —— 建 19725 个子项 +
        # 19725 个占位 = 近四万个节点、约 2.6 秒（65 µs/节点，实测）。
        #
        # ⚠️ **判据是"谁在调"，不是 `files`。** 踩过：`_refresh_item` 为了
        # 找一个**最后一级**的子项，会带着 `files=True` 去填**父级**
        # （`files=last` 那一行）—— 按 `files is None` 判断的话，
        # 那个 2601 条目的父级照样被整棵建出来（实测 2604 个节点）。
        # 程序态（`quiet_expand_depth > 0`）一律不许建这么大的层级；
        # 用户自己点开时（`files=True` 且不在程序态）才全量 ——
        # 那是他自己选的动作，他知道在等什么。
        if self._quiet_expand_depth > 0 and too_many_to_expand(len(entries)):
            # **记住这个结论**：一次导航里同一个节点会被问好几次
            # （`expand_to` / `_on_expanding` / `_refresh_item` / `TreeWalker`），
            # 而每问一次就要扫一遍目录 —— `WinSxS` 一次 40 ms，问六次就是 240 ms。
            # 实测 A/B：加了这条备忘，同一次导航 308 → 90 ms。
            self._too_big.add(item)
            return
        if self._quiet_expand_depth == 0:
            # 用户自己展开了：这个结论作废（他愿意等）
            self._too_big.discard(item)
        if files is None:
            files = not should_skip_files(len(entries))

        if state is None:
            self._build_children(item, entries, files)
        else:
            self._append_missing(item, entries)

    def _report_expand_error(self, item, error, *, keep_state: bool = False) -> None:
        """展开失败时**如实报出来**。

        :param keep_state: 保留已有记账（不重试）。
            `_append_missing` 失败时必须传 ``True``：那时子节点**已经存在**，
            把记账撤掉会让下一次展开走"重建"那条路 ⇒ `DeleteChildren`
            ⇒ 调用方手里的 item 悬空。宁可这次补得不全，也不要崩。
            默认（新建那条路）撤掉记账 —— 那时节点已被清空，下次重新建才对。
        """
        if not keep_state:
            self._populated.pop(item, None)
        try:
            where = self.path_of_node(item)
        except Exception:
            where = repr(item)
        report = self.on_error
        if report is not None:
            report(f"展开目录失败：{where}（{error!r}）")
        else:
            # 没接回调也不能静默 —— 至少让它出现在 stderr 上
            print(f"[dir_tree] 展开目录失败：{where}（{error!r}）",
                  file=sys.stderr)

    def _build_children(self, item, entries, files: bool) -> None:
        """**第一次**建某个节点的子项。这时可以有占位子项，可以整体删掉。

        `DeleteChildren(item)` 在这里是安全的：能走到这儿说明
        `self._populated` 里没有它，它的子项只可能是 `_add_placeholder`
        放的那个空占位项 —— **没有任何调用方持有它**
        （`expand_to` 按名字找子项，空名字永远匹配不上）。
        """
        # **批量插节点必须冻结重绘。**
        #
        # `AppendItem` 每插一个都会重排 + 重绘一次；插 N 个就是 N 次布局。
        # 实测 `C:\Windows`（85 个子节点、共 170 个节点）要 **241 ms**，
        # 约 1.4 ms/节点 —— 一半以上花在重复布局上。
        # `Freeze`/`Thaw` 是 wx 给"批量修改"准备的标准接口，
        # `reveal_in_tree` 那边本来就用了，**只有展开事件这条路漏了**。
        self.Freeze()
        try:
            self.DeleteChildren(item)
            added = 0
            for name, is_dir in entries:
                # **文件和文件夹都要列**（用户："只展示文件夹……会很困惑"），
                # 只有"大目录的自动档"才跳过文件。
                if not is_dir and not files:
                    continue
                child = self.AppendItem(item, name, self._icon_for(name, is_dir))
                added += 1
                # **每个子节点也要有占位子节点。**
                #
                # `wx.TreeCtrl` 靠"有没有子节点"决定画不画展开箭头 ——
                # 不加的话，展开一层之后**再也点不下去**（用户实测：
                # "每个磁盘展开后下面只有一级，不能接着展开了"）。
                #
                # 代价是"空目录也显示箭头"：盘根下有没有子目录**只能等展开时
                # 才知道**（列一次目录的代价不想在建树时付）。这是资源管理器
                # 同款的取舍。
                #
                # ⚠️ **只给目录加 —— 文件展开不了。**
                # 给文件加占位会让它显示一个点不开的箭头。
                if is_dir:
                    self._add_placeholder(child)
                    added += 1
            # **记账放在"真的干完之后"。**
            #
            # ⚠️ 审计查出的缺陷（2026-10-17）：原来 `self._populated.add(item)`
            # 写在循环**之前** —— 等于"工作还没做就先记账"。而上面那句
            # `DeleteChildren(item)` 已经把原子节点**清空**了，于是任何一步
            # 抛异常就变成：
            #
            #   * 这个目录在导航窗格里**永远是空的**（重启才恢复）
            #   * 之后每次展开都在 `item in self._populated` 处直接返回
            #   * `reveal_in_tree` / 地址栏定位到它也会**静默失败**
            #
            # 这与本项目另一条教训同型：**先记账、后干活 ⇒ 账本一旦脏了，
            # 就永远不再重试**（`_apply_selection_highlight` 那次也是）。
            self._populated[item] = "full" if files else "dirs"
            # **节点数也要在"真的建完"之后才加**（同上：先记账后干活会脏）
            self._node_count += added
        except Exception as error:
            self._report_expand_error(item, error)
        finally:
            self.Thaw()

    def _append_missing(self, item, entries) -> None:
        """把 `entries` 里**还不在树上**的子项**追加**进去 —— **只增不删**。

        ## ⚠️ 这里绝不能改成 `DeleteChildren` + 重建

        这一条是踩了 6 次才确认的（见交接文档第 4 节）：

        `wx.TreeCtrl` 唯一的"重建"方式就是删光再插，而只要在**已经有子节点**
        的节点上跑一次 `DeleteChildren(item)`，调用方（`expand_to` 的循环、
        `reveal_in_tree` 手里的 `item`、`GetSelection()`）拿着的
        `TreeItemId` **立刻变成悬空句柄** —— 之后任何 `GetItemText` /
        `IsOk()` 都是 C 层访问违例（`0xC0000005`），Python 抓不住。

        "只追加"顺带解决了另外两件事：

        * **不会丢文件节点**（第 3 版"点开目录只剩文件夹"就是重建丢的）
        * **新出现的文件夹能被找到**（第 1 版的缓存陈旧：这里按名字对比，
          缺什么补什么，不需要"作废整棵子树"）

        顺序也对得上：`_entries_of` 已经排成"文件夹在前、文件在后"，
        所以追加文件只会加在每个目录子项的**后面**，屏幕上方的行不动。
        """
        existing = set()
        child, cookie = self.GetFirstChild(item)
        while child.IsOk():
            existing.add(self.GetItemText(child).casefold())
            child, cookie = self.GetNextChild(item, cookie)

        self.Freeze()
        try:
            added = 0
            for name, is_dir in entries:
                key = name.casefold()
                if key in existing:
                    continue
                child = self.AppendItem(item, name, self._icon_for(name, is_dir))
                added += 1
                if is_dir:
                    self._add_placeholder(child)
                    added += 1
                existing.add(key)
            # 走到了这里就只有一种可能：**要文件的那次升级**
            self._populated[item] = "full"
            self._node_count += added
        except Exception as error:
            # **保留记账**：子节点已经进去了，重建才是危险操作
            self._report_expand_error(item, error, keep_state=True)
        finally:
            self.Thaw()

    def _refresh_item(self, item, *, files: bool | None = None) -> None:
        """重扫目录，把**新出现的**子项追加进去（仍然只增不删）。

        ## 什么时候需要它

        `expand_to` 沿路径找某一级却找不到时，除了"上一级是大目录、
        而这个子项是文件"，还有一种更常见的情况：**这一级是刚新建的** ——
        它的父目录早在启动时就填满了（`_populated == "full"`），
        缓存里当然没有它。

        这正是交接文档第 1 版"缓存陈旧：新建的文件夹找不到"那件事。
        第 2 版当时用"强制重填"（`DeleteChildren` + 重建）来解决，
        于是撞上悬空句柄崩溃；这里改成**只追加**，同一个问题换个安全的解。

        ## ⚠️ `files` 不能写死成 `True`

        写死的话，`WinSxS`（19727 个子目录）那条"程序态不展开"的闸
        （`too_many_to_expand`）会在这里被绕过去 —— 找不到子项就重扫，
        重扫就把四万个节点全建出来。所以**中间层仍然走 `files=None`**，
        只有最后一级（用户目标）才允许全量。
        """
        if item not in self._populated:
            self._populate_item(item, files=files if files is True else None)
            return
        self._append_missing(item, self._entries_of(item))

    @contextlib.contextmanager
    def quiet_expand(self):
        """在这个 ``with`` 里发生的展开都算**程序**发起的（只建到够用为止）。

        ## ⚠️ 为什么需要它（2026-10-25 实测，别再删）

        `wx.TreeCtrl.Expand()` **会同步回调** `EVT_TREE_ITEM_EXPANDING` ——
        也就是 `_on_expanding` 在 `Expand()` 返回之前就跑完了
        （实测：`tools/probes/probe_pathbar_populate.py` 里每次 `Expand`
        都紧跟着一条 `_on_expanding` 记录，不是延后到事件循环）。

        于是 `expand_to` 刚决定"这个目录太大、先别建文件"，
        下一句 `self.Expand(item)` 就会经 `_on_expanding` 把文件补回来。

        **交接文档里第 4 版"增量填充能跑但没效果（节点仍 +5793）"就是这件事**：
        填充逻辑没错，是被 `Expand()` 同步触发的那个回调推翻了。
        """
        self._quiet_expand_depth += 1
        try:
            yield
        finally:
            self._quiet_expand_depth -= 1

    def _on_expanding(self, event) -> None:
        item = event.GetItem()
        # **窗口正在销毁时不要再建节点**（`0xC0000005` 防护）。
        #
        # 症状：窗口销毁时进程**无声消失**（界面没了、没有异常、没有提示）。
        # `wx.Window.Destroy()` 是**延迟销毁**（只打标记，真正释放要等事件循环），
        # 在"已标记、未释放"那段里再建节点就是在访问一个正在被释放的控件。
        #
        # 实测：`tools/verify_gui.py` 在 `frame.Destroy()` 之后还会
        # `wx.YieldIfNeeded()`，不加这一句时连跑 3 次崩 2 次；加上之后 3/3 通过。
        #
        # > ⚠️ **2026-10-25 更正**：这里原来写着"`Expand()` 会**投递事件**"。
        # > 实测对 `EVT_TREE_ITEM_EXPANDING` **不成立** —— 它是**同步**派发的
        # > （见 `quiet_expand()`）。所以这条防护挡的**不是**"队列里排着的展开事件"，
        # > 而是销毁过程中别处仍会触发的展开/重绘。**机制没完全查清，
        # > 但"不加它就 3 次崩 2 次"是实测的 —— 别再删。**
        #
        # ⚠️ **必须用 `IsBeingDeleted()`，不是 `GetHandle()`** ——
        # 在"已标记、未释放"那段窗口里 `GetHandle()` 仍返回有效句柄，
        # 查它挡不住（第一版就是这么写错的，照样崩）。
        try:
            if self.IsBeingDeleted():
                event.Skip()
                return
        except (RuntimeError, AttributeError):
            event.Skip()
            return
        # **用户点的展开 = 要看全（含文件）；程序沿路径展开 = 够用就行。**
        #
        # ⚠️ 必须靠 `quiet_expand()` 的计数来分辨，不能"看是不是已填充"：
        # 已展开但只建了文件夹的节点，用户点箭头（先折叠再展开）时
        # 必须升级成 `files=True`，否则文件永远补不上。
        self._populate_item(
            item, files=True if self._quiet_expand_depth == 0 else None)
        event.Skip()

    def _entries_of(self, item) -> list[tuple[str, bool]]:
        """某个**节点**对应目录下的**全部**子项 —— ``[(名字, 是不是目录)]``。

        ⚠️ **文件和文件夹都要返回。**
        我一度只列目录，理由写的是"列文件会把树撑爆" ——
        而用户报："现在它只展示文件夹，不展示文件。这样用户看不到文件夹下
        有什么东西，会很困惑。" **那个限制是我自己加的，不是用户要的**；
        原来的 `wx.GenericDirCtrl` 默认两者都显示。

        所以"要不要真的建文件节点"由**调用方**决定
        （`_build_children` 的 `files` 参数），本方法只管如实读出目录里有什么 ——
        因为**判断"这个目录大不大"必须知道条目总数**。

        返回 `(名字, 是否目录)` 而不是纯名字 —— 调用方要据此选图标、
        并决定要不要加"占位子节点"（**文件展开不了，不能加**）。

        ## 两处必须记住的理由

        **① 收节点、不收标签。** 收标签就必须反查路径，而那个反查曾经是
        全树搜索（O(N)）⇒ 每个节点一次 ⇒ O(N²)，界面直接未响应。
        收节点之后是 O(深度)，见 `path_of_node`。

        **② 用 `os.scandir`，不要 `os.listdir` + `isdir` + `GetFileAttributes`。**
        实测 `C:\Windows`（111 个条目）要 **283 ms** —— 平均每条 2.5 ms，
        因为每个条目要发**三次系统调用**。
        `DirEntry` 自带 `dwFileAttributes`（`FindNextFile` 本来就返回了它），
        所以 `is_dir()` 与隐藏位都是**读缓存、零额外调用**。
        """
        path = self.path_of_node(item)
        if not path:
            return []
        out = []
        try:
            # ⚠️ `os.scandir` 是上下文管理器：不用 `with` 会泄漏目录句柄
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        # 读的是已缓存的属性，**不发额外系统调用**
                        is_dir = entry.is_dir()
                        if not self._show_hidden and _is_hidden_entry(entry):
                            continue
                    except OSError:
                        # 单个条目读不到（权限、竞态）不该让整个目录列不出来
                        continue
                    out.append((entry.name, is_dir))
        except OSError:
            # 目录不存在 / 没权限（U 盘拔了、系统目录）—— 返回空，不抛
            return []
        # **文件夹在前、文件在后**，各自按名字排 —— 与资源管理器一致。
        # 混在一起排会让"哪个能展开"变得难看出来。
        out.sort(key=lambda pair: (not pair[1], pair[0].lower()))
        return out

    # -- 路径 ↔ 节点 ------------------------------------------------------

    def path_of_node(self, item) -> str:
        """从节点**沿父链往上拼**出完整路径 —— **O(深度)**。

        ## 为什么必须有它（性能，不是风格）

        原来的 `path_of_label` 是**按文字搜全树**，每次 O(节点数)。
        而 `GetPath` 会被 `tree_nav.TreeWalker.bfs_find_by_path`
        **对每个访问到的节点**调用一次 ⇒ **O(N²)**。
        节点上千之后界面就**未响应**了（用户报的"回车就崩"）。

        沿父链走是 O(深度)（通常不到 10 层），且不碰 `GetItemText`
        之外的任何东西。
        """
        if not item.IsOk() or item == self._root:
            return ""
        parts = []
        node = item
        while node.IsOk():
            parent = self.GetItemParent(node)
            if not parent.IsOk():
                break
            text = self.GetItemText(node)
            # **空文本 = 占位子项**（`_add_placeholder` 放的那个）。
            #
            # 它不是一个目录，`os.path.join` 会把空串吃掉、于是**返回父目录的路径** ——
            # 这个"看起来有值"的假路径会让 `pick_fallback_item` 把占位子项
            # 当成"最深的、包含目标的祖先"，最后 `SelectItem` 选中一条**空白行**
            # （2026-10-25 实测：超上限的目录不展开时就会走到这里）。
            # 顺带也避免了"展开占位子项会列出父目录内容"这种荒谬行为。
            if not text:
                return ""
            drive = _as_drive_root(text)
            if drive:
                # 到盘符根了：拼起来收工
                return os.path.join(drive, *reversed(parts)) if parts else drive
            if parent == self._root:
                # 顶层节点却不是盘符 —— 认不出，别硬拼一个假路径
                return ""
            parts.append(text)
            node = parent
        return ""

    def _walk_items(self):
        """深度优先遍历所有节点（**不含虚拟根**）。

        ## ⚠️ 为什么不能从根开始 yield

        本类用了 `wx.TR_HIDE_ROOT`，此时根是**虚拟根**
        （`HTREEITEM` = `-0x10000`）。对它调 `GetItemText` 会触发
        C++ 断言：

        ```
        wxTreeCtrl::DoGetItem(): can't retrieve virtual root item
        ```

        实测就是这么炸的 —— 而 **wx 的断言在 Python 侧是抛异常**，
        整个验证器直接中断（不是某一条失败）。

        ⇒ 从**根的孩子们**开始遍历。
        """
        stack = []
        child, cookie = self.GetFirstChild(self._root)
        while child.IsOk():
            stack.append(child)
            child, cookie = self.GetNextChild(self._root, cookie)
        while stack:
            item = stack.pop()
            yield item
            child, cookie = self.GetFirstChild(item)
            while child.IsOk():
                stack.append(child)
                child, cookie = self.GetNextChild(item, cookie)

    def expand_to(self, path: str, *, select: bool = True):
        """沿 `path` 逐级展开，**返回终点节点**；找不到返回 `None`。

        ## 为什么它必须存在（懒加载的直接后果）

        `GenericDirCtrl` 是 **eager** 的 —— 一次把整棵树建出来，所以
        `tree_nav` 那套 `TreeWalker.find_by_names` / `bfs_find_by_path`
        能直接走到底。

        本类是**懒加载**：子节点要等 `EVT_TREE_ITEM_EXPANDING` 才创建。
        于是 `reveal_in_tree` 实测**只走到 `C:\\Users` 就停了** ——
        下一层节点还不存在。

        这个方法**边展开边创建**，正好补上那一环；
        `select=False` 让调用方自己决定要不要选中（`reveal_in_tree`
        有自己的选中逻辑，见那里的说明）。

        ## 中间那一级只建文件夹，**目标那一级全量**

        用户 2026-10-25 报"地址栏回车非常慢、关程序也慢"，实测
        （`tools/probes/probe_pathbar_populate.py`，路径
        ``C:\\Windows\\System32\\drivers\\etc``）：

        * ``C:\\Windows\\System32`` —— 4907 个子项（**4708 个是文件**）、192 ms
        * 而它只是为了把下面三级的 ``etc`` 显示出来

        所以中间层级走 `files=None`（大目录只建文件夹），
        **最后一级（用户输入的那个文件夹）走 `files=True`** ——
        用户输入的目标目录必须完整，这一点没有妥协。

        ## 展开之前先**收起上一次那条链**（2026-10-25）

        用户："每次打开的目录在导航窗格里全部都是展开的状态……原来展开的目录
        没有收回去"，并怀疑这就是"开几小时后卡几秒、关要十几秒"的原因。
        **实测他是对的**（`tools/probes/probe_tree_inflate.py`）：
        6295 节点关闭 352 ms，45746 节点关闭 **10941 ms**。

        所以这里只收起**上一次由程序展开**的那条链，用户自己点开的目录不动。
        """
        from .tree_nav import drive_in_label
        base = os.path.normpath(path)
        drive, rest = os.path.splitdrive(base)
        if not drive:
            return None
        drive_root = drive + os.sep
        target = None
        for item in self.iter_top():
            if _as_drive_root(self.GetItemText(item)) == drive_root:
                target = item
                break
        if target is None:
            return None
        parts = [seg for seg in rest.split(os.sep) if seg]
        # **先收旧链，再展新链**（顺序不能反：反了就是"先展后收"，
        # 收到刚展开的那条上，用户会看到树瞬间塌掉）
        self._collapse_revealed_chain()
        chain = []
        # **整段展开都算"程序在展开"。**
        # `Expand()` 会**同步**回调 `_on_expanding`，而它默认要建文件子项 ——
        # 不标记的话，上面"只建文件夹"的决定立刻被推翻
        # （交接文档第 4 版"增量填充没效果"就是这么来的）。
        with self.quiet_expand():
            self._populate_item(target)
            self.Expand(target)
            chain.append(target)
            for index, part in enumerate(parts):
                last = index == len(parts) - 1
                found = self._child_by_name(target, part)
                if found is None:
                    # 两种可能，都靠**重扫 + 追加**解决，而不是"作废整棵子树"：
                    #   ① 上一级是"只建文件夹"的大目录，这个子项是文件；
                    #   ② 这一级是刚新建的，父目录早就填满了（缓存陈旧）。
                    self._refresh_item(target, files=last)
                    found = self._child_by_name(target, part)
                if found is None:
                    self._revealed_chain = chain
                    return None
                # **先同步建子节点，再展开** —— 顺序反了就又会只走一层。
                self._populate_item(found, files=True if last else None)
                self.Expand(found)
                target = found
                chain.append(target)
        self._revealed_chain = chain
        if select:
            self.SelectItem(target)
        return target

    def _collapse_revealed_chain(self) -> None:
        """把**上一次由程序展开**的那条链收起来（用户点开的分支不动）。

        只 `Collapse`，**不删节点** —— 删节点会让调用方手里的 item 悬空
        （见 `_append_missing` 的说明）；节点回收交给"节点数超上限时的整体重建"
        （`tree_nav.MAX_TREE_NODES` + `app.reveal_in_tree` 里那次 `populate`）。
        """
        for item in self._revealed_chain:
            try:
                if item.IsOk() and self.IsExpanded(item):
                    self.Collapse(item)
            except Exception:
                # 树已经被重建 / 正在销毁 —— 这条链本来就没意义了
                pass
        self._revealed_chain = []

    @property
    def node_count(self) -> int:
        """当前树里由本类建出来的节点数（自己记账，**不是** O(N) 数一遍）。"""
        return self._node_count

    def needs_trim(self) -> bool:
        """节点数是不是已经超过上限、该整体重建了。

        判断在 `tree_nav.needs_trim`（纯函数，可单测）；重建由
        `app.reveal_in_tree` 在导航结束后触发，**不在建节点的过程中做** ——
        那会把调用方手里的 item 一起删掉。
        """
        return needs_trim(self._node_count)

    def _child_by_name(self, parent, name: str):
        """在 `parent` 的直接子项里按名字找一个；找不到返回 `None`。

        比较用 `casefold()`（不是 `lower()`）—— 与
        `tree_nav.find_child_by_label` 同一口径：Windows 路径不区分大小写，
        而树的显示文本可能是任一大小写形式。**两个函数描述同一件事，
        口径不一致会让路径栏在某条路径上静默失败。**
        """
        wanted = name.casefold()
        child, cookie = self.GetFirstChild(parent)
        while child.IsOk():
            if self.GetItemText(child).casefold() == wanted:
                return child
            child, cookie = self.GetNextChild(parent, cookie)
        return None

    def iter_top(self):
        child, cookie = self.GetFirstChild(self._root)
        while child.IsOk():
            yield child
            child, cookie = self.GetNextChild(self._root, cookie)

    # -- `GenericDirCtrl` 兼容层 ------------------------------------------
    #
    # 下面这几个方法**存在的唯一理由**：让 `app.py` 里那几十处调用
    # 一行都不用改。接口与 `wx.GenericDirCtrl` 对齐。

    def GetTreeCtrl(self) -> "DirectoryTree":
        """`GenericDirCtrl` 的调用方到处写 `dir_ctrl.GetTreeCtrl()`。

        **本类自己就是树**，所以返回 `self` —— 于是那些调用原样成立。
        """
        return self

    def GetPath(self, item=None) -> str:
        """选中项（或指定项）的**完整路径**；没有则返回空串。

        ## ⚠️ 必须容得下"虚拟根"

        `tree_nav.TreeWalker` 是**从根节点开始**遍历的，它会把根传进来。
        而本类用了 `wx.TR_HIDE_ROOT`，根是**虚拟根**（`HTREEITEM = -0x10000`），
        对它调 `GetItemText` 会抛 C++ 断言：

        ```
        wxTreeCtrl::DoGetItem(): can't retrieve virtual root item
        ```

        实测就是这么炸的（`app.reveal_in_tree` → `bfs_find_by_path` →
        本方法），而 **wx 的断言在 Python 侧是异常**，整个验证器直接中断。

        ⇒ **在这里挡掉，不要指望调用方不传根**：这个方法是对外的兼容接口，
        它得对任何传进来的 id 都安全。
        """
        if item is None or not item.IsOk() or item == self._root:
            item = self.GetSelection()
        if not item.IsOk() or item == self._root:
            return ""
        # **按节点走父链**，不要按文字搜全树（见 `path_of_node` 的说明）
        return self.path_of_node(item)

    @staticmethod
    def folder_for(path: str) -> str:
        """选中项是**文件**时返回它所在的文件夹；是目录就原样返回。

        ## 这是 v1.1 就有的规则

        用户："路径记录的规则是：当你**选中导航窗格里面的文件**时，
        记录的是这个文件的**父级文件夹**。"

        `wx.GenericDirCtrl` 时代这是由调用方（`app.py`）做的；
        换成自绘树之后**丢了**。放在这里写一次，比在各调用点
        各写一遍 `os.path.dirname` 更不容易漏。

        ⚠️ `os.path.isfile` 读不到（路径已不存在）时**原样返回** ——
        此时 `dirname` 会给出一个更没意义的路径。
        """
        try:
            if path and os.path.isfile(path):
                return os.path.dirname(path)
        except OSError:
            pass
        return path

    def GetPaths(self) -> list[str]:
        """所有选中项的路径（本树是单选，所以最多一条）。

        **返回列表而不是字符串** —— `GenericDirCtrl.GetPaths()` 就是列表，
        调用方（`open_targets`）按列表处理。
        """
        path = self.GetPath()
        return [path] if path else []
