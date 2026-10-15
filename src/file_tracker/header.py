"""列表表头：自绘。

## 为什么要自己画表头

用户反馈："深色主题下'访问的路径'等一栏**文字已经正确反色但背景还是浅色**，
导致看不见。"

实测两条路都不通（`tools/probes/probe_round6.py`、
`probe_header_dark_route.py`）：

======================  ==========================================
做法                     结果
======================  ==========================================
``SetHeaderAttr()``      返回 True，但原生表头仍是 ``#F0F0F0``
``SetWindowTheme``      返回 True，表头像素仍是 ``(255,255,255)``
======================  ==========================================

原生 ``SysHeader32`` 在浅色系统主题下不会按我们的意思变深。
第三条路是子类化父窗口处理 ``NM_CUSTOMDRAW``——**能成，但那是
ctypes 级别的窗口过程替换，写错会直接崩掉进程**。
本项目已经因为"改动过大"回归过两次，不值得为一个表头冒这个风险。

所以改成**自己画**：把原生表头隐藏，用一个 wx 自绘控件顶上去。
好处是完全可控、纯 wx、不碰窗口过程；代价是要自己同步列宽与点击。

## 与列表的配合

* :meth:`sync_from_list` 从 ``wx.ListCtrl`` 读列宽与标题
* 列表滚动、改列宽、改尺寸之后都要调一次
* 点击某一列时发 :attr:`on_column_click` 回调（列表的列头排序靠它）
"""

from __future__ import annotations

import wx

from .theme import METRICS, Theme, scale_for_dpi
from .widgets import dpi_of


class ColumnHeader(wx.Control):
    """自绘的列表表头。"""

    def __init__(self, parent, theme: Theme, titles: list[str], widths: list[int],
                 on_column_click=None):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.theme = theme
        self.titles = list(titles)
        self.widths = list(widths)
        self.on_column_click = on_column_click
        self._hover_column = -1
        self._sort_column = -1
        self._sort_reverse = False

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_SIZE, lambda event: self.Refresh())
        self._sync_height()

    # -- 与列表同步 ---------------------------------------------------------

    def sync_from_list(self, list_ctrl: wx.ListCtrl) -> None:
        """从列表读列标题与列宽。列表改过列宽之后必须调一次。"""
        try:
            count = list_ctrl.GetColumnCount()
            self.titles = [list_ctrl.GetColumn(i).GetText() for i in range(count)]
            self.widths = [list_ctrl.GetColumnWidth(i) for i in range(count)]
        except Exception:
            return
        self._sync_height()
        self.Refresh()

    def _sync_height(self) -> None:
        """高度取一个明确的值（与 DPI 联动）。

        **不能把文字高与内边距相加。** 实测 ``GetTextExtent("频次").height``
        在这台机器（175% 缩放）上返回 46——它是**物理**像素，且含行距。
        再加上 padding 会算出一个比列表行还高的表头。
        所以直接用一个按 DPI 换算的逻辑高度。
        """
        height = scale_for_dpi(METRICS.header_min_height, dpi_of(self))
        self.SetMinSize((-1, height))
        self.SetMaxSize((-1, height))
        # 光设 MinSize 不够：wx 的 sizer 会按"最佳尺寸"放大它。
        # 同时给 SetInitialSize 与 DoGetBestSize，三条一起才压得住。
        self.SetInitialSize((-1, height))

    def DoGetBestSize(self):  # noqa: N802 - 跟随 wx 命名
        """sizer 问"你想多大"时的答案——直接用我们算好的高度。"""
        return self.GetMinSize()

    def set_sort_indicator(self, column: int, reverse: bool) -> None:
        """标出当前排序列（在标题后面画一个小三角）。

        **排序是原版就有的功能，把它画出来**：否则用户点了列头、
        顺序确实变了，但界面上没有任何反馈。
        """
        self._sort_column = column
        self._sort_reverse = reverse
        self.Refresh()

    # -- 交互 ---------------------------------------------------------------

    def _column_at(self, x: int) -> int:
        total = 0
        for index, width in enumerate(self.widths):
            total += width
            if x < total:
                return index
        return -1

    def _on_motion(self, event) -> None:
        column = self._column_at(event.GetX())
        if column != self._hover_column:
            self._hover_column = column
            self.Refresh()
        event.Skip()

    def _on_leave(self, event) -> None:
        self._hover_column = -1
        self.Refresh()

    def _on_left_up(self, event) -> None:
        column = self._column_at(event.GetX())
        if column >= 0 and self.on_column_click is not None:
            self.on_column_click(column)

    # -- 绘制 ---------------------------------------------------------------

    def separator_positions(self) -> list[int]:
        """列间竖线的 x 坐标（**唯一**的位置来源）。

        抽出来是为了能被单独验证：`_on_paint` 需要真实的 paint DC，
        在测试里构造很麻烦；而"线画在哪"纯粹是几何计算，
        没必要绑在绘制上下文上。

        规则：**x = 列边界 − 线宽**。
        数据行的 `app._paint_column_separators` 用的是同一条规则，
        两边因此必然重合（用户反馈过"列标题和列数据分隔线未对齐"）。

        **`_on_paint` 必须调用本方法**，不要再在里面复制一遍算法——
        复制出来的第二份迟早与这份不同步，那正是这个 bug 的成因。
        """
        thickness = self.separator_thickness()
        positions = []
        x = 0
        for width in self.widths[:-1]:
            x += width
            if width > 0:
                positions.append(x - thickness)
        return positions

    def separator_thickness(self) -> int:
        """竖线的粗细，**物理像素，不按 DPI 缩放**（表头与数据行共用）。

        用户要求"改细，最细"。`METRICS.separator_thickness` 默认 1，
        而 **1 个物理像素就是能做到的极限**——所以这里**不做 DPI 换算**。

        若按 DPI 缩放，本机 175% 下 `scale_for_dpi(1, 168)` 会算出 **2**，
        那正是用户嫌粗的样子。

        分界线与"内容尺寸"不同：**1 像素的细线是显示器的属性，
        不是内容的属性**，所以这里刻意不换算。
        """
        return max(int(METRICS.separator_thickness), 1)

    def _on_paint(self, event) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        theme = self.theme
        width, height = self.GetClientSize()

        dc.SetBackground(wx.Brush(wx.Colour(theme.surface_alt)))
        dc.Clear()

        font = self.GetFont()
        dc.SetFont(font)
        text_height = dc.GetTextExtent("频次").height
        inset = scale_for_dpi(METRICS.header_text_inset, dpi_of(self))
        # 竖线的位置与粗细**只在这里取一次**，循环里直接用
        positions = self.separator_positions()
        thickness = self.separator_thickness()
        x = 0
        for index, title in enumerate(self.titles):
            column_width = self.widths[index] if index < len(self.widths) else 0
            if column_width <= 0:
                continue
            # 悬停列高亮——"这一列可以点"的视觉线索
            if index == self._hover_column:
                dc.SetBrush(wx.Brush(wx.Colour(theme.button_hover)))
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.DrawRectangle(x, 0, column_width, height)

            label = title
            if index == self._sort_column:
                label += " ▼" if self._sort_reverse else " ▲"

            dc.SetTextForeground(wx.Colour(theme.text))
            dc.DrawText(label, x + inset, int((height - text_height) / 2))

            # 列间竖线（**只画竖线**，用户明确说行之间不要线）。
            #
            # ## 位置与粗细必须和**数据行**那条完全一致
            #
            # 用户反馈："检查列标题和列数据分隔线为什么粗细不一致+未对齐"。
            # 原来这里画在 `x + column_width - 1 - gap`（`gap` = 6 逻辑像素
            # ≈ 10 物理像素），y 只占 `4 .. height-4`；
            # 数据行那条画在**精确的列边界**且**满高**——既错位又不等长。
            #
            # 现在**直接取用 :meth:`separator_positions` 的结果**，
            # 不在这里重算——重算出来的第二份算法迟早与那份不同步，
            # 而这个 bug 的成因恰恰就是"两处各算各的"。
            line_x = positions[index] if index < len(positions) else None
            if line_x is not None:
                dc.SetPen(wx.Pen(wx.Colour(theme.separator), thickness))
                dc.DrawLine(line_x, 0, line_x, height)
            x += column_width
