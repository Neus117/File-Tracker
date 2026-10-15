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

import wx

from . import win32
from .core import DEFAULT_SORT_KEY, SORT_SPECS, find_sort_spec, sort_keys
from .lang import CHOICES, DISPLAY_NAMES, L
from .theme import METRICS, Theme, scale_for_dpi


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

    def apply_theme(self, theme: Theme) -> None:
        """主题变化时重新取色并重绘。"""
        self.theme = theme
        self.SetBackgroundColour(wx.Colour(theme.background))
        self.Refresh()


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
                 no_label: str | None = None):
        # **默认值不能在签名里写 `L(...)`。** 默认参数在**函数定义时**求值一次，
        # 而那时语言可能还没定下来。所以在体内取。
        if yes_label is None:
            yes_label = L("是(Y)", "Yes")
        if no_label is None:
            no_label = L("否(N)", "No")
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

        # 按钮先建出来（尺寸由 `_layout` 定，这里只给最小尺寸）
        for label, handler in zip(self._labels, self._handlers()):
            button = RoundedButton(self, label, theme,
                                   variant="accent" if not self._buttons else "secondary",
                                   height=METRICS.dialog_button_height,
                                   min_width=METRICS.dialog_button_width,
                                   on_click=handler)
            self._buttons.append(button)

        self._layout()
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

        self._apply_window_chrome()

        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SHOW, self._on_show)
        self.Bind(wx.EVT_SIZE, self._on_size)

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
        body_height = self._measure_body_height(max_text_width)
        buttons_top = (body_top + body_height
                       + px(METRICS.dialog_body_to_buttons))

        # 正文实际需要多宽（`_wrap_lines` 已经把 `_lines` 填好了）
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        text_width = max(
            (dc.GetTextExtent(line).width for line in self._lines), default=0)
        content_width = min(text_width, max_text_width)
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
                lines.append("")
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

    def _draw_body(self, dc) -> None:
        """把正文**逐行居中**画到 ``dc`` 上。

        用户要求："现在让所有提示窗内容居中显示。"

        每一行按自己的宽度算中心——所以"⚠️ 这条路径已失效："与
        路径那一行、以及"要从记录中删除它吗？"三者都是各自居中的，
        而不是整块靠左。多行消息里这正是期望的观感。

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
        # 用 `_body_rect` 的中点当轴——左右各留了 margin，所以居中后
        # 两边到窗口边缘的距离相等。
        center = (left + right) // 2
        for index, line in enumerate(lines):
            x = center - dc.GetTextExtent(line).width // 2
            dc.DrawText(line, x, top + index * line_height)

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


def _wrap_buttons(buttons, max_width: int, gap: int,
                  row_height: int) -> list[list]:
    """把一排分段按钮按 ``max_width`` 折成若干块（每块占一行）。

    **宽度封顶靠它。** 四个排序列横排要 408 逻辑像素，加标签就逼近 600，
    弹窗会变成又宽又扁的横带（实测 897 像素）。折成 2×2 之后就回到
    与其它行相当的宽度。

    至少保留两个一行——一行一个太散，反而不像"一组里选一个"。
    """
    rows: list[list] = []
    current: list = []
    width = 0
    for button in buttons:
        button_width = button.GetBestSize().width
        needed = button_width if not current else gap + button_width
        if current and width + needed > max_width and len(current) >= 2:
            rows.append(current)
            current = [button]
            width = button_width
        else:
            current.append(button)
            width += needed
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
                 sort_reverse: bool | None = None):
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
        self._build_language_row()
        self._build_sort_rows()
        self._layout()

    # -- 构造 -------------------------------------------------------------

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

        for spec in SORT_SPECS:
            button = RoundedButton(
                self, spec.label(), self.theme,
                variant=("accent" if spec.key == self._sort_key
                         else "secondary"),
                height=METRICS.dialog_button_height,
                min_width=METRICS.dialog_button_width,
                on_click=(lambda _event, s=spec: self._choose_sort(s.key)),
            )
            button._sort_value = spec.key
            self._sort_buttons.append(button)

        self._direction_label = wx.StaticText(
            self, label=L("排序方向", "Order"))
        self._direction_label.SetForegroundColour(wx.Colour(self.theme.text))
        self._direction_label.SetBackgroundColour(
            wx.Colour(self.theme.background))

        # 顺序固定为「降序 / 升序」：两列里"大→小"都是更常用的那一个
        # （频次最高、时间最近），所以把它们放前面。
        for descending, caption in (
                (True, L("降序", "Descending")),
                (False, L("升序", "Ascending"))):
            button = RoundedButton(
                self, caption, self.theme,
                variant=("accent" if descending == self._sort_reverse
                         else "secondary"),
                height=METRICS.dialog_button_height,
                min_width=METRICS.dialog_button_width,
                on_click=(lambda _event, d=descending:
                          self._choose_direction(d)),
            )
            button._direction_value = descending
            self._direction_buttons.append(button)

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

    def _choose_direction(self, descending: bool) -> None:
        self._sort_reverse = descending
        # 顺手记住这一列的方向，这样在同一列上换来换去不会丢
        self._sort_directions[self._sort_key] = descending
        self._repaint_choices()

    def _choose(self, value: str) -> None:
        """点一下**立刻**换色，不等点确定。"""
        self._choice = value
        self._repaint_choices()

    def _repaint_choices(self) -> None:
        """按当前选择刷新所有分段按钮的配色。**只有一处判断**，
        免得"语言选中了但排序没跟上"这类不一致。"""
        for button in self._language_buttons:
            button.variant = ("accent"
                              if button._language_value == self._choice
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

        # 每一行 = 标签 + 一组（可能折成多行的）分段按钮
        self._rows = (
            (self._label, [list(self._language_buttons)]),
            (self._sort_label, _wrap_buttons(self._sort_buttons, max_width,
                                             gap, row_height)),
            (self._direction_label,
             [list(self._direction_buttons)]),
        )
        # 每一块分段自己还要能横着放下
        widest = 0
        body_height = 0
        for label, chunks in self._rows:
            label_width = label.GetBestSize().width
            for chunk in chunks:
                buttons_width = (sum(b.GetBestSize().width for b in chunk)
                                 + gap * (len(chunk) - 1))
                widest = max(widest, label_width + gap + buttons_width)
                body_height += row_height + row_gap
            body_height += row_gap * (len(chunks) - 1)
        body_height -= row_gap                     # 末尾那一次多加的

        # 底部两个按钮那一排也要放得下。
        # **它通常比设置行窄**（2×96+8 = 200 逻辑 < 240），
        # 所以客户区宽度基本由设置行决定；只有按钮特别多时它才会顶上来。
        footer = (len(self._labels) * px(METRICS.dialog_button_width)
                  + max(len(self._labels) - 1, 0)
                  * px(METRICS.dialog_button_gap))
        client_width = max(min(widest, max_width) + margin * 2,
                           footer + margin * 2)

        self._body_rect = (margin, margin, client_width - margin,
                           margin + body_height)
        self._buttons_top = (margin + body_height
                             + px(METRICS.dialog_body_to_buttons))
        client_height = (self._buttons_top + row_height
                         + px(METRICS.dialog_bottom))
        self.SetClientSize((client_width, client_height))
        self._place_buttons()
        self._place_rows(row_height + row_gap)
        self._center_on_parent()

    def _place_rows(self, row_pitch: int) -> None:
        """标签靠左；分段按钮**右对齐**，放不下就换到下一行。

        （不用 sizer：基类已经把"手动摆放"这条路走通了，
        混用 sizer 会让 `wx.Dialog` 的尺寸计算插一脚。）
        """
        left, top, right, _bottom = self._body_rect
        gap = scale_for_dpi(METRICS.padding_gap, dpi_of(self))
        y = top
        for label, chunks in self._rows:
            label_height = label.GetBestSize().height
            label.SetPosition((left, y + (row_pitch - label_height) // 2))
            # 第一块与标签同一行；后续块换到下面
            first = True
            for chunk in chunks:
                row_top = y if first else y + row_pitch
                if not first:
                    y += row_pitch
                first = False
                width = chunk[0].GetBestSize().width
                height = chunk[0].GetBestSize().height
                total = width * len(chunk) + gap * (len(chunk) - 1)
                x = right - total
                for button in chunk:
                    button.SetSize(x, row_top, width, height)
                    x += width + gap
            y += row_pitch

    def _place_language_row(self) -> None:
        """兼容旧调用点：只摆语言那一行。"""
        if not hasattr(self, "_label"):
            return
        self._place_rows(scale_for_dpi(METRICS.dialog_button_height,
                                       dpi_of(self)))

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

    #: 提示语。**短到不会在窄输入框里被截断**——改长之前先量宽度。
    #: 提示文字。**用 L() 包起来**——这是运行时读取的（`self.HINT`），
    #: 不是模块级求值后就被冻结的常量。
    HINT = L("输入或粘贴路径", "Type or paste a path")

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
        只设 PathBar 不设 text_ctrl 的话，输入框看起来还是小一号（实测 9pt）。"""
        self.text_ctrl.SetFont(body)
        self.Refresh()

    def draw(self, dc) -> None:
        """给输入框画圆角描边——``wx.TextCtrl`` 自己画不出圆角。

        描边画在输入框**外面**一圈（构造时留了 2 逻辑像素的内边距），
        否则会被输入框自己的背景盖住。有焦点时用强调色：
        **这是"这里可以输入"的主要视觉线索。**
        """
        rect = self.text_ctrl.GetRect()
        colour = wx.Colour(
            self.theme.accent if self.text_ctrl.HasFocus() else self.theme.border
        )
        x, y = rect.x - 1, rect.y - 1
        w, h = rect.width + 2, rect.height + 2

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
            gc.SetPen(wx.Pen(colour))
            gc.DrawRoundedRectangle(x, y, w, h, METRICS.radius_field)
        else:
            # 取不到 GC 时退回 GDI（会有锯齿，但不会崩、也不会不画）
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.SetPen(wx.Pen(colour))
            dc.DrawRoundedRectangle(x, y, w, h, METRICS.radius_field)

    def SetHint(self, text: str) -> None:
        """换提示文字（**换语言时用**）。

        名字故意与 `wx.TextCtrl.SetHint` 一致，这样"设置提示"只有一种叫法；
        真正的实现是把提示转交给内部的文本框。
        """
        self.HINT = text
        self.text_ctrl.SetHint(text)
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
