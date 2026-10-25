"""自绘控件：Win11 观感的按钮与输入框。

原实现的两个问题，这里都修掉：

**① 悬停时不可见。** ``CustomButton.on_paint`` 读 ``self.hovering``，但
``SetBackgroundColour`` 被重写成了"改 ``normal_color`` 并 ``Refresh()``"，
而 ``on_enter`` 只设 ``hovering`` 不改色——两个机制各写各的，
结果悬停效果取决于哪个先跑。

**② 画在错误的坐标系里。** ``rect = self.GetRect()`` 返回的是**相对父窗口**的矩形，
而 ``wx.PaintDC(self)`` 的原点在**控件自己的左上角**。控件不在父窗口原点时，
圆角矩形会被画偏，宽度也用了父窗口坐标系的值。

规范依据（Roboc 视觉规范第六节）：自绘必须双缓冲，否则重绘瞬间会露出半擦除状态。
"""

from __future__ import annotations

import math

import wx

from . import win32
from .core import DEFAULT_SORT_KEY, SORT_SPECS, find_sort_spec, sort_keys
from .lang import CHOICES, DISPLAY_NAMES, L
from .theme import (METRICS, THEME_CHOICES, THEME_DARK,
                    THEME_LIGHT, THEME_SYSTEM, THEME_TOOLTIPS, Theme,
                    scale_for_dpi)


def _measure_probe() -> str:
    """量行高用的样本字。**不是文案，不要翻译。**

    用一个有两三个字的样本顶到最高字形；换成英文单词量不到中文的
    字体高度，行距会算小。
    """
    return "频次"


def dpi_of(window) -> int:
    """取 ``window`` 所在显示器当前的 DPI。

    **为什么不用 ``wx.Window.FromDIP``**：它在**控件还没完成父级绑定**时
    会退回 96。实测过这个后果——同一个按钮：

    * 直接用 ``python`` 跑（未开 per-monitor DPI 感知）→ ``FromDIP(24)`` 得 24
    * 由 ``tools/verify_gui.ps1`` 跑（先调 ``SetProcessDpiAwareness(2)``）
      → ``FromDIP(24)`` 得 **42**

    两个数字都对不上，因为 ``FromDIP`` 问的是"这个控件现在挂在哪个窗口上"，
    而构造函数里控件还没挂上去。用户看到的就是"按钮偏大"。

    所以这里主动问**父窗口**的 DPI，拿不到再退回屏幕 DPI，最后才退回 96。

    **这个函数放在 widgets 而不是 theme**：它要 import wx，而 theme 的约定是
    不依赖 wx（``tests/test_core.py::test_module_does_not_import_wx`` 守着）。
    """
    candidates = []
    if window is not None:
        try:
            parent = window.GetParent()
            if parent is not None:
                candidates.append(parent)
        except Exception:
            pass
        candidates.append(window)

    for candidate in candidates:
        try:
            dpi = candidate.GetDPI()
        except Exception:
            continue
        # **wx 的 GetDPI 返回的是 Size（宽高两个值），不是 int。**
        # 直接拿它和 0 比会抛 TypeError（踩过）。
        value = dpi[0] if isinstance(dpi, (tuple, list)) else getattr(dpi, "width", dpi)
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value

    try:
        dpi = wx.ScreenDC().GetPPI()
        if dpi and dpi.width > 0:
            return int(dpi.width)
    except Exception:
        pass
    return 96


def scale(window, pixels: int) -> int:
    """把 96 DPI 逻辑像素换算成 ``window`` 所在显示器的物理像素。"""
    return scale_for_dpi(pixels, dpi_of(window))


class BufferedPanel(wx.Panel):
    """带双缓冲的自绘面板基类。

    子类实现 :meth:`draw`，用 ``dc`` 绘制；坐标系原点已是本控件左上角。
    """

    def __init__(self, parent, theme: Theme, **kwargs):
        super().__init__(parent, **kwargs)
        self.theme = theme
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)

    def _on_paint(self, event) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        # **用父窗口底色铺满，而不是自己的底色。**
        # 圆角控件的四个角要露出父窗口的颜色；用自身底色 Clear 会在
        # 深色主题下留下没扣干净的浅色像素。
        parent_colour = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(parent_colour))
        dc.Clear()
        self.draw(dc)

    def _on_size(self, event) -> None:
        self.Refresh()
        event.Skip()

    def draw(self, dc) -> None:  # pragma: no cover - 由子类实现
        """用 ``dc`` 绘制本控件。原点为控件左上角。"""

    def SetLabel(self, label: str) -> None:
        """**自绘按钮的标题只有一份状态。**

        ## 踩过的坑：两份状态必然分叉

        `_on_paint` 画的是 `self.label`；而 wx 那边也有一份标题，
        `GetLabel()` / `SetLabel()` 读写的是**它**。

        主窗口 `retranslate()` 换语言时走的是 `SetLabel()` ——
        **只改了 wx 那份，自绘那份一个字没动**，于是按钮文字纹丝不动。
        用户报："只有非按钮部分的语言发生了变更，
        **按钮部分实际上还是原语言**。"（截图里 `打开`/`清空` 还是中文。）

        这里把 `SetLabel` 接管过来，让它去写 `self.label`，
        于是**无论谁从哪边调，都落到同一份状态上**。

        `InvalidateBestSize()` 是必须的：`DoGetBestSize` 按标题文字算宽度，
        换了语言不重算，英文长标题就会被压掉尾巴。
        """
        self.label = label
        super().SetLabel(label)
        self.InvalidateBestSize()
        self.Refresh()

    def apply_theme(self, theme: Theme) -> None:
        """主题变化时重新取色并重绘。"""
        self.theme = theme
        self.SetBackgroundColour(wx.Colour(theme.background))
        self.Refresh()


def body_font() -> wx.Font:
    """正文 / 按钮 / 弹窗的**统一字号**：系统 UI 字号 + 1。

    ## 这是唯一的定义处

    以前这段算法只写在 `app.set_global_font` 里，于是**弹窗拿不到它**：
    `wx.Dialog` 是**独立的顶层窗口**，frame 的 `SetFont` 传播过不去，
    弹窗就回落到系统默认 —— 实测比「打开」按钮**小整整 1pt**。

    用户把这一条看出来了：「检查设置窗口、所有提示弹窗中的字体、字号
    （包括标题栏）是否和『打开』『清空』按钮一致」。

    **所以别再在别处重写这个 `+ 1`** —— 换一处写，就又多一个会漂移的副本。
    """
    base = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    return wx.Font(
        base.GetPointSize() + 1,
        base.GetFamily(),
        base.GetStyle(),
        wx.FONTWEIGHT_NORMAL,
        False,
        base.GetFaceName(),
    )


class RoundedButton(wx.Control):
    """圆角自绘按钮。

    用 :class:`wx.Control` 而不是 :class:`wx.Button`：后者在 Windows 上
    由原生主题引擎绘制，自绘会被原生绘制覆盖，出现"改了没反应"的观感。

    **尺寸必须自己算。** 裸的 ``wx.Control`` 不知道自己要多大，
    ``GetBestSize()`` 会返回一个与文字无关的值（实测 100×80），
    于是 sizer 把按钮撑得很大。所以这里重写 :meth:`DoGetBestSize`：
    高度取 :data:`~file_tracker.theme.Metrics.button_height`
    （对照原生按钮的 25 逻辑像素），宽度取"文字宽 + 内边距"与最小宽度的较大者。
    """

    def __init__(self, parent, label: str, theme: Theme,
                 *, variant: str = "secondary", min_width: int | None = None,
                 height: int | None = None, on_click=None):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.theme = theme
        self.label = label
        #: 设了它就**画图标**而不是文字（见 `_draw_icon`）。
        # 默认 `None` ⇒ 行为与以前完全一致，不影响任何现有按钮。
        self.icon_painter = None
        self.variant = variant
        self._hovering = False
        self._pressed = False
        self._hovering = False
        self._min_width = min_width or METRICS.button_min_width
        # `height` 用**逻辑像素**覆盖默认按钮高度。弹窗里的按钮要比主界面矮
        # （Roboc 的原生对话框是 32，主界面是 24——见 theme.dialog_button_height）。
        self._height = height or METRICS.button_height
        # 圆角按**实际高度**算：写死 4 而高度 24 时比例只有 0.167，
        # 用户反馈"圆角太小，看不出来"。见 Metrics.button_radius_for。
        self._radius = 0

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self._sync_min_size()

        if on_click is not None:
            self.Bind(wx.EVT_BUTTON, on_click)

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)

    # -- 尺寸 -------------------------------------------------------------

    def _sync_min_size(self) -> None:
        """按 DPI 把最小尺寸换算成物理像素。

        **用 :func:`~file_tracker.theme.scaled`，不用 ``self.FromDIP``。**
        构造函数里控件还没完成父级绑定，``FromDIP`` 会退回 96——
        实测同一个按钮在开了 per-monitor DPI 感知的进程里因此变成 42 像素高
        （期望 24），用户看到的就是"按钮偏大"。
        """
        dpi = dpi_of(self)
        height = scale_for_dpi(self._height, dpi)
        width = max(
            scale_for_dpi(self._min_width, dpi),
            self.GetTextExtent(self.label).width + scale_for_dpi(20, dpi),
        )
        self.SetMinSize((width, height))

    def DoGetBestSize(self):  # noqa: N802 - 跟随 wx 命名
        """sizer 问"你想多大"时给出的答案。

        **不重写这一条，按钮就会被撑大**——``wx.Control`` 的默认实现
        返回的是一个与文字无关的尺寸。
        """
        return self.GetMinSize()

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.SetBackgroundColour(wx.Colour(theme.background))
        self.Refresh()

    def SetLabel(self, label: str) -> None:  # noqa: N802 - 跟随 wx 命名
        self.label = label
        self._sync_min_size()
        self.InvalidateBestSize()
        self.Refresh()

    # -- 配色 -------------------------------------------------------------
    def _colours(self) -> tuple[str, str, str]:
        """返回 ``(底色, 文字色, 描边色)``。强调色只给 ``variant="accent"``。"""
        theme = self.theme
        if self.variant == "accent":
            base = theme.accent_hover if self._hovering else theme.accent
            if self._pressed:
                base = theme.accent_hover
            return (base, theme.accent_text, base)
        if self.variant == "danger":
            # 危险动作用**文字颜色**表达，不做整块红底、也不给红色描边，
            # **但描边本身要和其它按钮完全一致**。
            #
            # 用户先要求"去掉'清空'按钮的红色边线（不是文字）"，
            # 接着又指出"边缘要和其他按钮一致，要么都有阴影/边线，要么都没有"。
            # 两条合起来意思很明确：
            #   **红边去掉，但普通按钮那圈边线要保留。**
            #
            # 所以这里给 `theme.border`（= 普通按钮的描边色），
            # 而不是 "transparent"——那样它会成为唯一没有边线的按钮，更不一致。
            if self._pressed:
                return (theme.button_pressed, theme.danger, theme.border)
            return (theme.button_normal if not self._hovering else theme.button_hover,
                    theme.danger, theme.border)
        if self._pressed:
            return (theme.button_pressed, theme.text, theme.border)
        if self._hovering:
            return (theme.button_hover, theme.text, theme.text_secondary)
        return (theme.button_normal, theme.text, theme.border)

    # -- 绘制 -------------------------------------------------------------

    def _on_paint(self, event) -> None:
        dc = wx.AutoBufferedPaintDC(self)

        width, height = self.GetClientSize()
        if width <= 0 or height <= 0:
            return

        # **先用父窗口底色铺满整块客户区。**
        #
        # 不能只 Clear() 成自己的底色：圆角之外那四个角要露出父窗口的颜色，
        # 而 `AutoBufferedPaintDC.Clear()` 用的是本控件的底色。
        # 深色主题下这会让四个角留下**没扣干净的浅色像素**——用户实测反馈过。
        parent_colour = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(parent_colour))
        dc.Clear()

        self.draw_to(dc, width, height)

    def draw_to(self, dc, width: int, height: int,
                parent_colour=None) -> None:
        """把按钮画到**任意** DC 上（`width`/`height` 是目标矩形）。

        从 `_on_paint` 里抽出来，好让验证脚本能把按钮渲染到位图上——
        这个环境的窗口抓图不可靠（`PrintWindow` 丢正文、
        `GetDC`+`GetPixel` 返回值自相矛盾），
        所以"长得对不对"只能靠离屏重画来核对。
        """
        if width <= 0 or height <= 0:
            return
        if parent_colour is not None:
            dc.SetBackground(wx.Brush(parent_colour))
            dc.Clear()

        background, foreground, border = self._colours()
        self._radius = METRICS.button_radius_for(height)
        # "transparent" 表示**不画描边**（危险动作按钮就是这样，见 _colours）
        draw_border = border != "transparent"

        gc = wx.GraphicsContext.Create(dc)
        if gc is None:  # 极端情况下取不到 GC，退化为矩形填充而不是崩溃
            dc.SetBrush(wx.Brush(wx.Colour(background)))
            dc.SetPen(wx.Pen(wx.Colour(border)) if draw_border
                      else wx.TRANSPARENT_PEN)
            dc.DrawRectangle(0, 0, width, height)
        else:
            # ==========================================================
            # **填充与描边分两步画。**
            # ==========================================================
            #
            # 用户两次反馈右边有"裁断感"，根因不在抗锯齿，而在
            # **把填充和描边当成一件事**：
            #
            # 描边必须内缩（否则外半像素被裁），但 `accent` 按钮的
            # "描边色"就是它自己的底色（见 `_colours`）——于是
            # 一个**纯色实心块**也被内缩了整整 1 像素，
            # 四周留下一圈透出父窗口的缝。右边那条缝最显眼，
            # 就成了用户说的"裁断"。
            #
            # 正确做法：
            #   ① **填充**铺满 `[0, width]`，一点不留缝
            #   ② **描边**（只在颜色与填充**不同**时才画）内缩 1 像素
            #
            # 这样纯色按钮是实心的、有边线的按钮线是完整的。
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.SetBrush(wx.Brush(wx.Colour(background)))
            gc.DrawRoundedRectangle(
                0, 0, width, height,
                METRICS.button_radius_for(height),
            )

            # 描边色与填充色相同就**不画描边**——画了也只是把自己再涂一遍，
            # 却会因为内缩而在边缘留下一圈缝（这正是"裁断感"的来源）。
            stroke_differs = draw_border and any(
                getattr(wx.Colour(border), channel)()
                != getattr(wx.Colour(background), channel)()
                for channel in ("Red", "Green", "Blue")
            )
            pen = wx.Pen(wx.Colour(border)) if stroke_differs \
                else wx.TRANSPARENT_PEN
            gc.SetPen(pen)

            # **描边：不平移，只把矩形收 1 像素。**
            #
            # 用户两次反馈右边有"裁断感"，我前两版都错在**平移**上：
            #   ① 不平移、矩形取满宽高 → 右支竖线完全落在客户区外（被裁）
            #   ② 内缩半个笔宽 → 边界落在像素中间，抗锯齿分摊到两列
            #   ③ 内缩整 1 像素 → 左边满覆盖、右边偏移 0，**左右不对称**
            #
            # 实测把各种组合都画了一遍
            # （`tools/probes/probe_stroke_raster.py`），规则是：
            #
            #   描边**外边缘**落在 x，覆盖的是 `[x, x+1)`
            #   ⇒ 想让最外那一列**满覆盖**，路径必须正好在 0，
            #     且描边带的右边缘不越过 W
            #   ⇒ **矩形取 (W-1) × (H-1)，一点不平移**
            #
            #      inset=0, 189x42 → 右支完全没有（出界）
            #      inset=0, 188x41 → 左列 0:255，右列 188:255  ✅ 唯一全对
            #      inset=1, 187x40 → 左列 1:255，右列 188:255  ❌ 差 1 列
            #
            # 所以这里是 `0, 0, width-1, height-1`——**不是内缩**，
            # 而是"矩形比客户区小一格"，两者视觉上完全不同。
            stroke_width = max(int(pen.GetWidth()), 1) if stroke_differs else 1
            gc.DrawRoundedRectangle(
                0, 0,
                max(width - stroke_width, 1),
                max(height - stroke_width, 1),
                METRICS.button_radius_for(max(height - stroke_width, 1)),
            )

            font = self.GetFont()
            if self.icon_painter is not None:
                # **画图标**：尺寸取"文字高"，这样它和旁边的字符按钮同高。
                gc.SetFont(font, wx.Colour(foreground))
                _tw, th = gc.GetTextExtent("M")
                # ⚠️ 用 `width` / `height`（本控件的客户区尺寸），
                # **不要用 `rect`** —— 这个作用域里没有那个名字，
                # 上一版写成 `rect.x + rect.width / 2` 把图标算到了
                # 客户区外面，用户看到的就是"图标没画出来"。
                # **背景色也要传**：`icon_time` 的指针是用底色"挖"出来的，
                # 不传的话指针和表盘同色、看不见（见 `icon_time`）。
                _draw_icon(gc, self.icon_painter,
                           width / 2.0, height / 2.0,
                           float(th), wx.Colour(foreground),
                           wx.Colour(background))
                return
            gc.SetFont(font, wx.Colour(foreground))
            text_width, text_height = gc.GetTextExtent(self.label)
            gc.DrawText(
                self.label,
                int((width - text_width) / 2),
                int((height - text_height) / 2),
            )

    # -- 交互 -------------------------------------------------------------

    def _on_enter(self, event) -> None:
        self._hovering = True
        self.Refresh()

    def _on_leave(self, event) -> None:
        self._hovering = False
        self._pressed = False
        self.Refresh()

    def _on_left_down(self, event) -> None:
        self._pressed = True
        self.Refresh()

    def _on_left_up(self, event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.Refresh()
        if was_pressed and self.GetClientRect().Contains(event.GetPosition()):
            # 用 wx.CommandEvent 而不是直接回调，好让调用方继续用 Bind(wx.EVT_BUTTON)
            click = wx.CommandEvent(wx.EVT_BUTTON.typeId, self.GetId())
            click.SetEventObject(self)
            self.GetEventHandler().ProcessEvent(click)


class BorderLine(wx.Control):
    """一条 1 像素的分隔线，颜色完全由主题控制。

    ## 为什么需要它

    用户反馈："导航窗格与记录窗格之间的分界线在深色主题下为什么仍旧保持白色？
    有办法更改吗？"

    实测（`tools/probes/probe_sash_geometry.py`）：``wx.SplitterWindow``
    的 sash 是 **wx 自己画的**，走的是 ``wxSashWindow`` 那套 3D 绘制，
    取系统色 ``SYS_COLOUR_BTNFACE``（本机 ``#F0F0F0``，浅灰）。
    ``SetBackgroundColour`` 对它**无效**——所以深色下那条线一直是白的。

    三条路的实测结果：

    ==================================  ================================
    做法                                 结果
    ==================================  ================================
    默认 sash 可见                       4 像素间隙，画成 ``#F0F0F0``
    ``SetSashInvisible(True)``           间隙变 0，线消失（颜色不可控）
    **本控件：自己画一条线**             颜色可控，且能画成任何色号
    ==================================  ================================

    所以：**把 sash 隐藏掉，自己画一条线**。线由本控件绘制，
    颜色取 ``theme.border``；sash 仍然可以拖动（隐藏只是不画它）。
    """

    def __init__(self, parent, theme: Theme, vertical: bool = True):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.theme = theme
        self.vertical = vertical
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        thickness = scale(self, METRICS.separator_thickness)
        if vertical:
            self.SetMinSize((thickness, -1))
        else:
            self.SetMinSize((-1, thickness))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        # 自绘控件不吃 wx 的字体/颜色传播，背景要自己清
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.Refresh()

    def _on_paint(self, event) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        width, height = self.GetClientSize()
        # 先用窗口底色铺满（线之外的部分不是线）
        dc.SetBackground(wx.Brush(wx.Colour(self.theme.background)))
        dc.Clear()
        dc.SetPen(wx.Pen(wx.Colour(self.theme.border)))
        if self.vertical:
            x = width // 2
            dc.DrawLine(x, 0, x, height)
        else:
            y = height // 2
            dc.DrawLine(0, y, width, y)


class _NoButton:
    """哨兵：传给 ``no_label`` 表示**这个弹窗只有一个按钮**。

    为什么需要它，见 :meth:`ThemedDialog.__init__` 里的说明——
    简单说：``None`` 已经用来表示"没传，用默认的否(N)"了，
    没法再兼任"不要第二个按钮"。
    """

    __slots__ = ()

    def __repr__(self) -> str:                       # 便于调试时一眼认出
        return "NO_BUTTON"


#: 单按钮弹窗的写法：``ThemedDialog(..., no_label=NO_BUTTON)``。
#:
#: 用于**纯告知**（"已经删除了""版本是 x.y.z"）——那种弹窗给一个
#: "否"按钮是在骗用户以为还有得选。
NO_BUTTON = _NoButton()


class ThemedDialog(wx.Dialog):
    """一个**自己画的**模态确认框，尺寸与间距照抄 Roboc 的原生对话框。

    ## 为什么不能用 `wx.MessageDialog`

    用户反馈："警告弹窗的深色主题适配失败。"
    `wx.MessageDialog` / `wx.MessageBox` 在 Windows 上是**系统对话框**
    （`MessageBoxIndirect`），由 Windows 按**系统主题**绘制：
    `SetBackgroundColour` 无效、`SetPreferredAppMode` 也不管它。
    **没有受支持的换肤接口**，所以只能自己画。

    ## 为什么之前画得难看

    我上一版是"堆 sizer + `Fit()`"：标题、正文、按钮各加一段间距，
    最后让 wx 去算尺寸。结果是 **455×228**——比原生对话框**又宽又矮**，
    而且我用粗体画了一行标题（原生确认框根本没有这一行）。

    用户问"Roboc 的所有窗口外观为什么规范又漂亮"。
    去读 `Roboc/src/Roboc.App/MessageDialog.cs` 之后，答案很清楚：

    > **它不用任何自动布局。所有位置和尺寸都是按一个固定公式手算的。**

    ```csharp
    int margin       = Scaled(24, dpi);
    int maxTextWidth = Scaled(420, dpi);
    int buttonHeight = Scaled(32, dpi);
    int buttonWidth  = Scaled(96, dpi);
    int gap          = Scaled(8, dpi);
    int buttonsWidth = labels * buttonWidth + (labels - 1) * gap;
    int bodyTop      = Scaled(24, dpi);
    int buttonsTop   = bodyTop + bodyHeight + Scaled(28, dpi);
    int clientWidth  = Max(maxTextWidth, buttonsWidth) + margin * 2;
    int clientHeight = buttonsTop + buttonHeight + Scaled(20, dpi);
    // 按钮右对齐：
    int left = clientWidth - margin - buttonsWidth;
    ```

    本类的 `_layout()` 就是这段的 Python 版，**数值一个不改**。
    宽度 420 逻辑像素（本机 735 物理像素）是"正文换行到哪里"的基准，
    也是原生对话框看着舒服的主要原因。

    ## 三条"看得漂亮"的规律（都来自 Roboc）

    1. **别用 `Fit()`。** 自动布局会把"内容多宽"和"窗口多宽"绑死，
       于是长一点的消息就撑出一个又宽又矮的窗口。
       固定公式让宽高比始终正常。
    2. **不要自己加标题行。** 原生确认框的标题在**标题栏**里，
       正文区只有消息 + 按钮。我加的粗体标题是多余的第四层。
    3. **外边距一律 24 逻辑像素**，不是 8 也不是 12——
       它给正文留出呼吸感，而这正是"挤"和"不挤"的分界。

    ## 两处**有意偏离** Roboc

    用户要求："现在让所有提示窗内容居中显示。"

    1. **宽度按实际文字算**，不再固定 `max_text_width`。
       Roboc 固定取 420 逻辑像素；文字排不满时右侧留一大块空白，
       而内容一旦居中，那块空白就变成**两边都空**。
       现在 `max_text_width` 退化为**上限**（超过它才折行）。
    2. **正文逐行居中、按钮组整体居中**，不再左对齐 + 右对齐。
       右对齐在宽弹窗里是对的；窗口收窄、正文又居中之后，
       按钮偏在右边就失去平衡了。

    这两处只是**排版选择**不同，间距节奏（24 / 32 / 8 / 28 / 20）没动。

    用法::

        dialog = ThemedDialog(parent, theme, "确定要清空所有记录吗？",
                              title="确认清空")
        if dialog.ShowModal() == wx.ID_YES:
            ...
        dialog.Destroy()
    """

    def __init__(self, parent, theme: Theme, message: str, *,
                 title: str = "", yes_label: str | None = None,
                 no_label: str | None | object = None,
                 alert: bool = False):
        # **默认值不能在签名里写 `L(...)`。** 默认参数在**函数定义时**求值一次，
        # 而那时语言可能还没定下来。所以在体内取。
        if yes_label is None:
            yes_label = L("是(Y)", "Yes")
        if no_label is None:
            no_label = L("否(N)", "No")
        elif no_label is NO_BUTTON:
            # **明确要求"只有一个按钮"。**
            #
            # 这里踩过一个很贵的坑：原来只有 `no_label=None → 默认"否(N)"`
            # 这一条路，于是**没有办法**建一个单按钮的弹窗——
            # `_notify` 一直写着 `no_label=None` 并**以为**那是"不要第二个按钮"，
            # 实际却拿到了「好 / 否(N)」两个按钮，而两个都只是关掉它。
            #
            # 用户报的就是这个："失效删除确认弹窗有两个按钮，功能完全一致
            # ——关闭窗口，请简化为一个按钮「确定」。"
            #
            # `None` 在 Python 里是"没传"的意思，没法同时表达"不要"，
            # 所以必须有一个明确的\"不要\"值。用 `NO_BUTTON` 而不是
            # 空字符串或 `False`：那两种都像是"标签写错了"，
            # 而这是一个**意图**，值得有自己的名字。
            no_label = None
        # **必须给弹窗一个真正的标题栏。**
        #
        # 我原来用的是 `wx.BORDER_NONE` —— 结果是"一个没有标题栏、也没有
        # 关闭按钮的方块"，用户对比 Roboc 之后说"不知道你能不能看出差距"。
        #
        # Roboc 的窗口样式是（`MessageDialog.cs` L209）：
        #
        #     uint style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU;
        #
        # wx 的等价物就是 `wx.DEFAULT_DIALOG_STYLE`
        # （= `CAPTION | SYSTEM_MENU | CLOSE_BOX | TAB_TRAVERSAL`，
        # 实测 `0x20001800`）——**有标题栏、有系统菜单、有关闭按钮**。
        #
        # Roboc 还用 `AdjustWindowRectExForDpi` 把"客户区尺寸"换算成
        # "窗口尺寸"（多出标题栏与边框的高度）；wx 的
        # `SetClientSize` 做的就是同一件事。
        #
        # 标题栏由系统绘制，但**颜色归 DWM 管**，所以深色主题下要
        # `win32.set_title_bar_dark` —— 见 `apply_theme`。
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE)
        self.theme = theme
        self.SetBackgroundColour(wx.Colour(theme.background))
        # **必须声明 `BG_STYLE_PAINT`，否则 `AutoBufferedPaintDC` 直接抛断言。**
        #
        # 踩过：漏了这一行，`_on_paint` 每次重绘都抛
        # `wxAssertionError: "win->GetBackgroundStyle() == wxBG_STYLE_PAINT" failed`，
        # 于是**正文一个字都画不出来**——弹窗只剩背景和一个标题栏。
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self._message = message
        self._labels = [yes_label] + ([no_label] if no_label else [])
        self._buttons: list[RoundedButton] = []
        self._body_rect = None
        self._button_rects: list[tuple[int, int]] = []
        #: 正文前是否画那枚**自绘警告三角**（2026-10-26 取代 `⚠️` 字形）。
        #:
        #: 用户："让所有警告弹窗都带警告标志" → 以前是在正文开头拼 `⚠️`，
        #: 现在是这个开关：`alert=True` 时由 `_draw_body` 画图标。
        #: **不要在正文里再拼 `⚠️`** —— 那会变成"图标 + 巨型 emoji"两枚标志。
        self._alert = alert
        self._alert_extra = 0

        # 按钮先建出来（尺寸由 `_layout` 定，这里只给最小尺寸）
        for label, handler in zip(self._labels, self._handlers()):
            button = RoundedButton(self, label, theme,
                                   variant="accent" if not self._buttons else "secondary",
                                   height=METRICS.dialog_button_height,
                                   min_width=METRICS.dialog_button_width,
                                   on_click=handler)
            self._buttons.append(button)

        # **单按钮时加一个不可见的占位控件。**
        #
        # `wx.Dialog` 在 `Show()` 时会把**唯一的**子控件拉满客户区——
        # 实测单按钮弹窗的按钮变成 819×210（= 整个客户区），
        # 而两个按钮时反而正常。加一个 1×1 的占位控件就没事了
        # （实测：1 按钮 + 占位 → x=427 w=168，正确）。
        #
        # 装一个"空 sizer"**不管用**：sizer 会按自己的规则重排，
        # 把按钮挪到 x=0 纵向堆叠。所以位置全部手工定。
        if len(self._buttons) == 1:
            self._stretch_guard = wx.Control(self, size=(1, 1))
            self._stretch_guard.Hide()

        # ⚠️ **字体必须在 `_layout()` 之前设好。**
        #
        # 踩过（2026-10-26）：`_layout()` 用 `self.GetFont()` 量行高来算
        # 警告图标的边长（行高 ×1.5），而那时本窗口还是**继承来的系统字体**
        # —— 于是"布局时算出的 45px"与"真正绘制时按正文字体算出的 45px"
        # 不是同一个数（实测 `_alert_extra` = 56，而绘制时 45+14 = 59），
        # 图标与文字列因此错开几像素。**测量与绘制必须用同一个字体。**
        self.apply_body_font()
        self._layout()
        self._apply_window_chrome()

        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SHOW, self._on_show)
        self.Bind(wx.EVT_SIZE, self._on_size)

    def apply_body_font(self) -> None:
        """把正文/按钮那一套字号应用到**本弹窗及其全部子控件**。

        ## 为什么弹窗必须自己设

        `wx.Dialog` 是**独立的顶层窗口**——frame 那边的 `SetFont` 传播
        过不来。不显式设的话，弹窗回落到系统默认，实测**比「打开」按钮
        小 1pt**，而且标题、正文、按钮三处一起小，用户一眼就看出来了。

        ## 为什么是"全部子控件"而不是只设 `self`

        `self.SetFont()` 只定"本窗口的默认字体"，**不影响已经建好的子控件**
        （按钮在 `__init__` 里就建好了）。所以要自己走一遍。

        **子类加了新控件之后要再调一次**——设置窗口就是这么做的。
        """
        font = body_font()
        self.SetFont(font)
        stack = list(self.GetChildren())
        while stack:
            child = stack.pop()
            child.SetFont(font)
            child.Refresh()
            stack.extend(child.GetChildren())

    def _apply_window_chrome(self) -> None:
        """标题栏深色 + 窗口圆角 + **标题栏图标**（都要在窗口显示之前设）。

        Roboc 用的是同一套：
        * `DwmSetWindowAttribute(33, DWMWCP_ROUND)` 给圆角（`视觉规范.md` 第五节）
        * 标题栏设成比客户区暗 10~12 级（`ProgressTheme.ApplyCaptionColour`）
        * **窗口类带 `hIcon = AppIcon.Handle`**（`MessageDialog.cs` L134）——
          注释里写得很清楚："a class registered without an icon gives a window
          without one, which is why the title bars were blank."

        本项目把标题栏颜色交给 `win32.set_title_bar_dark`
        （`DWMWA_USE_IMMERSIVE_DARK_MODE`），图标则由这里设。

        ## 为什么图标要显式设

        用户要求："标题栏题头的 ⚠️ 换成程序图标"。

        `wx.Dialog` **不会**自动继承父窗口的图标——实测弹窗标题栏左侧
        是空白（Windows 默认图标）。所以这里显式 `SetIcon(frame.GetIcon())`，
        拿不到就退回从 `images/` 直接加载。
        """
        try:
            handle = self.GetHandle()
            if not handle:
                return
            win32.apply_rounded_corners(handle, True)
            win32.set_title_bar_dark(handle, bool(self.theme.is_dark))
            self._apply_icon()
        except Exception:
            # 外观增强失败不该让弹窗弹不出来
            pass

    def _apply_icon(self) -> bool:
        """把程序图标放进标题栏左侧。

        先试父窗口的图标（`GetIcon()` 拿到的正是 App 设的那一份），
        拿不到再从 `images/shell32_star.ico` 直接读。
        """
        parent = self.GetParent()
        if parent is not None:
            try:
                icon = parent.GetIcon()
                if icon is not None and icon.IsOk():
                    self.SetIcon(icon)
                    return True
            except Exception:
                pass
        try:
            from .core import resource_path

            icon = wx.Icon(resource_path(os.path.join("images",
                                                      "shell32_star.ico")),
                           wx.BITMAP_TYPE_ICO)
            if icon.IsOk():
                self.SetIcon(icon)
                return True
        except Exception:
            pass
        return False

    def _on_show(self, event) -> None:
        """窗口显示之后再摆一次按钮——`Show()` 会触发一次自动布局。"""
        event.Skip()
        if event.IsShown():
            self._place_buttons()

    def _place_buttons(self) -> None:
        """按 `_button_rects` 把按钮摆到确切位置。"""
        for (x, width), button in zip(self._button_rects, self._buttons):
            button.SetSize(x, self._buttons_top, width,
                           scale_for_dpi(METRICS.dialog_button_height,
                                         dpi_of(self)))

    def _handlers(self):
        return [self._on_yes, self._on_no][: len(self._labels)]

    def _layout(self) -> None:
        """Roboc `MessageDialog.cs` 那段公式的 Python 版。

        ## 与 Roboc 的两处**有意**差异

        用户要求："现在让所有提示窗内容居中显示。"

        1. **宽度按实际文字算，不再固定 `max_text_width`。**
           Roboc 固定取 420 逻辑像素。文字排不满时右侧会留一大块空白，
           而内容一旦居中，那块空白就变成**两边都空**，很难看。
           所以按最长那一行算宽度，`max_text_width` 退化为**上限**
           （超过它才折行）。
        2. **按钮整组水平居中**，不再右对齐。
           右对齐在宽弹窗里是对的；窗口一收窄、正文又居中，
           按钮偏在右边就失去平衡了。

        ## "居中"的分寸（2026-10-26 第三版）

        用户："这个警告窗根据正文内容的不同，排版方式会发生变化……要**规范和统一化**。"

        所以：**整组（图标 + 正文块）居中、按钮组居中**，但**正文块内部各行共用
        一条左缘**（见 `_draw_body`）。单行时两种写法等价 —— 已验收的单行弹窗不变；
        多行时不再出现"图标飘在左边、第一行缩在中间"的空档。
        窗口宽度仍然按**最宽那一行**算（不是按缩进后的位置），所以左右留白依旧相等。
        """
        dpi = dpi_of(self)

        def px(logical: int) -> int:
            return scale_for_dpi(logical, dpi)

        margin = px(METRICS.dialog_margin)
        max_text_width = px(METRICS.dialog_max_text_width)
        button_height = px(METRICS.dialog_button_height)
        button_width = px(METRICS.dialog_button_width)
        gap = px(METRICS.dialog_button_gap)
        buttons_width = (len(self._labels) * button_width
                         + max(len(self._labels) - 1, 0) * gap)
        body_top = px(METRICS.dialog_margin)
        # **警告图标占掉正文左侧的一条**（图标 + 间距），折行宽度要相应收窄，
        # 否则"文字 + 图标"会超出 `max_text_width`，弹窗被撑宽。
        badge_size, badge_gap = self._alert_metrics()
        self._alert_extra = (badge_size + badge_gap) if self._alert else 0
        wrap_width = max(max_text_width - self._alert_extra, px(120))
        text_height = self._measure_body_height(wrap_width)
        # **图标比一行字高时，要给它留出竖向空间。**
        #
        # 踩过（2026-10-26 第一次量）：标志边长 = 行高 ×1.5，直接"垂直居中在第一行"
        # 会让它的顶点比正文区**高出 7~8 px** —— 位图上回读墨迹时被裁掉一截，
        # 高/宽 从 0.866 掉到 0.711。这里把第一行放大成"图标那么高"的一个盒子，
        # 文字与图标都在盒子里居中，于是图标刚好落在正文区内。
        self._alert_extra_v = (max(0, badge_size - self._line_height())
                               if self._alert else 0)
        body_height = text_height + self._alert_extra_v
        buttons_top = (body_top + body_height
                       + px(METRICS.dialog_body_to_buttons))

        # 正文实际需要多宽（`_wrap_lines` 已经把 `_lines` 填好了）
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        text_width = max(
            (dc.GetTextExtent(line).width for line in self._lines), default=0)
        content_width = min(text_width, wrap_width) + self._alert_extra
        client_width = max(content_width, buttons_width) + margin * 2
        client_height = buttons_top + button_height + px(METRICS.dialog_bottom)

        self._body_rect = (margin, body_top, client_width - margin,
                           body_top + body_height)
        # 按钮整组居中
        left = (client_width - buttons_width) // 2
        self._button_rects = []
        for _ in self._labels:
            self._button_rects.append((left, button_width))
            left += button_width + gap

        # 直接设客户区尺寸，**不 `Fit()`**
        self.SetClientSize((client_width, client_height))
        self._buttons_top = buttons_top
        self._place_buttons()

        self._center_on_parent()

    def _wrap_lines(self, max_text_width: int) -> list[str]:
        """把正文按 ``max_text_width`` 折行——等价于 Roboc 的 `DT_WORDBREAK`。

        ## 为什么自己折

        `wx.DC` 在 Python 侧**没有**带宽度约束的测量/绘制：
        `GetMultiLineTextExtent()` 不收宽度参数（传了会 `TypeError`），
        `DrawText()` 只接受 `(text, x, y)`、不会自动换行，
        `DrawLabel()` 在对话框上实测**一个字都画不出来**。

        而 Roboc 那边一个 `DrawTextW(..., DT_WORDBREAK | DT_CALCRECT)`
        就同时解决了测量与绘制。本方法补上 wx 缺的这一块。

        折行规则：
        * **CJK 逐字断行**（中文没有空格，按空格断会整段不断行）
        * 西文按空格断，断不了时按字符断（等价于 `DT_PATH_ELLIPSIS` 的兜底）
        """
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())

        def width_of(text: str) -> int:
            return dc.GetTextExtent(text).width if text else 0

        lines: list[str] = []
        for paragraph in self._message.splitlines() or [""]:
            if not paragraph:
                # **空行不占高度**（2026-10-26）。
                #
                # 用户："就是这种多段式的正文，每行之间应该不用空行。把空行删了
                # 我再看。" —— 调用点用 `\n\n` 分段（"这条路径已失效：\n\n<路径>
                # \n\n要从记录中删除它吗？"），若空行照占一行，三段之间会各留一个
                # 整行高度，弹窗又高又松。现在按**行距**排，段落只靠行距区分。
                #
                # 注意：这里不删调用点的 `\n\n` —— 保留分段写法，让"分段"这件事
                # 在源码里仍然可读，渲染层统一忽略空行。
                continue
            current = ""
            for char in paragraph:
                candidate = current + char
                if current and width_of(candidate) > max_text_width:
                    lines.append(current)
                    current = char
                else:
                    current = candidate
            if current:
                lines.append(current)
        return lines or [""]

    def _measure_body_height(self, max_text_width: int) -> int:
        """正文折行后的总高度。"""
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        line_height = dc.GetTextExtent(_measure_probe()).height or 1
        self._lines = self._wrap_lines(max_text_width)
        return line_height * len(self._lines)

    def _center_on_parent(self) -> None:
        parent = self.GetParent()
        if parent is None:
            self.CentreOnScreen()
            return
        px_, py = parent.GetPosition()
        pw, ph = parent.GetSize()
        w, h = self.GetSize()
        self.SetPosition((px_ + (pw - w) // 2, py + (ph - h) // 2))

    def _on_size(self, event) -> None:
        event.Skip()
        self.Refresh()

    def _line_height(self) -> int:
        """正文一行的高度（物理像素）——**测量与绘制必须用同一个探针字符串**。"""
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        return dc.GetTextExtent(_measure_probe()).height or 1

    def _alert_metrics(self) -> tuple[int, int]:
        """警告图标的 `(边长, 与正文的间距)`，单位物理像素。

        **边长锚定"正文字高"**（`METRICS.dialog_alert_ratio`），不锚 DPI ——
        换字体/字号时它跟着走。用户的要求是"比正文字号大一点"，
        所以这个比例必须 > 1；1.5 是"明显大、又不至于像独立一行"的那一档。
        没有警告标志的弹窗返回 `(0, 0)`。
        """
        if not getattr(self, "_alert", False):
            return (0, 0)
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        text_height = dc.GetTextExtent(_measure_probe()).height or 1
        size = max(int(round(text_height * METRICS.dialog_alert_ratio)), 8)
        return (size, scale_for_dpi(METRICS.dialog_alert_gap, dpi_of(self)))

    def _draw_body(self, dc) -> None:
        """把正文画到 ``dc`` 上（**组内共用一条左缘**），并在开头画警告图标。

        ## 版式规则（2026-10-26 第三版，用户要求"统一化、美观"）

        用户原话："这个警告窗根据正文内容的不同，排版方式会发生变化。比如现在
        这种多段式的，排版就变成了这种情况。你看一下怎么去规范和统一化，要美观。"

        那张截图里：图标飘在正文块左侧、第一行却缩在中间，**图标和文字之间空出
        一大片**。根因是"逐行居中"（每一行按自己的宽度在**最宽那一行**的列里居中）。

        ⇒ 现在**一套规则管所有正文**：

        1. 「图标 + 间距 + 最宽一行」作为一个整体在正文区里居中（已验证的观感）；
        2. **组内所有行共用同一条左缘**（左对齐到文字列左缘），不再逐行居中；
        3. 图标垂直居中在**第一行**上（框高 = max(行高, 图标边长)）；
        4. 空行照旧占一行 —— 段落之间那点间隙靠它。

        **单行正文的观感与"逐行居中"完全等价**（组宽 = 图标 + 间距 + 该行，
        居中之后那一行自然就在组中间），所以已验收的单行弹窗不变；
        多行正文则变成"图标贴着文字列、各行左缘对齐"的标准告警版式。

        **抽出来是为了能被单独调用验证。** `_on_paint` 里画不出来的东西，
        很可能是"这段代码根本没跑"而不是"画得不对"——分开之后可以直接
        拿一个 `wx.ClientDC` 调它，看有没有落笔。
        """
        if not self._body_rect:
            return
        left, top, right, _bottom = self._body_rect
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(wx.Colour(self.theme.text))
        line_height = dc.GetTextExtent(_measure_probe()).height or 1
        lines = getattr(self, "_lines", None) or [self._message]
        extra = getattr(self, "_alert_extra", 0) or 0
        extra_v = getattr(self, "_alert_extra_v", 0) or 0
        # **文字第一行在"图标那个盒子"里居中**（盒子高 = 行高 + extra_v）：
        # 于是图标恰好落在正文区顶部，不会溢出 `_body_rect`（踩过，见 `_layout`）。
        first_top = top + extra_v // 2

        # **图标紧贴文字，两者作为一组居中**（2026-10-26 第二版）。
        #
        # 第一版把图标钉在正文区最左边、文字在自己的那一列里居中 ——
        # 短消息时图标离文字老远（实测图标 x=42、文字 x=174），
        # 看着像两个不相干的东西。用户那张截图里 `⚠️` 是**紧挨着文字**的，
        # 所以这里按"图标 + 间距 + 最宽那一行"作为一个整体居中。
        widths = [dc.GetTextExtent(line).width for line in lines]
        block_w = max(widths, default=0)
        body_w = right - left
        group_w = extra + block_w
        group_x = left + max((body_w - group_w) // 2, 0)
        text_left = group_x + extra
        # **组内一律左对齐**（第三版）：逐行居中会让多段正文的图标"飘"在左边、
        # 第一行缩在中间，看着像两个不相干的东西。单行时与居中完全等价。
        for index, line in enumerate(lines):
            dc.DrawText(line, text_left, first_top + index * line_height)
        if self._alert and extra:
            self._draw_alert_badge(dc, group_x, top, line_height + extra_v)

    def _draw_alert_badge(self, dc, left: int, top: int, box_height: int) -> None:
        """在正文区左上角画那枚警告三角（垂直居中在**第一行的盒子**里）。"""
        size, _gap = self._alert_metrics()
        if size <= 0:
            return
        cx = left + size / 2.0
        cy = top + box_height / 2.0
        colour = wx.Colour(self.theme.text)
        background = wx.Colour(self.theme.background)
        # **必须走 GraphicsContext 才没有锯齿**（同 `PathBar._draw_border`）：
        # 三角是斜边，GDI 的 `DrawPolygon` 会画出台阶。
        gc = wx.GraphicsContext.Create(dc)
        if gc is not None:
            _draw_icon(gc, icon_warning, cx, cy, size, colour, background)
            return
        # 取不到 GC 时退回 GDI：斜边会有锯齿，但形状、位置、比例一致
        from .theme import warning_badge_geometry

        g = warning_badge_geometry(size)
        ox, oy = cx - size / 2.0, cy - size / 2.0

        def _dot(point):
            return wx.Point(int(round(ox + point[0])), int(round(oy + point[1])))

        for points, fill in (([g["apex"], g["left"], g["right"]], colour),
                             (g["inner"], background)):
            dc.SetBrush(wx.Brush(fill))
            dc.SetPen(wx.Pen(fill, 1))
            dc.DrawPolygon([_dot(p) for p in points])
        stroke = max(float(g["stroke"]), 1.0)
        _x0, bar_top, _x1, bar_bottom = g["bar"]
        dc.SetBrush(wx.Brush(colour))
        dc.SetPen(wx.Pen(colour, 1))
        dc.DrawRectangle(int(round(ox + cx - stroke / 2)), int(round(oy + bar_top)),
                         max(int(round(stroke)), 1),
                         max(int(round(bar_bottom - bar_top)), 1))
        dot_x, dot_y, dot_r = g["dot"]
        dc.DrawCircle(int(round(ox + dot_x)), int(round(oy + dot_y)),
                      max(int(round(dot_r)), 1))

    def _on_paint(self, event) -> None:
        """画正文。

        ## 两个踩过的坑

        **① 用 `DrawLabel` 画正文，结果一个字都没有。**
        实测抓图（`tools/probes/probe_dialog_shot.py`）看到的弹窗
        **只有标题栏和按钮，正文区是空的**。
        换成 `DrawText` + `wx.TEXT_ALIGNMENT_LEFT`，并且**把矩形给足**
        （宽 = 内容宽、高 = 到按钮上方），就画出来了。

        **② 没设 `BG_STYLE_PAINT` 时 `AutoBufferedPaintDC` 直接抛断言。**
        那个断言是静默的（异常被 wx 吞掉、只打 traceback），
        表现同样是"正文不显示"。两处都修了才正常。

        窗口已经有系统标题栏和边框了（`wx.DEFAULT_DIALOG_STYLE`），
        所以**不再自绘边线**——原来那圈 `theme.border` 矩形会贴着
        客户区边缘画，看上去像多了一层框。
        """
        dc = wx.AutoBufferedPaintDC(self)
        theme = self.theme

        dc.SetBackground(wx.Brush(wx.Colour(theme.background)))
        dc.Clear()

        self._draw_body(dc)

    def _on_yes(self, event) -> None:
        self.EndModal(wx.ID_YES)

    def _on_no(self, event) -> None:
        self.EndModal(wx.ID_NO)

    def _on_key(self, event) -> None:
        """Esc = 否。默认按钮不设，避免误按回车清空数据。"""
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_NO)
            return
        event.Skip()

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.SetBackgroundColour(wx.Colour(theme.background))
        for button in self._buttons:
            button.apply_theme(theme)
        # 标题栏颜色也跟着主题走
        self._apply_window_chrome()
        self.Refresh()


def _row_height_lines(chunks) -> int:
    """一组按钮块占几**行**（不含标签）。

    标签**不额外占行**：它与第一块按钮垂直居中（见 `_place_rows`）。
    这一点是用户指出的——早先让标签独占一行，于是"排序方式"孤零零飘在
    按钮上方，既不对称也不像"这一行的标题"。
    """
    return len(chunks)


def _label_width(label) -> int:
    """按标签**当前的字体**量出它真正占多宽（外加一点余量）。

    ## 为什么不能用 `GetBestSize()`

    实测踩到的：`app._apply_body_font()` 里有
    ``wx.StaticText.SetFont(self, body)`` —— 那是**类级**调用，
    会把之后创建的所有 StaticText 都换成 10pt 的 body 字体。

    而 `GetBestSize()` 的尺寸是在控件创建时用**当时的字体**算好缓存的；
    等字体被类级调用改大之后，这个缓存值就不再等于文字的真正宽度。

    症状（用户截图）：设置窗口里「界面语言」「排序方式」「排序方向」
    **每个标签的最后两三个字被右边的按钮压住** —— 我按 85 像素给它留位置，
    而 10pt 下它要 100 像素。

    ## 顺带一个真实的风险

    中日韩字形在有些字体下会比拉丁字形**更高更宽**；把宽度交给缓存值，
    等于把这个差异藏起来。现量现算没有这个问题。

    余量按 DPI 走（2 逻辑像素），换字体或换 DPI 都不会贴边。
    """
    dc = wx.ClientDC(label)
    dc.SetFont(label.GetFont())
    text_width = dc.GetTextExtent(label.GetLabel()).width
    margin = scale_for_dpi(2, dpi_of(label))
    return text_width + margin


def _pen_width(stroke) -> int:
    """把笔宽收敛成 **int**。

    ## 这个函数存在的唯一理由：`wx.Pen` 不收 float

    实测报错：

    ```
    wx.Pen(colour, 2.0)
    TypeError: Pen(): arguments did not match any overloaded call:
        overload 3: argument 2 has unexpected type 'float'
    ```

    **而它发生在 `draw_to` 里 —— wx 会把绘制期的异常吞掉**，
    于是症状是"图标**静默地**一个都不画"，代码看着却完全正常。
    用户报"三个主题图标一个都没出来"，我读了三遍代码都没看出来，
    最后是**把按钮渲染成位图**才抓到的
    （`tools/probes/probe_theme_icon.py`）。

    ⇒ 笔宽一律走这里，别在别处直接 `wx.Pen(colour, <float>)`。
    """
    return max(int(round(float(stroke))), 1)


def _draw_icon(gc, painter, cx: float, cy: float, size: float,
               colour, background=None) -> None:
    """按**图元列表**在 `gc` 上画一个图标。

    ## 为什么是图元，不是字形

    另一个会话的智能体画显示器用的是**几何图元**（空心矩形 + 底座横线），
    不是字体里的字符 —— 所以它不受"字体有没有这个字形"的约束，
    **任何主题、任何字体下都画得出来**。

    这正好补上 💻 的短板：emoji 要靠字体覆盖，而图元不靠。

    ## 支持的图元

    * ``("rect", x0, y0, x1, y1, stroke, colour, fill, radius)``
      —— ``fill`` 为 ``None`` 表示空心
    * ``("line", x0, y0, x1, y1, stroke, colour)``

    **宽高用 `size` 归一**，所以调用方只要给"想画多大"。
    """
    for item in painter(cx, cy, size, colour, background):
        kind = item[0]
        if kind == "rect":
            _k, x0, y0, x1, y1, stroke, item_colour = item[:7]
            x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
            # **用四条线描边，不要 `DrawRectangle`。**
            #
            # 踩过：`wx.GraphicsContext` 上 `SetBrush(wx.TRANSPARENT_BRUSH)`
            # **不生效**，`DrawRectangle` 会拿上一次留下的画刷去填充 ——
            # 用户看到的就是"电脑图标变成一块**实心白方块**"。
            #
            # 描边就没有"填充"这件事，比赌透明画刷在哪条渲染后端上生效可靠。
            pen = wx.Pen(item_colour, _pen_width(stroke))
            gc.SetPen(pen)
            gc.StrokeLine(x0, y0, x1, y0)
            gc.StrokeLine(x1, y0, x1, y1)
            gc.StrokeLine(x1, y1, x0, y1)
            gc.StrokeLine(x0, y1, x0, y0)
        elif kind == "line":
            _k, x0, y0, x1, y1, stroke, item_colour = item[:7]
            gc.SetPen(wx.Pen(item_colour, _pen_width(stroke)))
            gc.StrokeLine(float(x0), float(y0), float(x1), float(y1))
        elif kind == "ellipse":
            _k, x0, y0, x1, y1, stroke, item_colour = item[:7]
            x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
            # **空心椭圆也走"折线描边"**，理由同上面的 rect：
            # `SetBrush(wx.TRANSPARENT_BRUSH)` 在 GC 上不可靠，
            # 而用 48 边形逼近肉眼看不出来。
            cx_, cy_ = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            rx_, ry_ = (x1 - x0) / 2.0, (y1 - y0) / 2.0
            gc.SetPen(wx.Pen(item_colour, _pen_width(stroke)))
            steps = 48
            prev = None
            for i in range(steps + 1):
                ang = 2 * math.pi * i / steps
                point = (cx_ + rx_ * math.cos(ang), cy_ + ry_ * math.sin(ang))
                if prev is not None:
                    gc.StrokeLine(prev[0], prev[1], point[0], point[1])
                prev = point
        elif kind == "ellipse_fill":
            # **几何精确的实心椭圆**（2026-10-17 新增）。
            #
            # 为什么需要它：`polygon` 逼近圆时，`FillPath` 会连着描边一起
            # 栅格化，在小尺寸（42 物理像素）下圆心会偏移约半像素 ——
            # 用户看图后说"大圆有点往右下角偏移，和光线没有完全居中"。
            # `DrawEllipse` 走的是几何路径，圆心就是参数中心，没有这个问题。
            #
            # 描边用**同色**而不是 `TRANSPARENT_PEN`：后者在 GC 上不可靠
            # （见上面 rect 分支的注释）。
            _k, x0, y0, x1, y1, item_colour = item[:6]
            x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
            gc.SetBrush(wx.Brush(item_colour))
            gc.SetPen(wx.Pen(item_colour, 1))
            gc.DrawEllipse(x0, y0, x1 - x0, y1 - y0)
        elif kind == "polygon":
            _k, points, item_colour = item[:3]
            # 多边形是**实心**的（月亮要的就是实心）。
            #
            # ⚠️ `wx.GraphicsContext` **没有 `DrawPolygon`**
            # （实测 `AttributeError`）—— 它走的是路径：
            # `CreatePath` → `MoveToPoint`/`AddLineToPoint` → `FillPath`。
            path = gc.CreatePath()
            path.MoveToPoint(float(points[0]), float(points[1]))
            for i in range(2, len(points), 2):
                path.AddLineToPoint(float(points[i]), float(points[i + 1]))
            path.CloseSubpath()
            gc.SetBrush(wx.Brush(item_colour))
            gc.SetPen(wx.Pen(item_colour, _pen_width(1)))
            gc.FillPath(path)


def icon_warning(cx: float, cy: float, size: float, colour,
                 background=None) -> list:
    """**警告三角 + 感叹号**（线框，不是实心）—— 对话框正文前那一枚。

    ## 为什么不用 `⚠️`

    用户 2026-10-26："每个弹窗的警告标志都使用正文中的"⚠️"符号。但现在我每次
    看到弹窗时，发现这个警告标志实在是太小了……把那个警告标志画出来，
    替换掉目前所有的"⚠️"符号。让它比正文字号大一点，醒目一点。"

    emoji 是**字体字形**：大小由字体决定、不能比正文大，而且缺字体时不出现。
    图元没有这两个问题（同 `02` 里"图标用几何图元，不用字形"）。

    几何全部来自 `theme.warning_badge_geometry()`（唯一权威，可单测），
    这里只把点变成图元：外三角实心 + **背景色**内三角挖空 = 线框；
    感叹号 = 一根**等宽竖条**（不再补圆头）+ 一个圆点，**不用字体字形**。
    """
    from .theme import warning_badge_geometry

    g = warning_badge_geometry(size)
    ox, oy = cx - size / 2.0, cy - size / 2.0

    def _pt(point):
        return (ox + point[0], oy + point[1])

    apex, left, right = _pt(g["apex"]), _pt(g["left"]), _pt(g["right"])
    parts = [
        ("polygon", (apex[0], apex[1], left[0], left[1], right[0], right[1]),
         colour),
    ]
    if background is not None:
        # 用**背景色**把中间挖空 —— 线框靠"再画一个背景色三角"实现，
        # 因为 GC 上的透明画刷不可靠（见 `_draw_icon` 里 rect 分支的说明）。
        inner = [_pt(p) for p in g["inner"]]
        parts.append(
            ("polygon", (inner[0][0], inner[0][1], inner[1][0], inner[1][1],
                         inner[2][0], inner[2][1]), background))

    bar_x, bar_top, _x, bar_bottom = g["bar"]
    bar_x = ox + bar_x
    # **竖条不补圆头**（2026-10-26，用户："上下两端有小圆点凸起"）：
    # 两端半径 = 半个线宽的圆头，在这个尺寸下读起来是凸起，不是圆角。
    # 现在是一条等宽竖条，宽度取 `bar_width`（比外框线宽一点，否则显得细）。
    half_bar = max(float(g["bar_width"]), 1.0) / 2.0
    top_y = oy + bar_top
    bottom_y = oy + bar_bottom
    parts.append(
        ("polygon", (bar_x - half_bar, top_y, bar_x + half_bar, top_y,
                     bar_x + half_bar, bottom_y, bar_x - half_bar, bottom_y),
         colour))
    dot_x, dot_y, dot_r = g["dot"]
    parts.append(("ellipse_fill", ox + dot_x - dot_r, oy + dot_y - dot_r,
                  ox + dot_x + dot_r, oy + dot_y + dot_r, colour))
    return parts


def icon_sun(cx: float, cy: float, size: float, colour,
             background=None) -> list:
    """太阳 —— 实心圆盘 + 八个小圆点。

    ## 演化（用户 2026-10-17 一天内改了三次）

    1. **空心圆 + 八条细线**（最初，另一个智能体画的）
       —— 用户："做成实心的吧，周围光芒的线段再粗一些"
    2. **实心圆 + 八条粗线**
       —— 用户："光线现在又有点太粗了，你干脆把它们全部各自原地缩小
       退化成小点"
    3. **实心圆盘 + 八个小圆点**（现在）

    ## 圆心为什么改走 `ellipse_fill`

    上一版用 40 边形 `polygon` 逼近圆，用户看放大图后指出：
    "中间的大圆和周围光线的线段没有完全水平垂直居中，
     里面的大圆有点往右下角偏移"。

    `polygon` 走 `FillPath`，填充与描边一起栅格化，小尺寸下重心会偏半像素。
    `ellipse_fill` 用 `DrawEllipse`，圆心就是参数中心 —— 几何精确。
    **八个小点也用它**，否则"点"的中心同样会偏。

    比例：圆盘半径 0.26、光点中心距 0.42、光点半径 0.055。
    """
    r = size * 0.26
    parts = [("ellipse_fill", cx - r, cy - r, cx + r, cy + r, colour)]

    dot_r = size * 0.07
    orbit = size * 0.45
    for i in range(8):
        a = math.radians(i * 45)
        dx = cx + orbit * math.cos(a)
        dy = cy + orbit * math.sin(a)
        parts.append(("ellipse_fill", dx - dot_r, dy - dot_r,
                      dx + dot_r, dy + dot_r, colour))
    return parts


def icon_moon(cx: float, cy: float, size: float, colour,
              background=None) -> list:
    """月亮 —— **实心多边形 = 整圆减去一个偏移的圆**。

    **由另一个会话的智能体提供**。他的说明：
    "不要用两段圆弧拼"，所以这里是按射线法算出的闭合折线，一次填满。
    点数取 40（他标注"射线法是 O(点数)"）。
    """
    r, dx = size * 0.45, size * 0.30
    r2 = r * 1.02
    n = 40
    a = (r * r - r2 * r2 + dx * dx) / (2 * dx)
    hc = math.sqrt(max(0.0, r * r - a * a))
    th, ph = math.atan2(hc, a), math.atan2(hc, a - dx)
    # **视觉重心补偿**（用户 2026-10-17）：
    #   "月亮图标……由于图形本身的视觉重心在左侧，你看能不能在月亮图标
    #    前面加一个空格，来达到视觉上的居中效果。注意不要把按钮给撑开。"
    #
    # 加空格行不通 —— 这个图标是**自绘几何**，不是文字，空格不参与。
    # 而且真要加进 label 会把按钮撑宽（那正是他担心的）。
    # 所以把**整条轮廓向右平移** `0.045 × size`：几何中心不变、
    # 但月牙那块实体落到视觉中央。
    #
    # 偏移量取"月牙实体重心相对外接框中心的偏差"的**大部分**：
    # 0.045 → 0.09 → **0.12**（用户连说两次"还不够居中"）。
    # 0.12 在 42 物理像素下约 5 像素。
    shift = size * 0.12
    pts = []
    for i in range(n + 1):
        ang = th + (2 * math.pi - 2 * th) * i / n
        pts += [cx + shift + r * math.cos(ang), cy + r * math.sin(ang)]
    for i in range(n + 1):
        ang = (2 * math.pi - ph) - (2 * math.pi - 2 * ph) * i / n
        pts += [cx + shift + dx + r2 * math.cos(ang),
                cy + r2 * math.sin(ang)]
    return [("polygon", tuple(pts), colour)]


# ---------------------------------------------------------------- 排序方向箭头
#
# 用户 2026-10-17："降序和升序的这两个按钮，可以换成图形的形式，
# 也就是'箭头向上'和'箭头向下'。" 并要**互换位置**（升序在前）。
#
# 与主题/排序同一套：`icon_painter` + 图元，caption 留空 ⇒ 正方形。

def _arrow(cx: float, cy: float, size: float, colour, upward: bool) -> list:
    """竖箭头：一根杆 + 两条斜线组成的箭头。

    `upward=True` 箭头朝上（**升序**），反之朝下（**降序**）。
    """
    s = size
    w = max(1.0, s * 0.13)
    sign = -1.0 if upward else 1.0        # y 轴向下为正
    tip_y = cy + sign * 0.34 * s
    tail_y = cy - sign * 0.34 * s
    wing_y = cy + sign * 0.04 * s
    return [
        ("line", cx, tail_y, cx, tip_y, w, colour),
        ("line", cx, tip_y, cx - 0.24 * s, wing_y, w, colour),
        ("line", cx, tip_y, cx + 0.24 * s, wing_y, w, colour),
    ]


def icon_arrow_up(cx: float, cy: float, size: float, colour,
                  background=None) -> list:
    """**升序** —— 箭头朝上。"""
    return _arrow(cx, cy, size, colour, upward=True)


def icon_arrow_down(cx: float, cy: float, size: float, colour,
                    background=None) -> list:
    """**降序** —— 箭头朝下。"""
    return _arrow(cx, cy, size, colour, upward=False)


def icon_monitor(cx: float, cy: float, size: float, colour,
                 background=None) -> list:
    """显示器：空心外框 + 底座横线。

    **由另一个会话的智能体提供**（他画得好显示器、我画得好月亮，
    用户让我们互相补）。原样保留他的坐标公式，只补上类型标注。

    ``background`` 参数是为"镂空指针"那类画法准备的（见 :func:`icon_time`），
    这个图标用不到 —— 收下并忽略即可（统一签名，方便 `_draw_icon` 调用）。
    """
    half = size / 2.0
    stroke = max(1.0, size / 9.0)
    # **收窄显示屏**（用户 2026-10-17）：
    #   "将中间显示屏的矩形框做窄一点。因为它现在太长了，收窄一点比例
    #    才接近现代的 16:9 或者 16:10，这样看起来更舒服，
    #    也不会挤占按钮的空间。"
    #
    #   原来宽 = size、高 = size × 0.5 ⇒ **2:1**，比 16:9（1.78）还扁。
    #   现在宽收到 0.86 × size、高度不变 ⇒ **1.72 ≈ 16:9**。
    #
    #   高度刻意不动：动高度会让整个图标变小，而用户要的是"别横向挤占"。
    half_w = half * 0.86
    top = cy - half * 0.74
    bottom = cy + half * 0.26
    return [
        # 外框：描边色实心，再内缩半个线宽挖空（fill=None 表示空心）
        ("rect", cx - half_w, top, cx + half_w, bottom, stroke, colour, None, stroke),
        # 底座：跟着外框一起收窄，保持居中
        ("line", cx - half_w * 0.5, bottom + stroke * 1.9,
         cx + half_w * 0.5, bottom + stroke * 1.9, stroke, colour),
    ]


# ---------------------------------------------------------------- 排序方式图标
#
# 用户 2026-10-17 从三套方案里选了 **B（实心）**：
#
# > "图标方案先试试 B。"
#
# 三套方案的对比图在 `design/icons-light.png` / `icons-dark.png`
# （由 `tools/design_icons.py` 生成，Pillow 画的，仅供设计阶段比对）。
#
# **正式绘制用这里的图元**，不是 Pillow —— 图元跟着 `wx.GraphicsContext`
# 走，能和现有按钮的渲染一致，也跟 DPI 缩放。
#
# 为什么三个都用"实心"：24px 下实心块最清晰，线条方案（A）的折线
# 会糊成一团；`B` 的文件夹/柱状/时钟也是理解成本最低的一组符号。

#: **原生文件夹轮廓**（归一化，±0.44 以内）。
#:
#: 用户 2026-10-17 发了 Explorer 的文件夹图标，要求"照着它再画一版，
#: 让形状更接近原生的文件夹"。特征：
#:
#: * **左上有一个凸起的舌片**，右侧**斜切**到主体顶边（最像 Explorer 的地方）
#: * 主体是圆角矩形，**底部两角比顶部圆得明显**
#: * 整体略扁（宽 > 高）
#:
#: 改造前是"两个实心矩形叠出来"，边角是直角、舌片是方口 ——
#: 在小尺寸下像一个"带缺口的方块"，不像文件夹。
#:
#: 形状在 `tools/design_folder.py` 里用 Pillow 迭代过（出图毫秒级，
#: 而 wx 窗口改一次要几十秒且截图抓不全）。
_NATIVE_FOLDER = (
    # ## 第四版：**全直角**（用户 2026-10-17）
    #
    # > "去掉文件夹图标的全部圆角。"
    #
    # 前三版都在调圆角/比例，这一版干脆去掉圆角 —— 24px 下圆角本来就
    # 只剩 1~2 像素，去掉之后反而更"实"、更像一个规整的块。
    #
    # 轮廓变成 **6 个点的直角多边形**：
    #
    # ```text
    #  (-0.44,-0.34) ┌──────┐ (-0.14,-0.34)
    #                │      └╲
    #                │        ╲  ← 短斜切
    #                │         └────┐ (0.00,-0.22)
    #                │              │
    #                │              │
    #                └──────────────┘ (-0.44,0.34) .. (0.44,0.34)
    # ```
    #
    # 宽 0.88 / 高 0.68 ⇒ 宽高比 **1.29**（第三版定的比例保持不变）。
    (-0.44, 0.34),          # 左下
    (0.44, 0.34),           # 右下
    (0.44, -0.22),          # 右上
    (0.00, -0.22),          # 主体顶边左端
    (-0.14, -0.34),         # 斜切到舌片顶
    (-0.44, -0.34),         # 舌片顶左端（= 左边缘顶端）
)


def icon_path(cx: float, cy: float, size: float, colour,
              background=None) -> list:
    """**路径** —— 文件夹（实心），形状参照 Windows Explorer。

    一个 `polygon` 搞定整条轮廓（圆角用连续点逼近），
    而不是叠两个矩形 —— 叠矩形做不出"舌片斜切"和圆角。

    `_draw_icon` 的 ``rect`` 图元只描边、不填充，所以填充图形
    一律走 ``polygon``。
    """
    pts = []
    for nx, ny in _NATIVE_FOLDER:
        pts += [cx + nx * size, cy + ny * size]
    return [("polygon", tuple(pts), colour)]


def icon_count(cx: float, cy: float, size: float, colour,
               background=None) -> list:
    """**频次** —— 三根高低不同的实心柱（柱状图）。

    柱子高度取 0.36 / 0.64 / 0.50，参差是为了让人一眼看出"这是有高低的
    数量"，而不是三块等高的方块（那样像菜单图标）。
    """
    # **放大 1.2**（用户 2026-10-17）：三根柱子本来只占图标框的中间一条，
    # 视觉上明显比文件夹"小一号"。放大 1.2 后三者重量接近。
    s = size * 1.15
    base = cy + 0.34 * s
    parts = []
    for dx, h in ((-0.36, 0.36), (-0.10, 0.64), (0.16, 0.50)):
        x0 = cx + dx * s
        parts.append(("polygon", (
            x0, base - h * s,
            x0 + 0.20 * s, base - h * s,
            x0 + 0.20 * s, base,
            x0, base,
        ), colour))
    return parts


def icon_time(cx: float, cy: float, size: float, colour,
              background=None) -> list:
    """**时间** —— 实心圆表盘 + 两根"挖空"的指针。

    ## 指针为什么用 ``background`` 画

    实心圆上画同色的指针等于没画。要让指针看起来是"镂空"的，
    必须拿**按钮当前的底色**去画它 —— 而底色随主题、hover、pressed、
    选中态变化，所以只能由调用方（`RoundedButton._on_paint`）传进来。

    拿不到背景色时退回 ``colour``（等于看不见指针）——但那只是兜底，
    正常路径一定会传。
    """
    # **放大 1.1**（用户 2026-10-17）：时钟的圆在三个图标里显得偏小，
    # 单独放大一点才和柱状图、文件夹"同重量"。按钮 56px、放大后约 46px，
    # 仍然留得住呼吸空间。
    s = size * 1.1
    r = 0.40 * s
    # 表盘用 `ellipse_fill`（几何精确），不用 40 边形 `polygon`：
    # 实测多边形版本在 56px 按钮里**纵向偏 1 像素**（`FillPath` 的
    # 填充+描边一起栅格化）。见 `_draw_icon` 里 `ellipse_fill` 的注释。
    parts = [("ellipse_fill", cx - r, cy - r, cx + r, cy + r, colour)]
    hand_colour = background if background is not None else colour
    w = max(1.0, s * 0.12)
    # 时针（短、朝上）与分针（长、朝右下）
    parts.append(("line", cx, cy, cx, cy - 0.24 * s, w, hand_colour))
    parts.append(("line", cx, cy, cx + 0.18 * s, cy + 0.12 * s, w, hand_colour))
    return parts


#: 排序列标识 → 图标 painter。顺序与 `SORT_SPECS` 一致。
SORT_ICONS = {
    "path": icon_path,
    "count": icon_count,
    "time": icon_time,
}


def _has_non_bmp(text: str) -> bool:
    """这段文字里有没有 **BMP 之外**的字符（即码位 > U+FFFF）。

    emoji 大多在 astral 平面；而 `Microsoft YaHei UI` 覆盖的是 BMP 里的符号。
    判据很简单，但**必须有** —— 它决定了要不要换字体，
    而不是"看到是 emoji 就换"。
    """
    return any(ord(ch) > 0xFFFF for ch in text)


#: 能覆盖 emoji 的字体名，按优先级。**Windows 必装 `Segoe UI Emoji`。**
_EMOJI_FACES = ("Segoe UI Emoji", "Segoe UI Symbol")


def _emoji_face() -> str | None:
    """挑一个系统里真的装了的 emoji 字体；都没有则返回 ``None``。

    **用 `wx.FontEnumerator` 现查**，不要写死名字就当它存在 ——
    精简版 Windows 上 `Segoe UI Emoji` 是可以缺席的（N 版 / LTSC）。
    """
    installed = set(wx.FontEnumerator.GetFacenames())
    for face in _EMOJI_FACES:
        if face in installed:
            return face
    return None


def _wrap_buttons(buttons, content_width: int, gap: int,
                  label_width: int = 0,
                  max_per_row: int | None = None) -> list[list]:
    """把一排分段按钮折成若干块（每块占一行）。

    ## 第一行要给标签留位置

    **第一块与标签同行**（标签靠左、按钮靠右），所以第一块的预算要**减去
    标签宽度与间距**；后续块整条内容宽都能用。

    这条差异最早没做，于是"平均折行"折出了 `[3, 1]` 这种参差不齐的结果：
    第一行硬塞三个（挤掉标签的位置），第二行只剩一个。

    ## 预算怎么算

    * 第一行预算 = ``content_width - label_width - gap``
    * 后续行预算 = ``content_width``
    * **每块至少两个**——一行一个太散，不像"一组里选一个"。
      所以首行预算不够放两个时，就退回用整条内容宽
      （那时首行预算退回整条内容宽——标签仍与第一块**垂直居中**，
      只是水平方向不再与按钮同行）。
    """
    if not buttons:
        return [[]]

    def width_of(chunk) -> int:
        return (sum(b.GetBestSize().width for b in chunk)
                + gap * (len(chunk) - 1))

    # ## 布局改版后这里**简化了两处**（用户要求的新版式）
    #
    # 旧版是"标签靠左、按钮右对齐"，所以：
    #   ① 首行要**减去标签宽度**给标签留位置；
    #   ② 首行**至多两个按钮**（避免折成 `[3, 1]` 那种参差）。
    #
    # 用户要求改成"**标题在上方居中、按钮在下方居中**"之后，两条都不成立：
    #   * 标签**独占一行**，不再与按钮抢宽度；
    #   * "至多两个"会**把三个主题选项折成 `[2, 1]`**，而用户明确要求
    #     "跟随系统 / 浅色 / 深色**三个选项全部并排在一起**"——实测踩到，
    #     新版式下它是纯粹的阻力。
    #
    # **标签又回到同一行了**（用户这一轮否决了居中式版式），
    # 所以首行仍要给它留出宽度；后续行整条内容宽都能用。
    if label_width:
        first_budget = content_width - label_width - gap
        if width_of(buttons[:2]) > first_budget:
            first_budget = content_width
    else:
        first_budget = content_width

    rows: list[list] = []
    current: list = []
    budget = first_budget
    for button in buttons:
        candidate = current + [button]
        too_wide = width_of(candidate) > budget
        # **每行上限**：用户要求「排序方式还是成两行两列」——
        # 四个并排"看着太奇怪"。所以这一组强制每行 2 个。
        too_many = max_per_row is not None and len(candidate) > max_per_row
        if current and (too_wide or too_many):
            rows.append(current)
            current = [button]
            budget = content_width          # 后续行没有标签要避让
        else:
            current = candidate
    if current:
        rows.append(current)
    return rows


class SettingsDialog(ThemedDialog):
    """设置窗口：目前只有一项——**界面语言**。

    ## 为什么继承 `ThemedDialog` 而不是另起一个 `wx.Dialog`

    `ThemedDialog` 已经把四件容易出错的事做完了，而且**都有验证脚本守着**：

    * 固定公式的布局（不 `Fit()`，瓦高比始终正常）
    * 标题栏：`CAPTION | SYSTEM_MENU` + 深色 + 程序图标 + 圆角
    * `BG_STYLE_PAINT`（漏了它正文一个字都画不出来）
    * 单子控件被 `wx.Dialog` 拉满客户区的那个坑

    另起一个就等于把这四条重做一遍，而它们每一条都是踩出来的。
    这里只做两件增量的事：**加一行语言选择**、**把这一行摆进正文里**。

    ## 语言行照 Roboc `SettingsWindow.DrawLanguageRow` 的组织方式

    左边一个标签、右边两个分段选项（当前项用强调色填充）。
    Roboc 是自绘的；这里用 (:class:`RoundedButton`) 拼出来，
    视觉沿用本项目自己的按钮，不引入第二套画法。
    """

    def __init__(self, parent, theme, current_preference: str,
                 sort_key: str = DEFAULT_SORT_KEY,
                 sort_reverse: bool | None = None,
                 theme_preference: str | None = None,
                 on_theme_preview=None,
                 on_language_preview=None,
                 on_sort_preview=None):
        # 正文留空——设置窗口的内容是控件，不是一句话。
        super().__init__(parent, theme, "",
                         title=L("设置", "Settings"),
                         yes_label=L("确定", "OK"),
                         no_label=L("取消", "Cancel"))
        self._choice = current_preference
        self._language_buttons: list[RoundedButton] = []
        self._sort_buttons: list[RoundedButton] = []
        self._direction_buttons: list[RoundedButton] = []
        # 排序选择：列 + 方向
        self._sort_key = sort_key if sort_key in sort_keys() else DEFAULT_SORT_KEY
        spec = find_sort_spec(self._sort_key)
        self._sort_reverse = (spec.default_reverse
                              if sort_reverse is None else bool(sort_reverse))
        # 各列"上次用的方向"。调用方（`FileTracker.on_settings`）会把它
        # 从配置里灌进来，这样在窗口里换列时能带出那一列自己的方向，
        # 与点表头的行为一致。默认空字典 = 每一列都用各自的默认方向。
        self._sort_directions: dict[str, bool] = {}
        # 主题偏好：`None` 与 `"system"` 都是跟随系统，显示上高亮"跟随系统"。
        self._theme_choice = (theme_preference
                              if theme_preference in THEME_CHOICES
                              else THEME_SYSTEM)
        self._theme_buttons: list[RoundedButton] = []
        # **预览回调**：点一下立刻生效（用户要求"所见即所得"）。
        # 由主窗口提供——只有它知道怎么给整扇窗重上色、怎么重取全部文案。
        self._on_theme_preview = on_theme_preview
        self._on_language_preview = on_language_preview
        self._on_sort_preview = on_sort_preview

        self._build_language_row()
        self._build_theme_row()
        self._build_sort_rows()
        # **加了新控件之后必须再套一次字体。**
        # 基类 `__init__` 里已经套过一次，但那是在语言行/排序行建出来**之前**——
        # 那时它们还不存在，`self.SetFont` 也传播不到后建的控件。
        self.apply_body_font()
        self._layout()

    # -- 构造 -------------------------------------------------------------

    def _build_theme_row(self) -> None:
        """主题选择：跟随系统 / 浅色 / 深色。

        用户要求："干脆把切换主题也加进设置吧，这样方便用户也方便你测试。"

        与语言那一行同构（标签 + 一排分段按钮，选中的用强调色）。

        ## 按钮上**没有文字**，只有自绘图标（2026-10-17）

        原来 caption 是符号 `💻`/`☀`/`☾`，但 `_on_paint` 早就改成用
        `icon_painter` 画几何图元了（符号只影响尺寸、不会被画）。
        而 `💻` 是 emoji、175% 下宽 30+ 像素，把按钮撑成 **56×40**，
        与"排序方式"那三个 56×56 的正方形不齐。

        用户要求"把界面主题的这 3 个按钮形状，也统一成排序方式这种
        正矩形" ⇒ caption 留空 ⇒ 宽度回落到 `min_width`（= 高度）⇒ 正方形。
        文案全部落在 tooltip（`THEME_TOOLTIPS`），可读性与无障碍不受影响。

        顺带：`THEME_DISPLAY_NAMES` 因此**没有任何读者**了，已删除
        （`check_wiring` 会抓"无人读取的常量"，留着就是死代码）。
        """
        self._theme_label = wx.StaticText(
            self, label=L("界面主题", "Theme"))
        self._theme_label.SetForegroundColour(wx.Colour(self.theme.text))
        self._theme_label.SetBackgroundColour(
            wx.Colour(self.theme.background))

        for value in THEME_CHOICES:
            button = RoundedButton(
                # **caption 留空**（用户 2026-10-17）：
                #   原来传的是符号 `💻`/`☀`/`☾`，而 `💻` 是 emoji、
                #   在 175% DPI 下宽度能到 30+ 物理像素，`_sync_min_size`
                #   里 `宽 = max(文字宽 + 内边距, min_width)` 于是把它撑成
                #   **宽扁矩形**（约 56×40），和"排序方式"那三个正方形
                #   （56×56）放在一起明显不齐。
                #
                #   图标本来就由 `icon_painter` 画（`_on_paint` 里
                #   `if icon_painter is not None` 会**跳过文字**），
                #   caption 只影响尺寸 ⇒ 留空即得正方形。
                #   文案仍在 tooltip 里，可读性与无障碍不受影响。
                self, "", self.theme,
                variant="accent" if value == self._theme_choice else "secondary",
                height=METRICS.dialog_button_height,
                min_width=METRICS.dialog_button_height,
                on_click=(lambda _event, v=value: self._choose_theme(v)),
            )
            button._is_icon_button = True
            # 符号说不清"这是什么主题"，完整名称放 tooltip
            button.SetToolTip(L(*THEME_TOOLTIPS[value]))
            # **「跟随系统」不用字形，用画出来的显示器。**
            #
            # 曾经这里想用 💻（U+1F4BB），但它是 astral 平面的 emoji：
            # 自绘按钮走 GDI+，而 **GDI+ 不做字体回退**，`Microsoft YaHei UI`
            # 里没有这个字形，于是画成 `.notdef`（用户看到的"非法标识符"方框）。
            #
            # 另一个会话的智能体给的 `icon_monitor` 用的是**几何图元** ——
            # 不依赖任何字体覆盖，所以**在任何主题、任何字体下都画得出来**。
            # 这正是这个位置的正确做法：**图标就该画，不该指望字体**。
            #
            # `☀`/`☾` 保持字形：它们是 BMP 符号，字体覆盖得到，
            # 而且与旁边的显示器图元视觉重量相当。
            # **三个都用画出来的图标**（用户拿来了对方画的太阳/月亮）。
            #
            # 图元不依赖字体覆盖 —— 这正是 `☀`/`☾` 换成绘制版的原因：
            # 字形要靠字体有那个码位，而**画出来的图形在任何字体、
            # 任何主题、任何精简版 Windows 上都一样**。
            button.icon_painter = {
                THEME_SYSTEM: icon_monitor,
                THEME_LIGHT: icon_sun,
                THEME_DARK: icon_moon,
            }.get(value)
            button._theme_value = value
            self._theme_buttons.append(button)

    def _choose_theme(self, value: str) -> None:
        """点一下立刻换高亮，**不等点确定**（与语言那一行一致）。

        写法与 :meth:`_repaint_choices` 相同：直接改 ``variant`` 再 ``Refresh()``。
        ``RoundedButton`` **没有** ``set_variant`` —— 别去发明一个，
        否则同一个效果就有两套实现。
        """
        self._theme_choice = value
        for button in self._theme_buttons:
            button.variant = ("accent"
                              if button._theme_value == value
                              else "secondary")
            button.Refresh()
        # **立刻生效**：主窗口换主题，并让本对话框重新上色。
        if self._on_theme_preview is not None:
            self._on_theme_preview(value)

    def selected_theme(self) -> str:
        return self._theme_choice

    def _all_buttons(self) -> list:
        """**所有**需要跟着主题走的按钮。

        ⚠️ 底部那对（确定/取消）是基类 `ThemedDialog` 建的，存在
        `self._buttons` 里 —— 一开始漏了它们，于是换主题时
        **只有「取消」保持旧配色**（用户截图里它是深色，其余是浅色）。
        """
        return (list(self._language_buttons) + list(self._theme_buttons)
                + list(self._sort_buttons) + list(self._direction_buttons)
                + list(getattr(self, "_buttons", [])))

    def _all_labels(self) -> list:
        return [self._label, self._theme_label,
                self._sort_label, self._direction_label]

    def apply_theme(self, theme: Theme) -> None:
        """**本对话框自己重新上色。**

        用户要的是"所见即所得"：他点月亮时，**设置窗口本身也必须变暗**——
        只把主窗口换掉、设置窗口还是亮的，那看着就像没生效。

        `RoundedButton` 是自绘的，不会跟着走，所以逐个推给它（`apply_theme`）。
        """
        self.theme = theme
        self.SetBackgroundColour(wx.Colour(theme.background))
        for label in self._all_labels():
            label.SetForegroundColour(wx.Colour(theme.text))
            label.SetBackgroundColour(wx.Colour(theme.background))
        for button in self._all_buttons():
            button.theme = theme
            button.Refresh()
        # **非客户区要重新声明。**
        #
        # 用户报（截图）："各项变化**刷新不完整**" —— 设置窗口主体变暗了，
        # 但**标题栏那一条还是浅的**。
        #
        # 根因：标题栏是**非客户区**，`SetBackgroundColour` 对它无效，
        # 只能靠 `DwmSetWindowAttribute`（`_apply_window_chrome` 里那一步），
        # 而那一步**只在 `__init__` 跑过一次**。所以这里必须补调一次。
        self._apply_window_chrome()
        self.Refresh()
        self.Update()

    def retranslate(self) -> None:
        """**本对话框自己重新取一遍文案**（换语言时用）。

        只改文字，不动尺寸；改完**必须重跑 `_layout()`** ——
        英文标签与中文标签宽度不同，不重排会压字。
        """
        self._label.SetLabel(L("界面语言", "Language"))
        self._theme_label.SetLabel(L("界面主题", "Theme"))
        self._sort_label.SetLabel(L("排序方式", "Sort by"))
        self._direction_label.SetLabel(L("排序方向", "Order"))

        # **按钮的文字也要重取** —— 上一版只改了标签，所以用户看到
        # "只有非按钮部分变了，按钮部分还是原语言"。
        #
        # 自绘按钮的标题走 `SetLabel`（已被 `RoundedButton` 接管，
        # 会同时写 `self.label` 并重算宽高）。
        for button in self._sort_buttons:
            spec = find_sort_spec(getattr(button, "_sort_value", None))
            if spec is None:
                continue
            if getattr(button, "_is_icon_button", False):
                # **图标按钮不能 SetLabel**：文字会把按钮从正方形撑成宽扁形。
                # 文案落到悬停提示里（仍然可读、也无障碍可访问）。
                button.SetToolTip(spec.label())
            else:
                button.SetLabel(spec.label())
        # **顺序必须与 `_build_sort_rows` 里创建时一致**（升序在前），
        # 否则语言一换、文案就贴到了错误的按钮上。
        for button, descending in zip(
                self._direction_buttons, (False, True)):
            caption = (L("降序", "Descending") if descending
                       else L("升序", "Ascending"))
            if getattr(button, "_is_icon_button", False):
                # 图标按钮不能 SetLabel（会把正方形撑宽）
                button.SetToolTip(caption)
            else:
                button.SetLabel(caption)
        # 底部那一对：文案与 `ThemedDialog.__init__` 里传的是同一组
        for button, key in zip(getattr(self, "_buttons", []),
                               (("确定", "OK"), ("取消", "Cancel"))):
            button.SetLabel(L(*key))
        # **主题按钮的 tooltip**（用户 2026-10-17 指出的漏接点）：
        #
        # > "图标悬停提示：鼠标悬停在图标上显示的提示信息，
        # >   '主题'那三栏仍然是中文提示。"
        #
        # 上一版这里写着"主题按钮是符号，与语言无关" —— 那句**已经过时**：
        # 按钮现在是**自绘图标 + tooltip**（caption 留空），
        # 而 tooltip 的文案是会随语言变的，必须一起刷新。
        #
        # 顺序与 `_build_theme_row` 里 `for value in THEME_CHOICES` 一致。
        for button, value in zip(getattr(self, "_theme_buttons", []),
                                 THEME_CHOICES):
            button.SetToolTip(L(*THEME_TOOLTIPS[value]))

        # **窗口标题**（同一个漏接点的另一半）：
        #
        # > "窗口标题：设置窗口左上角的标题仍然是中文。"
        #
        # 标题是 `ThemedDialog.__init__` 传进去的，之后没人再更新它。
        self.SetTitle(L("设置", "Settings"))

        # 语言按钮写的是语言自己的名字，**不该跟着翻译**
        # （"English" 在中文界面下仍然是 English）。
        self._layout()
        self.Refresh()
        self.Update()

    def _build_language_row(self) -> None:
        # **标签用 `wx.StaticText` 而不是自绘。** 它是纯静态文字，
        # 原生控件在这里足够，也天然跟随系统字体。
        self._label = wx.StaticText(self, label=L("界面语言", "Language"))
        self._label.SetForegroundColour(wx.Colour(self.theme.text))
        self._label.SetBackgroundColour(wx.Colour(self.theme.background))

        # 选项与显示名都从 `lang` 取——**不要在界面里再抄一份语言清单**，
        # 那样加一种语言就要改两处，而漏改的那一处不会有任何提示。
        for value in CHOICES:
            caption = DISPLAY_NAMES[value]
            button = RoundedButton(
                self, caption, self.theme,
                # 选中的那个用强调色——**"当前是哪一项"必须一眼看出来**，
                # 这正是 Roboc 用 accent 填充活动分段的原因。
                variant="accent" if value == self._choice else "secondary",
                height=METRICS.dialog_button_height,
                min_width=METRICS.dialog_button_width,
                on_click=(lambda _event, v=value: self._choose(v)),
            )
            button._language_value = value
            self._language_buttons.append(button)

    def _build_sort_rows(self) -> None:
        """两行：**排序列**与**排序方向**。

        用户要求："可以选择下次启动时的排序方式。
        目前是每次启动默认频次排序，太死板，我希望用户能根据自己的习惯调节。"

        拆成两行而不是挤一行：四列 × 两方向 = 八个按钮，
        挤在一行会宽得离谱，也会把标签压没。两行各自是一组"选一个"。
        """
        self._sort_label = wx.StaticText(
            self, label=L("排序方式", "Sort by"))
        self._sort_label.SetForegroundColour(wx.Colour(self.theme.text))
        self._sort_label.SetBackgroundColour(
            wx.Colour(self.theme.background))

        # ## 排序方式用**图标按钮**（用户 2026-10-17）
        #
        # > "排序方式现在也按照界面主题的分类一样，使用 3 个小按钮，
        # >   里面用图形来代表路径、频次和时间。"
        #
        # 与主题那三个（显示器 / 太阳 / 月亮）同一套机制：`icon_painter`
        # + `_draw_icon` 的几何图元 —— 不受字体有没有该字形的影响。
        #
        # **label 留空**：文字会把按钮撑成"宽扁"的，而图标按钮要接近正方形。
        # 空 label + `min_width = 高度` ⇒ 正方形（见 `_sync_min_size`）。
        # 原来的文字改成**悬停提示**，所以仍然可读、也无障碍可访问。
        for spec in SORT_SPECS:
            button = RoundedButton(
                self, "", self.theme,
                variant=("accent" if spec.key == self._sort_key
                         else "secondary"),
                height=METRICS.dialog_button_height,
                min_width=METRICS.dialog_button_height,
                on_click=(lambda _event, s=spec: self._choose_sort(s.key)),
            )
            button.icon_painter = SORT_ICONS.get(spec.key)
            button.SetToolTip(spec.label())
            button._sort_value = spec.key
            #: 图标按钮不需要文字，语言切换时只更新提示
            button._is_icon_button = True
            self._sort_buttons.append(button)

        self._direction_label = wx.StaticText(
            self, label=L("排序方向", "Order"))
        self._direction_label.SetForegroundColour(wx.Colour(self.theme.text))
        self._direction_label.SetBackgroundColour(
            wx.Colour(self.theme.background))

        # 顺序固定为「降序 / 升序」：两列里"大→小"都是更常用的那一个
        # （频次最高、时间最近），所以把它们放前面。
        # **图标 + 顺序互换**（用户 2026-10-17）：
        #
        # > "降序和升序的这两个按钮，可以换成图形的形式，
        # >   也就是'箭头向上'和'箭头向下'。"
        # > "这两个按钮的位置互换一下，视觉上看着会更符合直觉一些。"
        #
        # 顺序改成 **升序在前**（↑ 升序、↓ 降序）—— 与"上小下大"的
        # 空间直觉一致。`_apply_direction_labels` 里的 zip 顺序要同步改，
        # 那边用的是位置而不是 `_direction_value`。
        for descending in (False, True):
            button = RoundedButton(
                self, "", self.theme,
                variant=("accent" if descending == self._sort_reverse
                         else "secondary"),
                height=METRICS.dialog_button_height,
                min_width=METRICS.dialog_button_height,
                on_click=(lambda _event, d=descending:
                          self._choose_direction(d)),
            )
            button.icon_painter = (icon_arrow_down if descending
                                   else icon_arrow_up)
            button.SetToolTip(L("降序", "Descending") if descending
                              else L("升序", "Ascending"))
            button._direction_value = descending
            button._is_icon_button = True
            self._direction_buttons.append(button)

    def _preview_sort(self) -> None:
        """把"当前选中的排序"推给主窗口，**立刻重排列表**。

        用户报："排序方式、排序方向**没有及时生效**。"
        —— 主题与语言都接上了预览回调，**只有排序漏了**。

        排序与那两者不同：它不改配色也不改文案，只改**列表内容的顺序**，
        所以主窗口那边调 `apply_sort` 就够了，不需要重上色。
        """
        if self._on_sort_preview is not None:
            self._on_sort_preview(self._sort_key, self._sort_reverse)

    def _choose_sort(self, key: str) -> None:
        """换列时**带出那一列自己的方向**，与点表头的行为一致。

        不这么做的话，用户在这里选"路径"会沿用频次的降序，
        得到 Z→A —— 而列表里点表头却会给他 A→Z，两处行为不一致。
        """
        self._sort_key = key
        remembered = self._sort_directions.get(key)
        spec = find_sort_spec(key)
        self._sort_reverse = (spec.default_reverse if remembered is None
                              else remembered)
        self._repaint_choices()
        # **立刻重排**（用户报"排序方式没有及时生效"）
        #
        # ⚠️ 上一轮我漏了这一处：那次替换用的锚点文本
        # 在 `__init__` 里也有一份，`replace(..., 1)` 命中了
        # **第一处**（`__init__`），于是只有 `_choose_direction`
        # 接上了预览，`_choose_sort` 没有 ——
        # 症状就是"点排序方式不生效、点排序方向生效"。
        self._preview_sort()

    def _choose_direction(self, descending: bool) -> None:
        self._sort_reverse = descending
        # **立刻重排**（用户报"排序方向没有及时生效"）
        self._preview_sort()
        # 顺手记住这一列的方向，这样在同一列上换来换去不会丢
        self._sort_directions[self._sort_key] = descending
        self._repaint_choices()

    def _choose(self, value: str) -> None:
        """点一下**立刻**换色，不等点确定；并**立刻把语言也换掉**。

        用户要求"如果他切换了英文，界面的文字马上就全部变成英文"——
        所以这里不只是把选中项标出来，而是真的换语言。
        """
        self._choice = value
        self._repaint_choices()
        if self._on_language_preview is not None:
            self._on_language_preview(value)

    def _repaint_choices(self) -> None:
        """按当前选择刷新所有分段按钮的配色。**只有一处判断**，
        免得"语言选中了但排序没跟上"这类不一致。"""
        for button in self._language_buttons:
            button.variant = ("accent"
                              if button._language_value == self._choice
                              else "secondary")
            button.Refresh()
        for button in getattr(self, "_theme_buttons", []):
            button.variant = ("accent"
                              if button._theme_value == self._theme_choice
                              else "secondary")
            button.Refresh()
        for button in self._sort_buttons:
            button.variant = ("accent"
                              if button._sort_value == self._sort_key
                              else "secondary")
            button.Refresh()
        for button in self._direction_buttons:
            button.variant = ("accent"
                              if button._direction_value == self._sort_reverse
                              else "secondary")
            button.Refresh()

    def selected_preference(self) -> str:
        return self._choice

    def selected_sort(self) -> tuple[str, bool]:
        """``(排序列标识, 是否降序)``。"""
        return (self._sort_key, self._sort_reverse)

    # -- 布局 -------------------------------------------------------------

    def _layout(self) -> None:
        """先按基类算好，再把语言行插进正文区。

        基线：正文区在 `_body_rect`，按钮组在 `_buttons_top`。
        这里把正文区**留给语言行**（它比一行文字高），
        再把整体高度加上这一行的高度。

        **基类 `__init__` 会先调一次 `_layout()`**，那时语言行还没建出来。
        所以要先判断它是否存在——否则会 `AttributeError`
        （实测：`'SettingsDialog' object has no attribute '_label'`）。
        基类那一次只需要把按钮位置算好；真正的尺寸由我们随后这次定。
        """
        super()._layout()
        if not hasattr(self, "_label"):
            return
        dpi = dpi_of(self)

        def px(logical: int) -> int:
            return scale_for_dpi(logical, dpi)

        row_height = px(METRICS.dialog_button_height)
        gap = px(METRICS.padding_gap)
        margin = px(METRICS.dialog_margin)
        row_gap = px(METRICS.padding_tight)     # 行与行之间比"控件之间"更紧

        # **客户区宽度封顶。**
        #
        # 四个排序列横排要 4×96 + 3×8 = 408 逻辑像素，加上标签就逼近 600 ——
        # 弹窗会变成一条又宽又扁的横带（实测 897 像素宽），
        # 而它在屏幕上是居中的，左右会压到别的东西。
        # 所以按 `dialog_row_width`（"标签 + 两个按钮"）封顶，放不下的**换行**。
        max_width = px(METRICS.dialog_row_width)

        # 每组按钮，按**来源**分组。
        groups = (
            (self._label, list(self._language_buttons)),
            (self._theme_label, list(self._theme_buttons)),
            (self._sort_label, list(self._sort_buttons)),
            (self._direction_label, list(self._direction_buttons)),
        )

        def chunk_width(chunk) -> int:
            return (sum(b.GetBestSize().width for b in chunk)
                    + gap * (len(chunk) - 1))

        # 底部两个按钮那一排也要放得下
        footer = (len(self._labels) * px(METRICS.dialog_button_width)
                  + max(len(self._labels) - 1, 0)
                  * px(METRICS.dialog_button_gap))

        # **宽度 = max(标签+按钮, 底部按钮排, 下限)。**
        #
        # 版式回到"**标签在左、按钮在右**"（用户这一轮否决了居中式），
        # 所以标签又与按钮同行了 —— 宽度要按"标签宽 + 间距 + 按钮宽"算。
        #
        # 加 `settings_min_width` 下限：用户之前要求过"窗口可以放大一些"。
        # 标签与按钮之间用 **`padding_tight`**（比 `padding_gap` 紧一档）：
        # 用户要求"中间的空格全部删掉……最多打一两个空格就够了"。
        #
        # ⚠️ 真正摆放时 `_place_rows` 会改用量出来的"**两个空格**"
        # （用户后来明确了长度）。这里只用于**算内容宽度**，
        # 取紧的那一档即可 —— 算宽时宁可窄一点，不要让窗口被撑宽。
        label_gap = px(METRICS.padding_tight)
        natural = max(
            [_label_width(label) + label_gap + chunk_width(buttons)
             for label, buttons in groups]
            + [footer]
        )
        content_width = max(min(natural, max_width),
                            px(METRICS.settings_min_width), footer)

        # **每行按钮数上限**：`None` = 不限制，只按宽度折。
        #
        # 用户要求「排序方式还是成**两行两列**吧，四个并排看着还是太奇怪了」。
        # 其它三组不限制（语言 2 个、主题 3 个、方向 2 个，本来就排得下）。
        # **不再限制每行 2 个**：那是文字按钮时代的规则（四个并排太宽）。
        # 现在排序是 3 个**图标**按钮，一行放得下，而且用户明确要求
        # "像界面主题的分类一样" —— 主题那三个就是一行。（2026-10-17）
        per_row_caps = {}

        self._rows = tuple(
            (label, _wrap_buttons(buttons, content_width, gap,
                                  label_width=_label_width(label) + label_gap,
                                  max_per_row=per_row_caps.get(id(label))))
            for label, buttons in groups
        )

        # **每组 = 标签 + 若干按钮行；组与组之间空一行。**
        #
        # 用户要求「每个类之间**一定要多空一行**」—— 这就是"层次感"的来源。
        # 标签**不额外占行**，它与第一块按钮垂直居中（见 `_place_rows`）。
        group_gap = px(METRICS.dialog_group_gap)

        body_height = 0
        for index, (_label, chunks) in enumerate(self._rows):
            if index:
                body_height += group_gap
            body_height += (row_height + row_gap) * len(chunks)
        body_height -= row_gap                     # 末尾那一次多加的

        client_width = content_width + margin * 2

        self._body_rect = (margin, margin, margin + content_width,
                           margin + body_height)
        # **底部按钮与选项之间多空一行**（用户要求）。
        # 它在 `dialog_body_to_buttons` 之上**再加**一段。
        self._buttons_top = (margin + body_height
                             + px(METRICS.dialog_body_to_buttons)
                             + px(METRICS.dialog_footer_gap))
        client_height = (self._buttons_top + row_height
                         + px(METRICS.dialog_bottom))
        self.SetClientSize((client_width, client_height))

        # **底部按钮右对齐**（用户要求"放在底部右侧"）。
        #
        # 基类 `ThemedDialog._layout()` 把它们算成**居中**的，
        # 所以这里要重算 `_button_rects` 再摆；`_place_buttons()` 只负责
        # 按 `_button_rects` 落位，改这里就够了。
        footer_gap = px(METRICS.dialog_button_gap)
        footer_width = px(METRICS.dialog_button_width)
        x = client_width - margin - footer
        for index in range(len(self._labels)):
            self._button_rects[index] = (x, footer_width)
            x += footer_width + footer_gap
        self._place_buttons()
        self._place_rows(content_width)
        self._center_on_parent()

    def _place_rows(self, content_width: int) -> None:
        """**「标签 + 按钮」当成一整块，整段居中**；组与组之间空一行。

        ## 用户对间距的两次要求（都记下来）

        1. "按钮全部都挤在一起，**没有层次感**" → 加了组间空行。
        2. "标题和按钮之间**隔得太远了**，用户很难把这些东西关联到一起。
           ……**不要分别左对齐和右对齐**，就让它们**左右挨在一起**……
           然后让它们**整段居中**。"

        第 2 条说的就是早先那种"标签钉左边、按钮钉右边"的做法：
        内容一宽，两者之间就是一大片空白，**看不出谁属于谁**。
        现在整块居中之后，标签永远紧挨着它那组按钮。

        带宽由 :meth:`_layout` 传进来——**不要自己去读 `_body_rect`**，
        两者差一个 margin（见 `_layout` 里那段说明）。
        """
        left, top, _right, _bottom = self._body_rect
        dpi = dpi_of(self)
        gap = scale_for_dpi(METRICS.padding_gap, dpi)
        label_gap = scale_for_dpi(METRICS.padding_tight, dpi)
        row_gap = scale_for_dpi(METRICS.padding_tight, dpi)
        group_gap = scale_for_dpi(METRICS.dialog_group_gap, dpi)
        row_pitch = scale_for_dpi(METRICS.dialog_button_height, dpi) + row_gap

        # **标签与按钮之间留"两个空格"。**
        #
        # 用户："标题和按钮之间间隔**两个空格**我看看效果。"
        # 那就**按字体现量**两个空格有多宽，而不是写死一个像素数——
        # 换字体或换 DPI 时它仍然是"两个空格"，这正是用户描述的那个量。
        dc = wx.ClientDC(self)
        label_font = self._label.GetFont()
        dc.SetFont(label_font)
        # **三个空格**（用户："标题和按钮之间再加一个空格"）。
        # 按字体现量，换字体或换 DPI 时它仍然是"三个空格"。
        label_gap = max(dc.GetTextExtent("   ").width, scale_for_dpi(4, dpi))

        y = top
        for index, (label, chunks) in enumerate(self._rows):
            if index:
                y += group_gap              # ← "每个类之间多空一行"

            label_height = label.GetSize().height
            label_width = _label_width(label)

            def chunk_total(chunk) -> int:
                if not chunk:
                    return 0
                width = chunk[0].GetBestSize().width
                return width * len(chunk) + gap * (len(chunk) - 1)

            # **整段左对齐**（用户："整段左对齐"）。
            #
            # 上一版是整块居中；用户看过之后改主意了，就用内容区的左边界。
            block_left = left

            label.SetSize(block_left,
                          y + max((row_pitch - label_height) // 2, 0),
                          label_width, label_height)

            x0 = block_left + label_width + label_gap
            for chunk in chunks:
                width = chunk[0].GetBestSize().width if chunk else 0
                height = chunk[0].GetBestSize().height if chunk else 0
                x = x0                      # ← 各排**左对齐**，紧挨标签
                for button in chunk:
                    button.SetSize(x, y, width, height)
                    x += width + gap
                y += row_pitch
            y -= row_gap                     # 末尾那一次多加的

    def _on_paint(self, event) -> None:
        """基类会把 `_message` 画出来；设置窗口没有正文，所以只铺底色。"""
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.Colour(self.theme.background)))
        dc.Clear()


class IconButton(BufferedPanel):
    """自绘位图按钮（顶置开关用它）。

    **点击走 `on_click` 回调，不是 `wx.EVT_BUTTON` 绑定。**
    踩过一次：`_build_pin_button` 造出控件后忘了 `Bind`，于是
    "控件画得好好的、点了完全没反应"——用户报的"功能本身都失效了"。
    改成回调之后，**忘传回调是显式的**（`on_click=None` 一眼可见），
    不必再依赖"创建之后记得绑一下"这一步。

    与 :class:`RoundedButton` 保持同一种写法，两个按钮不再是两套约定。
    """

    def __init__(self, parent, bitmap: wx.Bitmap, theme: Theme,
                 size: tuple[int, int], on_click=None):
        super().__init__(parent, theme, size=size)
        self.bitmap = bitmap
        self._pressed = False
        self.on_click = on_click
        self.SetBackgroundColour(wx.Colour(theme.background))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda event: self.Refresh())
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)

    def SetBitmap(self, bitmap: wx.Bitmap) -> None:  # noqa: N802 - 跟随 wx 命名
        self.bitmap = bitmap
        self.Refresh()

    def draw(self, dc) -> None:
        """画图标按钮：只有图钉本身，**没有任何边框**。

        用户明确要求："右下角置顶窗口按钮不需要任何边框"。
        所以底色始终等于父面板底色，只有按下时才给一点反馈。

        （上一版画了 ``theme.border`` 的描边，深色主题下还会在圆角外
        露出没扣干净的浅色像素；现在整块先铺父底色，两个问题一起解决。）
        """
        width, height = self.GetClientSize()
        parent_colour = self.GetParent().GetBackgroundColour()
        dc.SetBrush(wx.Brush(parent_colour))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRectangle(0, 0, width, height)

        if self._pressed:
            dc.SetBrush(wx.Brush(wx.Colour(self.theme.button_pressed)))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRoundedRectangle(0, 0, width, height,
                                    METRICS.button_radius_for(height))

        if self.bitmap.IsOk():
            bitmap_width, bitmap_height = self.bitmap.GetSize()
            dc.DrawBitmap(
                self.bitmap,
                max(int((width - bitmap_width) / 2), 0),
                max(int((height - bitmap_height) / 2), 0),
                True,
            )

    def _on_left_down(self, event) -> None:
        self._pressed = True
        self.Refresh()

    def _on_left_up(self, event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.Refresh()
        if was_pressed and self.GetClientRect().Contains(event.GetPosition()):
            # 直接回调，不走 wx.CommandEvent——
            # 原来发一个命令事件出去，但**没有人绑它**，点击静默丢失。
            if self.on_click is not None:
                self.on_click(event)
            else:
                # 没有回调就把事件交给父级，方便将来有人想用 Bind
                click = wx.CommandEvent(wx.EVT_BUTTON.typeId, self.GetId())
                click.SetEventObject(self)
                self.GetEventHandler().ProcessEvent(click)

    def _on_leave(self, event) -> None:
        self._pressed = False
        self.Refresh()


class PathBar(BufferedPanel):
    """地址栏：粘贴路径 → 回车 → 打开该位置。

    **只有一个输入框，没有"前往"按钮。** 用户 2026-10-15 明确要求删掉它：
    "把'前往'按钮删了，鸡肋"——回车本来就够了，多一个按钮既占宽度又误导
    （看起来像必须点它）。输入框内按 Esc 清空。

    提示文字刻意短（"输入或粘贴路径"）：原来那句"粘贴或输入文件夹路径，回车前往"
    有 15 个字符，实测需要 345 物理像素，而输入框只有 270 像素——
    **提示直接被截断**。字号也比正文小一号，避免在窄框里喧宾夺主。
    """

    @property
    def HINT(self) -> str:
        """提示语。**每次读都重新取**，所以永远跟着当前语言。

        ## 为什么必须是 property，而不是类属性

        原来是 ``HINT = L("输入或粘贴路径", "Type or paste a path")`` ——
        **类属性在 import 时求值一次**，而那时语言还没定下来
        （`lang.apply` 在 `FileTracker.__init__` 里、建界面之前才调）。

        后果（审计实测）：中文系统上 import widgets → `HINT` 已经冻结成中文
        → 用户选了英文 → **启动后每一次看到的都还是中文提示**。
        只有去设置里重选一次语言，`retranslate` 才会把它改过来。
        英文系统上选中文，镜像同样成立。

        原来那行注释写着"这是运行时读取的（`self.HINT`），不是模块级求值后
        就被冻结的常量"——**那句话是错的**：类属性的求值时机与模块级常量
        一样早。这正是"注释与代码不一致"最坏的一种：它让人不去查。

        做成 property 之后，`PathBar.HINT`（类上读）返回的也是当前语言，
        而 `self.HINT` 与重建提示都自动正确，不需要额外同步。
        """
        return L("输入或粘贴路径", "Type or paste a path")

    def __init__(self, parent, theme: Theme, on_submit):
        super().__init__(parent, theme)
        self.on_submit = on_submit
        self.SetBackgroundColour(wx.Colour(theme.background))

        # 高度**按文字算，不用固定值**：用户先反馈"太矮"（我加了固定高度），
        # 又反馈"过高，适当降低高度与框内文字匹配"。固定值总会与文字对不上——
        # 所以取"一行文字的高度 + 上下各一个内边距"，并留一个下限。
        dpi = dpi_of(self)
        text_height = self.GetTextExtent(self.HINT).height
        inset = scale_for_dpi(METRICS.path_bar_text_inset, dpi)
        bar_height = max(
            text_height + inset * 2,
            scale_for_dpi(METRICS.path_bar_min_height, dpi),
        )
        self.SetMinSize((-1, bar_height))

        sizer = wx.BoxSizer(wx.HORIZONTAL)

        # 留出内边距，好让圆角描边画在输入框**外面**而不被它盖住
        self.text_ctrl = wx.TextCtrl(self, style=wx.BORDER_NONE | wx.TE_PROCESS_ENTER)
        self.text_ctrl.SetBackgroundColour(wx.Colour(theme.surface_alt))
        self.text_ctrl.SetForegroundColour(wx.Colour(theme.text))
        self.text_ctrl.SetHint(self.HINT)
        self._apply_hint_font()
        self.text_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_enter)
        self.text_ctrl.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.text_ctrl.Bind(wx.EVT_SET_FOCUS, self._on_focus_change)
        self.text_ctrl.Bind(wx.EVT_KILL_FOCUS, self._on_focus_change)
        # 点哪儿都能进输入框（自绘面板自己也要把点击转给子控件）
        self.Bind(wx.EVT_LEFT_DOWN, lambda event: self.text_ctrl.SetFocus())

        margin = scale_for_dpi(2, dpi_of(self))
        # **输入框跟着条一起长。** 用户反馈过："你把路径输入窗口间隔加高了，
        # 但窗口本身却没加高。" 所以条的 MinSize 与输入框的 MinSize 一起算。
        self.text_ctrl.SetMinSize((-1, bar_height - margin * 2))
        sizer.Add(self.text_ctrl, 1,
                  wx.ALIGN_CENTER_VERTICAL | wx.ALL, margin)
        self.SetSizer(sizer)

    def _on_focus_change(self, event) -> None:
        """焦点变化时重画描边：有焦点用强调色，没焦点用边框色。

        **这是"输入框看起来可以点"的主要视觉线索**——
        用户反馈"顶栏没有任何交互"，一部分原因是它在没有焦点时
        与背景几乎一样，看起来像个静态标签。
        """
        self.Refresh()
        event.Skip()

    def _apply_hint_font(self) -> None:
        """给输入框一个比**正文**小一号的字号。

        从 :data:`~file_tracker.theme.` 无关处取基准：以父窗口当前的字体为准
        （`set_global_font` 会把正文设成"系统 +1"），再减一号。

        **由 :meth:`apply_body_font` 在全局字体设好之后调用一次。**
        在构造函数里调用是错的——那时全局字体还没设，基准偏小，
        实测输入框会变成 8pt 而不是 9pt。
        """
        base = self.GetFont()
        point = base.GetPointSize()
        if point <= 0:
            point = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetPointSize()
        smaller = wx.Font(
            max(point - 1, 7),
            base.GetFamily(), base.GetStyle(), base.GetWeight(),
            False, base.GetFaceName(),
        )
        self.text_ctrl.SetFont(smaller)

    def apply_body_font(self, body: wx.Font) -> None:
        """全局字体变化后重新算输入框字号。

        **输入框本身也要用正文大小**——用户看的是"输入框里的字有多大"，
        而它由 :attr:`text_ctrl` 自己的字体决定，不是由 PathBar 的字体决定。
        只设 PathBar 不设 text_ctrl 的话，输入框看起来还是小一号（实测 9pt）。

        .. note::

           曾经这里还叠过一个"导航窗格偏移"，起因是用户要求把
           "导航窗格内的文字（包括顶栏标题）缩小 1pt"——**他随后更正说
           原意是"记录窗格"**，那处已撤回，所以这里就是**正文本身**。
        """
        self.text_ctrl.SetFont(body)
        self.Refresh()

    def draw(self, dc) -> None:
        """给输入框画圆角描边——``wx.TextCtrl`` 自己画不出圆角。

        描边画在输入框**外面**一圈（构造时留了 2 逻辑像素的内边距），
        否则会被输入框自己的背景盖住。有焦点时用强调色：
        **这是"这里可以输入"的主要视觉线索。**

        没有焦点时用 :attr:`Theme.field_border` 而**不是** `Theme.border`：
        后者画的是次要按钮和分隔条，那些控件**本身有填充色**表达"我是个控件"；
        而本输入框的填充几乎与背景同色，**框线是它唯一的线索**，
        所以它需要更高的对比度（用户："不然用户很难注意到它"）。

        ## ⚠️ 一次**没查出来**的排查，记在这里免得后人重走

        用户报："浅色主题下默认框线只有一条……深色主题下默认框线**里面
        还有一圈纯黑色**，让输入框看起来有了立体感，更像一个按钮。"

        用户进一步观察定出了位置：**右边线、底边线内部**有两条黑像素，
        **左边线、顶部边线内部没有**。这个**不对称**是"亮色走左上、
        暗色走右下"的凹陷边框签名。

        **排查结论：不是 `WS_EX_CLIENTEDGE`。**
        实测同款新建控件的 EX 样式：

        ==========================================  ============
        样式                                         EX 样式
        ==========================================  ============
        默认（不给 style）                            `0x00000200`（带）
        **`wx.BORDER_NONE`（本控件用的）**             `0x00000000`（**不带**）
        ==========================================  ============

        所以 `remove_client_edge()` 在这里是**空操作**（它返回 `True`
        只是因为"本来就没有也算成功"）。那条路走过了，别再走。

        ## 真正的原因：**1 物理像素的笔在 175% 缩放下是亚像素的**

        在用户截图上逐像素量四条边（图像由屏幕 5.57× 放大，见
        `tools/probes/analyze_shot*.py` 的记录）：

        ======  ==================  ==================================
        边      描边像素实测         说明
        ======  ==================  ==================================
        左      `#1A`（背景 `#19`）  只亮 1 级 —— **几乎没画出来**
        上      `#1A`               同上
        右      `#42`               接近本色 `#4A4A4A` —— 画出来了
        下      `#41`               同上
        ======  ==================  ==================================

        **同一条描边，四边强度差约 40 倍。** 而且右/底在填充与描边之间
        还夹着一层 `#292929`（比填充 `#2E2E2E` 更暗）——
        **那就是用户看到的"框线里面的黑"。**

        **机制**：`wx.Pen()` 默认宽度 **1 物理像素**，在 175% 缩放下
        只有 **0.57 逻辑像素**。GDI+ 抗锯齿把它摊到相邻两个物理像素上，
        摊多少取决于路径相对像素网格的位置 —— 右侧拿到约 85% 覆盖、
        左侧只有约 2%，于是同一条线一边实一边虚。

        **修法**：把笔宽**按 DPI 缩放成整数物理像素**
        （`scale_for_dpi(1, dpi)`，@168dpi = 2px）。这样四边都是整像素，
        不需要抗锯齿，强度自然一致。同时描边仍走 GC，圆角保持平滑。
        """
        rect = self.text_ctrl.GetRect()
        colour = wx.Colour(
            self.theme.accent if self.text_ctrl.HasFocus()
            else self.theme.field_border
        )
        x, y = rect.x - 1, rect.y - 1
        w, h = rect.width + 2, rect.height + 2

        # **笔宽必须按 DPI 取整。**
        #
        # 见上面那段：1 物理像素的笔在非整数缩放下是亚像素的，
        # 抗锯齿会让同一条线四边粗细不一（实测左 2%、右 85% 覆盖）。
        # 取 `scale_for_dpi(1, dpi)` 让它落在整数物理像素上。
        pen_width = max(scale_for_dpi(1, dpi_of(self)), 1)

        # **必须走 GraphicsContext 才没有锯齿。**
        #
        # 用户反馈："导航窗格顶部的路径输入框线四角有锯齿。"
        # 原因：`wx.DC.DrawRoundedRectangle` 是 GDI 调用，**不做抗锯齿**——
        # 圆角是硬边像素，放大看就是台阶。
        # `wx.GraphicsContext`（GDI+ / Direct2D 后端）的
        # `DrawRoundedRectangle` 带抗锯齿，四角是平滑的。
        # 注意按钮（`RoundedButton._on_paint`）一直用的就是 GC，所以只有这里锯齿。
        gc = wx.GraphicsContext.Create(dc)
        if gc is not None:
            gc.SetBrush(wx.TRANSPARENT_BRUSH)
            gc.SetPen(wx.Pen(colour, pen_width))
            gc.DrawRoundedRectangle(x, y, w, h, METRICS.radius_field)
        else:
            # 取不到 GC 时退回 GDI（会有锯齿，但不会崩、也不会不画）
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.SetPen(wx.Pen(colour, pen_width))
            dc.DrawRoundedRectangle(x, y, w, h, METRICS.radius_field)

    def refresh_hint(self) -> None:
        """把提示文字重新取一遍（**换语言时用**）。

        ## 为什么不再叫 `SetHint`、也不再接收文字

        原来是 ``SetHint(text)``：调用方算好文案传进来，还要 ``self.HINT = text``
        把它记下来。那是**两份状态**——一处忘了更新，提示与 `HINT` 就不一致。

        现在 `HINT` 是 property（每次读都按当前语言取），所以"换语言"这件事
        只需要**重新取一次并转交给内部文本框**。调用方不再需要知道文案是什么，
        也就不可能传错语言。

        取名 `refresh_hint` 而不是 `SetHint`：它不接受文案，
        叫 `Set*` 会让人以为要塞东西进去。
        """
        hint = self.HINT
        self.text_ctrl.SetHint(hint)
        # 提示文字换了、字体没换，所以行高不用重算；
        # 这里只要重画一遍，让自绘的那一层跟上。
        self.Refresh()

    def set_value(self, value: str) -> None:
        self.text_ctrl.SetValue(value or "")

    def focus(self) -> None:
        self.text_ctrl.SetFocus()
        self.text_ctrl.SelectAll()

    def select_all(self) -> None:
        """只选中、不抢焦点——提交之后调用，方便用户直接改路径。"""
        self.text_ctrl.SelectAll()

    def _on_key_down(self, event) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.text_ctrl.SetValue("")
            return
        event.Skip()

    def _on_enter(self, event) -> None:
        self._submit()

    def _submit(self) -> None:
        value = self.text_ctrl.GetValue()
        if self.on_submit is not None:
            self.on_submit(value)

    def apply_theme(self, theme: Theme) -> None:
        super().apply_theme(theme)
        self.text_ctrl.SetBackgroundColour(wx.Colour(theme.surface_alt))
        self.text_ctrl.SetForegroundColour(wx.Colour(theme.text))
        self.Refresh()
