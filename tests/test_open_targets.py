"""「打开」按钮该打开哪一处 —— 用户报的功能性 bug。

用户原话：

> 记录窗格中无论选中哪条记录，「打开」按钮都只会响应左侧导航窗格的选中项。
> 把「打开」设计成按用户鼠标焦点，即最后一个选中的项目/条目打开。

原来的实现是 ``self.dir_ctrl.GetPaths()`` —— **只看导航窗格**，
记录窗格里选了什么完全没读。所以右边选哪一条都白选。

## 这个文件为什么不碰 wx

其余测试都不建 GUI（CI 上没有桌面会话），这里跟随同样的做法：
`open_targets()` 只用到 ``_focus_pane``、``selected_path()`` 与
``dir_ctrl.GetPaths()``，用一个**桩**就能把逻辑测干净。
真实的窗口行为由 `tools/verify_gui.py` 在真桌面会话里验。
"""

from __future__ import annotations

import pytest

from file_tracker.app import FileTracker


class _Stub:
    """只带 `open_targets()` 需要的那三样东西。"""

    def __init__(self, pane: str, list_path: str = "",
                 tree_paths: list[str] | None = None):
        self._focus_pane = pane
        self._list_path = list_path
        self._tree_paths = list(tree_paths or [])

    def selected_path(self) -> str:
        return self._list_path

    @property
    def dir_ctrl(self):
        stub = self

        class _Dir:
            @staticmethod
            def GetPaths():
                return list(stub._tree_paths)

        return _Dir()


# `open_targets` 是纯函数（不碰 self 的其它属性），可以直接绑到桩上
FileTracker_open_targets = FileTracker.open_targets


def targets(pane: str, list_path: str = "",
            tree_paths: list[str] | None = None) -> list[str]:
    return FileTracker_open_targets(
        _Stub(pane, list_path, tree_paths))


# --------------------------------------------------------------------------
# 核心：跟着**最后一次选中**走
# --------------------------------------------------------------------------

def test_list_selection_wins_when_list_chose_last():
    """**这就是用户报的那条。** 在记录窗格里选中，就该打开那一条。"""
    assert targets("list", "D:\\Work\\proj", ["C:\\Windows"]) == ["D:\\Work\\proj"]


def test_tree_selection_wins_when_tree_chose_last():
    """在导航窗格里选中，就打开导航窗格那一项（原来的行为要保留）。"""
    assert targets("tree", "D:\\Work\\proj", ["C:\\Windows"]) == ["C:\\Windows"]


def test_default_is_tree():
    """刚启动时默认以导航窗格为准。

    那时记录窗格里的选中是**程序自己选的**（或没有），
    而导航窗格停在"上次浏览的目录"——那是用户上回的意图。
    """
    stub = _Stub("tree", "D:\\Work", ["C:\\Users"])
    assert FileTracker_open_targets(stub) == ["C:\\Users"]


# --------------------------------------------------------------------------
# 回退：选中的那一处为空时，用另一处
# --------------------------------------------------------------------------

def test_falls_back_to_tree_when_list_has_no_selection():
    """在记录窗格里点了空白取消选中，再按「打开」：
    打开导航窗格选中的目录，比什么都不做合理。"""
    assert targets("list", "", ["C:\\Windows"]) == ["C:\\Windows"]


def test_falls_back_to_list_when_tree_has_no_selection():
    assert targets("tree", "D:\\Work", []) == ["D:\\Work"]


def test_returns_nothing_when_neither_has_a_selection():
    """两处都没选中 → 什么都不打开（而不是报错或打开一个瞎猜的路径）。"""
    assert targets("tree", "", []) == []
    assert targets("list", "", []) == []


# --------------------------------------------------------------------------
# 每次只打开**一个**
# --------------------------------------------------------------------------

def test_opens_exactly_one_even_when_tree_has_many_selected():
    """导航窗格是**多选**的（`wx.DIRCTRL_MULTIPLE`）。

    原来那个 `for` 循环会把所有选中项挨个打开——一次弹出好几个资源管理器
    窗口。用户要的是"打开这一处"，所以只取第一个。
    """
    many = ["C:\\a", "C:\\b", "C:\\c"]
    result = targets("tree", "", many)
    assert len(result) == 1, f"一次选了 {len(many)} 个，却打开了 {result}"
    assert result == ["C:\\a"]


def test_list_selection_returns_exactly_one():
    assert len(targets("list", "D:\\only", ["C:\\a", "C:\\b"])) == 1


# --------------------------------------------------------------------------
# 空路径要被滤掉
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tree_paths", [[""], ["", ""], ["", "C:\\real"]])
def test_empty_paths_are_not_opened(tree_paths):
    """空串不是路径。`GetPaths()` 在某些状态下会返回空串——
    拿去 `os.path.exists` 会得到 False，于是走进"失效路径"流程、
    弹一个没有意义的确认框。"""
    result = targets("tree", "", tree_paths)
    assert "" not in result
    if tree_paths == ["", "C:\\real"]:
        assert result == ["C:\\real"]
    else:
        assert result == []
