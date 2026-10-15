"""视觉主题：Win11 风格，参数从系统读取。

规范来源：``D:\\Coding\\MyGitHub\\Roboc\\docs\\archive\\视觉规范.md``。
那是 Roboc（C# / Win32 自绘进度窗）的规范，其中**与语言无关、本项目直接沿用**的是：

| 规范条目 | 本项目怎么落实 |
|---|---|
| 配色从系统读取，不写死 | :func:`from_system` 读 ``AppsUseLightTheme`` 与 ``AccentColor`` |
| 字号以磅声明，正文 = 系统 UI 字号 | :meth:`Theme.body_font` 取 ``SYS_DEFAULT_GUI_FONT`` 磅值，不写死像素 |
| 强调色只给"程序推荐的那一个动作" | 只有"打开"按钮用强调色；清空按钮用危险色 |
| Win11 圆角 | :func:`file_tracker.win32.apply_rounded_corners` + 自绘控件圆角 |
| 自绘必须双缓冲 | :class:`~file_tracker.widgets.BufferedPanel` 用 ``wx.BufferedPaintDC`` |
| 深色主题要给标题栏单独声明 | :func:`file_tracker.win32.set_title_bar_dark`（DWM 绘制，自绘碰不到） |

**不沿用的部分**（那些是 Roboc 与其具体窗口绑定的）：纵向节奏表、速率曲线、
固定尺寸对话框、``WS_THICKFRAME`` 相关结论——File Tracker 是可调尺寸的文档窗口。

**所有数值在本文件声明一次，其它模块不得再出现字面量。**
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    """一套配色的全部取值。深浅两套由 :func:`from_system` 决定。

    ## 这是一套**手工调过**的中性配色，不是从系统强调色推导出来的

    用户 2026-10-15 的要求："一套真的配色方案（不是从系统色推出来的）"。

    原来的做法是"读系统强调色，再把它调亮/调暗当背景"——问题是
    **强调色是给按钮用的高饱和色**，拿它推导背景会得到一片蓝紫或橙，
    而且用户一改系统主题色整个界面就跟着变。现在：

    * **中性色（窗口底/卡片/表头/描边/正文）是手工定的**，与强调色无关
    * 强调色**只用于"程序推荐的那一个动作"**（"打开"按钮、输入框焦点描边）
    * 强调色读不到时用本文件里的兜底默认值

    ## 卡片分层

    ``background`` 是**窗口底色**，``card`` 是**内容区底色**。
    列表与目录树画在 ``card`` 上，按钮条与窗口留白用 ``background``——
    内容区因此像一张浮起来的卡片，而不是所有东西糊在同一层。

    浅色下卡片**更亮**（白卡浮在灰底上）；深色下卡片也**更亮**
    （``#242424`` 浮在 ``#191919`` 上）——两种主题都靠"提亮"表达浮起。
    """

    is_dark: bool
    # 表面
    background: str      # 窗口底色（卡片之外）
    card: str            # 卡片底色（列表/目录树画在这上面）
    surface_alt: str     # 表头、次级表面
    border: str          # 分隔线、卡片描边
    # 文字
    text: str            # 正文（主信息，如路径）
    text_secondary: str  # 次要信息（频次、时间）
    # 列表里路径列的文字色。
    #
    # 用户反馈："把所有路径记录条目文字颜色恢复为纯黑（浅色主题）/
    # 纯白（深色主题），灰色实在是不方便观察。"
    #
    # **与 `text` 分开是为了能单独调**：`text` 还管表头、弹窗正文、
    # 按钮文字；而列表内容用的是最纯的黑/白——长列表里纯色的
    # 可读性明显好于灰。
    list_text: str
    # 强调与状态
    accent: str          # 强调色：只给"推荐动作"
    accent_hover: str
    accent_text: str     # 画在强调色上的文字
    danger: str          # 危险动作（清空）
    pinned_row: str      # 置顶行的底色
    # **预选（悬停跟随）行的底色**——即用户说的"次级高亮"。
    #
    # 用户把需求分得很清楚："假设选中色有两档，高亮和次级高亮，
    # 鼠标左键单击后为高亮，鼠标移到目标上方不单击为次级高亮，
    # 这就是预选状态。"
    #
    # 两档分工：
    #   * 选中（高亮）  → `SYS_COLOUR_HIGHLIGHT`（`#0078D7`），系统色
    #   * 预选（次级）  → **本字段**，由本项目自绘
    #
    # ## 为什么预选要自己做，不用原生热跟踪
    #
    # 原生热跟踪（`LVS_EX_TRACKSELECT` / `*CLICKACTIVATE`）的表现
    # **依赖主题**，实测用户那边"深色有、浅色没有"，反复不一致。
    # 自己定色就没有这个不确定性：两个主题都是本字段说了算。
    row_hover: str
    # 列间竖线：**不能直接用 border**，浅色下 #DCDFE4 在白底上看不见
    separator: str       # 列间竖线
    # 自绘按钮
    button_normal: str
    button_hover: str
    button_pressed: str

    @staticmethod
    def light(accent: str = "#0F6CBD") -> "Theme":
        """浅色主题：冷中性灰，卡片比窗口底更亮。"""
        return Theme(
            is_dark=False,
            background="#F3F4F6",      # 窗口底：比卡片暗一档
            card="#FFFFFF",            # 卡片：列表/目录树
            surface_alt="#EEF0F3",     # 表头
            border="#DCDFE4",
            text="#1B1A19",
            text_secondary="#6B7280",  # 次要信息（频次、时间）
            # 列表内容用**纯黑**——用户要求灰色实在是不方便观察
            list_text="#000000",
            accent=accent,
            accent_hover=darken(accent, 0.12),
            accent_text="#FFFFFF",
            danger="#C42B1C",
            # ---- 置顶色：用户指定的观感，**不是按对比度算出来的** ----
            #
            # 用户先后说过"置顶行的底色不对"、"已置顶条目上的强调色消失"。
            # 我把它理解成**颜色选得不好**，于是量了对比度
            # （``#FFF8DC`` 与白底只有 1.065），换成更饱和的黄、
            # 又换成跟随强调色的浅蓝。
            #
            # 用户明确否决两次，最后说明："**不是你调色的问题，
            # 是此前不知道动错了哪些代码导致它失效。**"
            # ——真正失效的是"行属性根本没被应用"。
            # 后来又截图对比："你现在的黄色饱和度太低，适当提高。"
            #
            # **两条规矩**：① 用户说某个视觉元素不对时，先确认它**有没有被画出来**；
            # ② 颜色由用户定，**不要拿对比度计算去推翻它**。
            pinned_row="#FFFFB7",
            # 次级高亮：比选中蓝（#0078D7）明显淡，但白底上看得清。
            # 取 Win11 浅色主题悬停那一档的观感。
            row_hover="#DCE9F7",
            # 列间竖线：**不能直接用 border**——浅色下 #DCDFE4 在白卡上看不见，
            # 用户为此反馈过两次"三条间隔线浅色主题不可见"。
            separator="#C9CDD4",
            button_normal="#FFFFFF",
            button_hover="#F3F4F6",
            button_pressed="#E5E7EB",
        )

    @staticmethod
    def dark(accent: str = "#4CC2FF") -> "Theme":
        """深色主题：卡片比窗口底**更亮**（深色下"浮起来"同样靠提亮）。

        深色下强调色要比浅色更亮，否则在深底上对比度不足；
        但按钮上的文字要反过来用深色——浅蓝底配白字的对比度是不够的。
        """
        return Theme(
            is_dark=True,
            background="#191919",      # 窗口底
            card="#242424",            # 卡片：比窗口底亮一档
            surface_alt="#2E2E2E",     # 表头
            border="#3A3A3A",
            text="#F5F5F5",
            text_secondary="#A0A0A0",
            # 列表内容用**纯白**
            list_text="#FFFFFF",
            accent=accent,
            accent_hover=lighten(accent, 0.15),
            accent_text="#10222E",
            danger="#FF99A4",
            pinned_row="#3A3520",
            # 次级高亮（深色）：比选中蓝暗，但在 #242424 卡片上分得出。
            row_hover="#2B4A66",
            separator="#3F3F3F",
            button_normal="#2E2E2E",
            button_hover="#3A3A3A",
            button_pressed="#454545",
        )


def lighten(color: str, ratio: float) -> str:
    """把颜色朝白色推进 ``ratio``（0..1）。数值越大越浅。"""
    return _blend(color, "#FFFFFF", ratio)


def darken(color: str, ratio: float) -> str:
    """把颜色朝黑色推进 ``ratio``（0..1）。"""
    return _blend(color, "#000000", ratio)


def _blend(color: str, target: str, ratio: float) -> str:
    """在两个 ``#RRGGBB`` 之间线性插值。"""
    ratio = max(0.0, min(1.0, float(ratio)))
    source_rgb = _parse_hex(color)
    target_rgb = _parse_hex(target)
    if source_rgb is None or target_rgb is None:
        return color
    blended = tuple(
        int(round(a + (b - a) * ratio)) for a, b in zip(source_rgb, target_rgb)
    )
    return "#{:02X}{:02X}{:02X}".format(*blended)


def _parse_hex(color: str) -> tuple[int, int, int] | None:
    """``#RRGGBB`` → ``(r, g, b)``；解析失败返回 ``None``。"""
    if not isinstance(color, str):
        return None
    text = color.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def from_system() -> Theme:
    """按当前系统主题与强调色构造 :class:`Theme`。

    **不缓存**：主题可以在运行期间被用户改掉，窗口重新激活时重读一次的成本
    是一次注册表查询，可忽略。
    """
    from . import win32

    accent_rgb = win32.system_accent_color()
    if win32.system_uses_light_theme():
        if accent_rgb:
            return Theme.light("#{:02X}{:02X}{:02X}".format(*accent_rgb))
        return Theme.light()

    if accent_rgb:
        # 深色主题下把强调色提亮，否则在深底上对比不足
        brightened = lighten("#{:02X}{:02X}{:02X}".format(*accent_rgb), 0.35)
        return Theme.dark(brightened)
    return Theme.dark()


# --------------------------------------------------------------------------
# 间距与圆角：以 96 DPI 逻辑像素声明
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Metrics:
    """间距与圆角。以 96 DPI 逻辑像素声明，用时按 DPI 换算。

    **尺寸基准是"原生按钮有多大"，不是拍脑袋定的数。**
    实测本机原生 ``wx.Button`` 是 75×25（96 DPI 等价），
    所以按钮高度取 24、内边距 12 —— 与系统按钮同一量级。
    第一版写的是 32，在 175% 缩放下变成 56 物理像素，用户反馈"偏大"。
    """

    # 圆角。
    #
    # 调过多次，用户的要求是"循序渐进，不要一次调太多"：
    #   第一版 4  → 高 24 时比例 0.167，用户说"太小，看不出来"
    #   第二版 12 → 高度的一半（胶囊形），用户说"太大"
    #   第三版 8  → 比例 0.333，用户说"圆角过大"
    #   第四版 6  → 用户说"继续收到 5"
    #   第五版 5  → 用户又说"感觉圆角又太小了，回调到 6"
    #   第六版 6  → 用户仍觉得小
    #   现在   8  → **用户在源码里自己改定的**（本行）
    #
    # **8 是用户亲手改的，不要再替他调整。**
    # 这个值在 5 / 6 / 8 之间来回过，纯粹是主观观感，没有客观最优解。
    #
    # ## 为什么从"比例"改成"绝对值"
    #
    # 用户要求"统一参数"。用比例（`5/24`）时，只有高度是 24 的整数倍
    # 才正好得到 5，其它高度会因取整得到 4 或 6 —— **不同按钮的
    # 实际圆角就不一样了**，与"统一参数"矛盾。
    #
    # 改成绝对值后，任何高度的按钮圆角**都是同一个值**，这才是"统一"。
    # （本机 175% 下 8 逻辑 = 14 物理像素。）
    #
    # 说明：Win11 原生按钮是固定的 **4 物理像素**、不随 DPI 变。
    # 本项目按逻辑像素 × DPI 走，要更接近原生就把这个数往下调。
    radius_button: int = 8
    radius_field: int = 6
    # 内边距
    #
    # **统一到 4 像素的间距网格。** 用户要求"统一间距与对齐网格"。
    # 原来各处是零散的 6/8/10（`padding_gap=6`、`padding_window=10`…），
    # 现在所有间距都是 4 的倍数：4 / 8 / 12 / 16 / 24。
    # **加新间距时从这组数里取，不要随手写 7 或 11。**
    padding_window: int = 12     # 窗口四周
    padding_control_x: int = 12  # 控件内部横向
    padding_control_y: int = 8   # 控件内部纵向
    padding_gap: int = 8         # 控件之间
    padding_tight: int = 4       # 紧凑间隔（卡片内缘等）
    # 控件高度（对照原生按钮 25 逻辑像素）
    button_height: int = 24
    button_min_width: int = 64
    # 弹窗尺寸与间距
    #
    # **数值全部照抄 Roboc 的原生对话框**（`Roboc/src/Roboc.App/MessageDialog.cs`
    # 的构造函数）。用户问"Roboc 的所有窗口外观为什么规范又漂亮"，
    # 答案就是：**它不用任何自动布局，所有位置都按一个固定公式手算**。
    #
    # 我原来那一版用"堆 sizer + Fit()"，结果是 455×228——比原生对话框
    # 又宽又矮，而且多了一行我自己加的粗体标题（原生确认框没有这一行）。
    #
    # Roboc 原值（逻辑像素，96 DPI）：
    #   margin = 24, maxTextWidth = 420, buttonHeight = 32, buttonWidth = 96,
    #   gap = 8, bodyTop = 24, body→buttons = 28, 底部 = 20
    dialog_margin: int = 24
    dialog_max_text_width: int = 420
    dialog_button_width: int = 96
    dialog_button_height: int = 32
    dialog_button_gap: int = 8
    dialog_body_to_buttons: int = 28
    dialog_bottom: int = 20
    icon_button_padding: int = 5
    icon_target_size: int = 20
    # 地址栏
    #
    # 用户先说"太矮"，加高到 30；再说"过高，适当降低高度与框内文字匹配"。
    # 现在按"文字高 + 上下各 4"算，不再用固定值——固定值总会与文字对不上。
    path_bar_text_inset: int = 4   # 输入框上下各留多少（逻辑像素）
    path_bar_min_height: int = 24  # 下限
    # 列表行距（Win11 观感：行更透气）
    #
    # 用户反馈"适当微调路径记录之间的间隔，使其上下间隔更大"。
    # 这个值通过 LVM_SETITEMSPACING 施加（见 app.apply_window_theme），
    # 单位是"在默认行高之上额外增加的像素"。步长 ±2，别一次加太多。
    list_item_extra_height: int = 6
    # 列表字号在系统默认之上加多少磅
    #
    # 用户反馈"路径记录的字体请增加 1pt"。原版列表是系统默认字体（9pt），
    # 这里明确 +1。**注意列表与列头仍不是"正文 +1"那条链**——
    # 正文是另一套（body_font），这里只针对列表。
    list_font_point_delta: int = 1
    # 自绘表头
    #
    # 用户反馈"频次"的排序小三角被列间竖线切到了——原因是竖线画在
    # ``x + column_width - 1``，而三角就在标题文字的末尾，两者撞上了。
    # 所以：表头留出更多右侧空间，竖线也从**列的最右边**往左挪一点。
    header_padding: int = 5
    header_min_height: int = 28
    header_text_inset: int = 7     # 标题距列左边的距离
    header_separator_inset: int = 0  # 竖线距列右边的距离（避开排序三角）
    # 目录树最小宽度
    tree_min_width: int = 300
    # 自己画的分隔线粗细（sash 那条白线被隐藏了，见 widgets.BorderLine）
    #
    # **单位是物理像素，不按 DPI 缩放。**
    #
    # 用户要求"改细，最细"。1 个**物理**像素是能做到的极限——
    # 若按 DPI 缩放，本机 175% 下 `scale_for_dpi(1, 168)` 会变成 **2**，
    # 那是之前的样子（用户嫌粗）。
    #
    # 分界线与"内容尺寸"不同：**1 像素的细线是显示器的属性，不是内容的属性**，
    # 所以这里刻意不做 DPI 换算。见 `header.separator_thickness()`
    # 与 `app._paint_column_separators`。
    separator_thickness: int = 1
    sash_position: int = 400
    # 窗口与屏幕边缘之间留出的安全边距（逻辑像素，用时按 DPI 换算）
    window_margin: int = 8

    def button_radius_for(self, height: int) -> int:
        """按钮圆角半径，**逻辑像素**，与按钮高度无关。

        ## 为什么不再按高度算比例

        用户要求"所有按钮圆角过大，**统一参数**、适当缩小圆角"。

        前几版用的是**比例**（`radius_button_ratio`）。比例的问题在于：
        只有高度恰好的整数倍时才得到目标半径，其它高度会因取整
        得到相邻值 —— **不同按钮的实际圆角就不一样了**，
        与"统一参数"直接矛盾。

        现在改成**绝对值** :attr:`radius_button`，任何高度的按钮
        圆角都等于它。`height` 参数保留只是为了调用点统一、
        以及留一个将来"极小按钮要收一点"的余地。

        历次取值（用户逐次亲手确认）：
        4（"太小，看不出来"）→ 12（胶囊形，"太大"）→ 8（"圆角过大"）
        → 6 → 5（"又太小了"）→ 6 → **8（用户自己改定）**。

        > **8 是用户自己在源码里改定的**（`radius_button: int = 8`）。
        > 中间在 5 / 6 / 8 之间来回过几次，说明这纯粹是主观观感，
        > **不要再"替用户觉得合适"地改动它**。

        附：Win11 原生按钮是固定的 **4 物理像素**、不随 DPI 变；
        本项目按"逻辑像素 × DPI"走，本机 175% 下 8 逻辑 = 14 物理。
        """
        radius = max(int(self.radius_button), 1)
        # 半径不能超过半个高度，否则圆角会互相吃掉变成畸形
        return max(min(radius, max(height // 2, 1)), 1)


METRICS = Metrics()


def scale_for_dpi(pixels: int, dpi: int) -> int:
    """把 96 DPI 逻辑像素换算成目标 DPI 下的物理像素。

    规范第一节：**物理像素不是尺寸单位，是显示器的单位。**
    在 175% 缩放的机器上按 96 DPI 写死的数值会小 75%。
    """
    if dpi <= 0:
        dpi = 96
    return int(round(pixels * dpi / 96.0))


def point_size_for_dpi(points: float, dpi: int) -> int:
    """把磅值换算成像素字高（负值形式，供 ``wx.Font`` 使用）。"""
    if dpi <= 0:
        dpi = 96
    return -int(round(points * dpi / 72.0))


# --------------------------------------------------------------------------
# 关于 DPI 的一个坑（结论留在这里，实现在 widgets.dpi_of）
# --------------------------------------------------------------------------
#
# **不要用 ``wx.Window.FromDIP`` 去算控件的尺寸。** 它在控件还没完成父级
# 绑定时会退回 96。实测同一个按钮：
#
#   * 直接跑（未开 per-monitor DPI 感知）→ ``FromDIP(24)`` 得 24
#   * 由 ``tools/verify_gui.ps1`` 跑（先调 ``SetProcessDpiAwareness(2)``）
#     → ``FromDIP(24)`` 得 **42**
#
# 两个数字都对不上，因为 ``FromDIP`` 问的是"这个控件现在挂在哪个窗口上"，
# 而构造函数里控件还没挂上去。用户看到的就是"按钮偏大"。
#
# 正确做法是主动问**父窗口**的 DPI，实现在
# :func:`file_tracker.widgets.dpi_of`——它必须 import wx，所以放在
# widgets 里而不是本模块：**本模块的约定是不依赖 wx**，
# ``tests/test_core.py::test_module_does_not_import_wx`` 守着这条。
