"""目录树导航规则的测试。

**用假树对象，不创建真实控件**——`TreeWalker` 只要求传入的对象提供 wx 那套方法，
所以这些规则可以在无桌面会话的环境里验证。

这是路径栏那一项里最容易出错、也最难靠人眼发现的部分：路径匹配失败的表现
只是"窗口没跳过去"，没有任何报错。
"""

from __future__ import annotations

import pytest

from file_tracker import tree_nav


class FakeItem:
    """模拟 ``wx.TreeItemId``。

    ``__eq__`` / ``__hash__`` 必须实现：真实代码里有 ``item is None`` 与
    ``in`` 判断，假对象也得让它们有意义。
    """

    def __init__(self, path: str):
        self.path = path

    def IsOk(self) -> bool:  # noqa: N802 - 跟随 wx 命名
        return True

    def __eq__(self, other) -> bool:
        return isinstance(other, FakeItem) and other.path == self.path

    def __hash__(self) -> int:
        return hash(self.path)

    def __repr__(self) -> str:
        return f"FakeItem({self.path!r})"


class _NoItem(FakeItem):
    """``wx.TreeCtrl`` 在"没有更多子项"时返回的无效项：``IsOk()`` 为假。

    用一个**独立的类**而不是 ``FakeItem("<none>")``——后者会被字典当作
    一个合法路径键，曾经因此把 ``<none>`` 混进节点表里。
    """

    def __init__(self):
        super().__init__("<no-item>")

    def IsOk(self) -> bool:  # noqa: N802
        return False


NO_ITEM = _NoItem()


class FakeTree:
    """一棵只有父子关系、没有绘制逻辑的目录树。

    刻意模拟真实 ``wx.GenericDirCtrl`` 的两个行为，因为**导航逻辑依赖它们**：

    * 盘符节点的显示名是 ``SYSTEM (C:)`` 这种形式，**不是** ``C:``
      （实测见 ``tools/probes/probe_lazy_expand.py``）
    * 树是懒加载的：先 ``Expand`` 才有子项。这里用一个"未展开则返回空"的开关
      来模拟，好让"必须先展开"这条约束真的被测到
    """

    #: 盘符 -> 卷标，与真实机器上的形式一致
    VOLUME_LABELS = {"C": "SYSTEM", "D": "ACTIVE", "E": "LIBRARY"}
    #: 懒加载开关。为 True 时未展开的节点返回空子项列表
    LAZY = True

    def __init__(self, paths: list[str], lazy: bool | None = None):
        self.lazy = self.LAZY if lazy is None else lazy
        self.root = FakeItem("<root>")
        self._items: dict[str, FakeItem] = {"<root>": self.root}
        self._children: dict[str, list[str]] = {"<root>": []}
        self._expanded: set[str] = {"<root>"}
        self.expand_calls: list[str] = []
        for path in paths:
            self._add(path)

    def _canonical(self, path: str) -> str:
        """把路径统一成树里节点的规范形式。

        盘符根统一带尾分隔符（``C:`` → ``C:\\``）。**不做这一步的话，
        ``C:`` 与 ``C:\\`` 会变成两个不同的节点**，而 ``_add`` 自动补父节点时
        产生的正是 ``C:`` 形式——于是"逐级匹配"会匹配到一个不是根的空壳节点。
        """
        import ntpath

        drive, rest = ntpath.splitdrive(path)
        if drive and not rest.strip("\\"):
            return drive if drive.endswith("\\") else drive + "\\"
        return path

    def _parent_of(self, path: str) -> str:
        """父节点路径。

        盘符根 / UNC 的 ``\\\\server\\share`` 在树里直接挂在隐藏根下。
        判断"是不是根"时要**去掉尾分隔符再比**：``ntpath.splitdrive("C:\\\\")[0]``
        是 ``"C:"``，而路径本身是 ``"C:\\\\"``，直接比会不相等，
        于是 ``C:\\`` 会去找自己的父节点 ``C:``，再规范化回 ``C:\\``——**死循环**。
        """
        import ntpath

        stripped = path.rstrip("\\") or path
        if ntpath.splitdrive(stripped)[0] == stripped:
            return "<root>"
        parent = ntpath.dirname(stripped)
        return parent if parent and parent != stripped else "<root>"

    def _add(self, path: str) -> FakeItem:
        path = self._canonical(path)
        if path in self._items:
            return self._items[path]
        parent_key = self._canonical(self._parent_of(path))
        if parent_key not in self._items and parent_key != "<root>":
            self._add(parent_key)
        item = FakeItem(path)
        self._items[path] = item
        self._children[path] = []
        self._children.setdefault(parent_key, []).append(path)
        return item

    def expand_all(self) -> None:
        """把整棵树全部标记为已展开（模拟用户手动浏览过一遍）。"""
        self._expanded.update(self._items)

    # -- wx.TreeCtrl 接口 --------------------------------------------------

    def GetRootItem(self):  # noqa: N802
        return self.root

    def GetItemText(self, item):  # noqa: N802
        if item.path == "<root>":
            return ""
        import ntpath
        import re

        drive, rest = ntpath.splitdrive(item.path)
        if drive and not rest.strip("\\"):
            letter = drive.rstrip(":\\")
            label = self.VOLUME_LABELS.get(letter.upper(), "Local Disk")
            return f"{label} ({letter}:)"
        # **不能对 "C:" 调 ntpath.basename** —— 它内部会因为盘符后没有分隔符
        # 而反复补反斜杠直到内部分割上限，表现为"卡住"
        return ntpath.basename(item.path.rstrip("\\")) or item.path

    def Expand(self, item):  # noqa: N802
        self._expanded.add(item.path)
        self.expand_calls.append(item.path)

    def IsExpanded(self, item):  # noqa: N802
        return item.path in self._expanded

    def GetFirstChild(self, item):  # noqa: N802
        if self.lazy and item.path not in self._expanded:
            return (NO_ITEM, None)
        children = self._children.get(item.path, [])
        if not children:
            return (NO_ITEM, None)
        return (self._items[children[0]], 0)

    def GetNextChild(self, item, cookie):  # noqa: N802
        children = self._children.get(item.path, [])
        if cookie is None or cookie + 1 >= len(children):
            return (NO_ITEM, None)
        return (self._items[children[cookie + 1]], cookie + 1)


def path_of(tree: FakeTree):
    """``GetPath`` 的替身：节点 -> 完整路径。"""
    return lambda item: "" if item.path == "<root>" else item.path


# --------------------------------------------------------------------------
# 占位项识别
# --------------------------------------------------------------------------

@pytest.mark.parametrize("label", ["(空)", "（空）", "空", "无", "empty", "(Empty)"])
def test_placeholder_labels_are_recognised(label):
    assert tree_nav.is_placeholder_label(label)


def test_empty_label_is_not_a_placeholder():
    """空标签是"没有标签"，不是"（空）"这个占位项——两者要去的地方不一样。"""
    assert not tree_nav.is_placeholder_label("")
    assert not tree_nav.is_placeholder_label("   ")


@pytest.mark.parametrize("label", ["Users", "Windows", "Neus", "程序文件", "empty-ish"])
def test_real_labels_are_not_placeholders(label):
    """反向对照：真目录名不能被当成占位项，否则会整批漏掉子目录。"""
    assert not tree_nav.is_placeholder_label(label)


def test_looks_like_drive_root():
    assert tree_nav.looks_like_drive_root("C:")
    assert tree_nav.looks_like_drive_root("C:\\")
    assert not tree_nav.looks_like_drive_root(r"C:\Users")


# --------------------------------------------------------------------------
# 逐级名称匹配
# --------------------------------------------------------------------------

def test_find_child_by_label_is_case_insensitive():
    item = FakeItem(r"C:\users")
    assert tree_nav.find_child_by_label([("Users", item)], "users") == item
    assert tree_nav.find_child_by_label([("Users", item)], "USERS") == item


def test_find_child_by_label_returns_none_when_absent():
    assert tree_nav.find_child_by_label([("Users", FakeItem("x"))], "Windows") is None
    assert tree_nav.find_child_by_label([("Users", FakeItem("x"))], "") is None


def test_child_names_for_path():
    assert tree_nav.child_names_for_path(r"C:\Users\Neus") == ["C:", "Users", "Neus"]
    assert tree_nav.child_names_for_path("C:\\") == ["C:"]
    assert tree_nav.child_names_for_path("") == []


# --------------------------------------------------------------------------
# 遍历
# --------------------------------------------------------------------------

def test_find_by_names_walks_to_the_target():
    tree = FakeTree([r"C:\Users", r"C:\Users\Neus", r"C:\Users\Neus\Docs"])
    found = tree_nav.TreeWalker(tree).find_by_names(["C:", "Users", "Neus", "Docs"])
    assert found is not None
    assert found.path == r"C:\Users\Neus\Docs"


# --------------------------------------------------------------------------
# 两条实测发现的约束 —— 不满足它们，路径栏在任何盘符路径上都会失败
# --------------------------------------------------------------------------

def test_drive_in_label_extracts_the_letter():
    """``wx.GenericDirCtrl`` 把驱动器显示成 ``SYSTEM (C:)``，不是 ``C:``。

    实测（`tools/probes/probe_lazy_expand.py`）：三个盘符的标签分别是
    ``SYSTEM (C:)`` / ``ACTIVE (D:)`` / ``LIBRARY (E:)``。
    """
    assert tree_nav.drive_in_label("SYSTEM (C:)") == "C:"
    assert tree_nav.drive_in_label("本地磁盘 (D:)") == "D:"
    assert tree_nav.drive_in_label("[E:]") == "E:"
    assert tree_nav.drive_in_label("Users") is None
    assert tree_nav.drive_in_label("") is None


def test_drive_target_matches_a_volume_labelled_node():
    """这条守的是路径栏的**第一级**：盘符匹配不上，后面全都白搭。"""
    node = FakeItem("C:\\")
    assert tree_nav.find_child_by_label([("SYSTEM (C:)", node)], "C:") == node


def test_exact_label_still_wins_over_drive_fallback():
    """同名节点优先于"从标签里抽出盘符"的兜底匹配。"""
    exact = FakeItem("C:\\Users")
    drive = FakeItem("C:\\")
    matched = tree_nav.find_child_by_label(
        [("SYSTEM (C:)", drive), ("C:", exact)], "C:",
    )
    assert matched == exact


def test_find_by_names_expands_each_level_before_reading_children():
    """**树是懒加载的**：未展开的节点 ``GetFirstChild`` 返回空。

    实测：展开 ``C:`` 之前子项数 0，``Expand`` 之后 12。
    所以"先展开、再取子项"的顺序不能反——把顺序写反的话，
    路径栏会静默地什么都不做（找不到节点，也没有报错）。
    """
    tree = FakeTree([r"C:\Users\Neus\Docs"], lazy=True)
    walker = tree_nav.TreeWalker(tree)
    found = walker.find_by_names(["C:", "Users", "Neus", "Docs"])

    assert found is not None, "懒加载的树上导航失败——先展开再取子项的顺序错了"
    assert tree.expand_calls == ["C:\\", r"C:\Users", r"C:\Users\Neus"]


def test_lazy_tree_fails_if_expansion_is_skipped():
    """阳性对照：证明上面那条测试真的在测"展开"这件事。

    把 ``Expand`` 变成空操作后，导航必须失败——否则说明这个假树
    根本没有模拟懒加载，上面那条测试是空的。
    """
    tree = FakeTree([r"C:\Users\Neus\Docs"], lazy=True)
    tree.Expand = lambda item: None          # 把展开变成空操作
    assert tree_nav.TreeWalker(tree).find_by_names(
        ["C:", "Users", "Neus", "Docs"],
    ) is None


def test_walker_never_expands_the_hidden_root():
    """对隐藏根调用 ``Expand`` 会抛 wxAssertionError。

    ``Can't expand/collapse hidden root node!``（treectrl.cpp:1750）。
    根节点的子项（各驱动器）本来就可见，不需要也没法展开。
    """
    tree = FakeTree([r"C:\Users"], lazy=True)
    tree_nav.TreeWalker(tree).find_by_names(["C:", "Users"])
    assert "<root>" not in tree.expand_calls


def test_find_by_names_returns_none_for_absent_branch():
    tree = FakeTree([r"C:\Users"])
    assert tree_nav.TreeWalker(tree).find_by_names(["C:", "Windows", "System32"]) is None


def test_find_by_names_stops_at_max_depth():
    """**遍历必须有上限**：没有上限的话，选中网络驱动器或超大目录会卡住界面。"""
    tree = FakeTree([r"C:\a", r"C:\a\b", r"C:\a\b\c"])
    walker = tree_nav.TreeWalker(tree, max_depth=2)
    assert walker.find_by_names(["C:", "a", "b", "c"]) is None
    assert walker.truncated is True


def test_find_by_names_stops_at_max_nodes():
    tree = FakeTree([r"C:\a", r"C:\a\b", r"C:\a\b\c"])
    walker = tree_nav.TreeWalker(tree, max_nodes=1)
    assert walker.find_by_names(["C:", "a", "b", "c"]) is None
    assert walker.truncated is True


def test_bfs_find_by_path_scans_expanded_items():
    """兜底路径：按完整路径扫描，用于层级结构与盘符假设不一致的情况。"""
    tree = FakeTree([r"C:\Users", r"C:\Users\Neus"])
    walker = tree_nav.TreeWalker(tree)
    found = walker.bfs_find_by_path(r"c:\users\neus", path_of(tree))
    assert found is not None
    assert found.path == r"C:\Users\Neus"


def test_bfs_find_by_path_is_case_insensitive():
    tree = FakeTree([r"C:\Users"])
    walker = tree_nav.TreeWalker(tree)
    assert walker.bfs_find_by_path(r"C:\USERS", path_of(tree)) is not None


def test_bfs_returns_none_for_absent_path():
    tree = FakeTree([r"C:\Users"])
    walker = tree_nav.TreeWalker(tree)
    assert walker.bfs_find_by_path(r"C:\Nope", path_of(tree)) is None


# --------------------------------------------------------------------------
# 兜底：最深的包含目标的祖先
# --------------------------------------------------------------------------

def test_pick_fallback_item_prefers_deepest_ancestor():
    """逐级匹配失败时，用户至少该看到附近的位置，而不是被弹回树顶。

    这里先用 ``expand_all()`` 模拟"用户已经手动浏览过这些目录"——
    ``pick_fallback_item`` 只在**已展开的节点**里找，它不做展开。
    """
    tree = FakeTree([r"C:\Users", r"C:\Users\Neus", r"C:\Windows"])
    tree.expand_all()
    item, item_path = tree_nav.pick_fallback_item(
        tree, r"C:\Users\Neus\Documents\deep", path_of(tree),
    )
    assert item_path == r"C:\Users\Neus"


def test_pick_fallback_item_returns_none_when_nothing_contains_target():
    tree = FakeTree([r"C:\Windows"])
    item, item_path = tree_nav.pick_fallback_item(tree, r"D:\Elsewhere", path_of(tree))
    assert item is None
    assert item_path == ""


# --------------------------------------------------------------------------
# build_walk_plan：把判断与动作分开
# --------------------------------------------------------------------------

def test_build_walk_plan_for_existing_directory(tmp_path):
    plan = tree_nav.build_walk_plan(str(tmp_path))
    assert plan["status"] == "ok"
    assert plan["folder"] == str(tmp_path)
    assert plan["names"]


def test_build_walk_plan_for_a_file_points_at_its_folder(tmp_path):
    """输入指向文件时，跳它所在的目录——与双击列表里一个文件路径一致。"""
    file_path = tmp_path / "note.txt"
    file_path.write_text("x", encoding="utf-8")

    plan = tree_nav.build_walk_plan(str(file_path))
    assert plan["status"] == "file"
    assert plan["folder"] == str(tmp_path)


def test_build_walk_plan_for_missing_path(tmp_path):
    plan = tree_nav.build_walk_plan(str(tmp_path / "nope"))
    assert plan["status"] == "missing"
    assert plan["folder"] is None
    assert "不存在" in plan["hint"]


def test_hint_follows_language(tmp_path):
    """hint 必须**跟着语言走**，而且两种语言都要真的存在。

    这条测试是因为一次 CI 事故补的：原来的写法只有
    ``assert "不存在" in plan["hint"]``，它**假设了中文**。
    在英文系统的 CI 上（GitHub Actions 的 runner）拿到
    ``'Path not found: ...'`` 就挂了——而本地是中文系统，永远看不到。

    `conftest.py` 里那条 autouse fixture 已经把语言钉成中文，
    所以这里**显式地**把两种都验一遍：既确认中文分支，
    也确认英文分支真的被翻译过（而不是漏成中文或空串）。
    """
    from file_tracker import lang

    saved = lang._chinese
    target = str(tmp_path / "nope")
    try:
        lang.apply(lang.PREFERENCE_CHINESE)
        chinese = tree_nav.build_walk_plan(target)["hint"]
        lang.apply(lang.PREFERENCE_ENGLISH)
        english = tree_nav.build_walk_plan(target)["hint"]
    finally:
        lang._chinese = saved

    # 两种语言都要给出提示，而且**确实不同**（否则等于没翻译）
    assert chinese and english
    assert chinese != english, f"两种语言给出同一句话：{chinese!r}"
    # 都要带上那条路径——提示的作用就是告诉用户哪个路径没找到
    assert target in chinese and target in english
    # 判据落在**路径之外的那部分文案**上，而不是"整串是否含某个词"：
    #   * 后者又是在假设具体文案，改动一个词就会误报；
    #   * 而"整串是否 ASCII"会被临时目录里的非 ASCII 字符带偏
    #     （本机 `C:\Users\Neus117` 恰好是纯 ASCII，换个用户名就不成立）。
    chinese_text = chinese.replace(target, "")
    english_text = english.replace(target, "")
    assert any(ord(ch) > 0x7F for ch in chinese_text), chinese_text
    assert all(ord(ch) < 0x80 for ch in english_text), english_text


def test_build_walk_plan_for_empty_input():
    plan = tree_nav.build_walk_plan("   ")
    assert plan["status"] == "empty"
    assert plan["folder"] is None


def test_build_walk_plan_normalizes_pasted_path(tmp_path):
    """资源管理器"复制为路径"会带引号，粘贴进来必须照样能用。"""
    plan = tree_nav.build_walk_plan(f'"{tmp_path}"')
    assert plan["status"] == "ok"
    assert plan["folder"] == str(tmp_path)


def test_build_walk_plan_accepts_forward_slashes(tmp_path):
    plan = tree_nav.build_walk_plan(str(tmp_path).replace("\\", "/"))
    assert plan["status"] == "ok"


def test_build_walk_plan_does_not_touch_the_network_for_unc_paths():
    """**这条测试是有意不走真实文件系统的。**

    对 ``\\\\server\\share`` 调用真实的 ``os.path.exists`` 会在 SMB 连接上
    阻塞到网络超时——而这发生在一按回车就会走的路径上。注入判断函数既能
    保持逻辑可测，也避免测试套件挂在一次网络等待里。
    """
    plan = tree_nav.build_walk_plan(
        r"\\server\share\docs", exists=lambda _p: True, is_file=lambda _p: False,
    )
    assert plan["status"] == "ok"
    assert plan["folder"] == r"\\server\share\docs"
    # UNC 的 "\\server\share" 整体算一级（它就是那个"根"），
    # 与 core.split_path_chain 的切法一致
    assert plan["names"] == ["\\\\server\\share", "docs"]


def test_build_walk_plan_reports_missing_without_touching_disk():
    plan = tree_nav.build_walk_plan(
        r"Z:\gone", exists=lambda _p: False, is_file=lambda _p: False,
    )
    assert plan["status"] == "missing"
    assert "Z:\\gone" in plan["hint"]
