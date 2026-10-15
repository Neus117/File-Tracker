"""目录树导航：把"某个路径"变成树里被选中并可见的那一项。

这是路径栏那一项里最复杂的一块。**``wx.GenericDirCtrl`` 没有"展开到指定路径"
的公开 API**——只有 ``ExpandPath`` 是反方向（给节点问路径），没有"给路径找节点"。
所以要自己遍历底层 ``wx.TreeCtrl``。

**为什么放在独立模块而不是塞进 ``app.py``**：路径匹配规则（大小写、分隔符、
末尾反斜杠、盘符根）是可以纯逻辑测试的，塞进 GUI 类就永远只能靠人眼看。
这个模块只依赖 ``re`` / ``ntpath`` / :mod:`file_tracker.core`，**不 import wx**，
所以能在无显示器环境下测试。
"""

from __future__ import annotations

import re

from .core import normalize_path, path_is_within

_DRIVE_RE = re.compile(r"^[A-Za-z]:$")
#: ``wx.GenericDirCtrl`` 把驱动器节点显示成 ``SYSTEM (C:)`` / ``本地磁盘 (D:)``
#: ——**不是** ``C:``。实测（`tools/probes/probe_tree_labels.py`）：三个盘符的标签分别是
#: ``SYSTEM (C:)`` / ``ACTIVE (D:)`` / ``LIBRARY (E:)``。
#: 不做这一步的话，路径栏在任何盘符路径上都会在第一级就匹配失败。
_DRIVE_LABEL_RE = re.compile(r"[\(\[]\s*([A-Za-z]:)\s*[\)\]]")
#: 可能是"尚未展开、但展开后会有子节点"的占位项名（中英文本地化都覆盖）
_PLACEHOLDER_RE = re.compile(
    r"^\s*(?:\(?\s*(?:empty|none)\s*\)?|无|空|没有(?:子)?(?:文件|文件夹|项目)?)\s*$",
    re.IGNORECASE,
)

#: 遍历上限。目录树一个节点展开就可能带出上千个子项，
#: **没有上限的遍历会在选中网络驱动器或超大目录时卡住界面**。
DEFAULT_MAX_NODES = 4000
DEFAULT_MAX_DEPTH = 40


def looks_like_drive_root(path: str) -> bool:
    """``"C:"`` / ``"C:\\\\"`` 这类盘符根。"""
    return bool(_DRIVE_RE.match(normalize_path(path).rstrip("\\")))


def drive_in_label(label: str) -> str | None:
    """从驱动器节点标签里取出盘符。

    ``"SYSTEM (C:)"`` → ``"C:"``；``"SYSTEM"`` → ``None``。
    """
    if not label:
        return None
    match = _DRIVE_LABEL_RE.search(label)
    return match.group(1) if match else None


def is_placeholder_label(label: str) -> bool:
    """判断树节点文本是不是"（空）"这类占位项。

    Windows 的 ``SHBrowseForFolder`` / 通用目录控件在访问受限的目录下
    会插入一个占位子节点，它**不是真实的子目录**。把占位项当成匹配目标
    会让导航停在一个假节点上。
    """
    if not label:
        return False
    text = label.strip()
    if not text:
        return False
    if _PLACEHOLDER_RE.match(text):
        return True
    # "（空）" / "(空)" 这类带全角括号的形态
    stripped = text.strip("()（）[]【】").strip()
    return bool(_PLACEHOLDER_RE.match(stripped))


def find_child_by_label(labels_and_items, target: str):
    """在一组 ``(label, item)`` 里找出与 ``target`` 同名的一项。

    比较用 ``casefold()``：Windows 路径不区分大小写，而树的显示文本可能是
    任一大小写形式。

    **还会尝试从驱动器标签里取盘符**——树的盘符节点显示成 ``SYSTEM (C:)``，
    直接比 ``"C:"`` 永远匹配不上。这是实测发现的：不做这一步，
    路径栏在任何盘符路径上都会在第一级就失败。

    :param labels_and_items: 可迭代的 ``(label, item)`` 二元组
    :param target: 目标名称（``"Users"`` / ``"C:"`` / ``"\\\\server\\share"``）
    :return: 匹配到的 ``item``；没有匹配返回 ``None``
    """
    wanted = (target or "").casefold()
    if not wanted:
        return None

    fallback = None
    for label, item in labels_and_items:
        text = (label or "").casefold()
        if text == wanted:
            return item
        # 盘符形态：标签里带 "(C:)" 而目标是 "C:"
        if fallback is None:
            label_drive = drive_in_label(label)
            if label_drive and label_drive.casefold() == wanted:
                fallback = item
    return fallback


def child_names_for_path(path: str) -> list[str]:
    """把一个路径拆成"逐级要匹配的名称"序列。

    ``C:\\Users\\Neus`` → ``['C:', 'Users', 'Neus']``

    盘符那一段统一成 ``C:``（不带反斜杠）——树里显示的是 ``SYSTEM (C:)``，
    由 :func:`find_child_by_label` 负责从标签里取出盘符来匹配。

    UNC 路径的 ``\\\\server\\share`` 整体算一级（它就是那个"根"，不带尾分隔符），
    与 :func:`file_tracker.core.split_path_chain` 的切法保持一致——
    两个函数描述同一件事，不一致会让路径栏在其中一条路径上静默失败。
    """
    import ntpath

    text = normalize_path(path)
    if not text:
        return []

    drive, rest = ntpath.splitdrive(text)
    names: list[str] = []
    if drive:
        names.append(drive.rstrip("\\") if drive.startswith("\\\\") else drive)
    names.extend(part for part in rest.split("\\") if part)
    return names


class TreeWalker:
    """对 ``wx.TreeCtrl`` 的一次遍历，带节点数与深度上限。

    刻意不继承任何 wx 类型、也不在 ``__init__`` 里碰控件——
    传入的 ``tree`` 只需提供 wx 那套方法即可，因此可以用假对象测试。
    """

    def __init__(self, tree, max_nodes: int = DEFAULT_MAX_NODES,
                 max_depth: int = DEFAULT_MAX_DEPTH):
        self.tree = tree
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.visited = 0
        self.truncated = False

    def _is_root(self, item) -> bool:
        """是不是那个隐藏的根节点。

        **对隐藏根调用 ``Expand`` 会抛 wxAssertionError**
        （``Can't expand/collapse hidden root node!``，treectrl.cpp），
        而它不需要展开——根节点的子项（各驱动器）本来就可见。
        """
        try:
            return item == self.tree.GetRootItem()
        except Exception:
            return False

    def _children(self, item, expand: bool = False) -> list[tuple[str, object]]:
        """取一个节点的直接子项 ``(label, item)``，跳过占位项。

        **``expand=True`` 是必须的**：``wx.GenericDirCtrl`` 的树是**懒加载**的，
        未展开的节点 ``GetFirstChild`` 返回空。实测（`tools/probes/probe_lazy_expand.py`）：

            展开 C: 之前，它的子项数 = 0
            调用 Expand(C:) 之后，子项数 = 12

        所以"先展开、再取子项"这个顺序不能反。好消息是 ``Expand`` **同步完成**——
        紧接着调用 ``GetFirstChild`` 就能拿到数据，不需要 ``Yield`` 或等待
        （实测再等 50/100/150 ms，结果完全一样）。

        遍历用固定的 ``GetFirstChild`` / ``GetNextChild`` 循环，
        **页码从已取到的第一个子项开始**（那个 ``cookie`` 是真实的，
        而不是把 ``None`` 塞给下一次调用再期望它不崩）。
        """
        if expand and not self._is_root(item):
            self.tree.Expand(item)

        children: list[tuple[str, object]] = []
        child, cookie = self.tree.GetFirstChild(item)
        if not child.IsOk():
            return children

        label = self.tree.GetItemText(child)
        if not is_placeholder_label(label):
            children.append((label, child))

        while True:
            child, cookie = self.tree.GetNextChild(item, cookie)
            if not child.IsOk():
                break
            label = self.tree.GetItemText(child)
            if not is_placeholder_label(label):
                children.append((label, child))
        return children

    def find_by_names(self, names: list[str], start=None):
        """从 ``start``（默认根）出发，按名称层级逐级向下找。

        每一级都**先展开当前节点再取子项**——树是懒加载的，见 :meth:`_children`。

        :param names: 逐级名称，例如 ``['C:', 'Users', 'Neus']``
        :param start: 起始节点；``None`` 表示树根
        :return: 找到的节点；任一级匹配不到就返回 ``None``
        """
        if not names:
            return None

        current = self.tree.GetRootItem() if start is None else start
        if not current.IsOk():
            return None

        for depth, name in enumerate(names):
            if depth >= self.max_depth:
                self.truncated = True
                return None

            match = find_child_by_label(self._children(current, expand=True), name)
            if match is None:
                return None
            current = match
            self.visited += 1
            if self.visited > self.max_nodes:
                self.truncated = True
                return None

        return current

    def bfs_find_by_path(self, path: str, path_of, start=None):
        """广度优先地按**完整路径**找节点。

        这是 :meth:`find_by_names` 的兜底：当树的层级结构与盘符假设不一致时
        （例如某个节点显示的是完整路径而不是末级名），按名称逐级匹配会失败，
        此时扫描节点、比较各自的完整路径更可靠。

        **每个被访问的节点都会先展开**（根节点除外，它不可展开）。
        不展开的话，树里那些尚未展开的子树在这个扫描中根本不存在——
        实测：``Expand`` 之前子项数为 0。逐级匹配已经展开过路径上的每一级，
        这里再展开一次是幂等的。

        :param path: 目标路径
        :param path_of: ``item -> 该节点的完整路径`` 的取值函数
        :param start: 起始节点；``None`` 表示树根
        :return: 匹配到的节点；找不到返回 ``None``
        """
        target = normalize_path(path)
        if not target:
            return None

        current = self.tree.GetRootItem() if start is None else start
        if not current.IsOk():
            return None

        queue = [(current, 0)]
        while queue:
            item, depth = queue.pop(0)
            if not self._is_root(item):
                self.tree.Expand(item)
            self.visited += 1
            if self.visited > self.max_nodes:
                self.truncated = True
                return None

            item_path = normalize_path(path_of(item) or "")
            if item_path and item_path.casefold() == target.casefold():
                return item

            if depth >= self.max_depth:
                continue
            for _, child in self._children(item):
                queue.append((child, depth + 1))

        return None


def build_walk_plan(path: str, last_directory: str = "", *, exists=None,
                    is_file=None) -> dict:
    """为"导航到 ``path``"算出一份纯数据计划，供界面层执行。

    把判断与动作分开的理由：**判断可以测试，动作只能人眼看。**
    返回的字典里：

    ``status``
        ``"ok"``     —— 可以导航（``folder`` 是要展开的目标文件夹）
        ``"file"``   —— 输入指向文件，``folder`` 是它所在的目录（与双击文件一致）
        ``"empty"``  —— 输入为空
        ``"missing"``—— 路径不存在（``hint`` 是给用户的原话）
    ``folder``
        实际要导航到的文件夹；非 ``ok`` / ``file`` 时为 ``None``
    ``names``
        :meth:`TreeWalker.find_by_names` 用的逐级名称
    ``fallback_dir``
        逐级匹配失败时的兜底起点（上次浏览的目录）；空串表示不兜底
    ``hint``
        失败时给用户看的说明

    :param exists: 存在性判断，默认 :func:`os.path.exists`。可注入的理由不只是测试——
        **对 UNC 路径调用真实的 ``os.path.exists`` 会在 SMB 连接上阻塞到网络超时**，
        而这是在一按回车就会发生的路径上。
    :param is_file: 是否为文件判断，默认 :func:`os.path.isfile`
    """
    text = normalize_path(path)
    if not text:
        return {
            "status": "empty",
            "folder": None,
            "names": [],
            "fallback_dir": last_directory or "",
            "hint": "请输入或粘贴一个文件夹路径。",
        }

    if exists is None or is_file is None:
        import os

        exists = exists or os.path.exists
        is_file = is_file or os.path.isfile

    if not exists(text):
        return {
            "status": "missing",
            "folder": None,
            "names": [],
            "fallback_dir": last_directory or "",
            "hint": f"路径不存在：{text}",
        }

    if is_file(text):
        # 指向文件时跳它所在的目录——与双击列表里一个文件路径的处理一致
        import os

        folder = os.path.dirname(text)
        status = "file"
    else:
        folder = text
        status = "ok"

    return {
        "status": status,
        "folder": folder,
        "names": child_names_for_path(folder),
        "fallback_dir": last_directory or "",
        "hint": "",
    }


def pick_fallback_item(tree, folder: str, path_of, start=None):
    """逐级匹配失败时的兜底：在已展开的节点里找**最深的、包含目标路径的祖先**。

    比直接跳回根节点好：用户至少能看到附近的位置，而不是被弹回树顶。

    :return: ``(item, 该节点路径)``；找不到返回 ``(None, "")``
    """
    target = normalize_path(folder)
    if not target:
        return (None, "")

    current = tree.GetRootItem() if start is None else start
    if not current.IsOk():
        return (None, "")

    best_item = None
    best_depth = -1

    queue = [(current, 0)]
    visited = 0
    while queue and visited < DEFAULT_MAX_NODES:
        item, depth = queue.pop(0)
        visited += 1
        item_path = normalize_path(path_of(item) or "")
        if item_path and path_is_within(target, item_path) and depth > best_depth:
            best_item, best_depth = item, depth
        if depth < DEFAULT_MAX_DEPTH:
            child, cookie = tree.GetFirstChild(item)
            while child.IsOk():
                queue.append((child, depth + 1))
                child, cookie = tree.GetNextChild(item, cookie)

    if best_item is None:
        return (None, "")
    return (best_item, normalize_path(path_of(best_item) or ""))
