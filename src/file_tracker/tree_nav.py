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
from .lang import L

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

#: 沿路径展开某个目录时，**条目多过这个数就只建子文件夹**（不建文件）。
#:
#: ## 为什么需要这条线（2026-10-25 实测，别再删回去）
#:
#: 用户报："地址栏回车打开文件夹非常慢非常卡……关闭程序也变得很缓慢。"
#: 实测（``tools/probes/probe_pathbar_populate.py``，路径
#: ``C:\Windows\System32\drivers\etc``）：
#:
#: =========================  ========  ========  ==========
#: 目录                        条目数     其中文件   建节点耗时
#: =========================  ========  ========  ==========
#: ``C:\Windows``                  112        26       23.7 ms
#: ``C:\Windows\System32``        **4907**  **4708**   **192.3 ms**
#: ``…\drivers``                   475       467        9.9 ms
#: ``…\etc``                       6         6         4.8 ms
#: =========================  ========  ========  ==========
#:
#: 一共 5500 个节点、230 ms，而 ``System32`` 那 4708 个文件**只是为了
#: 把下面三级的 ``etc`` 显示出来** —— 对"找到下一级"毫无用处。
#: 代价还不止回车：那些节点要一直留到关闭（关闭 58 → 367 ms）。
#:
#: ## 为什么是 300，不是"一律不建文件"
#:
#: 单个节点约 20–40 µs。300 条约 10 ms，**七个祖先全踩线也才 70 ms**；
#: 而小目录（绝大多数）**行为与以前完全一样** —— 改动面越小，
#: 用户越不容易发现"这里怎么少东西了"。
DIRS_ONLY_ENTRY_THRESHOLD = 300


def should_skip_files(entry_count: int,
                      threshold: int = DIRS_ONLY_ENTRY_THRESHOLD) -> bool:
    """沿路径展开一个目录时，要不要**跳过它的文件子项**。

    纯判断，不碰 wx / 文件系统 —— 所以可以在没有桌面会话的环境里测试
    （`tests/test_tree_nav.py`）。

    :param entry_count: 该目录的条目总数（文件夹 + 文件）
    :param threshold: 分界值；**等于它不算超**（``>`` 而不是 ``>=``）
    """
    return entry_count > threshold


#: 沿路径展开时，一个目录的**子项**多过这个数就**干脆不展开它**（程序态）。
#:
#: ## 为什么还需要这一刀（2026-10-25 实测）
#:
#: `DIRS_ONLY_ENTRY_THRESHOLD` 只挡住"文件多"的目录。可有些目录是**子目录多**：
#:
#: ==============================================================  =========  =====
#: 目录                                                             条目        子目录
#: ==============================================================  =========  =====
#: ``C:\\Windows\\WinSxS``                                            **19727**  **19725**
#: ``C:\\Windows\\Microsoft.NET\\assembly\\GAC_MSIL``                    528        528
#: ``C:\\Users\\Neus117\\AppData\\Local\\Temp``                          622        271
#: ==============================================================  =========  =====
#:
#: 建一个节点约 **65 µs**（实测：44802 个节点用了 2896 ms），
#: 而且每个子目录还要再加一个占位子项 —— `WinSxS` 一级就是**近四万个节点、约 2.6 秒**。
#: 用户报的"卡六七秒才打开"就是这种量级。
#:
#: ## 为什么是"不展开"，不是"少建几个"
#:
#: 少建几个 ⇒ 想要的子项可能正好没建 ⇒ 只能报"找不到"，**行为不确定**；
#: 而"这次不展开"是**确定的**：`_populate_item` 什么都不做、占位子项留着、
#: 箭头还在，用户自己点开时仍然全量建出来（那是他自己选的动作，他知道在等什么）。
MAX_PROGRAMMATIC_CHILDREN = 2500


def too_many_to_expand(entry_count: int,
                       limit: int = MAX_PROGRAMMATIC_CHILDREN) -> bool:
    """沿路径展开时，这个目录是不是**大到不该由程序去展开**。

    :param entry_count: 该目录的条目总数（文件夹 + 文件）
    :param limit: 上限；**等于它不算超**
    """
    return entry_count > limit


#: 树里节点总数的上限；超过就**整体重建**（只保留当前这条路径）。
#:
#: ## 关闭耗时是**超线性**的（2026-10-25 实测，`probe_tree_inflate.py`）
#:
#: ==========  ==============  ================
#: 节点数      一次正常导航     关闭
#: ==========  ==============  ================
#: 6295        86 ms           **352 ms**
#: 45746       308 ms          **10941 ms**
#: ==========  ==============  ================
#:
#: 4.6 万节点就复现了用户说的"关闭要等十几秒"。而**导航一旦经过大目录，
#: 节点就是几万几万地涨**，且旧节点从不回收 ⇒ 开着用几小时必然到这个量级。
#: 4000 这一档对应"关闭约 200–350 ms"，与刚启动时没有可感差别。
MAX_TREE_NODES = 4000

#: **手动展开**时触发重建的上限（比 `MAX_TREE_NODES` 高很多）。
#:
#: 为什么两个上限：`MAX_TREE_NODES` 是"程序导航结束后顺手清一次"，
#: 而用户在树里自己点开的目录**不能刚点完就被拆掉** —— 那正是用户
#: 2026-10-26 截图报的 bug：展开 `WinSxS` 花 2.7 秒建了 39697 个节点，
#: 紧接着"上限"触发整体重建，节点全删、界面变回空白。
#:
#: 现在手动展开每个节点最多只建 `MAX_EXPAND_PAGE` 个（见下），所以要到这个
#: 硬上限需要连着手动展开六七个巨目录 —— 那时树已经不好用了，重建它反而对。
MAX_TREE_NODES_HARD = 12000

#: 用户自己点开一个超大目录时，**一次最多列这么多子项**（还有更多，会显示一行说明）。
#:
#: 实测成本：一个节点约 65 µs，加占位子项翻倍。800 个 ≈ 1600 节点 ≈ **100 ms**；
#: 而 `WinSxS` 全部 19727 个要 **2.7 秒**（且树一下就废了）。
MAX_EXPAND_PAGE = 800


def next_page_count(already: int, total: int,
                    page: int = MAX_EXPAND_PAGE) -> int:
    """分页加载时，这一轮还该再放进去多少个子项。

    :param already: 已经放到树里的子项数
    :param total: 这个目录一共有多少条目
    :param page: 每页多少条
    :return: 本次应新增的条数（0 表示已经没有更多了）
    """
    if total <= already:
        return 0
    return min(page, total - already)


def needs_trim(node_count: int, limit: int = MAX_TREE_NODES) -> bool:
    """节点数是不是超过上限了（超过就该重建，只保留当前路径）。"""
    return node_count > limit


def needs_hard_trim(node_count: int,
                    limit: int = MAX_TREE_NODES_HARD) -> bool:
    """手动展开之后用的那道更高的上限（见 `MAX_TREE_NODES_HARD` 的说明）。"""
    return node_count > limit


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

        ## ⚠️ 它**只扫已经存在的节点，不展开**（2026-10-25 改）

        原来这里对每个访问到的节点都 `Expand()`。问题是它只在"逐级匹配已经
        失败"之后才跑 —— 而失败恰恰可能是**因为**某个祖先太大、程序态拒绝展开
        （`too_many_to_expand`）。那时再整树展开一遍等于把省下的开销又花掉：
        实测扫过一层 `%TEMP%`（271 个子目录）就会额外建出上千个节点，
        在 `WinSxS` 那种目录上直接是几秒（65 µs/节点）。

        所以兜底扫描的语义改成"在**已经建出来**的节点里找"：逐级展开
        （`expand_to`）已经建好了路径上该有的节点，它找不到，就说明这一级
        真的没法由程序展开 —— 此时正确答案是**退到最近的祖先**，
        而不是把整棵树的兄弟节点都建出来。

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
            self.visited += 1
            if self.visited > self.max_nodes:
                self.truncated = True
                return None

            item_path = normalize_path(path_of(item) or "")
            if item_path and item_path.casefold() == target.casefold():
                return item

            if depth >= self.max_depth:
                continue
            # **不展开**：只看已经建出来的子节点（见上面的说明）
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
            "hint": L("请输入或粘贴一个文件夹路径。",
                     "Type or paste a folder path."),
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
            "hint": L(f"路径不存在：{text}", f"Path not found: {text}"),
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
