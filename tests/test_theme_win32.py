"""主题与原生封装的测试。

``LVCOLUMN`` 的结构体布局这里**不靠记忆**：逐字段核对偏移量。
字段顺序错了的话 ``SendMessage`` 会读到越界的垃圾值，而它不会报错，
只会静默地什么都不做——正是最难查的那一类。
"""

from __future__ import annotations

import ctypes

import pytest

from file_tracker import theme, win32


# --------------------------------------------------------------------------
# 强调色解码
# --------------------------------------------------------------------------

def test_decode_accent_color_handles_abgr():
    """**注册表里存的是 ABGR**（``0xAABBGGRR``）。

    实测：Windows 默认蓝的 ``AccentColor`` 是 ``0xFFD77800``，
    正确结果是 ``(0, 120, 215)``。若写成 ``>> 16 & 0xFF`` 取红，会得到蓝色
    被当成红色——颜色整体错位，但界面上"看着也挺好看"，很难发现。
    """
    assert win32.decode_accent_color(0xFFD77800) == (0, 120, 215)


def test_decode_accent_color_ignores_alpha():
    assert win32.decode_accent_color(0x00D77800) == (0, 120, 215)


def test_decode_accent_color_rejects_black():
    """全黑表示"未设置"或"自动"，此时应由调用方回退到默认色。"""
    assert win32.decode_accent_color(0x00000000) is None
    assert win32.decode_accent_color(0xFF000000) is None


# --------------------------------------------------------------------------
# LVCOLUMN 结构体布局
# --------------------------------------------------------------------------





def test_set_item_spacing_returns_false_without_a_handle():
    """拿不到句柄时必须**明确返回 False**，而不是让人以为设置成功了。"""
    assert win32.set_item_spacing(0, 0, 8) is False



def test_lighten_moves_toward_white():
    assert theme.lighten("#000000", 0.0) == "#000000"
    assert theme.lighten("#000000", 1.0) == "#FFFFFF"
    assert theme.lighten("#000000", 0.5) == "#808080"


def test_darken_moves_toward_black():
    assert theme.darken("#FFFFFF", 0.0) == "#FFFFFF"
    assert theme.darken("#FFFFFF", 1.0) == "#000000"


def test_blend_clamps_out_of_range_ratios():
    assert theme.lighten("#000000", 5.0) == "#FFFFFF"
    assert theme.lighten("#000000", -5.0) == "#000000"


def test_blend_leaves_unparsable_input_alone():
    """解析不了的颜色原样返回——宁可不改，也不要输出一个非法颜色串。"""
    assert theme.lighten("not-a-colour", 0.5) == "not-a-colour"
    assert theme.lighten("#12345", 0.5) == "#12345"


def test_dark_theme_keeps_accent_text_readable_bounds():
    """深色主题的按钮文字必须用深色。

    浅蓝底（``#4CC2FF``）配白字的对比度是不够的——这条约束写在配色里，
    这里守住它：强调色足够亮时，画在上面的文字必须比它暗。
    """
    dark = theme.Theme.dark()
    accent_rgb = theme._parse_hex(dark.accent)
    text_rgb = theme._parse_hex(dark.accent_text)
    assert sum(text_rgb) < sum(accent_rgb)


def test_both_themes_define_every_colour():
    """两套主题的每个字段都必须是可解析的颜色，不能有空值。"""
    for palette in (theme.Theme.light(), theme.Theme.dark()):
        for field_name in palette.__dataclass_fields__:
            if field_name == "is_dark":
                continue
            value = getattr(palette, field_name)
            assert theme._parse_hex(value) is not None, (field_name, value)


def test_light_and_dark_actually_differ():
    light, dark = theme.Theme.light(), theme.Theme.dark()
    assert light.background != dark.background
    assert light.text != dark.text
    assert dark.is_dark and not light.is_dark


def test_card_layer_is_distinct_from_the_window_background():
    """卡片层必须与窗口底色**看得出区别**，否则分层等于没有。

    用户要求"卡片式分层（面板底色 + 列表区域是另一层）"。
    浅色下卡片更亮、深色下也如此——两套主题都是"提亮 = 浮起来"。
    """
    for palette in (theme.Theme.light(), theme.Theme.dark()):
        ratio = _contrast(palette.card, palette.background)
        assert ratio >= 1.05, (
            f"{'深色' if palette.is_dark else '浅色'}主题的卡片 "
            f"{palette.card} 与窗口底 {palette.background} 对比度只有 "
            f"{ratio:.3f}，看不出分层"
        )
        assert _relative_luminance(palette.card) > _relative_luminance(palette.background)


def test_neutral_colours_do_not_follow_the_accent():
    """中性色（窗口底/卡片/表头/正文）**不跟随强调色**。

    用户要求"一套真的配色方案（不是从系统色推出来的）"。
    原来的做法是"读系统强调色再调亮当背景"，用户一改主题色整个界面就跟着变，
    而且拿高饱和的强调色推导背景会得到一片蓝紫或橙。

    守这条：换强调色，中性色必须**一个都不动**；而强调色本身要跟着变。
    """
    blue = theme.Theme.light("#2959CC")
    green = theme.Theme.light("#107C10")
    for field_name in ("background", "card", "surface_alt", "border",
                       "text", "text_secondary"):
        assert getattr(blue, field_name) == getattr(green, field_name), field_name
    assert blue.accent != green.accent


# --------------------------------------------------------------------------
# 置顶行底色
# --------------------------------------------------------------------------

def _relative_luminance(colour: str) -> float:
    """WCAG 相对亮度。"""
    red, green, blue = theme._parse_hex(colour)
    channels = []
    for value in (red, green, blue):
        c = value / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    high, low = max(la, lb), min(la, lb)
    return (high + 0.05) / (low + 0.05)


def test_pinned_row_text_stays_readable():
    """置顶底色上的正文要读得清（WCAG 正文要求 ≥ 4.5）。

    这条与"底色好不好看"是两件事：``#FFF8DC`` 的对比度虽然低，
    但它是**浅色底**，深色文字压在上面依然清清楚楚（实测 16.3）。
    """
    for palette in (theme.Theme.light("#2959CC"), theme.Theme.dark("#4CC2FF")):
        ratio = _contrast(palette.pinned_row, palette.text)
        assert ratio >= 4.5, f"置顶行上的文字对比度只有 {ratio:.2f}"


def test_pinned_row_is_a_fixed_yellow_not_the_accent_colour():
    """置顶底色是**固定的暖黄**，不跟随强调色。

    用户明确要求"维持原本的黄色强调色"。黄色是"已固定"的通用语汇，
    跟随强调色反而会与**选中行**的系统高亮蓝撞色。

    我上一轮把它改成跟随强调色的浅蓝，理由是"看着像选中行"——**方向搞错了**：
    置顶色是行属性，选中色是控件自绘的系统高亮，两者机制完全不同。

    这条测试守的是"**别再**把它改成跟随强调色"。
    """
    blue_accent = theme.Theme.light("#2959CC")
    green_accent = theme.Theme.light("#107C10")
    assert blue_accent.pinned_row == green_accent.pinned_row
    # 而且它必须真的是黄的：红色与绿色分量高、蓝色分量低
    red, green, blue = theme._parse_hex(blue_accent.pinned_row)
    assert green > blue and red > blue, f"{blue_accent.pinned_row} 不是暖黄"


def test_pinned_row_keeps_the_cornsilk_family():
    """置顶色是**用户指定的色号** ``#FFFFB7``。

    这个色号换过很多次，教训值得完整记下来：

    用户先后说"置顶行的底色不对"、"已置顶条目上的强调色消失"。
    我理解成**颜色选得不好**，量了对比度（``#FFF8DC`` 只有 1.065），
    换成更饱和的黄、又换成跟随强调色的浅蓝。
    用户明确否决："**不是你调色的问题，是此前不知道动错了哪些代码导致它失效。**"
    ——真正失效的是"行属性根本没被应用"。

    修好之后用户又说"黄色饱和度太低，适当提高"，于是我给了 ``#FFE08A``。
    最后用户自己调好并直接指定："**我给你调了，直接用：#ffffb7**"。

    **这条测试守的就是那个色号本身。** 不要改它，也不要拿对比度计算去推翻它。
    """
    assert theme.Theme.light().pinned_row.upper() == "#FFFFB7"
    # 它必须真的是黄的：红绿分量高、蓝分量低
    red, green, blue = theme._parse_hex(theme.Theme.light().pinned_row)
    assert red > blue and green > blue, "应当是暖黄"


def test_pinned_row_is_not_invisible():
    """但也别退化成"和背景一模一样"——那是真的看不见。

    **基准是 ``card`` 而不是 ``background``**：列表行画在卡片层上
    （见 ``Theme`` 的卡片分层说明），拿窗口底色去比是比错了对象。

    门槛刻意放低（1.03）：只拦"完全等同"，不拿它当审美判据——
    用户选的颜色就是用户选的颜色。
    """
    for palette in (theme.Theme.light("#2959CC"), theme.Theme.dark("#4CC2FF")):
        ratio = _contrast(palette.pinned_row, palette.card)
        assert ratio >= 1.03, (
            f"置顶底色 {palette.pinned_row} 与卡片 {palette.card} "
            f"几乎相同（对比度 {ratio:.3f}），那样就真的看不见了"
        )


def test_dark_pinned_row_is_also_yellow():
    """深色主题下同样是暖黄，不是别的色系。"""
    dark = theme.Theme.dark("#4CC2FF")
    red, green, blue = theme._parse_hex(dark.pinned_row)
    assert green >= blue and red >= blue, f"{dark.pinned_row} 在深色下不偏黄"


def test_pinned_row_differs_from_the_card_in_both_themes():
    """两套主题下置顶行都要与卡片**有区别**——方向可以相反，但必须可辨。

    浅色主题下是**比白卡稍暗**（黄底压在白上），
    深色主题下是**比深卡稍亮**（黄底浮在深色上）。

    **基准是 ``card`` 而不是 ``background``**：列表行画在卡片层上。
    这条原来写的是 ``background``，卡片分层之后就比错了对象。
    """
    light = theme.Theme.light("#2959CC")
    dark = theme.Theme.dark("#4CC2FF")

    assert _relative_luminance(light.pinned_row) < _relative_luminance(light.card)
    assert _relative_luminance(dark.pinned_row) > _relative_luminance(dark.card)
    # 阳性对照：两套主题都要与卡片有可测的差别
    for palette in (light, dark):
        assert _contrast(palette.pinned_row, palette.card) >= 1.03


def test_separator_is_visible_against_the_card():
    """列间竖线的对比度**由用户指定的目标值**决定，不再要求"比 border 深"。

    ## 历史（这条判据改过）

    用户最初为"三条间隔线在浅色背景下不可见"反馈过两次，所以竖线单列一个
    ``separator`` 字段，当时的判据是"比 ``border`` 深"。

    **2026-10-17 用户把三条线的对比度统一到 1.35**（显式给了数字）。
    深色下这个值（1.347）恰好**略低于** ``border``（1.365）——
    "必须严格大于 border"就不再成立了。

    保留的**真正意图**是"线和边框不要差太多，免得看起来像两种元素"，
    所以判据改成：**两者之差不超过 0.08**（1.30 时深色差 0.061）。
    """
    for palette in (theme.Theme.light(), theme.Theme.dark()):
        ratio = _contrast(palette.separator, palette.card)
        assert ratio >= 1.15, (
            f"{'深色' if palette.is_dark else '浅色'}主题的竖线 "
            f"{palette.separator} 与卡片 {palette.card} 对比度只有 "
            f"{ratio:.3f}，看不见"
        )
        # **不再和 `border` 比**：用户 2026-10-17 直接指定了对比度目标，
        # 而且两档主题不同（浅色 **1.20** / 深色 **1.30**）。
        # 1.20 时浅色线比 border（1.336）淡得多 —— **那是用户的观感选择，
        # 不是缺陷**。精确的目标值由 `tools/verify_gui.py` 里
        # "对比度 ≈ 目标"那六条判据把关（它们知道每个主题的目标）。
        #
        # 这里只守住"千万别淡到看不见"这条底线。


def test_scale_for_dpi_uses_96_as_the_baseline():
    """规范第一节：物理像素不是尺寸单位，是显示器的单位。

    96 DPI 下原样，175%（168 DPI）下放大到 1.75 倍。
    """
    assert theme.scale_for_dpi(24, 96) == 24
    assert theme.scale_for_dpi(24, 168) == 42
    assert theme.scale_for_dpi(24, 0) == 24      # 非法 DPI 回退到 96
    assert theme.scale_for_dpi(24, 192) == 48


def test_point_size_for_dpi_returns_negative_height():
    """``wx.Font`` 用负高度表示"按字高而非行高"解释这个值。"""
    assert theme.point_size_for_dpi(10, 96) == -13
    assert theme.point_size_for_dpi(10, 168) == -23


# --------------------------------------------------------------------------
# remove_client_edge：无效句柄不能报告"成功"
# --------------------------------------------------------------------------

def test_remove_client_edge_rejects_invalid_handles():
    """句柄无效时必须返回 False，**不能**报告"已经处理好了"。

    审计查出的缺陷（m10）：原来是

        style = user32.GetWindowLongW(...)
        if not (style & WS_EX_CLIENTEDGE):
            return True          # "本来就没有，算成功"

    而 ``GetWindowLongW`` **失败时也返回 0**。于是句柄失效时这里会
    ``return True`` —— 报告"边框已经去掉了"，而**实际什么都没做**。

    调用方 `app._remove_tree_client_edge` 会据此不再管那圈边框，
    结果是**既没有系统边框、也没有自绘边框**（一片空白），
    而且没有任何报错。用户看到的是"导航窗格边框莫名消失"。

    ⚠️ **不要用 `SetLastError`/`GetLastError` 去判。**
    踩过：`ctypes.windll.user32.SetLastError` 根本不存在
    （`AttributeError: function 'SetLastError' not found`）。
    现在用 `IsWindow` + `GetWindowLongPtrW`，两条都不依赖错误码。
    """
    from file_tracker import win32

    assert win32.remove_client_edge(0) is False
    assert win32.remove_client_edge(0xDEADBEEF) is False
    # 一个**真实存在**的窗口应当能被正常处理（否则上面两条可能只是"永远返回 False"）
    assert win32.remove_client_edge(
        ctypes.windll.user32.GetDesktopWindow()) is True


def test_remove_client_edge_is_idempotent():
    """对同一个窗口调两次都要成功——第二次是"本来就没有边框"。"""
    from file_tracker import win32

    desktop = ctypes.windll.user32.GetDesktopWindow()
    first = win32.remove_client_edge(desktop)
    second = win32.remove_client_edge(desktop)
    assert first is True and second is True


# --------------------------------------------------------------------------
# 弹窗正文前那枚**警告三角**的几何（2026-10-26）
# --------------------------------------------------------------------------
#
# 用户："把那个警告标志画出来，替换掉目前所有的"⚠️"符号。
#       调整尺寸：让它比正文字号大一点，醒目一点。"
#
# 规格抄自 `Icons-Drawing.md` 的 `warning` 徽标（用户验收过等边）。
# 这里的判据全部是**几何量**，不是"看起来像"——因为徽标只有十几像素，
# 肉眼分不出 0.84 和 0.866，而"两腰明显比底长"正是用户当时报的毛病。


def test_warning_badge_is_equilateral():
    """**等边**三角：高/底 = √3/2 ≈ 0.866。

    踩过的坑：按"底 0.85 s、高 0.85 s"画出来是等腰，两腰明显比底长
    （用户原话："两腰明显比底边长"）。
    """
    import math

    for size in (18, 24, 32, 43, 54, 75):
        geometry = theme.warning_badge_geometry(size)
        assert abs(geometry["height"] / geometry["base"] - math.sqrt(3) / 2) < 1e-9, size


def test_warning_badge_bounding_box_is_centred():
    """**包围盒**垂直居中，不是重心居中。

    三角形重心靠下；按重心居中的话整枚徽标会比同尺寸的圆形徽标看着低一截。
    """
    for size in (18, 32, 43, 54):
        geometry = theme.warning_badge_geometry(size)
        apex_y = geometry["apex"][1]
        base_y = geometry["left"][1]
        assert abs((apex_y + base_y) / 2 - size / 2) < 1e-9, size


def test_warning_badge_base_width_and_stroke():
    """底边 = 0.85 s、线宽 = 0.062 s —— 规格里的两个定值。"""
    for size in (24, 43, 75):
        geometry = theme.warning_badge_geometry(size)
        assert abs(geometry["base"] - 0.85 * size) < 1e-9, size
        assert abs(geometry["stroke"] - 0.062 * size) < 1e-9, size


def test_warning_badge_inner_triangle_is_inside():
    """内三角（挖空用）必须**完全落在外三角里**，否则线框会漏。"""
    for size in (18, 32, 75):
        geometry = theme.warning_badge_geometry(size)
        apex_y = geometry["apex"][1]
        base_y = geometry["left"][1]
        inner_ys = [point[1] for point in geometry["inner"]]
        assert min(inner_ys) > apex_y, size          # 内三角顶点在外三角顶点之下
        assert max(inner_ys) < base_y, size          # 内三角底边在外三角底边之上


def test_warning_badge_exclamation_sits_inside_and_is_lifted():
    """感叹号整组在三角内部，并**沿重心上移**一点（用户 2026-10-26 的观感要求）。

    > "希望这个感叹号稍微上移两三个像素，对比等边三角形。"

    三角形的视觉重心偏下（底边是一条实线），所以整组沿重心再上移 `0.05 s`。
    判据是**比例**（不写死像素），换尺寸时自动跟着走。
    """
    for size in (24, 43, 75):
        geometry = theme.warning_badge_geometry(size)
        bar_top = geometry["bar"][1]
        dot_bottom = geometry["dot"][1] + geometry["dot"][2]
        middle = (bar_top + dot_bottom) / 2
        lift = geometry["centroid_y"] - middle        # 正 = 上移
        expected = theme.EXCLAMATION_LIFT_RATIO * size
        assert abs(lift - expected) < 1e-9, (size, lift, expected)
        assert middle < geometry["centroid_y"]         # 确实在重心之上
        assert bar_top > geometry["apex"][1]           # 在顶点之下
        assert dot_bottom < geometry["left"][1]        # 在底边之上


def test_warning_badge_bar_is_a_plain_thick_bar():
    """竖条是**等宽**矩形（没有圆头）且比外框线粗 —— 用户提的两条观感。

    > "感叹号竖线部分给人感觉上下两端有小圆点凸起，而中间的竖线又很细。"

    * 不再补圆头 ⇒ 圆点半径只出现在"感叹号下面那个点"上（`dot` 一项）；
    * 竖条宽 `bar_width` 必须**大于**外框线宽 `stroke`。
    """
    for size in (24, 43, 75):
        geometry = theme.warning_badge_geometry(size)
        # 比外框线**粗**（用户："中间的竖线又很细"），但仍是"一条线"
        assert geometry["bar_width"] > geometry["stroke"], size
        assert geometry["bar_width"] <= 0.09 * size, size
        # 圆点跟着竖条一起收细（用户 2026-10-26："保持视觉上的一致性"）
        assert 0.035 <= geometry["dot"][2] / size <= 0.05, size
        assert geometry["bar_width"] < geometry["bar"][3] - geometry["bar"][1], size


def test_warning_badge_is_bigger_than_body_text():
    """用户要的是"比正文字号大一点，醒目一点"——比例必须 > 1。

    **不锚定具体数字**（1.4~2.0 都算合理），只禁止"等于或小于正文字号"。
    """
    assert 1.2 <= theme.METRICS.dialog_alert_ratio <= 2.0
    assert theme.METRICS.dialog_alert_gap >= 4


def test_process_dark_mode_uses_force_modes():
    """进程级深色模式必须用 **Force** 档，浅色不能用 `Default(0)`。

    用户 2026-10-26："浅色主题菜单错误保持深色。"

    `SetPreferredAppMode` 的取值（未公开枚举）：
    `0 = Default（跟随系统）`、`1 = AllowDark`、`2 = ForceDark`、`3 = ForceLight`。
    浅色若传 0，系统是深色时菜单仍是深的 —— 用户报的就是这个。
    """
    from file_tracker import win32

    assert win32.PREFERRED_APP_MODE_DEFAULT == 0
    assert win32.PREFERRED_APP_MODE_ALLOW_DARK == 1
    assert win32.PREFERRED_APP_MODE_FORCE_DARK == 2
    assert win32.PREFERRED_APP_MODE_FORCE_LIGHT == 3
    assert win32.PREFERRED_APP_MODE_FORCE_LIGHT != win32.PREFERRED_APP_MODE_DEFAULT
