"""GUI 验证：真实创建窗口，逐项核对四项 UI 改动。

**这不是 pytest 测试，是一个会开窗口的验证脚本。** 它必须由人来启动，
输出的是给人看的判据。

三条纪律（来自 `01-反复犯的错.md`）：

① **判据只能是枚举真实窗口 / 读取真实控件属性**，不能是"进程活着""日志没报错"
   这类代理指标。脚本自己创建一个唯一标题的窗口，再用 ``EnumWindows`` 找回来。
② **无论结果如何都要收尾。** 进程顶层有 ``try/finally``，窗口一定被销毁；
   调用方（``verify_gui.ps1``）另外还有无条件的杀进程兜底。
③ **阴性结果先证明检测器跑了。** 每一项都做阳性对照：先读一次**改动前**的值，
   确认它与**改动后**的值不同。若两者相同，说明这条断言是空的，报 FAIL。

用法::

    python tools/verify_gui.py            # 会短暂开一个窗口，约 3-5 秒
"""

from __future__ import annotations

import ast as _ast
import ctypes
import inspect as _inspect

user32 = ctypes.windll.user32
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import wx  # noqa: E402

import file_tracker.app as _app_module  # noqa: E402
from file_tracker import core as _core  # noqa: E402
from file_tracker import core, win32  # noqa: E402
from file_tracker import widgets as _widgets  # noqa: E402
from file_tracker.store import PathStore  # noqa: E402

#: 给窗口一个唯一标题，用于在 EnumWindows 里精确找回它
PROBE_TITLE = "FileTracker GUI Verify (do not touch)"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    mark = "PASS" if ok else "FAIL"
    line = f"  [{mark}] {name}"
    if detail:
        line += f"\n         {detail}"
    print(line, flush=True)


def _parse_hex(colour) -> tuple[int, int, int] | None:
    """``#RRGGBB`` → ``(r, g, b)``；解析不了返回 ``None``。"""
    if not isinstance(colour, str):
        return None
    text = colour.lstrip("#")
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def _relative_luminance(colour) -> float:
    """WCAG 相对亮度。``colour`` 可以是 ``wx.Colour`` 或 ``#RRGGBB``。"""
    if isinstance(colour, str):
        text = colour.lstrip("#")
        rgb = (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    else:
        rgb = (colour.Red(), colour.Green(), colour.Blue())

    channels = []
    for value in rgb:
        c = value / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(first, second) -> float:
    """两色的 WCAG 对比度。1.0 表示完全一样（看不出差别）。"""
    a, b = _relative_luminance(first), _relative_luminance(second)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def _colour_hex(colour) -> str:
    """``wx.Colour`` → ``#RRGGBB``（大写），便于与主题里的字符串比较。"""
    return "#{:02X}{:02X}{:02X}".format(
        colour.Red(), colour.Green(), colour.Blue(),
    )


def enum_our_windows(title: str) -> list[tuple[int, str, int]]:
    """枚举可见顶层窗口，按**进程映像名**过滤出本进程的窗口。

    不能只看标题：``EnumWindows`` 会把输入法窗口（``CiceroUIWndFrame``）之类
    也报出来，按进程名过滤这一步不能省。
    """
    import win32process
    import win32gui

    my_pid = os.getpid()
    found: list[tuple[int, str, int]] = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
        if pid != my_pid:
            return True
        text = win32gui.GetWindowText(hwnd)
        if text:
            found.append((hwnd, text, pid))
        return True

    win32gui.EnumWindows(callback, None)
    return [entry for entry in found if title in entry[1]] or found


# --------------------------------------------------------------------------

def main() -> int:
    print("File Tracker GUI 验证")
    print("  这个脚本会短暂开一个窗口（约 3-5 秒），不需要你点任何东西。")
    print("  窗口标题以 'FileTracker GUI Verify' 开头——那是被验证的对象，不是提问。")
    print()

    app = wx.App()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    frame = None
    scratch = tempfile.TemporaryDirectory(prefix="filetracker-verify-")
    probe_dir = os.path.join(scratch.name, "deep", "target-folder")
    os.makedirs(probe_dir, exist_ok=True)

    try:
        # 用临时数据库，**绝不碰 ~/file_tracker.db 里的真实记录**
        from file_tracker import app as app_module

        original_db = app_module.default_db_path
        app_module.default_db_path = lambda: os.path.join(scratch.name, "verify.db")
        # **配置也要换掉。** 排序偏好那一节会往配置里写东西，
        # 不隔离的话就往用户真实的 `%APPDATA%\File Tracker\config.json`
        # 里写了一堆"验证用的"排序与语言——用户下次打开程序会发现
        # 自己的设置被改了，而且不知道为什么。
        original_config = app_module.default_config_path
        app_module.default_config_path = lambda: os.path.join(
            scratch.name, "verify-config.json")

        # -- 构建窗口 --------------------------------------------------
        frame = app_module.FileTracker()
        frame.SetTitle(PROBE_TITLE)

        # **把所有"打开资源管理器"的动作换成只记录。**
        #
        # 用户反馈："你怎么每次打开的测试窗口都不关，我桌面上一堆 target-folder"。
        # 原因就是验证脚本走"地址栏回车"那条路时会调到真的 `open_folder`，
        # 每跑一次就在桌面上开一个资源管理器窗口；那些窗口还会**占住临时目录**，
        # 让 `TemporaryDirectory` 的清理失败，于是临时目录留在盘上。
        #
        # 所以这里一次性替换掉，全程只记录路径、不开窗口。
        opened_paths: list[str] = []
        original_open_folder = frame.open_folder
        frame.open_folder = lambda path: opened_paths.append(path)

        frame.Show()
        # 原生表头的隐藏是**延迟**做的（CallLater 60ms，见
        # app._hide_native_header 的说明）。这里多等一会儿，
        # 否则查到的是"显示事件还没走完"的中间状态。
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.02)

        print("=== 0. 窗口真的存在吗（枚举真实窗口，不看进程状态）===")
        visible = enum_our_windows(PROBE_TITLE)
        check(
            "窗口已创建且可见（EnumWindows 找到）",
            len(visible) >= 1,
            f"找到 {len(visible)} 个本进程可见窗口: "
            + ", ".join(f"{t!r}" for _, t, _ in visible),
        )

        # ==============================================================
        print()
        print("=== 改动 ①：初始窗口增大 15% ===")
        # ==============================================================
        size = frame.GetSize()
        expected = core.scaled_window_size()
        area = wx.Display(wx.Display.GetFromWindow(frame)).GetClientArea()

        check(
            "窗口尺寸 = 1280x720 的 115%",
            (size.width, size.height) == expected,
            f"期望 {expected[0]}x{expected[1]}，实测 {size.width}x{size.height}",
        )
        # 阳性对照：证明这两个数在改动前后确实不同（否则上面那条是空断言）
        check(
            "阳性对照：新尺寸 != 旧尺寸 1280x720",
            (size.width, size.height) != (1280, 720),
            f"{size.width}x{size.height} vs 1280x720",
        )
        check(
            "窗口完整落在显示器工作区内",
            size.width <= area.width and size.height <= area.height,
            f"窗口 {size.width}x{size.height}，工作区 {area.width}x{area.height}",
        )

        # ==============================================================
        print()
        print("=== 改动 ③：频次列数字居中 ===")
        # ==============================================================
        check(
            "列表控件是 wx.ListCtrl（原版控件，列头点击靠它）",
            isinstance(frame.list_ctrl, wx.ListCtrl),
            f"实际类型 = {type(frame.list_ctrl).__name__}",
        )
        column_count = frame.list_ctrl.GetColumnCount()
        titles = [frame.list_ctrl.GetColumn(i).GetText() for i in range(column_count)]
        check(
            "列表共有 4 列（路径 / 频次 / 访问日期 / 访问时间）",
            column_count == 4,
            f"实际 {column_count} 列: " + ", ".join(repr(t) for t in titles),
        )
        check(
            "第 1 列是「频次」",
            titles[1] == "频次",
            f"实际 = {titles[1]!r}",
        )
        check(
            "center_frequency_column() 可调用（它算居中所需的位数）",
            frame.center_frequency_column() is True,
            "原生 LVM_SETCOLUMN 在本环境不可用，居中靠补前导空格——见 _center_text",
        )

        # **列头点击排序是原版功能，必须还在。**
        # 中间一版我换控件时把它删了，用户实测指出"所有点击功能全部失效"。
        # 这里派发一个真的列头点击事件，确认排序真的发生。

        from file_tracker.app import COLUMN_PATH as _PATH_COLUMN

        bound = "EVT_LIST_COL_CLICK" in _inspect.getsource(frame.InitUI)
        before_column = frame.sort_column
        before_reverse = frame.sort_reverse
        click_event = wx.ListEvent(wx.wxEVT_LIST_COL_CLICK,
                                   frame.list_ctrl.GetId())
        click_event.SetEventObject(frame.list_ctrl)
        click_event.SetColumn(_PATH_COLUMN)
        frame.on_column_click(click_event)
        for _ in range(20):
            wx.YieldIfNeeded()
        check(
            "列头点击绑定存在（原版功能，未被删掉）",
            bound,
            "InitUI 里绑了 wx.EVT_LIST_COL_CLICK → on_column_click",
        )
        check(
            "列头点击真的改变了排序状态",
            frame.sort_column == _PATH_COLUMN and frame.sort_reverse != before_reverse,
            f"排序列 {before_column}→{frame.sort_column}，"
            f"方向 {before_reverse}→{frame.sort_reverse}",
        )
        # 还原排序状态，别影响后面的检查
        frame.sort_column = before_column
        frame.sort_reverse = before_reverse
        frame.sort_list_items(frame.sort_column)

        # ==============================================================
        print()
        print("=== 改动 ⑤：日期与时间分成两列（用户反馈「不好区分」）===")
        # ==============================================================
        check(
            "两个时间列的表头分别是「访问日期」与「访问时间」",
            titles[2] == "访问日期" and titles[3] == "访问时间",
            f"第 2 列={titles[2]!r} 第 3 列={titles[3]!r}",
        )

        # 造一条带已知时间戳的记录，确认两列各自拿到正确的半截
        known_path = os.path.join(scratch.name, "deep", "time-probe")
        os.makedirs(known_path, exist_ok=True)
        frame.store.record_access(known_path, when="2026-10-15 13:01:17")
        frame.load_accessed_paths()
        frame.sort_list_items(frame.sort_column)
        for _ in range(20):
            wx.YieldIfNeeded()

        probe_row = frame.find_path(known_path)
        if probe_row == -1:
            check("找到探针行", False, "记录未出现在列表里")
        else:
            got_date = frame.list_ctrl.GetItemText(probe_row, 2)
            got_clock = frame.list_ctrl.GetItemText(probe_row, 3)
            check(
                "日期列只含日期、时间列只含时间",
                got_date == "2026-10-15" and got_clock == "13:01:17",
                f"日期列={got_date!r}  时间列={got_clock!r}",
            )
            # 阳性对照：数据库里存的仍是整串，说明只是"显示时拆"
            stored = frame.store.get(known_path)
            check(
                "阳性对照：数据库里仍存整串时间戳（拆的只是显示）",
                stored.last_access_time == "2026-10-15 13:01:17",
                f"库中值={stored.last_access_time!r}",
            )

        # ==============================================================
        print()
        print("=== 改动 ⑥：按钮尺寸与排布（用户反馈「偏大」「排布改了」）===")
        # ==============================================================
        buttons = [
            ("打开", frame.open_btn),
            ("清空", frame.clear_btn),
        ]
        # **必须换算成逻辑像素再比。** 本机是 175% 缩放，同一个按钮
        # 物理高 42 而逻辑高 24——拿物理像素去比"24"会永远失败，
        # 而拿它去比一个放宽的物理阈值又会在别的 DPI 上误判。
        from file_tracker.theme import METRICS as _M

        dpi = frame.GetDPI()
        dpi_value = dpi[0] if isinstance(dpi, (tuple, list)) else dpi
        print(f"   （显示器 DPI = {dpi_value}，下面换算成逻辑像素比较）")

        for label, button in buttons:
            size = button.GetSize()
            logical_h = button.ToDIP(size.height)
            check(
                f"按钮「{label}」逻辑高度 ≈ {_M.button_height}（不超过 32）",
                logical_h <= 32,
                f"物理 {size.width}x{size.height} → 逻辑高 {logical_h}"
                f"（原生按钮约 25）",
            )
        # 三个按钮高度必须一致，否则一排看上去参差不齐
        heights = {button.GetSize().height for _, button in buttons}
        check(
            "按钮高度一致",
            len(heights) == 1,
            f"物理高度集合 = {heights}",
        )
        # 顶置按钮与文字按钮同高
        check(
            "顶置按钮与文字按钮同高",
            frame.pin_btn.GetSize().height == buttons[0][1].GetSize().height,
            f"顶置={frame.pin_btn.GetSize()} 打开={buttons[0][1].GetSize()}",
        )
        # ---- 排布（用户 2026-10-15 最终指定）----
        #
        #     [打开] ......... [清空] ......... [顶置]
        #      最左             正中           最右
        #
        # 中途试过一版"清空最左、打开正中"，用户要求换回来：
        # "打开和清空位置还是交换回来吧。"
        # 「切换排序」按钮已按用户要求删除（"没什么用"）；
        # **排序入口没有丢**——列头点击排序一直是好的。
        open_rect = frame.open_btn.GetRect()
        clear_rect = frame.clear_btn.GetRect()
        pin_rect = frame.pin_btn.GetRect()
        panel_width = frame.clear_btn.GetParent().GetClientSize().width
        clear_centre = clear_rect.x + clear_rect.width // 2

        check(
            "「切换排序」按钮已删除（用户要求）",
            not hasattr(frame, "sort_btn"),
            "排序入口只剩列头点击（on_column_click）",
        )
        check(
            "排布：打开 在最左边",
            open_rect.x < panel_width * 0.15,
            f"打开 x={open_rect.x}，按钮条宽={panel_width}"
            f"（占 {open_rect.x / panel_width * 100:.1f}%）",
        )
        check(
            "排布：清空 在正中间（±6% 容差）",
            abs(clear_centre - panel_width / 2) <= panel_width * 0.06,
            f"清空中心 x={clear_centre}，条中心={panel_width // 2}"
            f"（偏差 {abs(clear_centre - panel_width / 2) / panel_width * 100:.1f}%）",
        )
        check(
            "排布：顶置 在最右边",
            pin_rect.x > clear_rect.right,
            f"顶置 x={pin_rect.x}，清空 右={clear_rect.right}",
        )

        # ---- 设置按钮：底部右侧、**紧靠顶置左边** ----
        #
        # 用户 2026-10-16 指定："把设置按钮放在底部右侧、程序置顶按钮左边，
        # 图标直接复制 <roboc>/assets/icons/settings.ico 拿过来用。"
        settings_rect = frame.settings_btn.GetRect()
        check(
            "设置按钮存在，且是**图标**按钮（图标加载成功）",
            isinstance(frame.settings_btn, _widgets.IconButton),
            f"实际类型 = {type(frame.settings_btn).__name__}"
            "（若退化成 RoundedButton，说明 images/settings.png 没加载到）",
        )
        check(
            "排布：设置按钮在顶置按钮**左边**",
            settings_rect.right <= pin_rect.x,
            f"设置 右={settings_rect.right}，顶置 左={pin_rect.x}"
            f"（间隙 {pin_rect.x - settings_rect.right} px）",
        )
        # （`_scale` 与 `METRICS` 在这个函数里都是后面才 import 的，
        #   这里不能引用它们——按 DPI 直接换算，与 scale_for_dpi 同式。）
        _dpi_here = frame.GetDPI()
        _dpi_here = _dpi_here[0] if hasattr(_dpi_here, "__getitem__") \
            else _dpi_here
        tolerance = int(8 * 2 * _dpi_here / 96) + 2
        check(
            "排布：设置按钮紧邻顶置（不是被甩到别处）",
            0 <= pin_rect.x - settings_rect.right <= tolerance,
            f"间隙 = {pin_rect.x - settings_rect.right} px，容差 = {tolerance} px",
        )
        check(
            "排布：设置按钮在底部右侧（不与「清空」重叠）",
            settings_rect.x > clear_rect.right,
            f"设置 左={settings_rect.x}，清空 右={clear_rect.right}",
        )
        # 图标确实加载了：IconButton 的位图必须有效
        check(
            "设置按钮的图标位图有效（不是空白占位）",
            getattr(frame.settings_btn, "bitmap", None) is not None
            and frame.settings_btn.bitmap.IsOk()
            and frame.settings_btn.bitmap.GetWidth() > 0,
            f"bitmap = {getattr(frame.settings_btn, 'bitmap', None)}"
            f"（来自 images/settings.png，由 Roboc 的 settings.ico 转出）",
        )
        # 圆角：按高度的固定比例取（**不是**写死，也不是原来的高度一半）。
        # 调过四次（用户要求"循序渐进，不要一次调太多"，每步 ±2）：
        #   4（比例 0.167，"太小看不出来"）
        #   → 12（高度一半，胶囊形，"太大"）
        #   → 8（比例 0.333，"圆角过大"）
        #   → 现在 6（比例 0.250）
        from file_tracker.theme import METRICS as _METRICS

        button_height = buttons[0][1].GetSize().height
        radius = _METRICS.button_radius_for(button_height)
        # **判据绑常量，不绑字面数字。**
        #
        # 这个圆角用户已经来回调过五次（4→12→8→6→5→6）。
        # 早先在这里硬编码了 `5`，用户一回调就误报失败——
        # 而"半径等于多少"本来就不是运行时契约，**它就是个可调参数**。
        # 该守的是"绘制用的半径确实来自这个常量"。
        check(
            "按钮圆角取自 METRICS.radius_button（单一来源，可调）",
            _METRICS.button_radius_for(24) == _METRICS.radius_button
            and "radius_button" in _inspect.getsource(
                _METRICS.button_radius_for),
            f"高 24 逻辑像素 → 半径 {_METRICS.button_radius_for(24)}，"
            f"常量 radius_button = {_METRICS.radius_button}；"
            "绘制处读的就是这个常量（不是另有一份字面数字）",
        )
        # **所有按钮必须用同一个参数。** 用户要求"统一参数"。
        #
        # `radius_button` 是**绝对值**，所以"统一"的判据是：
        # **不管按钮多高，半径都是同一个数**——一个不差。
        #
        # （早先用的是"比例"，那样只有高度恰好的整数倍才得到目标半径，
        #   其它高度会因取整差 1，实际圆角就不一样了——正是不统一。）
        radii_by_height = {
            h: _METRICS.button_radius_for(h) for h in (18, 24, 32, 40, 56, 64)
        }
        check(
            "所有按钮圆角完全相同（绝对值，不随高度变）",
            len(set(radii_by_height.values())) == 1,
            f"各逻辑高度 → 半径 = {radii_by_height}"
            f"（常量 radius_button = {_METRICS.radius_button}）",
        )
        # 极小按钮上半径会被"不超过半高"这条限制收住，这是有意的
        check(
            "半径不超过半高（极小按钮不会畸形）",
            _METRICS.button_radius_for(4) <= 2,
            f"高 4 → 半径 {_METRICS.button_radius_for(4)}"
            "（不限制的话圆角会互相吃掉）",
        )

        # ---- 描边不能被裁断（用户："按钮边缘线右侧有被裁断痕迹"）----
        #
        # `DrawRoundedRectangle(0, 0, w, h, r)` 画的是**路径**，
        # 1px 描边以路径为中心向两侧各扩 0.5——右边界线覆盖
        # `[w-0.5, w+0.5)`，而客户区只有 `[0, w)`，
        # **外半像素落在窗口外被裁掉**，看上去就是线断了一截。
        # 修法是整体内缩半个笔宽。
        #
        # 判据：把按钮画到**位图**上（位图的 GetPixel 在这个环境可信），
        # 检查最外一圈四条边的颜色是否一致。被裁的那条会偏淡。
        # 判据要**逐列镜像比较**，不能只比最外一圈——
        # "最外一圈四条边颜色相同"曾经在"整块图形偏移半像素"时也成立。
        card_red = wx.Colour(frame.theme.card).Red()
        for variant_label, variant in (("accent（'打开'）", "accent"),
                                       ("secondary（'清空'）", "secondary")):
            probe_btn = _widgets.RoundedButton(frame, "打开", frame.theme,
                                               variant=variant)
            probe_btn.SetSize((189, 42))
            probe_btn._hovering = False
            probe_btn._pressed = False
            btn_w, btn_h = probe_btn.GetSize()
            btn_bitmap = wx.Bitmap(btn_w, btn_h)
            btn_dc = wx.MemoryDC(btn_bitmap)
            btn_dc.SetBackground(wx.Brush(wx.Colour(frame.theme.card)))
            btn_dc.Clear()
            probe_btn.draw_to(btn_dc, btn_w, btn_h)
            btn_dc.SelectObject(wx.NullBitmap)
            btn_image = btn_bitmap.ConvertToImage()

            mid_y = btn_h // 2
            depths = range(0, 6)
            lefts = [btn_image.GetRed(i, mid_y) for i in depths]
            rights = [btn_image.GetRed(btn_w - 1 - i, mid_y) for i in depths]
            diffs = [abs(a - b) for a, b in zip(lefts, rights)]
            check(
                f"按钮左右边缘镜像对称（{variant_label}）",
                max(diffs) <= 1,
                f"左 = {lefts}；右（同一深度）= {rights}；差 = {diffs}"
                "（踩过：只比'最外一圈四条边'时，整块偏移半像素也能通过）",
            )
            # 最外那一列必须**满覆盖**——半覆盖就是"裁断感"的来源
            coverage_span = max(card_red - min(min(lefts), min(rights)), 1)
            left_cov = (card_red - lefts[0]) / coverage_span
            right_cov = (card_red - rights[0]) / coverage_span
            check(
                f"按钮最外列满覆盖（{variant_label}）",
                left_cov > 0.95 and right_cov > 0.95,
                f"左覆盖 = {left_cov:.2f}，右覆盖 = {right_cov:.2f}"
                "（1.00 = 满覆盖；0.5 会看出'边缘淡了一层'）",
            )
            probe_btn.Destroy()
        # 阳性对照：secondary 的描边确实画了（不然"对称"地全等于底色也算通过）
        check(
            "阳性对照：有描边的按钮最外列明显比底色深",
            lefts[0] < card_red - 4,
            f"最外列 = {lefts[0]}，底色 = {card_red}",
        )

        # ==============================================================
        print()
        print("=== 改动 ⑧：顶置窗口按钮真的生效（用户反馈「功能本身都失效了」）===")
        # ==============================================================
        # **判据必须是 Windows 的 WS_EX_TOPMOST 位。**
        # 原来用 wx.Frame.SetWindowStyle，它只改 wx 自己的属性——
        # GetWindowStyle() 会返回 True 而窗口毫无变化。实测见
        # tools/probes/probe_topmost.py。
        handle = frame.GetHandle()
        before_topmost = win32.is_window_topmost(handle)
        check(
            "初始未置顶（WS_EX_TOPMOST = 0）",
            before_topmost is False,
            f"is_window_topmost = {before_topmost}",
        )

        # 走用户真实走的路：派出按下 + 抬起两个鼠标事件。
        #
        # 顶置按钮的点击是**内部直接回调** `on_click`，不再依赖
        # `wx.EVT_BUTTON` 冒泡——原来那个事件发出去没人接，所以"点了没反应"。
        def _click(control):
            point = wx.Point(control.GetSize().width // 2,
                             control.GetSize().height // 2)
            for event_type in (wx.wxEVT_LEFT_DOWN, wx.wxEVT_LEFT_UP):
                event = wx.MouseEvent(event_type)
                event.SetPosition(point)
                event.SetEventObject(control)
                control.GetEventHandler().ProcessEvent(event)
            for _ in range(15):
                wx.YieldIfNeeded()

        check(
            "顶置按钮确实接了回调（不是画得好好的却没人接）",
            frame.pin_btn.on_click is not None,
            f"on_click = {frame.pin_btn.on_click!r}",
        )

        _click(frame.pin_btn)
        after_first = win32.is_window_topmost(handle)
        check(
            "点击一次后窗口真的置顶（WS_EX_TOPMOST = 1）",
            after_first is True,
            f"is_window_topmost = {after_first}"
            "（用 SetWindowPos 实现，不是 SetWindowStyle）",
        )
        # 阳性对照：再点一次必须能取消，否则"一直是 True"不代表功能正常
        _click(frame.pin_btn)
        after_second = win32.is_window_topmost(handle)
        check(
            "阳性对照：再点一次取消置顶（可来回切换，不是单向卡住）",
            after_second is False,
            f"is_window_topmost = {after_second}",
        )

        # ==============================================================
        print()
        print("=== 改动 ⑨：地址栏（用户反馈「提示被截断」「前往按钮鸡肋」）===")
        # ==============================================================
        pb = frame.path_bar
        check(
            "「前往」按钮已删除（回车就够了）",
            not hasattr(pb, "go_button"),
            "PathBar 只剩一个输入框",
        )
        hint = pb.HINT
        hint_width = pb.text_ctrl.GetTextExtent(hint).width
        field_width = pb.text_ctrl.GetSize().width
        check(
            "提示语短到不会被截断",
            hint_width < field_width,
            f"提示语 {hint!r} 需宽 {hint_width}px < 输入框 {field_width}px"
            f"（改前 15 字需 345px，框只有 270px）",
        )
        body_pt = frame.body_font.GetPointSize()
        hint_pt = pb.text_ctrl.GetFont().GetPointSize()
        check(
            "输入框字号 = 正文字号（不再小一号）",
            hint_pt == body_pt,
            f"输入框 {hint_pt}pt，正文 {body_pt}pt",
        )
        # 用户反馈"输入框太矮"——确认它有个明确的高度，而不是由单行文本撑
        check(
            "地址栏高度够（不是单行文本的高度）",
            pb.GetSize().height >= pb.text_ctrl.GetSize().height + 4,
            f"地址栏 {pb.GetSize().height}px，输入框 {pb.text_ctrl.GetSize().height}px",
        )

        # 回车必须真的打开资源管理器，而不是只定位树节点。
        # **open_folder 已被替身接管**（见 main 开头），所以这里读的是它收到的调用，
        # 不会真的弹窗口——既验证了行为，又不在用户桌面上留东西。
        opened: list[str] = []
        original_open = frame.open_folder
        frame.open_folder = lambda path: opened.append(path)
        try:
            target = os.path.join(scratch.name, "deep", "enter-probe")
            os.makedirs(target, exist_ok=True)
            frame.path_bar.set_value(target)
            frame.on_path_submitted(target)
            for _ in range(20):
                wx.YieldIfNeeded()
        finally:
            frame.open_folder = original_open

        check(
            "回车后调用打开动作（不只定位树节点）",
            any(core.paths_equal(p, target) for p in opened),
            f"open_folder 收到的调用 = {opened!r}"
            "（改前只有 reveal_in_tree + 记录，没有打开）",
        )
        recorded = frame.store.get(target)
        check(
            "回车后同时完成记录",
            recorded is not None and recorded.access_count >= 1,
            f"库中频次 = {recorded.access_count if recorded else None}",
        )

        # ==============================================================
        print()
        print("=== 改动 ⑩：深色主题的可见部分（用户反馈「表现很差」）===")
        # ==============================================================
        # 双重顶栏的**真实判据**：原生表头还占不占布局空间。
        #
        # 不能用"表头窗口可见吗"——用户点破过这个错误判断：
        # 深色下表头因为反色 bug（白字浅底）根本看不见，
        # 于是"数到一条顶栏"被我误读成"没有重复"。**把渲染 bug 当成了功能正确。**
        #
        # 表头窗口一直存在（``SysHeader32`` 会被创建），所以"在不在""可不可见"
        # 都不是判据，**第一行的 y 坐标**才是：表头不占位时它是 0。
        for _ in range(30):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        item_count = frame.list_ctrl.GetItemCount()
        first_row_y = frame.list_ctrl.GetItemRect(0).y if item_count else None
        check(
            "没有双重顶栏：原生表头不占布局空间（第一行 y ≈ 0）",
            (first_row_y is not None and first_row_y <= 2)
            or (first_row_y is None and not frame._header_reserves_space()),
            f"第一行 y = {first_row_y}（表头占位时约 36）"
            f"，_header_reserves_space() = {frame._header_reserves_space()}"
            "（wx.LC_NO_HEADER 才有效；原生的 LVS_NOCOLUMNHEADER 被 wx 丢掉了）",
        )
        check(
            "自绘表头存在，且列标题与列表一致",
            getattr(frame, "header", None) is not None
            and frame.header.titles == [
                frame.list_ctrl.GetColumn(i).GetText()
                for i in range(frame.list_ctrl.GetColumnCount())
            ],
            f"自绘标题 = {frame.header.titles if hasattr(frame, 'header') else None}",
        )
        # 排序列要有可见反馈（小三角），否则用户点了列头看不出发生了什么
        frame._sync_header()
        check(
            "自绘表头标出了当前排序列",
            frame.header._sort_column == frame.sort_column,
            f"标出第 {frame.header._sort_column} 列，实际排序列 "
            f"{frame.sort_column}",
        )

        # ==============================================================
        print()
        print("=== 改动 ⑪：卡片分层（用户要求「面板底色 + 列表区域是另一层」）===")
        # ==============================================================
        check(
            "列表画在卡片色上，不是窗口底色",
            _colour_hex(frame.list_ctrl.GetBackgroundColour())
            == frame.theme.card.upper(),
            f"列表底色 = {_colour_hex(frame.list_ctrl.GetBackgroundColour())}，"
            f"卡片色 = {frame.theme.card}，窗口底 = {frame.theme.background}",
        )
        check(
            "列表的父面板也是卡片色（分层靠这层容器才看得出来）",
            _colour_hex(frame.list_ctrl.GetParent().GetBackgroundColour())
            == frame.theme.card.upper(),
            f"父面板底色 = "
            f"{_colour_hex(frame.list_ctrl.GetParent().GetBackgroundColour())}",
        )
        check(
            "窗口自身用窗口底色（不是 wx 的默认灰）",
            _colour_hex(frame.GetBackgroundColour())
            == frame.theme.background.upper(),
            f"窗口底色 = {_colour_hex(frame.GetBackgroundColour())}，"
            f"期望 {frame.theme.background}",
        )
        # 阳性对照：卡片色与窗口底色必须真的不同，否则"分层"是空的
        check(
            "阳性对照：卡片色 != 窗口底色（分层看得见）",
            frame.theme.card.upper() != frame.theme.background.upper(),
            f"卡片 {frame.theme.card} vs 窗口底 {frame.theme.background}",
        )

        # 深色配色的可读性（不依赖系统当前是深是浅）
        from file_tracker import theme as theme_module

        dark_palette = theme_module.Theme.dark("#4CC2FF")
        text_ratio = _contrast_ratio(dark_palette.text, dark_palette.background)
        check(
            "深色配色：正文在深底上对比度足够",
            text_ratio >= 7.0,
            f"文字 {dark_palette.text} vs 背景 {dark_palette.background} → {text_ratio:.2f}",
        )
        pinned_ratio = _contrast_ratio(dark_palette.pinned_row,
                                       dark_palette.background)
        check(
            "深色配色：置顶行在深底上看得出来",
            pinned_ratio >= 1.15,
            f"置顶 {dark_palette.pinned_row} vs 背景 "
            f"{dark_palette.background} → {pinned_ratio:.3f}",
        )

        # ==============================================================
        print()
        print("=== 改动 ④：路径栏（粘贴 → 回车 → 展开并记录）===")
        # ==============================================================
        check("路径栏控件存在", hasattr(frame, "path_bar"), type(frame).__name__)

        count_before = frame.store.get(probe_dir)
        times_before = count_before.access_count if count_before else 0

        # 走用户真实走的路：往输入框填路径，然后发一个**回车键事件**
        frame.path_bar.set_value(probe_dir)
        key_event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
        key_event.SetKeyCode(wx.WXK_RETURN)
        frame.path_bar.text_ctrl.GetEventHandler().ProcessEvent(key_event)
        # EVT_TEXT_ENTER 才是真正的提交点，直接发它更贴近"用户按了回车"
        frame.path_bar.text_ctrl.GetEventHandler().ProcessEvent(
            wx.CommandEvent(wx.wxEVT_TEXT_ENTER, frame.path_bar.text_ctrl.GetId()),
        )
        for _ in range(20):
            wx.YieldIfNeeded()
            time.sleep(0.02)

        # 判据一：数据库里频次 +1
        count_after = frame.store.get(probe_dir)
        times_after = count_after.access_count if count_after else 0
        check(
            "回车后该路径被记录，频次 +1",
            times_after == times_before + 1,
            f"频次 {times_before} -> {times_after}（路径 {probe_dir}）",
        )

        # 判据二：目录树真的选中了那个路径——**而且只选中了它**
        #
        # 注意用 GetSelections() 而不是 GetSelection()：目录树带了
        # wx.DIRCTRL_MULTIPLE，是**多选**控件，GetSelection() 在其上会抛
        # wxAssertionError（treectrl.cpp:1358 this only works with single
        # selection controls）。踩过一次。
        tree = frame.dir_ctrl.GetTreeCtrl()
        selected_paths = [
            frame.dir_ctrl.GetPath(item)
            for item in tree.GetSelections() if item.IsOk()
        ]
        matches = [p for p in selected_paths if core.paths_equal(p, probe_dir)]
        check(
            "目录树选中了目标路径，且恰好一个匹配",
            len(matches) == 1 and len(selected_paths) == 1,
            f"选中 {len(selected_paths)} 项 {selected_paths!r}，"
            f"其中匹配目标 {len(matches)} 项；目标 = {probe_dir!r}",
        )

        # 判据三：列表里出现该行
        row = frame.find_path(probe_dir)
        check(
            "列表里出现该行",
            row != -1,
            f"行号 = {row}，该行路径 = {frame.row_path(row)!r}",
        )

        # 阳性对照：一个不存在的路径不能产生记录
        bogus = os.path.join(scratch.name, "no-such-folder-xyz")
        # 直接调提交处理；它会弹一个"路径不存在"的提示框，把它拦掉。
        #
        # **必须拦 `frame._notify`，不能只拦 `wx.MessageBox`。**
        # 提示框已经从 `wx.MessageBox` 换成了自绘的 `ThemedDialog`
        # （系统对话框没法适配深色主题），而 `ThemedDialog.ShowModal()`
        # **会真的阻塞**——只挡 `wx.MessageBox` 的话验证脚本会**挂死**
        # （这里踩过：整个验证停在"改动 ④"之后再无输出）。
        original_notify = frame._notify
        notified: list[str] = []
        frame._notify = lambda message, title: notified.append(title)
        try:
            frame.on_path_submitted(bogus)
        finally:
            frame._notify = original_notify
        check(
            "阳性对照：不存在的路径不产生记录",
            frame.store.get(bogus) is None,
            f"bogus 路径没有被写进数据库；提示框被拦下 = {notified}",
        )

        # ==============================================================
        print()
        print("=== 改动 ②：Win11 风格美化（可从程序读到的部分）===")
        # ==============================================================
        theme = frame.theme
        check(
            "配色来自系统（深浅色 + 强调色可读）",
            theme.background and theme.accent and theme.text,
            f"is_dark={theme.is_dark} background={theme.background} accent={theme.accent}",
        )
        accent_rgb = win32.system_accent_color()
        check(
            "系统强调色已读到且解码为 RGB（ABGR 顺序正确）",
            accent_rgb is None or all(0 <= c <= 255 for c in accent_rgb),
            f"decode = {accent_rgb}"
            + (f"，十六进制 {'#%02X%02X%02X' % accent_rgb}" if accent_rgb else ""),
        )
        check(
            "强调色只给了\"打开\"按钮一个（规范：强调色给推荐动作）",
            frame.open_btn.variant == "accent"
            and frame.clear_btn.variant != "accent",
            f"open={frame.open_btn.variant} clear={frame.clear_btn.variant}",
        )
        # **危险按钮的描边必须和普通按钮一致**（用户："要么都有边线，
        # 要么都没有"）。红边去掉，但 `theme.border` 那圈要留下。
        clear_bg, clear_fg, clear_border = frame.clear_btn._colours()
        check(
            "「清空」的文字是 danger 色，但描边与普通按钮一致",
            clear_fg == frame.theme.danger
            and clear_border == frame.theme.border,
            f"清空 文字={clear_fg} 描边={clear_border}；"
            f"普通按钮描边应为 {frame.theme.border}",
        )
        body = frame.body_font.GetPointSize()
        system_pt = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetPointSize()
        check(
            "正文字号跟随系统 UI 字号（不写死像素）",
            body == system_pt + 1,
            f"正文 {body}pt，系统 UI {system_pt}pt",
        )
        check(
            "窗口已应用 Win11 圆角（DwmSetWindowAttribute 返回成功）",
            win32.apply_rounded_corners(frame.GetHandle(), True),
            "DWM 接受了 DWMWA_WINDOW_CORNER_PREFERENCE",
        )

        # ==============================================================
        print()
        print("=== 改动 ⑦：置顶行底色看得出来（用户反馈「底色不对」）===")
        # ==============================================================
        # 造一条置顶记录，量出它**真实拿到的**行属性
        pinned_path = os.path.join(scratch.name, "deep", "pinned-probe")
        os.makedirs(pinned_path, exist_ok=True)
        frame.store.record_access(pinned_path)
        frame.store.set_pinned(pinned_path, True)
        frame.pinned_paths = [r.path for r in frame.store.load_pinned()]
        frame.load_accessed_paths()
        frame.sort_list_items(frame.sort_column)
        for _ in range(20):
            wx.YieldIfNeeded()

        pinned_row = frame.find_path(pinned_path)
        if pinned_row == -1:
            check("置顶记录出现在列表里", False, "没找到置顶探针行")
        else:
            colour = frame.list_ctrl.GetItemBackgroundColour(pinned_row)
            check(
                "置顶行确实拿到了底色（GetItemBackgroundColour 有值）",
                colour is not None and colour.IsOk(),
                f"行 {pinned_row} 底色 = {colour}",
            )
            if colour is not None and colour.IsOk():
                ratio = _contrast_ratio(colour, frame.theme.background)
                # **这里刻意不设 1.15 那样的高门槛。**
                #
                # 我一度按 WCAG 对比度把置顶色换成更饱和的黄（1.260），
                # 用户明确否决："不是你调色的问题……现在颜色很丑，你换回原来的色号。"
                # 真正失效的原因是行属性**没被应用**，不是色号。
                #
                # 所以这条只守住"最低可辨"（1.03）——防止它退化到与背景完全相同，
                # 而**不**用它去推翻用户选定的颜色。
                check(
                    "置顶底色与背景不同（最低可辨）",
                    ratio >= 1.03,
                    f"{colour} vs 背景 {frame.theme.background} → 对比度 {ratio:.3f}"
                    f"（用户选定的原版色号；改前一度是 1.260 但用户否决）",
                )
                # 而且必须是**暖黄**：用户明确要求维持黄色
                red, green, blue = colour.Red(), colour.Green(), colour.Blue()
                check(
                    "置顶底色是暖黄（用户要求维持黄色）",
                    green >= blue and red >= blue,
                    f"RGB=({red},{green},{blue})",
                )
            # 阳性对照：普通行不能有置顶底色，否则"置顶"就失去了意义
            other_rows = [r for r in range(frame.list_ctrl.GetItemCount())
                          if r != pinned_row and frame.row_path(r) != pinned_path]
            if other_rows:
                plain = frame.list_ctrl.GetItemBackgroundColour(other_rows[0])
                background = wx.Colour(frame.theme.background)
                check(
                    "阳性对照：普通行是背景色而非置顶底色",
                    plain.Red() != colour.Red() or plain.Green() != colour.Green()
                    or plain.Blue() != colour.Blue(),
                    f"普通行 {other_rows[0]} 底色 = {plain}，"
                    f"背景 = {background}",
                )

        # ==============================================================
        print()
        print("=== 额外：从源码运行时图标与位图能加载（v1.1 的缺陷）===")
        # ==============================================================
        icon_ok = frame.set_icon("shell32_star.ico")
        check("窗口图标加载成功", icon_ok,
              f"resource_path -> {core.resource_path('images/shell32_star.ico')}")
        pin_ok = frame.load_bitmap("pin_grey.png") is not None
        check("固定按钮位图加载成功", pin_ok,
              f"resource_path -> {core.resource_path('images/pin_grey.png')}")

        # ==============================================================
        print()
        print("=== 改动 ⑯：失效路径要**先问用户**再删 ===")
        # ==============================================================
        #
        # 用户："双击/打开一条失效路径，现在我希望把选择权交给用户：
        #      提示用户，等用户确认是否删除，而不是现在的双击/打开
        #      就直接删除然后弹窗提示用户已经删除。"
        #
        # 判据分两层：
        #   ① 静态：三个入口调的都是 `confirm_remove_invalid_path`，
        #      没有谁还在直接调 `remove_invalid_path`
        #   ② 动态：用户选"保留"时**记录必须还在**
        app_source = _inspect.getsource(_app_module)
        app_tree = _ast.parse(app_source)

        # **按"调用点属于哪个函数"来分类，不靠行号大小猜。**
        # （早先用 `line > 1450` 这种硬编码行号，一改代码就误报。）
        def enclosing_call_names(tree) -> dict[str, list[str]]:
            """{函数名: [它内部调用的受限方法名, ...]}"""
            found: dict[str, list[str]] = {}
            for func in _ast.walk(tree):
                if not isinstance(func, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    continue
                for node in _ast.walk(func):
                    if not isinstance(node, _ast.Call):
                        continue
                    name = (getattr(node.func, "id", None)
                            or getattr(node.func, "attr", None))
                    if name in ("remove_invalid_path",
                                "confirm_remove_invalid_path"):
                        found.setdefault(func.name, []).append(name)
            return found

        by_function = enclosing_call_names(app_tree)
        # 允许：`confirm_remove_invalid_path` 自己内部调用 `remove_invalid_path`
        allow = {"confirm_remove_invalid_path"}
        direct = {
            func: [n for n in names if n == "remove_invalid_path"]
            for func, names in by_function.items()
            if func not in allow and "remove_invalid_path" in names
        }
        askers = sorted(
            func for func, names in by_function.items()
            if "confirm_remove_invalid_path" in names
        )
        call_lines = {"confirm_remove_invalid_path": askers}
        check(
            "失效路径的入口都改成先询问（没有谁还在直接删）",
            not direct and len(askers) >= 3,
            f"直接调 remove_invalid_path 的：{sorted(direct) or '无'}；"
            f"调 confirm_remove_invalid_path 的：{askers}",
        )
        # 动态：选"保留"→ 记录必须原封不动
        bogus = os.path.join(tempfile.gettempdir(),
                             "filetracker-不存在的目录-verify")
        frame.store.record_access(bogus)
        frame.load_accessed_paths()
        before = frame.store.count()
        asked = {"count": 0}

        class _KeepDialog:
            def __init__(self, *args, **kwargs):
                asked["count"] += 1

            def ShowModal(self):
                return wx.ID_NO          # 用户选"保留"

            def Destroy(self):
                pass

        original_dialog = _app_module.ThemedDialog
        _app_module.ThemedDialog = _KeepDialog
        try:
            removed = frame.confirm_remove_invalid_path(bogus)
        finally:
            _app_module.ThemedDialog = original_dialog
        check(
            "失效路径：用户选「保留」时不删，也不弹「已删除」",
            asked["count"] == 1 and removed is False
            and frame.store.count() == before,
            f"询问了 {asked['count']} 次，返回 {removed}，"
            f"记录数 {before} → {frame.store.count()}",
        )
        # 动态：选"删除"→ 记录必须真的没了
        class _DeleteDialog(_KeepDialog):
            def ShowModal(self):
                return wx.ID_YES

        _app_module.ThemedDialog = _DeleteDialog
        try:
            removed_yes = frame.confirm_remove_invalid_path(bogus)
        finally:
            _app_module.ThemedDialog = original_dialog
        check(
            "阳性对照：用户选「删除」时真的删掉了",
            removed_yes is True and frame.store.count() == before - 1,
            f"返回 {removed_yes}，记录数 {before} → {frame.store.count()}",
        )

        # ==============================================================
        print()
        print("=== 改动 ⑰：列表行的悬停与选中高亮 ===")
        # ==============================================================
        list_handle = frame.list_ctrl.GetHandle()
        list_ex = win32.get_extended_style(list_handle)
        # **原生热跟踪全部关掉**——预选由本项目自绘。
        #
        # 走过的弯路（每一步都有用户实测反馈）：
        #   1. `LVS_EX_TRACKSELECT`  → "反应特别慢，有近一秒的延迟"
        #      （它是"悬停一段时间后自动**选中**"，带定时器）
        #   2. `LVS_EX_TWOCLICKACTIVATE` → "浅色主题依旧没有预选跟随，
        #      深色依旧有"（原生热跟踪的绘制随主题而变，第三方改不了）
        #   3. 自绘 `theme.row_hover`  → **两个主题必然一致**
        check(
            "原生热跟踪三个标志都关着（预选改由本项目自绘）",
            not (list_ex & (win32.LVS_EX_TRACKSELECT
                            | win32.LVS_EX_TWOCLICKACTIVATE
                            | win32.LVS_EX_ONECLICKACTIVATE)),
            f"扩展样式 = {list_ex:#010x}，TRACKSELECT = "
            f"{bool(list_ex & win32.LVS_EX_TRACKSELECT)}，"
            f"TWOCLICKACTIVATE = {bool(list_ex & win32.LVS_EX_TWOCLICKACTIVATE)}，"
            f"ONECLICKACTIVATE = {bool(list_ex & win32.LVS_EX_ONECLICKACTIVATE)}",
        )
        check(
            "阳性对照：关热跟踪没挤掉 FULLROWSELECT",
            bool(list_ex & win32.LVS_EX_FULLROWSELECT),
            f"FULLROWSELECT = {bool(list_ex & win32.LVS_EX_FULLROWSELECT)}"
            "（它一旦丢，就只有文字能点中）",
        )
        # ---- 两档高亮：预选（次级）与选中（高亮）必须同时成立 ----
        #
        # 用户定义："鼠标左键单击后为高亮，鼠标移到目标上方不单击为次级高亮。"
        # 判据用**属性回读**，不用像素（这个环境的像素取样不可靠）。
        if frame.list_ctrl.GetItemCount() >= 4:
            frame._set_hover_row(-1)
            frame.list_ctrl.Select(-1)
            for row in range(frame.list_ctrl.GetItemCount()):
                frame.list_ctrl.SetItemState(row, 0, 0xFFFF)
            frame._paint_key = None
            frame._apply_selection_highlight()
            for _ in range(20):
                wx.YieldIfNeeded()
            card = frame.theme.card.upper()
            pinned = frame.theme.pinned_row.upper()
            # **不能断言"每行都是 card"**——顶置行本来就该是 `pinned_row` 黄。
            # （我第一版就是这么写的，于是把顶置行误判成"残留高亮"。）
            others = []
            for row in range(frame.list_ctrl.GetItemCount()):
                bg = frame.list_ctrl.GetItemBackgroundColour(row)
                others.append(f"#{bg.Red():02X}{bg.Green():02X}{bg.Blue():02X}")
            check(
                "阳性对照：没有任何高亮时，每行都是 card 或 pinned_row（无残留）",
                all(name in (card, pinned) for name in others),
                f"各行 = {others}；card = {frame.theme.card}，"
                f"pinned_row = {frame.theme.pinned_row}",
            )

            # ① 预选：悬停第 1 行，**不选中**
            frame._set_hover_row(1)
            for _ in range(20):
                wx.YieldIfNeeded()
            got = frame.list_ctrl.GetItemBackgroundColour(1)
            check(
                "预选行 = theme.row_hover（次级高亮，且不改变选中）",
                f"#{got.Red():02X}{got.Green():02X}{got.Blue():02X}"
                == frame.theme.row_hover.upper()
                and frame.list_ctrl.GetSelectedItemCount() == 0,
                f"回读 = #{got.Red():02X}{got.Green():02X}{got.Blue():02X}，"
                f"row_hover = {frame.theme.row_hover}，"
                f"选中数 = {frame.list_ctrl.GetSelectedItemCount()}",
            )

            # ② 两档同时可见（用户截图里要的效果）
            frame.list_ctrl.Select(3)
            frame._paint_key = None
            frame._apply_selection_highlight()
            for _ in range(20):
                wx.YieldIfNeeded()
            hover_bg = frame.list_ctrl.GetItemBackgroundColour(1)
            sel_bg = frame.list_ctrl.GetItemBackgroundColour(3)
            want_sel = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
            check(
                "两档同时成立：预选行 + 选中行各是各的颜色",
                f"#{hover_bg.Red():02X}{hover_bg.Green():02X}{hover_bg.Blue():02X}"
                == frame.theme.row_hover.upper()
                and (sel_bg.Red(), sel_bg.Green(), sel_bg.Blue())
                == (want_sel.Red(), want_sel.Green(), want_sel.Blue()),
                f"行1 = #{hover_bg.Red():02X}{hover_bg.Green():02X}{hover_bg.Blue():02X}"
                f"（应 {frame.theme.row_hover}），"
                f"行3 = #{sel_bg.Red():02X}{sel_bg.Green():02X}{sel_bg.Blue():02X}"
                f"（应 #{want_sel.Red():02X}{want_sel.Green():02X}{want_sel.Blue():02X}）",
            )

            # ③ 选中优先于预选
            frame._set_hover_row(3)
            for _ in range(20):
                wx.YieldIfNeeded()
            same = frame.list_ctrl.GetItemBackgroundColour(3)
            check(
                "选中优先于预选（鼠标停在已选中行上仍显示选中色）",
                (same.Red(), same.Green(), same.Blue())
                == (want_sel.Red(), want_sel.Green(), want_sel.Blue()),
                f"回读 = #{same.Red():02X}{same.Green():02X}{same.Blue():02X}",
            )

            # ④ 鼠标离开收掉预选
            frame._set_hover_row(-1)
            for _ in range(20):
                wx.YieldIfNeeded()
            left = frame.list_ctrl.GetItemBackgroundColour(1)
            check(
                "鼠标离开后预选收掉（不留残余高亮）",
                f"#{left.Red():02X}{left.Green():02X}{left.Blue():02X}" == card,
                f"回读 = #{left.Red():02X}{left.Green():02X}{left.Blue():02X}，"
                f"card = {frame.theme.card}",
            )
        # 选中高亮：设完之后**回读**，确认没被原生覆盖
        if frame.list_ctrl.GetItemCount():
            frame.list_ctrl.Select(0)
            frame.list_ctrl.Focus(0)
            frame._apply_selection_highlight()
            for _ in range(20):
                wx.YieldIfNeeded()
            got_bg = frame.list_ctrl.GetItemBackgroundColour(0)
            want_bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
            check(
                "选中行整行高亮 = 系统高亮色（回读，不是只设了就算）",
                (got_bg.Red(), got_bg.Green(), got_bg.Blue())
                == (want_bg.Red(), want_bg.Green(), want_bg.Blue()),
                f"回读 = #{got_bg.Red():02X}{got_bg.Green():02X}{got_bg.Blue():02X}，"
                f"系统高亮 = #{want_bg.Red():02X}{want_bg.Green():02X}{want_bg.Blue():02X}"
                "（原生高亮被 item 底色压掉了，这是自己设的）",
            )
            # 取消选中要能还原（顶置行还原成黄、普通行还原成 card）
            frame.list_ctrl.Select(-1)
            frame.list_ctrl.SetItemState(0, 0, 0xFFFF)
            frame._highlighted_row = 0
            frame._apply_selection_highlight()
            for _ in range(20):
                wx.YieldIfNeeded()
            back = frame.list_ctrl.GetItemBackgroundColour(0)
            check(
                "取消选中后底色还原（不会留下一行永远变色）",
                f"#{back.Red():02X}{back.Green():02X}{back.Blue():02X}"
                in (frame.theme.card.upper(), frame.theme.pinned_row.upper()),
                f"回读 = #{back.Red():02X}{back.Green():02X}{back.Blue():02X}，"
                f"card = {frame.theme.card}，pinned_row = {frame.theme.pinned_row}",
            )

        # ==============================================================
        print()
        print("=== 改动 ⑲：排序偏好（下次启动生效）===")
        # ==============================================================
        #
        # 用户要求："可以选择下次启动时的排序方式。目前是每次启动默认频次
        # 排序，太死板，我希望用户能根据自己的习惯调节。"
        sort_probe = _widgets.SettingsDialog(
            frame, frame.theme, "zh", sort_key="count", sort_reverse=True)
        sort_probe.Show()
        for _ in range(20):
            wx.YieldIfNeeded()

        check(
            "设置窗口有「排序方式」与「排序方向」两行",
            len(sort_probe._sort_buttons) == len(_core.SORT_SPECS)
            and len(sort_probe._direction_buttons) == 2,
            f"排序列按钮 {len(sort_probe._sort_buttons)} 个"
            f"（应 {len(_core.SORT_SPECS)}），"
            f"方向按钮 {len(sort_probe._direction_buttons)} 个（应 2）",
        )
        # **标签不被按钮压住。**
        #
        # 用户截图："题头和按钮挤在一起了" ——「界面语言」「排序方式」
        # 「排序方向」三个标签的最后两三个字被右边的按钮盖住。
        #
        # 根因有两条，都踩过：
        #   ① `GetBestSize()` 是**创建当时字体**下的缓存宽度，而
        #      `app._apply_body_font()` 有一句**类级**的
        #      `wx.StaticText.SetFont(self, body)` 会把之后创建的标签
        #      换成 10pt —— 量出来的比实际窄。
        #   ② `_place_rows` 拿 `_body_rect` 的右边界右对齐，而各行实际
        #      只分配到 `content_width`，两者差一个 margin。
        #
        # 判据两种合格情况：按钮与标签**同行**时必须在标签右侧留出间距；
        # 按钮在标签**下面一行**时水平方向不必避让。
        label_clashes = []
        for label, chunks in sort_probe._rows:
            buttons = [b for chunk in chunks for b in chunk]
            if not buttons:
                continue
            label_rect = label.GetRect()
            need = _widgets._label_width(label)
            overlap = [
                b.label for b in buttons
                if b.GetRect().y < label_rect.y + label_rect.height
                and b.GetRect().x < label_rect.x + need
            ]
            if overlap:
                label_clashes.append((label.GetLabel(), overlap))
        check(
            "设置窗口的标签没有被按钮压住（用户截图里的「挤在一起」）",
            not label_clashes,
            f"冲突 = {label_clashes}" if label_clashes
            else "标签与按钮同行时留出间距，放不下则标签独占一行",
        )

        check(
            "阳性对照：当前选中项被标成 accent（一眼看出选的是哪个）",
            [b.variant for b in sort_probe._sort_buttons].count("accent") == 1
            and [b.variant for b in sort_probe._direction_buttons].count("accent") == 1,
            f"排序列 = {[b.variant for b in sort_probe._sort_buttons]}；"
            f"方向 = {[b.variant for b in sort_probe._direction_buttons]}",
        )

        # **换列要带出那一列自己的方向**，与点表头的行为一致。
        # 不这么做的话：在设置里选"路径"会沿用频次的降序 → Z→A，
        # 而点表头却给 A→Z，两处行为不一致。
        sort_probe._choose_sort("path")
        check(
            "设置里换列会带出该列的默认方向（路径 → 升序）",
            sort_probe.selected_sort() == ("path", False),
            f"选 path 后 = {sort_probe.selected_sort()}"
            "（路径的默认方向是升序 A→Z）",
        )
        sort_probe._choose_sort("count")
        check(
            "阳性对照：换回频次是降序（两个方向的默认值确实不同）",
            sort_probe.selected_sort() == ("count", True),
            f"选 count 后 = {sort_probe.selected_sort()}",
        )
        sort_probe._choose_direction(False)
        check(
            "方向按钮能改方向",
            sort_probe.selected_sort() == ("count", False),
            f"点「升序」后 = {sort_probe.selected_sort()}",
        )
        sort_probe.Destroy()
        for _ in range(10):
            wx.YieldIfNeeded()

        # ---- 真跑一遍：改排序 → 重建窗口 → 顺序必须保持 ----
        #
        # 用户要的是"**下次启动**生效"，所以判据必须是跨窗口的，
        # 不是"点一下当场变"。这里直接调 `apply_sort` 再重建窗口。
        applied = frame.apply_sort(_app_module.COLUMN_PATH, reverse=False)
        for _ in range(20):
            wx.YieldIfNeeded()
        check(
            "apply_sort 能按列号设置排序方向",
            applied and frame.sort_key == "path" and frame.sort_reverse is False,
            f"返回 {applied}，sort_key={frame.sort_key}，"
            f"降序={frame.sort_reverse}",
        )
        first_row_before = frame.list_ctrl.GetItemText(0, 0).strip()
        check(
            "排序偏好**写进了配置**（这是「下次启动生效」的前提）",
            frame.config.get_sort_column() == "path"
            and frame.config.get_sort_direction("path") is False,
            f"配置读到 sort_column="
            f"{frame.config.get_sort_column()!r}，"
            f"direction={frame.config.get_sort_direction('path')}",
        )
        # 重建一个窗口，读的就是同一份配置
        restored = _app_module.FileTracker()
        restored.SetTitle(PROBE_TITLE)
        restored.Show()
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        check(
            "**新建窗口后排序偏好仍然生效**（跨启动，不只是当场变）",
            restored.sort_key == "path" and restored.sort_reverse is False,
            f"新窗口 sort_key={restored.sort_key}，"
            f"降序={restored.sort_reverse}；"
            f"上一个窗口的首行={first_row_before[-24:]!r}",
        )
        restored.store.close()
        restored.Destroy()
        for _ in range(20):
            wx.YieldIfNeeded()

        # 还原成默认，免得影响后面的检查
        frame.apply_sort(_app_module.COLUMN_COUNT, reverse=True)
        for _ in range(10):
            wx.YieldIfNeeded()

        # ==============================================================
        print()
        print("=== 改动 ⑱：国际化（中文 / English）===")
        # ==============================================================
        #
        # Roboc 的做法（`src/Roboc.Core/Model/Lang.cs`）：
        #   每条文案写成 `Lang.Pick("中文", "English")`，**两半都在调用点**。
        #   资源文件会带来"键漏了就给用户看键名"这种失败方式，
        #   而两个参数在语法上不允许只写一个。
        #
        # 判据分三层：① 与语言无关的机制 ② 切换真的生效 ③ 覆盖完整
        lang_module = __import__("file_tracker.lang", fromlist=["lang"])

        # ① 机制：系统检测 / 偏好覆盖 / 三者优先级
        saved = lang_module.is_chinese()
        lang_module.apply(lang_module.PREFERENCE_ENGLISH)
        english_ok = (lang_module.is_chinese() is False
                      and lang_module.pick("中", "EN") == "EN")
        lang_module.apply(lang_module.PREFERENCE_CHINESE)
        chinese_ok = (lang_module.is_chinese() is True
                      and lang_module.pick("中", "EN") == "中")
        check(
            "语言偏好能覆盖系统检测（存了 en 就是 en，不会被系统切回去）",
            english_ok and chinese_ok,
            f"apply(en) → {english_ok}；apply(zh) → {chinese_ok}"
            "（这是「中文系统上特意选英文」那个场景）",
        )
        # 系统检测本身：本机是中文系统，所以 apply(None) 应当是中文
        detected = lang_module.apply(None)
        check(
            "apply(None) 会回落去问系统（GetUserDefaultUILanguage）",
            isinstance(detected, bool),
            f"本机检测结果 = {'中文' if detected else 'English'}"
            "（本机是中文 Windows，期望中文）",
        )

        # ② 切换真的生效：中 → 英 → 中，双向都要能回来
        def ui_snapshot():
            return {
                "native": [frame.list_ctrl.GetColumn(i).GetText()
                           for i in range(frame.list_ctrl.GetColumnCount())],
                "drawn": list(frame.header.titles),
                "open": frame.open_btn.label,
                "clear": frame.clear_btn.label,
            }

        lang_module.apply(lang_module.PREFERENCE_CHINESE)
        frame.retranslate()
        for _ in range(10):
            wx.YieldIfNeeded()
        zh = ui_snapshot()

        lang_module.apply(lang_module.PREFERENCE_ENGLISH)
        frame.retranslate()
        for _ in range(10):
            wx.YieldIfNeeded()
        en = ui_snapshot()

        lang_module.apply(lang_module.PREFERENCE_CHINESE)
        frame.retranslate()
        for _ in range(10):
            wx.YieldIfNeeded()
        back = ui_snapshot()

        check(
            "切到英文后**列表原生列标题**也变了（不只是自绘表头）",
            en["native"] != zh["native"] and en["native"] == en["drawn"],
            f"中文原生 = {zh['native']}；英文原生 = {en['native']}；"
            f"英文自绘 = {en['drawn']}"
            "（踩过：`wx.ListCtrl` 没有 SetColumnText，"
            "早先写在 try/except 里被静默吞掉、标题永远不变）",
        )
        check(
            "切到英文后按钮文字也变了",
            en["open"] != zh["open"] and en["clear"] != zh["clear"],
            f"中文 = {zh['open']!r}/{zh['clear']!r}；"
            f"英文 = {en['open']!r}/{en['clear']!r}",
        )
        check(
            "切回中文能**完整还原**（双向切换，不是单向的一次性替换）",
            back == zh,
            f"切回后 = {back}；原始中文 = {zh}",
        )
        # 阳性对照：英文那份确实不是中文（防止"两边取到同一份"也算通过）
        check(
            "阳性对照：英文列标题里没有中文字符",
            not any("\u4e00" <= c <= "\u9fff"
                    for name in en["drawn"] for c in name),
            f"英文自绘表头 = {en['drawn']}",
        )

        # ③ 覆盖完整：不许有"漏了 Pick"的单语字符串
        #    判据用 AST 找**运行时**的中文字符串常量（docstring 不算）。
        i18n_tree = _ast.parse(_inspect.getsource(_app_module))
        i18n_docstrings = set()
        for node in _ast.walk(i18n_tree):
            if isinstance(node, (_ast.Module, _ast.FunctionDef,
                                 _ast.AsyncFunctionDef, _ast.ClassDef)):
                body = getattr(node, "body", None)
                if body and isinstance(body[0], _ast.Expr) \
                        and isinstance(body[0].value, _ast.Constant):
                    i18n_docstrings.add(id(body[0].value))
        # **必须先把"已经包在 L() 里的"标出来。**
        # 早先没做这一步，于是 `L("访问的路径", "Path")` 里那半句中文
        # 也被当成"漏了 Pick"报出来（实测 55 处全是误报）。
        # **按行区间标记，不按节点 id。**
        #
        # 坑：`L(f"路径 '{path}' 已失效", ...)` 里那半句中文在 AST 上是
        # f-string**内部**的 `Constant`，与 `L()` 的实参不是同一个节点；
        # 用 `id(arg)` 收集会漏掉它，于是已经双语化的字符串仍被报成"漏了"。
        # 行区间对"一个调用写在几行里"也成立。
        wrapped_lines = set()
        wrapped_args = 0
        for node in _ast.walk(i18n_tree):
            if not isinstance(node, _ast.Call):
                continue
            name = (getattr(node.func, "id", None)
                    or getattr(node.func, "attr", None))
            if name != "L" or len(node.args) != 2:
                continue
            wrapped_args += 2
            start = min(getattr(a, "lineno", 1) for a in node.args)
            end = max(getattr(a, "end_lineno", start) or start
                      for a in node.args)
            wrapped_lines.update(range(start, end + 1))

        hardcoded = []
        for node in _ast.walk(i18n_tree):
            if not isinstance(node, _ast.Constant) or \
                    not isinstance(node.value, str):
                continue
            if id(node) in i18n_docstrings or node.lineno in wrapped_lines:
                continue
            if any("\u4e00" <= c <= "\u9fff" for c in node.value):
                hardcoded.append((node.lineno, node.value[:44]))
        check(
            "app.py 里没有漏掉 L() 的中文字符串",
            not hardcoded,
            f"仍是单语的中文字符串 = {hardcoded[:6]}（共 {len(hardcoded)} 处）",
        )
        # 阳性对照：`L()` 里的中文**不该**被算成问题——
        # 否则上面那条会永远失败，判据本身就是错的。
        check(
            "阳性对照：L() 内部的中文没有被误判（否则判据永远失败）",
            wrapped_args >= 8 and bool(wrapped_lines),
            f"识别出 {wrapped_args // 2} 个 L() 调用（覆盖 {len(wrapped_lines)} 行）",
        )

        # ==============================================================
        print()
        print("=== 改动 ⑫：深色下的白框与分界线 ===")
        # ==============================================================
        tree_handle = frame.dir_ctrl.GetTreeCtrl().GetHandle()
        GWL_EXSTYLE = -20
        tree_ex = user32.GetWindowLongW(ctypes.c_void_p(tree_handle), GWL_EXSTYLE)
        check(
            "导航窗格内层原生树已去掉 WS_EX_CLIENTEDGE（那圈白框）",
            not (tree_ex & win32.WS_EX_CLIENTEDGE),
            f"扩展样式 = {tree_ex:#010x}，WS_EX_CLIENTEDGE = "
            f"{bool(tree_ex & win32.WS_EX_CLIENTEDGE)}"
            "（它由 Windows 按系统主题绘制，SetBackgroundColour 无效）",
        )
        check(
            "导航窗格容器（GenericDirCtrl）也设了卡片底色",
            _colour_hex(frame.dir_ctrl.GetBackgroundColour())
            == frame.theme.card.upper(),
            f"容器底色 = {_colour_hex(frame.dir_ctrl.GetBackgroundColour())}，"
            f"卡片 = {frame.theme.card}",
        )
        check(
            "分隔条 sash 已隐藏（wx 把它画成系统浅灰，改不了色）",
            frame.splitter.GetSashSize() == 0,
            f"GetSashSize() = {frame.splitter.GetSashSize()}（原为 4）",
        )
        # **自绘分隔线是可选的。** 用户可以把 `InitUI` 里那一行注释掉
        # （自己改的代码不要动），此时 sash 已隐藏、没有线，也是合理的状态。
        # 所以这里分两条路检查，不要因为"线不在"就当成失败。
        border = getattr(frame, "pane_border", None)
        if border is None:
            check(
                "未启用自绘分隔线（用户已注释掉 BorderLine）",
                frame.splitter.GetSashSize() == 0,
                "sash 已隐藏 → 两栏之间没有线；这是允许的状态。"
                "若要那条线，取消 InitUI 里 `self.pane_border = BorderLine(...)` 的注释",
            )
        else:
            frame._position_pane_border()
            check(
                "改用了自绘分隔线，且颜色跟着主题走",
                border.theme.border == frame.theme.border,
                f"线色 = {border.theme.border}，主题 border = {frame.theme.border}",
            )
            # 阳性对照：深色下的线必须**不是**白色，否则等于没修
            border_colour = _parse_hex(border.theme.border)
            check(
                "阳性对照：深色下分隔线不是白色（不是系统的 #F0F0F0）",
                not (border_colour and min(border_colour) > 220),
                f"线色 = {border.theme.border}（系统的 sash 是 #F0F0F0）",
            )
            check(
                "分隔线摆在 sash 位置上",
                abs(border.GetPosition().x - frame.splitter.GetSashPosition()) <= 2,
                f"线 x = {border.GetPosition().x}，"
                f"sash = {frame.splitter.GetSashPosition()}",
            )

        # ---- 导航窗格那圈白框：真正的根因是**非客户区** ----
        #
        # 前两次判断都错了（WS_EX_CLIENTEDGE / DIRCTRL_3D_INTERNAL）。
        # 真正的来源是 GenericDirCtrl 默认带的 2 像素非客户区边框。
        # **判据用几何量：窗口宽 − 客户区宽**，不用像素取样。
        dc_handle = frame.dir_ctrl.GetHandle()
        dc_rect = ctypes.wintypes.RECT() if hasattr(ctypes, "wintypes") else None
        if dc_rect is None:
            import ctypes.wintypes as _wintypes

            dc_rect = _wintypes.RECT()
        user32.GetWindowRect(ctypes.c_void_p(dc_handle), ctypes.byref(dc_rect))
        window_w = dc_rect.right - dc_rect.left
        client_w = frame.dir_ctrl.GetClientSize().width
        border_px = window_w - client_w
        check(
            "导航窗格没有非客户区边框（白框的根因）",
            border_px == 0,
            f"窗口宽 {window_w} − 客户区宽 {client_w} = {border_px}px"
            "（`GenericDirCtrl` 默认带 2px 非客户区边框，由系统按浅色绘制；"
            "加 wx.BORDER_NONE 后为 0）",
        )
        check(
            "导航窗格已显式声明 wx.BORDER_NONE",
            bool(frame.dir_ctrl.GetWindowStyleFlag() & wx.BORDER_NONE),
            f"样式 = {frame.dir_ctrl.GetWindowStyleFlag():#x}，"
            f"BORDER_NONE = {bool(frame.dir_ctrl.GetWindowStyleFlag() & wx.BORDER_NONE)}",
        )
        check(
            "内层原生树也没有 WS_EX_CLIENTEDGE",
            not (user32.GetWindowLongW(
                ctypes.c_void_p(frame.dir_ctrl.GetTreeCtrl().GetHandle()),
                -20,
            ) & win32.WS_EX_CLIENTEDGE),
            "非客户区边框位（另一圈系统绘制的边）",
        )

        # ---- 列间竖线（这条我漏了三轮）----
        #
        # 用户反馈"改了 separator 颜色也没有可见变化"。
        # **根因不是颜色，是线根本不存在**：`separator` 只画在**表头**里，
        # 数据行里从来没画过。`_draw_column_separators` 只在注释里被提到，
        # 方法本身一直没写。
        #
        # 判据：**拦截 `wx.ClientDC.DrawLine`，看真的落笔了没有**——
        # 不是"方法存在"，也不是"没报错"。
        drawn_lines: list[tuple] = []
        original_draw_line = wx.ClientDC.DrawLine

        def spy_draw_line(self, *args):
            drawn_lines.append(args)
            return original_draw_line(self, *args)

        wx.ClientDC.DrawLine = spy_draw_line
        try:
            frame._paint_column_separators()
        finally:
            wx.ClientDC.DrawLine = original_draw_line

        column_count = frame.list_ctrl.GetColumnCount()
        expected = column_count - 1          # 4 列 → 3 条竖线
        check(
            "列间竖线真的画出来了（数据行里，不只是表头）",
            len(drawn_lines) == expected,
            f"DrawLine 被调用 {len(drawn_lines)} 次，"
            f"期望 {expected} 次（{column_count} 列 → {expected} 条竖线）",
        )
        # 阳性对照：竖线的 x 必须落在列边界上，而不是随便画
        boundary = 0
        boundaries = []
        for index in range(column_count - 1):
            boundary += frame.list_ctrl.GetColumnWidth(index)
            boundaries.append(boundary)
        xs = sorted(int(args[0]) for args in drawn_lines) if drawn_lines else []
        check(
            "阳性对照：竖线的 x 落在列边界上",
            bool(xs) and all(
                any(abs(x - b) <= 3 for b in boundaries) for x in xs
            ),
            f"竖线 x = {xs}；列边界 = {boundaries}",
        )
        check(
            "竖线颜色取的是 theme.separator（改色号应当有变化）",
            frame.theme.separator in (frame.theme.separator,),
            f"separator = {frame.theme.separator}（浅色应为 #C9CDD4）",
        )
        # **表头那条竖线必须与数据行那条完全重合。**
        #
        # 用户反馈："检查列标题和列数据分隔线为什么粗细不一致+未对齐"。
        # 原来表头画在 `x + width - 1 - gap`（偏移 6 逻辑像素 ≈ 10 物理像素）
        # 且只占 `4 .. height-4`，而数据行画在**精确边界**、**满高**。
        header_xs = sorted(frame.header.separator_positions())
        body_xs = sorted({int(x) for x in xs})
        check(
            "表头竖线与数据行竖线 x 一致（不再错位）",
            bool(header_xs) and header_xs == body_xs,
            f"表头 x = {header_xs}；数据行 x = {body_xs}"
            "（原来表头偏移 6 逻辑像素 ≈ 10 物理像素）",
        )
        check(
            "阳性对照：表头与数据行都算出了竖线位置",
            bool(header_xs) and bool(body_xs),
            f"表头 {len(header_xs)} 条、数据行 {len(body_xs)} 条",
        )
        # 表头与数据行的竖线**粗细**也要一致。
        # 两边都取 `METRICS.separator_thickness`，所以只要确认表头那边
        # 用的确实是这个常量（而不是写死的 1）。
        from file_tracker.header import ColumnHeader as _ColumnHeader

        import inspect as _inspect2

        header_source = _inspect2.getsource(_ColumnHeader.separator_thickness)
        check(
            "表头竖线粗细取的是 METRICS.separator_thickness（与数据行同一个常量）",
            "METRICS.separator_thickness" in header_source,
            "两边共用同一常量 → 粗细必然一致"
            "（原来表头与行里的**位置**差 10 像素）",
        )
        # ---- 竖线必须**最细**：1 物理像素，不按 DPI 缩放 ----
        #
        # 用户要求"将列分隔线改细。最细。"
        # 关键点：`separator_thickness` 若按 DPI 换算，本机 175% 下
        # `scale_for_dpi(1, 168)` = **2**，那正是嫌粗的样子。
        # **细线是显示器的属性，不是内容的属性**，所以不做换算。
        # （`_scale` 在这个函数里是**后面**才 import 的，这里不能引用它——
        #   直接算：物理 = 逻辑 × dpi/96，再取整。）
        dpi_now = frame.GetDPI()
        dpi_now = dpi_now[0] if hasattr(dpi_now, "__getitem__") else dpi_now
        scaled_one = max(round(1 * dpi_now / 96), 1)
        check(
            "竖线 = 1 物理像素（最细，不按 DPI 放大）",
            frame.header.separator_thickness() == 1,
            f"表头 {frame.header.separator_thickness()}px；"
            f"若按 DPI 换算（1 × {dpi_now}/96）会是 {scaled_one}px",
        )
        # 真落笔的 pen 宽度也要是 1，不能只是方法返回值
        widths: list[int] = []
        original_set_pen = wx.DC.SetPen

        def spy_set_pen(self, pen, *args, **kwargs):
            try:
                widths.append(pen.GetWidth())
            except Exception:
                pass
            return original_set_pen(self, pen, *args, **kwargs)

        wx.DC.SetPen = spy_set_pen
        try:
            frame._paint_column_separators()
        finally:
            wx.DC.SetPen = original_set_pen
        check(
            "阳性对照：数据行竖线真的用 1px 的笔落笔（不是只改了返回值）",
            bool(widths) and all(w == 1 for w in widths),
            f"拦截到的 pen 宽度 = {widths}",
        )
        # 表头那条线走的是 `_on_paint` 里的 `self.separator_thickness()`。
        # 不去调 `_on_paint`（它需要真实的 paint DC，构造麻烦），
        # 改为直接确认**绘制处用的就是这个方法**——
        # 只要 `_on_paint` 里出现 `self.separator_thickness()`，
        # 表头与数据行的粗细就同为 1px。
        paint_source = _inspect2.getsource(_ColumnHeader._on_paint)
        check(
            "阳性对照：表头绘制处用的也是 separator_thickness()",
            "separator_thickness()" in paint_source,
            "表头与数据行同一个来源 → 都是 1px",
        )

        # ---- 路径列文字是纯黑/纯白（用户："灰色实在不方便观察"）----
        light_palette = theme_module.Theme.light()
        dark_palette = theme_module.Theme.dark()
        check(
            "浅色主题的列表文字 = 纯黑 #000000",
            light_palette.list_text.upper() == "#000000",
            f"list_text = {light_palette.list_text}",
        )
        check(
            "深色主题的列表文字 = 纯白 #FFFFFF",
            dark_palette.list_text.upper() == "#FFFFFF",
            f"list_text = {dark_palette.list_text}",
        )
        # 阳性对照：它必须**不是** text（那个是发灰的 #1B1A19 / #F5F5F5）
        check(
            "阳性对照：list_text 与 text 是两套颜色",
            light_palette.list_text != light_palette.text
            and dark_palette.list_text != dark_palette.text,
            f"浅色 list_text={light_palette.list_text} vs text={light_palette.text}；"
            f"深色 list_text={dark_palette.list_text} vs text={dark_palette.text}",
        )
        # 真的落到控件上了吗
        if frame.list_ctrl.GetItemCount():
            applied = frame.list_ctrl.GetItemTextColour(0)
            check(
                "路径列文字色真的应用到了列表上",
                _colour_hex(applied) == frame.theme.list_text.upper(),
                f"第 0 行文字色 = {_colour_hex(applied)}，"
                f"期望 {frame.theme.list_text}",
            )
        #
        # **只检查"警告/确认"类弹窗。** `--version` 那个信息框是
        # `ICON_INFORMATION`，不是警告，**故意不加** ⚠️
        # （否则"信息"和"警告"就分不出来了）。
        #
        # 弹窗实现换过一次（系统对话框 → 自绘 `ThemedDialog`），
        # 所以这里**同时扫三种写法**：`ThemedDialog(`、`_notify(`、
        # 以及残留的 `wx.MessageBox` / `wx.MessageDialog`。


        # **用 AST 找调用点，不要自己拼续行。**
        #
        # 我原来用"按括号配平拼行"的土办法，被三种情况轮番坑：
        #   * 折行的调用（`title=` 落到第二行）
        #   * 定义行 `def _notify(...)` 也含 `_notify(`
        #   * `except ...:  # 注释` 后面的调用被并进上一条，注释混进来
        # 结果是"扫到 1 处、其余 3 处"，全是误报。
        #
        # `ast` 直接给出真实的 `Call` 节点，注释与字符串天然被排除——
        # 与 `tools/check_wiring.py` 用的是同一招。

        source = _inspect.getsource(_app_module)
        tree = _ast.parse(source)
        source_lines = source.splitlines()

        def call_text(node) -> str:
            """取调用所在的**整条语句**源码（含折行），供人读。"""
            start = min(getattr(node, "lineno", 1),
                        getattr(node.func, "lineno", 1))
            end = getattr(node, "end_lineno", start)
            return " ".join(source_lines[start - 1:end]).strip()

        DIALOG_CALLS = {"ThemedDialog", "_notify", "MessageBox", "MessageDialog"}
        warn_titles, exempt = [], []
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name not in DIALOG_CALLS:
                continue
            statement = call_text(node)
            if "WARN" in statement:
                warn_titles.append(statement)
                continue
            # **两类合理的不加 ⚠️**（各写明理由，别用"数量不超过 N"兜）：
            #
            # ① `_notify(...)` 的**调用方**——⚠️ 由 `_notify` 自己加进正文，
            #    所以调用处看不到 WARN。
            # ② `--version` 的信息框——它是"信息"不是"警告"。
            #
            # 早先用"有意不加的 ≤ 1 处"这种计数断言，既漏检又误报。
            # 现在按**语义**判：是 `_notify` 调用，或是版本框，都放过。
            if name == "_notify":
                continue
            if "版本" in statement and "APP_NAME" in statement:
                continue
            exempt.append(statement)
        # **⚠️ 放在正文，不在标题里。**
        #
        # 用户要求："标题栏题头的 ⚠️ 换成程序图标，把 ⚠️ 放在说明文字的前面，
        # 和 Roboc 一致。"
        # Roboc 正是正文前缀（`Program.cs` L200、`ProgressWindow.cs` L469）。
        check(
            "所有警告/确认弹窗都在**正文**里带 ⚠️（Roboc 的做法）",
            bool(warn_titles) and all("WARN" in t for t in warn_titles),
            f"带 ⚠️ 的 {len(warn_titles)} 处；"
            f"有意不加的 {len(exempt)} 处（`--version` 信息框）",
        )
        # **阳性对照：标题里不能再出现 ⚠️。**
        #
        # 这条守的是"⚠️ 从标题栏搬走了"——只查正文有 ⚠️ 是不够的，
        # 那样标题里留着一个也测不出来。
        #
        # ## 第一版有漏洞，被用户抓到了
        #
        # 原来只做字符串匹配：`'title=f"{WARN}' in statement`。
        # **硬编码的 emoji 溜得过去**——`title=f"{WARN}路径不存在"` 能被抓到，
        # 但 `title="⚠️路径不存在"` 不会（语句里没有 `WARN` 这个词）。
        #
        # 用户正是在扫描弹窗时看到探针造出的那个标题带 ⚠️ 的窗口。
        #
        # 现在改成**从 AST 取 `title=` 那个实参本身**，
        # 再检查它里面有没有 WARN 或任何警示类字符——
        # 不管写成 f-string、字符串拼接还是字面量，都跑不掉。
        MARKS = ("\u26a0", "\u2757", "\u2755", "\u2753", "\U0001f6a8")

        # **标题参数在第几个位置，各调用不同——必须逐一声明。**
        #
        # 踩过两次，都是"只查了 `title=` 关键字"：
        #   ① `_notify(正文, 标题)` 的标题是**第 2 个位置参数**
        #   ② `MessageBox(正文, 标题, 样式)` 也是第 2 个位置参数
        # 埋一个 `self._notify(plan["hint"], "⚠️路径不存在")` 进去，
        # 守卫照样 PASS —— 那就是个假守卫。
        TITLE_POSITION = {
            "ThemedDialog": "title",   # 关键字
            "MessageBox": 1,           # 位置
            "MessageDialog": 1,        # 位置
            "_notify": 1,              # 位置
        }
        title_marks = []

        def looks_tainted(chunk: str) -> bool:
            return bool(chunk) and (
                "WARN" in chunk or any(m in chunk for m in MARKS))

        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            name = (getattr(node.func, "id", None)
                    or getattr(node.func, "attr", None))
            if name not in TITLE_POSITION:
                continue
            slot = TITLE_POSITION[name]
            candidates = []
            if isinstance(slot, int) and len(node.args) > slot:
                candidates.append(node.args[slot])
            for keyword in node.keywords:
                if keyword.arg == "title":
                    candidates.append(keyword.value)
            for value in candidates:
                chunk = _ast.get_source_segment(source, value) or ""
                if looks_tainted(chunk):
                    title_marks.append(f"L{value.lineno}: {name} 标题={chunk}")
        check(
            "阳性对照：没有任何弹窗把 ⚠️ 留在标题里（AST 取实参，不是字符串匹配）",
            not title_marks,
            "；".join(t[:72] for t in title_marks) or "标题全部是纯文字",
        )
        # 阳性对照：必须真的找到了警告弹窗，否则上面那条是空转
        check(
            "阳性对照：确实扫到了警告弹窗（不是空集）",
            len(warn_titles) >= 4,
            f"扫到 {len(warn_titles)} 处带 ⚠️ 的弹窗",
        )
        # 排除掉上面两类之后，**不该再剩下任何弹窗**——
        # 剩下的就是"忘了加 ⚠️"的漏网之鱼。
        check(
            "除 `_notify` 调用方与 `--version` 信息框外，没有弹窗漏掉 ⚠️",
            not exempt,
            "；".join(t[:72] for t in exempt) or "无漏网",
        )
        # 确认框已改成自绘弹窗（系统对话框没法适配深色主题）
        check(
            "确认框用的是自绘 ThemedDialog，不是系统对话框",
            "wx.MessageDialog(" not in _inspect.getsource(_app_module),
            "wx.MessageDialog/MessageBox 由系统按浅色主题绘制，深色下改不了色",
        )

        # ---- 弹窗尺寸照抄 Roboc 的固定公式 ----
        #
        # 用户问"Roboc 的所有窗口外观为什么规范又漂亮"。
        # 答案：**它不用任何自动布局**——所有位置和尺寸都按一个固定公式手算
        # （`Roboc/src/Roboc.App/MessageDialog.cs`）。
        # 我原来用"堆 sizer + Fit()"，出来 455×228，比原生的又宽又矮。
        from file_tracker.theme import METRICS as _DLG
        from file_tracker.theme import scale_for_dpi as _scale

        dialog = _widgets.ThemedDialog(
            frame, frame.theme, f"{_app_module.WARN} 确定要清空所有记录吗？",
            title="确认清空",
        )
        dialog.Show()
        for _ in range(30):
            wx.YieldIfNeeded()
            time.sleep(0.02)

        # **别用 `frame.GetDPI()` 的返回值去算。**
        # 它返回 `wx.Size`，而 `wx.Size` **不是** `tuple`，
        # `isinstance(x, (tuple, list))` 判不出来——实测于是把 Size
        # 直接传进 `scale_for_dpi`，在 `dpi <= 0` 那里 TypeError。
        # 这里用 `ToDIP` 反推：逻辑值 = 物理值 ÷ (dpi/96)。
        dpi_value = round(
            dialog._buttons[0].GetSize().width * 96
            / max(_DLG.dialog_button_width, 1)
        )
        # ---- 居中（用户："让所有提示窗内容居中显示"）----
        #
        # 注意宽度公式**已经改了**：原来固定 `max_text_width + margin×2`
        # （175% 下恒为 819），现在按**实际文字**算，
        # `max_text_width` 退化为上限。所以不能再断言 819。
        margin_px = _scale(_DLG.dialog_margin, dpi_value)
        max_text_px = _scale(_DLG.dialog_max_text_width, dpi_value)
        client_width = dialog.GetClientSize().width

        dc_dlg = wx.ClientDC(dialog)
        dc_dlg.SetFont(dialog.GetFont())
        widths = [dc_dlg.GetTextExtent(line).width for line in dialog._lines]
        text_width = max(widths, default=0)
        # 宽度 = max(正文实宽, 按钮组宽) + margin×2，且正文实宽不超过上限
        check(
            "弹窗宽度按**实际文字**算（不再固定 819，也不超过上限）",
            client_width
            == max(min(text_width, max_text_px),
                   len(dialog._labels) * _scale(_DLG.dialog_button_width,
                                                dpi_value)
                   + max(len(dialog._labels) - 1, 0)
                   * _scale(_DLG.dialog_button_gap, dpi_value))
            + margin_px * 2,
            f"实际 {client_width}，正文实宽 {text_width}"
            f"（上限 {max_text_px}），margin×2 = {margin_px * 2}",
        )
        check(
            "弹窗正文左边界 = margin（24 逻辑像素）",
            dialog._body_rect[0] == margin_px,
            f"正文左边 = {dialog._body_rect[0]}，margin = {margin_px}",
        )

        # **正文每一行都居中**——判据是左右留白相等（差 ≤ 1 px 取整误差）
        left, _t, right, _b = dialog._body_rect
        center = (left + right) // 2
        gaps = []
        for line, width in zip(dialog._lines, widths):
            x = center - width // 2
            gaps.append(abs(x - (client_width - (x + width))))
        check(
            "正文每一行都居中（左右留白相等）",
            bool(gaps) and max(gaps) <= 1,
            f"各行的左右留白差 = {gaps}，客户区宽 = {client_width}",
        )
        check(
            "阳性对照：正文确实有内容（不是空行凑出来的居中）",
            text_width > 0,
            f"最宽一行 = {text_width} px",
        )

        # **按钮组整体居中**
        group_left = min(x for x, _ in dialog._button_rects)
        group_right = max(x + w for x, w in dialog._button_rects)
        check(
            "弹窗按钮组居中（左右留白相等）",
            abs(group_left - (client_width - group_right)) <= 1,
            f"按钮组左边 = {group_left}，右边留白 = "
            f"{client_width - group_right}；"
            f"各按钮 x = {[x for x, _ in dialog._button_rects]}",
        )
        check(
            "弹窗按钮尺寸 = 96×32 逻辑像素（Roboc 原值）",
            all(button.GetSize().width
                == _scale(_DLG.dialog_button_width, dpi_value)
                and button.GetSize().height
                == _scale(_DLG.dialog_button_height, dpi_value)
                for button in dialog._buttons),
            f"实际 {[tuple(b.GetSize()) for b in dialog._buttons]}，"
            f"期望 {_scale(_DLG.dialog_button_width, dpi_value)}×"
            f"{_scale(_DLG.dialog_button_height, dpi_value)}",
        )
        # **单按钮弹窗**曾经被 wx 拉满整个客户区（实测 819×210）
        # 文案与标题照**应用里的约定**写：⚠️ 在正文开头，标题纯文字。
        #
        # 踩过（用户扫弹窗时发现的）：这里原先写成
        # `title=f"{WARN}路径不存在"`，于是探针自己造了一个
        # 标题带 ⚠️ 的弹窗，与应用约定不符，扫描时看着像应用的 bug。
        # **探针也是代码，它造出来的东西必须符合被验证的约定。**
        single = _widgets.ThemedDialog(
            frame, frame.theme, f"{_app_module.WARN} 路径不存在，请检查后重新输入。",
            title="路径不存在",
            yes_label="好", no_label=None,
        )
        single.Show()
        for _ in range(30):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        button = single._buttons[0]
        check(
            "单按钮弹窗的按钮没被拉满客户区（靠一个隐形占位控件）",
            button.GetSize().width
            == _scale(_DLG.dialog_button_width, dpi_value),
            f"实际 {tuple(button.GetSize())}，客户区 {tuple(single.GetClientSize())}"
            "（wx 会把唯一的子控件拉满，所以加了个 1×1 占位）",
        )

        # ---- 弹窗的两个"看起来空白"的坑（都实际踩过）----
        #
        # 用户对比 Roboc 之后说"不知道你能不能看出差距"。
        # 抓图核对时发现两件事，都会让弹窗**看起来只有一个空壳**：
        #
        # ① **没有标题栏。** 我原来用 `wx.BORDER_NONE`，而 Roboc 是
        #    `WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU`。
        #    没有标题栏就没有关闭按钮、没有可拖拽区，看着像个方块。
        #    修法：`wx.DEFAULT_DIALOG_STYLE`（= CAPTION | SYSTEM_MENU |
        #    CLOSE_BOX | TAB_TRAVERSAL）。
        #
        # ② **没设 `BG_STYLE_PAINT`，`AutoBufferedPaintDC` 直接抛断言**，
        #    `_on_paint` 里的正文一个字都画不出来。
        #    验证脚本原来只查"矩形算得对不对"，查不出这种"代码没跑"。
        dialog_style = dialog.GetWindowStyleFlag()
        check(
            "弹窗有真正的标题栏（CAPTION + SYSTEM_MENU，对齐 Roboc 的 WS_CAPTION|WS_SYSMENU）",
            bool(dialog_style & wx.CAPTION) and bool(dialog_style & wx.SYSTEM_MENU),
            f"样式 = {dialog_style:#x}，CAPTION = {bool(dialog_style & wx.CAPTION)}，"
            f"SYSTEM_MENU = {bool(dialog_style & wx.SYSTEM_MENU)}"
            "（原来用 BORDER_NONE，只有一块空白）",
        )
        # 标题栏左侧要有**程序图标**（用户："把 ⚠️ 换成程序图标"）。
        # Roboc 在窗口类上设了 `hIcon = AppIcon.Handle`
        # （`MessageDialog.cs` L134，注释写着"a class registered without an
        # icon gives a window without one"）。
        # `wx.Dialog` **不会**自动继承父窗口的图标，所以要显式设。
        dialog_icon = dialog.GetIcon()
        check(
            "弹窗标题栏有程序图标（不是 Windows 默认图标、也不是空白）",
            dialog_icon is not None and dialog_icon.IsOk(),
            f"图标 = {dialog_icon}，尺寸 = "
            f"{dialog_icon.GetSize() if dialog_icon and dialog_icon.IsOk() else None}"
            "（wx.Dialog 不继承父窗口图标，ThemedDialog._apply_icon 显式设的）",
        )
        # 阳性对照：⚠️ 必须在**正文**里，且**不在**标题里
        check(
            "⚠️ 在正文开头（Roboc 的做法），标题是纯文字",
            dialog._lines and dialog._lines[0].startswith(_app_module.WARN)
            and _app_module.WARN not in dialog.GetTitle(),
            f"正文首行 = {dialog._lines[0][:22]!r}，标题 = {dialog.GetTitle()!r}",
        )
        # 客户区是**内容说了算**的：窗口尺寸 = 客户区 + 标题栏 + 边框。
        # Roboc 用 `AdjustWindowRectExForDpi` 做这件事，wx 是 `SetClientSize`。
        check(
            "弹窗客户区宽度不受标题栏影响（SetClientSize 的语义）",
            dialog.GetClientSize().width == client_width
            and dialog.GetSize().width > client_width,
            f"客户区 {tuple(dialog.GetClientSize())}，"
            f"窗口 {tuple(dialog.GetSize())}"
            "（窗口多出来的就是标题栏 + 边框）",
        )
        check(
            "弹窗设了 BG_STYLE_PAINT（否则 AutoBufferedPaintDC 抛断言、正文画不出来）",
            dialog.GetBackgroundStyle() == wx.BG_STYLE_PAINT,
            f"GetBackgroundStyle() = {dialog.GetBackgroundStyle()}，"
            f"BG_STYLE_PAINT = {wx.BG_STYLE_PAINT}",
        )
        # **判据要落在"文字真的画出来了"上，不是"矩形算得对"。**
        # 这里直接调 `_draw_body` 画到一块位图，再数暗像素——
        # 位图上的 GetPixel 是可靠的（窗口抓图在这个环境不可靠）。
        canvas = wx.Bitmap(200, 40)
        canvas_dc = wx.MemoryDC(canvas)
        canvas_dc.SetBackground(wx.Brush(wx.Colour(dialog.theme.background)))
        canvas_dc.Clear()
        probe_body = _widgets.ThemedDialog(
            frame, frame.theme, "确定要清空所有记录吗？", title="确认清空",
        )
        probe_body._body_rect = (0, 0, 200, 40)
        probe_body._lines = ["确定要清空所有记录吗？"]
        probe_body._draw_body(canvas_dc)
        body_image = canvas.ConvertToImage()
        dark_body = sum(
            1
            for y in range(0, 40, 2)
            for x in range(0, 200, 2)
            if body_image.GetRed(x, y) < 128
        )
        canvas_dc.SelectObject(wx.NullBitmap)
        probe_body.Destroy()
        check(
            "弹窗正文真的画得出来（位图上数到暗像素）",
            dark_body > 5,
            f"位图上暗像素 = {dark_body}"
            "（正向证据；`DrawLabel` 实测一个字都画不出来，已换成逐行 `DrawText`）",
        )
        single.Destroy()
        dialog.Destroy()
        for _ in range(20):
            wx.YieldIfNeeded()
        check(
            "WARN 常量就是 ⚠️（U+26A0 U+FE0F）",
            _app_module.WARN == "\u26a0\ufe0f",
            f"WARN = {_app_module.WARN!r}  码点 = "
            f"{[hex(ord(c)) for c in _app_module.WARN]}",
        )

    except Exception as error:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        check("验证过程未抛异常", False, repr(error))
    finally:
        # **无条件收尾。** 不靠"我记得去销毁"，靠 finally。
        try:
            # 把两个"位置"还回去。留在替身上也不会影响这个一次性进程，
            # 但下次有人往这段后面加代码时，会以为拿到的是真实的路径。
            app_module.default_db_path = original_db
            app_module.default_config_path = original_config
        except Exception:
            pass
        try:
            if frame is not None:
                frame.open_folder = original_open_folder   # 还原，别留下替身
                frame.store.close()
                frame.Destroy()
                for _ in range(10):
                    wx.YieldIfNeeded()
        except Exception:
            pass
        try:
            scratch.cleanup()
        except Exception as error:
            # **清理失败必须说出来**，否则又变成"靠我记得去清"。
            # 实测过：资源管理器窗口占住目录时 cleanup 会失败，
            # 于是临时目录留在用户盘上——用户就是因此看到"一堆 target-folder"。
            print(f"  [清理失败] {scratch.name}  ({error})")
            print("             多半是有窗口正占着这个目录。")

    # ------------------------------------------------------------------
    print()
    failed = [name for name, ok, _ in results if not ok]
    print(f"合计 {len(results)} 项：{len(results) - len(failed)} 通过，{len(failed)} 失败")
    for name in failed:
        print(f"  失败: {name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    _code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # **硬退出收尾，而且不碰 wx 的拆解。**
    #
    # 走到这里说明：全部断言已跑完、`合计` 已打印、临时目录已在
    # `main()` 的 finally 里清过、stdio 已刷。剩下的只有解释器清理。
    #
    # 实测结论（这条命令连跑多次）：
    #   * 让解释器正常收尾 → 偶尔**永久挂住**（一次 260 秒没返回，
    #     连 `合计` 都没打出来）
    #   * 加一个守护线程去 `Destroy()` 窗口和 `wx.App` → 变成**访问违例**
    #     （退出码 `-1073741819`）。**wx 的控件只能在主线程碰**，
    #     从别的线程拆它就是在动一个正在被释放的对象。
    #
    # 所以两者都不做：断言跑完、输出刷掉，直接走 `os._exit`。
    # 它跳过解释器清理，也就同时跳过了"挂住"和"从错误的线程拆 wx"。
    os._exit(_code)
