r"""「打开」按钮该打开哪一处 —— 用户报的功能性 bug。

用户原话：

> 记录窗格中无论选中哪条记录，「打开」按钮都只会响应左侧导航窗格的选中项。
> 把「打开」设计成按用户鼠标焦点，即最后一个选中的项目/条目打开。

原来的实现是 ``self.dir_ctrl.GetPaths()`` —— **只看导航窗格**，
记录窗格里选了什么完全没读。所以右边选哪一条都白选。

## 2026-10-17：记录窗格那条分支改成"返回**全部**选中"

用户加了"多选打开"，并选定"**打开所有选中项**"（多选了 3 条就开 3 个窗口）。
所以 `_Stub` 要提供 `selected_paths()`（列表）而不是 `selected_path()` ——
后者在应用里已经降级成"只要第一条"的版本。

**导航窗格那条分支仍然只取第一条**：那是 v1.1 起就验收过的行为
（导航窗格是多选的，早年一次弹出好几个窗口是用户抱怨过的）。

## ⚠️ 本文件里的 Windows 路径**一律写成 raw string**

踩过：用 shell heredoc 写这个文件时，`"D:\Work"` 被吃掉一层反斜杠变成
`"D:\Work"`，于是 pytest 收集阶段就报 `invalid escape sequence`。
**raw string + 正斜杠或双反斜杠并用**都能避开，这里统一用 raw string。

## 这个文件为什么不碰 wx

其余测试都不建 GUI（CI 上没有桌面会话），这里跟随同样的做法：
`open_targets()` 只用到 ``_focus_pane``、``selected_paths()`` 与
``dir_ctrl.GetPaths()``，用一个**桩**就能把逻辑测干净。
真实的窗口行为由 `tools/verify_gui.py` 在真桌面会话里验。
"""

from __future__ import annotations

import pytest

from file_tracker.app import FileTracker
from file_tracker.dir_tree import DirectoryTree


class _Stub:
    """只带 `open_targets()` 需要的那几样东西。"""

    def __init__(self, pane: str, list_paths="", tree_paths=None):
        self._focus_pane = pane
        if isinstance(list_paths, str):
            list_paths = [list_paths] if list_paths else []
        self._list_paths = list(list_paths)
        self._tree_paths = list(tree_paths or [])

    def selected_paths(self) -> list[str]:
        """记录窗格选中的**全部**路径（多选之后是复数的）。"""
        return list(self._list_paths)

    def selected_path(self) -> str:
        """应用里它是"只要第一条"的降级版本 —— 桩里也照这个语义实现。"""
        return self._list_paths[0] if self._list_paths else ""

    @property
    def dir_ctrl(self):
        stub = self

        class _Dir:
            @staticmethod
            def GetPaths():
                return list(stub._tree_paths)

            # **用真实现，不要在桩里再写一遍假规则。**
            #
            # "文件 → 父目录"是 `DirectoryTree` 的语义（v1.1 就有，
            # 换自绘树时丢过一次）。桩里若复制一份，测试就变成"测它自己"。
            folder_for = staticmethod(DirectoryTree.folder_for)

        return _Dir()


# `open_targets` 是纯函数（不碰 self 的其它属性），可以直接绑到桩上
FileTracker_open_targets = FileTracker.open_targets


def targets(pane: str, list_paths="", tree_paths=None) -> list[str]:
    return FileTracker_open_targets(_Stub(pane, list_paths, tree_paths))


# --------------------------------------------------------------------------
# 核心：跟着**最后一次选中**走
# --------------------------------------------------------------------------

def test_list_selection_wins_when_list_chose_last():
    """**这就是用户报的那条。** 在记录窗格里选中，就该打开那一条。"""
    assert targets("list", r"D:\Work\proj", [r"C:\Windows"]) == [r"D:\Work\proj"]


def test_tree_selection_wins_when_tree_chose_last():
    """在导航窗格里选中，就打开导航窗格那一项（原来的行为要保留）。"""
    assert targets("tree", r"D:\Work\proj", [r"C:\Windows"]) == [r"C:\Windows"]


def test_default_is_tree():
    """刚启动时默认以导航窗格为准。"""
    stub = _Stub("tree", r"D:\Work", [r"C:\Users"])
    assert FileTracker_open_targets(stub) == [r"C:\Users"]


# --------------------------------------------------------------------------
# 回退：选中的那一处为空时，用另一处
# --------------------------------------------------------------------------

def test_falls_back_to_tree_when_list_has_no_selection():
    """在记录窗格里点了空白取消选中，再按「打开」：
    打开导航窗格选中的目录，比什么都不做合理。"""
    assert targets("list", "", [r"C:\Windows"]) == [r"C:\Windows"]


def test_falls_back_to_list_when_tree_has_no_selection():
    assert targets("tree", r"D:\Work", []) == [r"D:\Work"]


def test_returns_nothing_when_neither_has_a_selection():
    """两处都没选中 → 什么都不打开（而不是报错或打开一个瞎猜的路径）。"""
    assert targets("tree", "", []) == []
    assert targets("list", "", []) == []


# --------------------------------------------------------------------------
# 多选打开（用户 2026-10-17 选定："打开所有选中项"）
# --------------------------------------------------------------------------

def test_list_multi_selection_returns_all():
    """**这次新加的行为**：记录窗格多选了 3 条 ⇒ 三条都打开。"""
    picked = [r"C:\a", r"C:\b", r"C:\c"]
    assert targets("list", picked, [r"C:\Windows"]) == picked


def test_list_multi_selection_keeps_order():
    """顺序必须**照行号顺序**（= 用户看到的上下顺序），不能乱。"""
    picked = [r"C:\first", r"C:\second", r"C:\third"]
    assert targets("list", picked, []) == picked


def test_list_single_selection_unchanged():
    """单选时与改动前**完全一致**（一条）。"""
    assert targets("list", [r"D:\only"], [r"C:\a", r"C:\b"]) == [r"D:\only"]


# --------------------------------------------------------------------------
# 导航窗格那条分支：**仍然只打开一个**
# --------------------------------------------------------------------------

def test_opens_exactly_one_even_when_tree_has_many_selected():
    """导航窗格是**多选**的（`wx.DIRCTRL_MULTIPLE`）。

    原来那个 `for` 循环会把所有选中项挨个打开——一次弹出好几个资源管理器
    窗口。用户要的是"打开这一处"，所以只取第一个。

    ⚠️ **用户没有要求改这一条**，别顺手把它也改成"全打开"。
    """
    many = [r"C:\a", r"C:\b", r"C:\c"]
    result = targets("tree", "", many)
    assert len(result) == 1, f"一次选了 {len(many)} 个，却打开了 {result}"
    assert result == [r"C:\a"]


# --------------------------------------------------------------------------
# 空路径要被滤掉
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tree_paths", [[""], ["", ""], ["", r"C:\real"]])
def test_empty_paths_are_not_opened(tree_paths):
    """空串不是路径。`GetPaths()` 在某些状态下会返回空串——
    拿去 `os.path.exists` 会得到 False，于是走进"失效路径"流程、
    弹一个没有意义的确认框。

    ⚠️ **判据按"过滤后还剩几条"分，不能按 `len(tree_paths)` 分**：
    三个参数里"过滤后还剩一条"的只有 `["", "C:\\real"]`；
    `["", ""]` 过滤完是**空的**。第一版我按长度判断，
    把 `["", ""]` 归进了"应该剩一条"，于是报了个**假失败**。
    """
    result = targets("tree", "", tree_paths)
    assert "" not in result
    if any(p for p in tree_paths):
        assert result == [r"C:\real"]
    else:
        assert result == []


# --------------------------------------------------------------------------
# **(b) 选中"文件"时，记录的是它的父级文件夹**（v1.1 的规则）
# --------------------------------------------------------------------------

def test_tree_file_maps_to_its_parent_folder(tmp_path):
    """导航树里选中一个**文件** ⇒ 打开/记录的是它所在的文件夹。"""
    folder = tmp_path / "some" / "folder"
    folder.mkdir(parents=True)
    a_file = folder / "note.txt"
    a_file.write_text("x", encoding="utf-8")

    assert targets("tree", tree_paths=[str(a_file)]) == [str(folder)]


def test_tree_folder_is_unchanged(tmp_path):
    """选中**文件夹**时原样返回 —— 这条规则只对文件生效。"""
    folder = tmp_path / "plain"
    folder.mkdir()
    assert targets("tree", tree_paths=[str(folder)]) == [str(folder)]


def test_missing_path_is_returned_unchanged():
    """路径已不存在时**原样返回** —— `dirname` 会给出更没意义的结果。"""
    ghost = "Z:" + chr(92) + "no" + chr(92) + "such" + chr(92) + "file.txt"
    assert targets("tree", tree_paths=[ghost]) == [ghost]
