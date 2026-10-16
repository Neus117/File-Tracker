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

import ctypes
import os
import string
import sys

import wx

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
        #: 建树时把子节点推迟到"展开时"再加 —— 盘符下的目录可能上千个
        self._populated: set = set()
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
        """列出所有盘符；`expand_path` 指向的那条链**自动展开并选中**。"""
        self.DeleteChildren(self._root)
        self._populated.clear()
        for drive in self._drives():
            # 标签用外壳给的名字（`SYSTEM (C:)`），路径反查由
            # `_as_drive_root` 里的 `drive_in_label` 负责 —— 它认的正是这种。
            item = self.AppendItem(self._root, _drive_label(drive), ICON_DRIVE)
            self._add_placeholder(item)
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

    def _populate_item(self, item) -> None:
        """把某个节点的子目录**同步**建出来（懒加载的唯一实现处）。

        **抽出来是因为有两条路要走它**：

        * `_on_expanding` —— 用户点开箭头时（事件驱动）
        * `expand_to` —— 程序沿路径展开时（**必须同步**）

        踩过：`expand_to` 里只用 `self.Expand(item)`，而它**投递事件**、
        处理函数要到下一轮事件循环才跑 —— 紧接着迭代 `GetFirstChild`
        什么也拿不到，于是路径**只展开一层就停**（实测只到 `C:\\Users`）。
        """
        if not item.IsOk() or item in self._populated:
            return
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
            for name, is_dir in self._children_of(item):
                child = self.AppendItem(item, name,
                                        self._icon_for(name, is_dir))
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
            # 而 `_icon_for` → `_shell_icon` 是**故意只兜 `OSError`** 的
            # （编程错误要露出来）—— 所以这条路径真的可能被走到。
            #
            # 这与本项目另一条教训同型：**先记账、后干活 ⇒ 账本一旦脏了，
            # 就永远不再重试**（`_apply_selection_highlight` 那次也是）。
            self._populated.add(item)
        except Exception as error:
            # **失败时把记账撤掉（下次展开会重试），并如实报出来。**
            #
            # 静默吞掉的话用户只看到"这个目录点不开、里面什么都没有"，
            # 没有任何线索。
            self._populated.discard(item)
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
        finally:
            self.Thaw()

    def _on_expanding(self, event) -> None:
        item = event.GetItem()
        self._populate_item(item)
        event.Skip()

    def _children_of(self, item) -> list[str]:
        """某个**节点**对应目录下、该显示的子项 —— **(名字, 是不是目录)**。

        ⚠️ **文件和文件夹都要列。**
        我一度只列目录，理由写的是"列文件会把树撑爆" ——
        而用户报："现在它只展示文件夹，不展示文件。这样用户看不到文件夹下
        有什么东西，会很困惑。" **那个限制是我自己加的，不是用户要的**；
        原来的 `wx.GenericDirCtrl` 默认两者都显示。

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
        """
        from .tree_nav import drive_in_label
        path = os.path.normpath(path)
        drive, rest = os.path.splitdrive(path)
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
        self._populate_item(target)
        self.Expand(target)
        for part in [seg for seg in rest.split(os.sep) if seg]:
            found = None
            child, cookie = self.GetFirstChild(target)
            while child.IsOk():
                if self.GetItemText(child).lower() == part.lower():
                    found = child
                    break
                child, cookie = self.GetNextChild(target, cookie)
            if found is None:
                return None
            # **先同步建子节点，再展开** —— 顺序反了就又会只走一层。
            self._populate_item(found)
            self.Expand(found)
            target = found
        if select:
            self.SelectItem(target)
        return target

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
