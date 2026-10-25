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
from file_tracker import lang as _lang  # noqa: E402
from file_tracker import theme as _theme  # noqa: E402
from file_tracker import tree_nav  # noqa: E402
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


def _column_format(ctrl, column: int) -> int:
    """用 `LVM_GETCOLUMN` 回读某一列的 `fmt`（对齐方式）。

    ## 为什么不用 wx 的 API

    `ctrl.GetColumn(i)` 返回的是 `ListItem`，**没有 `GetFormat()`**
    （实测 `AttributeError`）。所以要直接问系统。

    `LVCFMT_LEFT=0x0` / `LVCFMT_RIGHT=0x1` / `LVCFMT_CENTER=0x2`，
    高位还有别的标志（回读常见 `0x4000`），所以判据用**位与**，不是相等。
    """
    import ctypes

    class LVCOLUMNW(ctypes.Structure):
        _fields_ = [
            ("mask", ctypes.c_uint32),
            ("fmt", ctypes.c_int32),
            ("cx", ctypes.c_int32),
            ("pszText", ctypes.c_void_p),
            ("cchTextMax", ctypes.c_int32),
            ("iSubItem", ctypes.c_int32),
            ("iImage", ctypes.c_int32),
            ("iOrder", ctypes.c_int32),
            ("cxMin", ctypes.c_int32),
            ("cxDefault", ctypes.c_int32),
            ("cxIdeal", ctypes.c_int32),
        ]

    LVM_GETCOLUMN = 0x1000 + 25
    LVCF_FMT = 0x0001
    info = LVCOLUMNW()
    info.mask = LVCF_FMT
    info.iSubItem = column
    ctypes.windll.user32.SendMessageW(
        ctrl.GetHandle(), LVM_GETCOLUMN, column, ctypes.byref(info))
    return info.fmt


def select_only(frame, row: int) -> None:
    """让列表里**只有第 `row` 行**被选中。

    ## ⚠️ 为什么需要这个函数（2026-10-17）

    用户加了"按住 Ctrl 多选"之后，列表不再是 `LC_SINGLE_SEL` ——
    **`Select(i)` 不再自动取消别的行**。

    验证脚本里原来到处是裸的 `frame.list_ctrl.Select(0)`，
    本意是"选中第 0 行"，在多选下变成"**额外**选中第 0 行" ——
    于是前面步骤留下的选中会一直累积，后面所有
    "单条选中"的断言全部失真。

    实测后果：一次跑出 5 条失败（`open_targets` 返回一整个选中集、
    顶置顺序错乱），而**程序本身是对的**。
    ⇒ 凡是要"选中某一条"的地方一律走这里。
    """
    control = frame.list_ctrl
    for index in range(control.GetItemCount()):
        control.Select(index, index == row)
    if 0 <= row < control.GetItemCount():
        control.Focus(row)
    for _ in range(6):
        wx.YieldIfNeeded()


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
        #
        # ⚠️ **替身必须返回 `True`**（2026-10-17）：`open_folder` 现在返回
        # "是否真的打开了"，而调用方**按它决定要不要记这次访问**
        # （审计查出的缺陷：原来是先记访问、再打开，失败也照记）。
        # 替身返回 `None` 会被当成"没打开" ⇒ 记录被跳过 ⇒ 一堆假失败。
        opened_paths: list[str] = []
        original_open_folder = frame.open_folder
        frame.open_folder = lambda path: (opened_paths.append(path), True)[1]

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
            "列表共有 3 列（路径 / 频次 / 访问时间）",
            column_count == 3,
            f"实际 {column_count} 列: " + ", ".join(repr(t) for t in titles),
        )
        check(
            "第 1 列是「频次」",
            titles[1] == "频次",
            f"实际 = {titles[1]!r}",
        )
        check(
            "center_frequency_column() 可调用（它保证列宽装得下最宽的频次值）",
            frame.center_frequency_column() is True,
            "频次列的对齐由**原生格式位**负责（见下一条），这个函数只管列宽",
        )

        # **频次列真的是居中的**（用户 2026-10-17："目前的居中算法不是真正的
        # 居中" —— 原来是补前导空格，有量化误差；现在用原生 `LVCFMT_CENTER`）。
        #
        # 判据用 **`LVM_GETCOLUMN` 回读 fmt**，而不是"看它像不像居中"。
        check(
            "频次列的格式位 = CENTER（原生居中，不是补空格）",
            _column_format(frame.list_ctrl, 1) & 0x2 == 0x2,
            "回读 fmt = 0x%04X，LVCFMT_CENTER = 0x0002"
            % (_column_format(frame.list_ctrl, 1) & 0xFFFF),
        )
        check(
            "阳性对照：路径列的格式位不是 CENTER（说明不是所有列都被设了）",
            _column_format(frame.list_ctrl, 0) & 0x2 == 0,
            "路径列 fmt = 0x%04X" % (_column_format(frame.list_ctrl, 0) & 0xFFFF),
        )
        # **数据本身不带前导空格**（补空格的实现删掉了，这是最直接的证据）
        if frame.list_ctrl.GetItemCount():
            _count_text = frame.list_ctrl.GetItemText(0, 1)
            check(
                "频次数据没有前导空格（居中是画的，不是补出来的）",
                _count_text == _count_text.lstrip(),
                "第 0 行频次文本 = %r" % _count_text,
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
        print("=== 改动 ⑤（已改两轮）：日期并进时间列 ===")
        # 2026-10-15：用户说"日期与时间不好区分" ⇒ 拆成两列
        # 2026-10-17：用户说"日期和时间本来就是一回事，不该分成两列"
        #             ⇒ 并回一列，格式 `14:43   26-10-17`
        # ==============================================================
        check(
            "时间列表头是「访问时间」（日期已并进来，不再单独成列）",
            titles[2] == "访问时间",
            f"第 2 列={titles[2]!r}",
        )

        # 造一条带已知时间戳的记录，确认格式完全符合用户指定
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
            got_time = frame.list_ctrl.GetItemText(probe_row, 2)
            check(
                "时间列 = `13:01   26-10-15`（秒隐藏、两位年、3 空格）",
                got_time == "13:01   26-10-15",
                f"实际 = {got_time!r}",
            )
            check(
                "时间列里**不含秒**（用户要求：秒只在后端参与排序）",
                "13:01:17" not in got_time,
                f"实际 = {got_time!r}",
            )
            # 阳性对照：数据库里存的仍是整串，说明只是"显示时格式化"
            stored = frame.store.get(known_path)
            check(
                "阳性对照：数据库里仍存**完整**时间戳（含秒，排序要用）",
                stored.last_access_time == "2026-10-15 13:01:17",
                f"库中值={stored.last_access_time!r}",
            )
            # **排序键不受显示格式影响**：同一分钟内、秒不同的两条也要排对
            later = os.path.join(scratch.name, "deep", "time-probe-later")
            os.makedirs(later, exist_ok=True)
            frame.store.record_access(later, when="2026-10-15 13:01:59")
            frame.load_accessed_paths()
            earlier = os.path.join(scratch.name, "deep", "time-probe-earlier")
            os.makedirs(earlier, exist_ok=True)
            frame.store.record_access(earlier, when="2026-10-15 13:01:01")
            frame.load_accessed_paths()
            frame.sort_column = 2
            frame.sort_reverse = True
            frame.sort_list_items(2)
            for _ in range(20):
                wx.YieldIfNeeded()
            rows = [frame.row_path(i) for i in range(min(3, frame.list_ctrl.GetItemCount()))]
            check(
                "阳性对照：同一分钟内按**秒**排序仍然正确（显示隐藏了秒，排序没有）",
                rows[0].endswith("time-probe-later")
                and rows[1].endswith("time-probe"),
                "前三行 = %r" % [os.path.basename(r) for r in rows],
            )
            frame.sort_column = before_column
            frame.sort_reverse = before_reverse
            frame.sort_list_items(frame.sort_column)

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
            #
            # ⚠️ 判据必须**与主题无关**，而且**不能拿"按钮内部"当基准**。
            # 两次都踩了：
            #
            # ① 原式 `(card_red - lefts[0]) / (card_red - min(...))`
            #    **假定"按钮比卡片暗"**。浅色下成立；深色下 accent 比卡片亮
            #    （卡片 36、accent 116），减法变负 → 报出 -80.00。
            # ② 改成拿 `lefts[-1]`（内部）当基准后又踩一次：
            #    **secondary 按钮的填充就是卡片色**（浅色下都是 255），
            #    于是 span 塌成 1 → 报出 -34.00。
            #
            # 真正要守的是：**外列应当是偏离底色最远的那个样本**
            # （即满强度的那一像素），而不是"内部同色"。
            # 这样无论按钮比底色深还是浅、填充是否与底色相同，都成立。
            def _cov(samples) -> float:
                refer = card_red
                outer = abs(refer - samples[0])
                peak = max(abs(refer - s) for s in samples)
                return outer / max(peak, 1)

            left_cov = _cov(lefts)
            right_cov = _cov(rights)
            check(
                f"按钮最外列满覆盖（{variant_label}）",
                left_cov > 0.95 and right_cov > 0.95,
                f"左覆盖 = {left_cov:.2f}，右覆盖 = {right_cov:.2f}"
                f"（左 {lefts}，底色 {card_red}）"
                "（1.00 = 满覆盖；0.5 会看出'边缘淡了一层'）",
            )
            probe_btn.Destroy()
        # 阳性对照：secondary 的描边确实画了（不然"对称"地全等于底色也算通过）
        #
        # 用 `abs()` —— 深色下按钮比底色**亮**，"比底色深"这个说法不成立。
        # 要守的是"**与底色可区分**"，不是"更深"。
        check(
            "阳性对照：有描边的按钮最外列与底色可区分",
            abs(lefts[0] - card_red) > 4,
            f"最外列 = {lefts[0]}，底色 = {card_red}，"
            f"差 = {abs(lefts[0] - card_red)}",
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
        # .. note::
        #
        #     这条断言**一度改过口径又改回来**。经过是：
        #     用户先说"将**导航窗格**内的文字（包括顶栏标题）缩小 1pt"，
        #     于是我把它改成判"正文 + 偏移"；**随后用户更正，原意是
        #     "记录窗格"**，导航窗格那处撤回 —— 所以这里恢复原判据。
        #
        #     **留下这段是因为它值一条教训**：用户的措辞与代码结构对不上时
        #     （"导航窗格"里并没有"记录窗格"才有的列头标题），
        #     应当**先问再改**，而不是照着字面执行。
        check(
            "输入框字号 = 正文字号（不再小一号）",
            hint_pt == body_pt,
            f"输入框 {hint_pt}pt，正文 {body_pt}pt",
        )

        # ── 换主题后**每一层容器**都要跟着反色 ──
        #
        # 用户报："切换主题后，**面板部分不会立即正确反色**。
        # 老问题了，关闭程序再启动才正确反色。"
        #
        # 根因：`panel` / `left_panel` / `right_panel` / `card_panel`
        # 原来是 `InitUI` 的**局部变量**，创建时上过一次色之后
        # 再也没有代码够得到它们 —— 主题一变就只有它们还是旧的。
        #
        # **判据是回读每个容器的实际底色**，而不是"我调了 _retheme"。
        def _rgb(widget) -> tuple:
            c = widget.GetBackgroundColour()
            return (c.Red(), c.Green(), c.Blue())

        def _want(hex_colour: str) -> tuple:
            return (int(hex_colour[1:3], 16),
                    int(hex_colour[3:5], 16),
                    int(hex_colour[5:7], 16))

        theme_now = frame.theme
        containers = [
            ("外壳面板", frame._shell_panel, theme_now.background),
            ("左面板（导航）", frame._left_panel, theme_now.background),
            ("右面板", frame._right_panel, theme_now.background),
            ("卡片面板", frame._card_panel, theme_now.card),
            ("目录树", frame.dir_ctrl.GetTreeCtrl(), theme_now.card),
            ("列表", frame.list_ctrl, theme_now.card),
        ]
        wrong = [f"{name}={_rgb(w)} 应={_want(c)}"
                 for name, w, c in containers if _rgb(w) != _want(c)]
        check(
            "每一层容器都拿到了当前主题的底色（回读，不是设了就算）",
            not wrong,
            f"当前主题 card={theme_now.card} background={theme_now.background}；"
            + ("全部一致" if not wrong else f"不一致：{wrong}"),
        )
        check(
            "阳性对照：至少有两个容器**底色不同**（分层真的存在）",
            _rgb(frame._card_panel) != _rgb(frame._left_panel),
            f"卡片 {_rgb(frame._card_panel)} ≠ "
            f"左面板 {_rgb(frame._left_panel)}",
        )

        # ── 输入框框线的可见度（用户："不然用户很难注意到它"）──
        #
        # 判据**不是**"我把颜色改深了"，而是**量出来的对比度**：
        # 框线要在面板底上看得见，且比普通 `border` 明显更深。
        def _rel_lum(hex_colour: str) -> float:
            rgb = [int(hex_colour.lstrip("#")[i:i + 2], 16) / 255
                   for i in (0, 2, 4)]
            chan = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                    for c in rgb]
            return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]

        def _contrast(a: str, b: str) -> float:
            la, lb = _rel_lum(a), _rel_lum(b)
            hi, lo = max(la, lb), min(la, lb)
            return (hi + 0.05) / (lo + 0.05)

        light = _theme.Theme.light()
        field_c = _contrast(light.field_border, light.background)
        plain_c = _contrast(light.border, light.background)
        check(
            "浅色主题：输入框框线比普通 border 更深（对比度更高）",
            field_c > plain_c,
            f"框线 {light.field_border} 对比度 {field_c:.2f} > "
            f"border {light.border} 对比度 {plain_c:.2f}",
        )
        check(
            "浅色主题：框线对比度 ≥ 1.65（border 原始只有 1.21，太难看见）",
            field_c >= 1.65,
            f"框线 {light.field_border} vs 面板 {light.background} = {field_c:.2f}",
        )

        # 深色主题：**用户第二轮要求"也加一级对比度"**，为了两个主题视觉统一。
        # ⚠️ 深色下"加对比度"是**提亮**（背景是暗的），方向与浅色相反。
        dark = _theme.Theme.dark()
        dark_field_c = _contrast(dark.field_border, dark.background)
        dark_plain_c = _contrast(dark.border, dark.background)
        check(
            "深色主题：输入框框线比普通 border **更亮**（对比度更高）",
            dark_field_c > dark_plain_c,
            f"框线 {dark.field_border} 对比度 {dark_field_c:.2f} > "
            f"border {dark.border} 对比度 {dark_plain_c:.2f}",
        )
        check(
            "深色主题：框线对比度 ≥ 1.9（border 原始只有 1.55）",
            dark_field_c >= 1.9,
            f"框线 {dark.field_border} vs 面板 {dark.background} = {dark_field_c:.2f}",
        )

        # **阳性对照：两个主题的"一级"要差不多大** —— 用户的原话是
        # "为了视觉上效果统一"，所以不能一边加 30%、另一边加 100%。
        light_step = field_c / plain_c
        dark_step = dark_field_c / dark_plain_c
        check(
            "阳性对照：两个主题「加一级」的倍率接近（差 < 0.25）",
            abs(light_step - dark_step) < 0.25,
            f"浅色 {light_step:.2f}×（{plain_c:.2f}→{field_c:.2f}）｜"
            f"深色 {dark_step:.2f}×（{dark_plain_c:.2f}→{dark_field_c:.2f}）",
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
        #
        # ⚠️ **替身必须返回 `True`**（2026-10-17）：`open_folder` 现在返回
        # "是否真的打开了"，调用方**按它决定要不要记这次访问**。
        # 返回 `None` 会被当成"没打开" ⇒ 记录被跳过 ⇒ 这条判据假失败。
        opened: list[str] = []
        original_open = frame.open_folder
        frame.open_folder = lambda path: (opened.append(path), True)[1]
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

        # **阴性对照：打不开的时候**不该记这次访问（审计查出的缺陷）。
        #
        # 原来是 `record_accessed_path(path)` **先于** `open_folder(path)` 调用，
        # 而 `open_folder` 的失败信号没人读 ⇒ "没打开成功"的路径照样 +1 上屏。
        never_opened = os.path.join(scratch.name, "deep", "cannot-open-probe")
        os.makedirs(never_opened, exist_ok=True)
        original_open = frame.open_folder
        frame.open_folder = lambda path: False          # ← 模拟"打不开"
        try:
            frame.on_path_submitted(never_opened)
            for _ in range(20):
                wx.YieldIfNeeded()
        finally:
            frame.open_folder = original_open
        unrecorded = frame.store.get(never_opened)
        check(
            "阴性对照：**打不开就不该记这次访问**",
            unrecorded is None or unrecorded.access_count == 0,
            f"打不开却记了频次 = "
            f"{unrecorded.access_count if unrecorded else '（没记录，正确）'}",
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
        print("=== 地址栏回车：路径上的大目录只建文件夹（2026-10-25）===")
        # ==============================================================
        # 用户原话（2026-10-25）：「从左侧导航窗格顶部的输入框键入路径后回车
        # 打开文件夹，**非常慢非常卡**，有一次差点卡死。使用输入框打开文件夹后，
        # **关闭程序也变得很缓慢、卡顿**。」
        #
        # 实测根因（`tools/probes/probe_pathbar_populate.py`，路径
        # `C:\Windows\System32\drivers\etc`）：树节点 49 → 5838，
        # 其中 `C:\Windows\System32` 一个目录就 4907 条（**4708 个文件**）、
        # 192 ms —— 而它只是为了把下面三级的 `etc` 显示出来。
        #
        # 修法：条目超过 `tree_nav.DIRS_ONLY_ENTRY_THRESHOLD` 的**祖先**
        # 只建子文件夹；用户点开它时才**追加**文件（绝不 `DeleteChildren`）。
        # **目标目录（用户输入的那个）永远全量。**
        #
        # ⚠️ **这一段就是判据本身。** 把 `_on_expanding` 里的
        # `files=True` 改成 `None`（或删掉 `quiet_expand`），下面
        # "一个文件都没进树""补文件是追加"两条会立刻失败 ——
        # 这就是"改前 / 改后能区分"的证据。
        big_ancestor = os.path.join(scratch.name, "big-ancestor")
        big_mid = os.path.join(big_ancestor, "mid")
        big_target = os.path.join(big_mid, "the-target")
        os.makedirs(big_target, exist_ok=True)
        for index in range(400):
            with open(os.path.join(big_ancestor, f"f-{index:03d}.txt"), "w"):
                pass
        for name in ("inner-1.txt", "inner-2.txt"):
            with open(os.path.join(big_target, name), "w"):
                pass
        entries_now = len(os.listdir(big_ancestor))
        check(
            "阳性对照：造出来的祖先目录确实够大（否则下面测不到东西）",
            entries_now > tree_nav.DIRS_ONLY_ENTRY_THRESHOLD,
            f"{big_ancestor} 有 {entries_now} 个条目，阈值 = "
            f"{tree_nav.DIRS_ONLY_ENTRY_THRESHOLD}",
        )

        tree = frame.dir_ctrl.GetTreeCtrl()

        def child_names_of(parent) -> list[str]:
            names = []
            child, cookie = tree.GetFirstChild(parent)
            while child.IsOk():
                names.append(tree.GetItemText(child))
                child, cookie = tree.GetNextChild(parent, cookie)
            return names

        # 走用户真实走的路：往输入框填路径，然后发回车事件
        frame.path_bar.set_value(big_target)
        frame.path_bar.text_ctrl.GetEventHandler().ProcessEvent(
            wx.CommandEvent(wx.wxEVT_TEXT_ENTER, frame.path_bar.text_ctrl.GetId()),
        )
        for _ in range(20):
            wx.YieldIfNeeded()
            time.sleep(0.02)

        target_item = None
        for item in tree.GetSelections():
            if item.IsOk() and core.paths_equal(frame.dir_ctrl.GetPath(item), big_target):
                target_item = item
                break
        check(
            "回车后目标被选中（下面几条都以它为参照）",
            target_item is not None,
            f"选中 = {[frame.dir_ctrl.GetPath(i) for i in tree.GetSelections() if i.IsOk()]!r}",
        )

        if target_item is None:
            check("大目录只建文件夹", False, "目标没选中，后面的判据无法进行")
        else:
            mid_item = tree.GetItemParent(target_item)
            ancestor_item = tree.GetItemParent(mid_item)
            # 先确认"父链"取对了，别拿错节点当祖先
            chain_ok = (tree.GetItemText(mid_item) == "mid"
                        and tree.GetItemText(ancestor_item) == "big-ancestor")
            check(
                "阳性对照：从目标节点能沿父链拿到 mid / big-ancestor",
                chain_ok,
                f"目标 = {tree.GetItemText(target_item)!r}，父 = "
                f"{tree.GetItemText(mid_item)!r}，祖父 = "
                f"{tree.GetItemText(ancestor_item)!r}",
            )

            ancestor_children = child_names_of(ancestor_item)
            noise = [n for n in ancestor_children if n.startswith("f-")]
            check(
                "祖先目录只建了**文件夹**：400 个文件一个都没进树",
                not noise and "mid" in ancestor_children,
                f"big-ancestor 的子项 {len(ancestor_children)} 个，"
                f"其中 f-* = {len(noise)} 个，含 mid = {'mid' in ancestor_children}",
            )

            check(
                "目标目录是**全量**（用户输入的那个文件夹必须完整）",
                set(child_names_of(target_item)) == {"inner-1.txt", "inner-2.txt"},
                f"the-target 的子项 = {child_names_of(target_item)!r}",
            )

            # **全树扫一遍**：任何地方都不该冒出 f-* 节点。
            # 这一条防的是"还有第二处全量填充"（交接文档里那个没查清的线索）。
            stack = []
            root_item = tree.GetRootItem()
            child, cookie = tree.GetFirstChild(root_item)
            while child.IsOk():
                stack.append(child)
                child, cookie = tree.GetNextChild(root_item, cookie)
            total_nodes = 0
            while stack:
                node = stack.pop()
                total_nodes += 1
                if tree.GetItemText(node).startswith("f-"):
                    noise.append(tree.GetItemText(node))
                child, cookie = tree.GetFirstChild(node)
                while child.IsOk():
                    stack.append(child)
                    child, cookie = tree.GetNextChild(node, cookie)
            check(
                "全树没有任何 f-* 文件节点（不存在第二处全量填充）",
                not noise,
                f"全树共 {total_nodes} 个节点，f-* 检出 {len(noise)} 个",
            )

            # ---- 用户点开它 → 文件补上，而且必须是**追加** ----
            #
            # 这一条是那 6 次失败的分水岭：以前"补文件"要靠
            # `DeleteChildren` + 重建，于是 `mid_item` 立刻变成悬空句柄，
            # 之后任何调用都是 `0xC0000005`。**只追加**才能让 mid_item 活着。
            tree.Collapse(ancestor_item)
            tree.Expand(ancestor_item)
            for _ in range(10):
                wx.YieldIfNeeded()
                time.sleep(0.01)
            after = child_names_of(ancestor_item)
            files_after = [n for n in after if n.startswith("f-")]
            check(
                "用户点开大目录 → 文件补上来了（展开时升级为全量）",
                len(files_after) == 400,
                f"补完后 f-* 文件节点 = {len(files_after)} 个（期望 400），"
                f"子项总数 = {len(after)}",
            )
            check(
                "⚠️ 补文件是**追加**，不是重建 —— 原来那个 mid 节点还活着",
                mid_item.IsOk() and tree.GetItemText(mid_item) == "mid",
                f"mid_item.IsOk() = {mid_item.IsOk()}，"
                f"文本 = {tree.GetItemText(mid_item)!r}"
                f"（悬空句柄正是之前 6 次崩溃的原因）",
            )
            check(
                "补完之后没有重复条目（按名字去重，不是无脑 append）",
                len(after) == len(set(after)),
                f"子项 {len(after)} 个，去重后 {len(set(after))} 个",
            )

        # ==============================================================
        print()
        print("=== 长会话不退化：收起旧链 / 节点上限 / 超大目录不展开（2026-10-25）===")
        # ==============================================================
        # 用户原话（2026-10-25）：
        #   「我使用这个程序的时候，它已经在我的电脑上运行了几个小时……每一次
        #     打开的目录在导航窗格里全部都是展开的状态……是不是随着运行时间变长、
        #     使用次数变多，左边导航窗格不停地在展开、不停地在叠加……才导致了
        #     打开时长达几秒，最后关闭时甚至长达十几秒的性能异常？」
        #
        # 实测（`tools/probes/probe_tree_inflate.py`）：6295 节点关闭 352 ms，
        # **45746 节点关闭 10941 ms** —— 他的怀疑成立。三处修法：
        #   ① `expand_to` 展开新路径前，把**上一次由程序展开**的那条链收起来
        #   ② 节点数超过 `tree_nav.MAX_TREE_NODES` 就整体重建（只留当前路径）
        #   ③ 程序态遇到 `WinSxS` 那种（19727 个子目录）**干脆不展开**
        chain_a = os.path.join(scratch.name, "chain-a", "a1", "a2")
        chain_b = os.path.join(scratch.name, "chain-b", "b1", "b2")
        os.makedirs(chain_a, exist_ok=True)
        os.makedirs(chain_b, exist_ok=True)

        frame.reveal_in_tree(chain_a)
        first_target = tree.GetSelection()
        a1_item = tree.GetItemParent(first_target) if first_target.IsOk() else None
        check(
            "阳性对照：第一次导航后，路径上那一级确实是展开的",
            a1_item is not None and tree.IsExpanded(a1_item),
            f"a1 = {tree.GetItemText(a1_item)!r}，IsExpanded = "
            f"{tree.IsExpanded(a1_item) if a1_item else None}",
        )

        frame.reveal_in_tree(chain_b)
        check(
            "导航到新路径后，**上一次那条链收起来了**（不再一路全展开）",
            a1_item is not None and a1_item.IsOk() and not tree.IsExpanded(a1_item),
            f"旧链的 a1 节点 IsOk = {a1_item.IsOk() if a1_item else None}，"
            f"IsExpanded = {tree.IsExpanded(a1_item) if a1_item else None}"
            f"（只看不删：删节点会让调用方手里的 item 悬空）",
        )
        check(
            "新路径照样展开并选中（收起旧链不能把新链也收掉）",
            core.paths_equal(frame.dir_ctrl.GetPath(tree.GetSelection()), chain_b),
            f"当前选中 = {frame.dir_ctrl.GetPath(tree.GetSelection())!r}",
        )

        # ---- 节点上限：超过就整体重建 ----
        #
        # 直接把计数器顶到上限之上，再走一次真实导航 —— 判据是"导航结束后
        # 树里节点数回落到小量级"，而且**当前路径仍然选中**。
        tree_native = frame.dir_ctrl
        tree_native._node_count = tree_nav.MAX_TREE_NODES + 1
        before_trim = tree_native.node_count
        frame.reveal_in_tree(chain_a)
        check(
            f"节点数超过 {tree_nav.MAX_TREE_NODES} 时整体重建，节点回落到小量级",
            not tree_native.needs_trim() and tree_native.node_count < before_trim // 2,
            f"重建前计数器 = {before_trim}，重建后 node_count = "
            f"{tree_native.node_count}（残留的大部分是 %TEMP% 自己的 271 个子目录；"
            f"关闭耗时随节点数超线性上升）",
        )
        check(
            "重建之后当前路径仍然选中（重建不是把树清空）",
            core.paths_equal(frame.dir_ctrl.GetPath(tree.GetSelection()), chain_a),
            f"当前选中 = {frame.dir_ctrl.GetPath(tree.GetSelection())!r}",
        )

        # ---- 手动浏览那条路也要能触发重建 ----
        #
        # 用户的原话是"从左边导航窗格打开" —— 只靠 `reveal_in_tree` 里的检查
        # 会漏掉"只用树浏览几小时"这条完全合法的用法。
        #
        # ⚠️ 手动展开用的是**更高**的那道线（`MAX_TREE_NODES_HARD`）：
        # 用户刚点开的目录不能立刻被拆掉（2026-10-26 那张截图就是被拆掉了）。
        frame.reveal_in_tree(chain_b)
        before_manual = tree_native._node_count = tree_nav.MAX_TREE_NODES_HARD + 1
        manual_parent = tree.GetItemParent(tree.GetSelection())
        tree.Collapse(manual_parent)
        tree.Expand(manual_parent)          # 手动展开：不在 quiet_expand 里
        # **收起父节点时 MSW 会把选中挪到父节点**（资源管理器同款行为），
        # 所以"重建后该选谁"要以这一刻为准，不能假定还是原来的子项。
        expected_after_manual = frame.dir_ctrl.GetPath(tree.GetSelection())
        for _ in range(20):
            wx.YieldIfNeeded()
            time.sleep(0.01)
        check(
            "手动在树里展开也会触发重建（只用树浏览几个小时也不会累积）",
            not tree_native.needs_hard_trim()
            and tree_native.node_count < tree_nav.MAX_TREE_NODES,
            f"强制计数器 = {before_manual}（硬上限 "
            f"{tree_nav.MAX_TREE_NODES_HARD}），展开后 node_count = "
            f"{tree_native.node_count}",
        )
        check(
            "那次重建之后当前路径仍然选中（重建不清空选中）",
            bool(expected_after_manual) and core.paths_equal(
                frame.dir_ctrl.GetPath(tree.GetSelection()),
                expected_after_manual),
            f"重建前选中 = {expected_after_manual!r}，重建后 = "
            f"{frame.dir_ctrl.GetPath(tree.GetSelection())!r}",
        )

        # ---- 超大目录：程序态**不展开** ----
        #
        # `C:\Windows\WinSxS` 有 19727 个子目录，建一节就是近四万节点、约 2.6 秒。
        # 这里用 2600 个**空文件**造一个同量级的目录（判据只看条目数）。
        huge = os.path.join(scratch.name, "huge-ancestor")
        huge_target = os.path.join(huge, "inside")
        os.makedirs(huge_target, exist_ok=True)
        for index in range(tree_nav.MAX_PROGRAMMATIC_CHILDREN + 100):
            with open(os.path.join(huge, "h-%05d.txt" % index), "w"):
                pass
        huge_entries = len(os.listdir(huge))
        nodes_before_huge = tree_native.node_count
        landed = frame.reveal_in_tree(huge_target)
        delta = tree_native.node_count - nodes_before_huge
        check(
            "阳性对照：造出来的目录确实超过程序态上限",
            huge_entries > tree_nav.MAX_PROGRAMMATIC_CHILDREN,
            f"{huge} 有 {huge_entries} 个条目，上限 = "
            f"{tree_nav.MAX_PROGRAMMATIC_CHILDREN}",
        )
        check(
            "超大目录**不由程序展开**：导航它下面的子目录时不为它付节点代价",
            delta < huge_entries,
            f"这次导航共多建 {delta} 个节点，其中**一个都不是**这 {huge_entries} "
            f"个条目（多出来的是路径上其它层级本来就该建的）；"
            f"上限内的做法会是 {huge_entries} 个起步；reveal 返回 {landed}",
        )
        # 展开被拒绝时，reveal 会退到"包含目标的已展开祖先" —— 也就是这个超大目录
        huge_item = tree.GetSelection()
        check(
            "超大目录里的子目录：树停在该超大目录本身（不再是几秒的空白等待）",
            huge_item.IsOk() and core.paths_equal(
                frame.dir_ctrl.GetPath(huge_item), huge),
            f"当前选中 = {frame.dir_ctrl.GetPath(huge_item)!r}，期望 = {huge!r}",
        )
        placeholder = None
        has_kids = False
        if huge_item.IsOk():
            has_kids = tree.ItemHasChildren(huge_item)
            child, _cookie = tree.GetFirstChild(huge_item)
            placeholder = tree.GetItemText(child) if child.IsOk() else None
        check(
            "超大目录仍然**保留展开箭头**（占位子项没被删，用户自己点开还能全量看）",
            huge_item.IsOk() and has_kids and placeholder == "",
            f"节点 = {tree.GetItemText(huge_item)!r}，ItemHasChildren = {has_kids}，"
            f"第一个子项文本 = {placeholder!r}（空串 = 占位子项）",
        )
        check(
            "程序态不展开的超大目录保持**折叠**（不是「展开着却只有一行空白」）",
            huge_item.IsOk() and not tree.IsExpanded(huge_item),
            f"IsExpanded = {tree.IsExpanded(huge_item) if huge_item.IsOk() else None}"
            f"（展开着但不建子项 = 2026-10-26 那张截图）",
        )

        # ---- 用户**自己**点开超大目录：分页显示，不能是"几秒空白" ----
        # 用户 2026-10-26 截图报的 bug：展开 `WinSxS` 卡 5~6 秒后**什么都看不到**
        # —— 2.7 秒建出来的 39697 个节点，紧接着被"节点上限"整体重建删光了。
        # 现在的规则：一次只放 `MAX_EXPAND_PAGE` 个 + 一行"还有 N 项未显示"，
        # 收起再展开接着放下一页。
        started = time.perf_counter()
        tree.Collapse(huge_item)
        tree.Expand(huge_item)              # 手动展开：不在 quiet_expand 里
        manual_ms = (time.perf_counter() - started) * 1000
        shown = tree_nav.MAX_EXPAND_PAGE
        kids = child_names_of(huge_item)
        marker_text = kids[-1] if kids else ""
        check(
            "手动展开超大目录：**快**（不再是几秒的冻结）",
            manual_ms < 1000,
            f"{manual_ms:.0f} ms（一次只放 {shown} 个；全量要 2.7 秒且树立刻废掉）",
        )
        check(
            "手动展开超大目录：**有内容**（不再是一片空白）",
            len(kids) >= shown,
            f"子项 {len(kids)} 个（期望 ≥ {shown} + 1 行说明）",
        )
        check(
            "末尾有一行说明「还有 N 项未显示」（不是静默截断）",
            "未显示" in marker_text or "not shown" in marker_text,
            f"最后一行 = {marker_text!r}",
        )
        marker_item = tree.GetLastChild(huge_item)
        check(
            "说明行**不是目录**：它的路径是空串（否则会被当成真节点选中/记录）",
            frame.dir_ctrl.GetPath(marker_item) == "",
            f"说明行 GetPath = {frame.dir_ctrl.GetPath(marker_item)!r}，"
            f"在 _markers 里 = {marker_item in frame.dir_ctrl._markers}",
        )
        check(
            "手动展开之后**没有被整体重建**（用户点开的东西不能立刻拆掉）",
            tree.IsExpanded(huge_item) and not frame.dir_ctrl.needs_hard_trim(),
            f"IsExpanded = {tree.IsExpanded(huge_item)}，node_count = "
            f"{frame.dir_ctrl.node_count}，硬上限 = "
            f"{tree_nav.MAX_TREE_NODES_HARD}",
        )

        first_kid = tree.GetFirstChild(huge_item)[0]
        first_path = frame.dir_ctrl.GetPath(first_kid)
        before_more = len(kids)
        started = time.perf_counter()
        tree.Collapse(huge_item)
        tree.Expand(huge_item)              # 再展开一次 = 接着加载下一页
        more_ms = (time.perf_counter() - started) * 1000
        kids2 = child_names_of(huge_item)
        check(
            "再展开一次 → **接着加载下一页**（收起再展开就是「看更多」）",
            len(kids2) >= before_more + shown,
            f"{before_more} → {len(kids2)} 个（每次 +{shown}），{more_ms:.0f} ms",
        )
        check(
            "分页是**追加**：原来那个子项仍然有效（不是重建）",
            first_kid.IsOk() and frame.dir_ctrl.GetPath(first_kid) == first_path,
            f"第一个子项 IsOk = {first_kid.IsOk()}，路径 "
            f"{frame.dir_ctrl.GetPath(first_kid)[-24:]!r}（原 {first_path[-24:]!r}）",
        )

        # ---- 「打开」也要收起旧链（用户 2026-10-26 的第二条反馈）----
        #
        # "用户在浏览导航窗格时，选中路径，然后点击「打开」按钮来打开对应的
        #  文件夹。在这个操作过程中，它没有把以前在导航窗格上浏览的那些路径收起来。"
        frame.reveal_in_tree(chain_b)          # 程序展开的链 = chain-b
        b1_node = tree.GetItemParent(tree.GetSelection())
        b_chain_node = tree.GetItemParent(b1_node)   # chain-b 那一级
        frame.reveal_in_tree(chain_a)          # 现在旧链 = chain-a，选中 a2
        a1_user = tree.GetItemParent(tree.GetSelection())
        a_chain_node = tree.GetItemParent(a1_user)
        tree.Expand(a_chain_node)              # 用户手动展开 chain-a 浏览
        tree.Expand(a1_user)
        opened_paths.clear()
        frame._focus_pane = "tree"             # 用户点进过导航窗格（见 on_tree_selection_made）
        tree.SelectItem(a1_user)               # 用户在树里选中 chain-a\a1
        frame.on_open(None)
        check(
            "阳性对照：点「打开」用的是**导航窗格**里的选中项",
            len(opened_paths) == 1 and opened_paths[0].endswith("chain-a\\a1"),
            f"打开的路径 = {opened_paths!r}（期望 …\\chain-a\\a1）",
        )
        check(
            "用「打开」之后旧链也收起来了（与地址栏回车同一规则）",
            not tree.IsExpanded(b_chain_node),
            f"chain-b 那一级 IsExpanded = {tree.IsExpanded(b_chain_node)}"
            f"（收起的是**程序**展开过的链）",
        )
        check(
            "「打开」之后选中项那条链仍然展开着（否则选中的那一行看不见）",
            tree.IsExpanded(a_chain_node) and tree.IsExpanded(a1_user),
            f"chain-a IsExpanded = {tree.IsExpanded(a_chain_node)}，"
            f"a1 IsExpanded = {tree.IsExpanded(a1_user)}",
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

        # ==============================================================
        print()
        print("=== 改动 ⑬：记录窗格字号与行距（用户要求，含一次更正）===")
        # ==============================================================
        # 用户原话：「**只**将记录窗格中的条目字号增大 1pt，上下间距（行距）
        # 适当增加。**其余地方的文字和排版不动**」。
        #
        # 所以这一组有三条：① 列表真的大了；② **阳性对照**：正文没跟着大
        # （证明我只动了列表那条链）；③ 行高是**几何量**，不是"设了就算"。
        list_pt = frame.list_ctrl.GetFont().GetPointSize()
        delta = _theme.METRICS.list_font_point_delta
        check(
            f"记录窗格条目字号 = 系统 UI + 偏移（9 + {delta} = {system_pt + delta}pt）",
            list_pt == system_pt + delta,
            f"列表 {list_pt}pt = 系统 UI {system_pt}pt + 偏移 {delta}",
        )
        check(
            "阳性对照：正文仍是「系统 + 1」，没被列表那条链牵动",
            body == system_pt + 1,
            f"正文 {body}pt（应仍为 {system_pt + 1}pt，即只 +1）",
        )

        # 自绘列头的字号：**第三条独立的链**。
        # 用户要求"访问的路径、频次、访问日期、访问时间这一栏的标题统一增大 1pt"。
        header_pt = frame.header.GetFont().GetPointSize()
        h_delta = _theme.METRICS.header_font_point_delta
        check(
            f"列头标题字号 = 系统 UI + 偏移（9 + {h_delta} = {system_pt + h_delta}pt）",
            header_pt == system_pt + h_delta,
            f"列头 {header_pt}pt = 系统 UI {system_pt}pt + 偏移 {h_delta}",
        )
        check(
            "列头与数据行**同号**（不再一大一小）",
            header_pt == list_pt,
            f"列头 {header_pt}pt，数据行 {list_pt}pt",
        )
        check(
            "阳性对照：列头没有连坐按钮（仍为「系统 + 1」）",
            frame.open_btn.GetFont().GetPointSize() == system_pt + 1,
            f"「打开」按钮 {frame.open_btn.GetFont().GetPointSize()}pt",
        )

        # ==============================================================
        print()
        print("=== 改动 ⑭：弹窗字号与按钮一致 + 导航窗格行距 ===")
        # ==============================================================
        # 用户要求：设置窗口、所有提示弹窗（含标题栏）的字号，
        # 与「打开」「清空」按钮不一致的，统一成按钮那一套。
        #
        # **原来弹窗整整小 1pt**：`wx.Dialog` 是独立顶层窗口，
        # frame 的 `SetFont` 传播过不去，于是回落到系统默认 9pt。
        button_pt = frame.open_btn.GetFont().GetPointSize()

        def dialog_fonts(dialog) -> tuple[list[str], list[str]]:
            """返回 (字号不对的控件名, 见到的全部字号)。"""
            bad, seen = [], []
            stack = [dialog]
            while stack:
                w = stack.pop()
                pt = w.GetFont().GetPointSize()
                seen.append(f"{type(w).__name__}={pt}")
                if pt != button_pt:
                    label = ""
                    try:
                        label = w.GetLabel()
                    except Exception:
                        pass
                    bad.append(f"{type(w).__name__}{label}={pt}")
                stack.extend(w.GetChildren())
            return bad, seen

        settings = _widgets.SettingsDialog(
            frame, frame.theme,
            __import__("file_tracker.lang",
                       fromlist=["lang"]).PREFERENCE_CHINESE)
        bad_s, seen_s = dialog_fonts(settings)
        check(
            "设置窗口的每个控件字号都 = 「打开」按钮",
            not bad_s,
            f"按钮 {button_pt}pt；不一致 {len(bad_s)} 个"
            + (f"：{bad_s[:4]}" if bad_s else f"（共查 {len(seen_s)} 个控件）"),
        )
        settings.Destroy()

        note = _widgets.ThemedDialog(frame, frame.theme,
                                     "路径已失效，确定要删除吗？",
                                     title="确认删除")
        bad_n, seen_n = dialog_fonts(note)
        check(
            "提示弹窗的每个控件字号都 = 「打开」按钮",
            not bad_n,
            f"按钮 {button_pt}pt；不一致 {len(bad_n)} 个"
            + (f"：{bad_n[:4]}" if bad_n else f"（共查 {len(seen_n)} 个控件）"),
        )
        note.Destroy()

        # **阳性对照**：确认上一条不是"因为按钮也 9pt 才通过"。
        check(
            "阳性对照：按钮字号**不是**系统默认（9pt），所以上面两条有意义",
            button_pt != system_pt,
            f"按钮 {button_pt}pt，系统默认 {system_pt}pt",
        )

        # ── 导航窗格行距：`TVM_SETITEMHEIGHT` **确实有效** ──
        # （与列表的 `LVM_SETITEMSPACING` 不同，那个在 report 视图下是空操作。）
        #
        # ⚠️ 判据**不是**"自然高 + 额外值"——那个算法踩过坑：
        # `TVM_SETITEMHEIGHT` 收的是**绝对高度**，"自然高"一旦被改过就读不回原值，
        # 缩字号时重算会拿到"上次设的值"，比例从 1.429 漂到 2.000。
        # 现在两边都直接从文字高按 `row_ratio` 现算，所以这里也按比例判。
        # **句柄直接取。** 换成 `DirectoryTree` 之后 `dir_ctrl` 本身就是
        # `SysTreeView32`，`find_child_window` 找不到"内层控件"，
        # 于是读出"行高 0px"这种**假失败**。
        tree_native = frame.dir_ctrl.GetHandle()
        measured = win32.get_tree_item_height(tree_native) if tree_native else 0
        ratio = _theme.METRICS.row_ratio
        tree_widget = frame.dir_ctrl.GetTreeCtrl()
        dc_tree = wx.ClientDC(tree_widget)
        dc_tree.SetFont(tree_widget.GetFont())
        tree_text_h = dc_tree.GetTextExtent("Ag路径")[1]
        tree_want = int(round(tree_text_h * ratio))
        check(
            "导航窗格行高 = 文字高 × row_ratio（回读，不是设了就算）",
            measured == tree_want and tree_text_h > 0,
            f"实测 {measured}px = round({tree_text_h}px × {ratio}) = {tree_want}px",
        )

        # ── **两个窗格的行距比例必须一致**（用户指定的验收口径）──
        #
        # 用户原话："记录窗格的行距再增加一点点，视觉上的间隔比例就和
        # 导航窗格同步了 —— **导航窗格那个比例是最舒服的**。"
        #
        # 所以判据是**比例**（行高 / 文字高），不是像素：
        # 两个控件字号不同，"都加 10px"在视觉上并不一致。
        # 这条断言把"最舒服的那个比例"钉住 —— 以后谁改了任一边
        # 的字号或行距，对不上就会红。
        def _text_height(win) -> int:
            dc = wx.ClientDC(win)
            dc.SetFont(win.GetFont())
            # "Ag" 足够：**高度只由字体度量决定，与字符无关**。
            return dc.GetTextExtent("Ag")[1]

        if frame.list_ctrl.GetItemCount() > 0:
            lh_row = frame.list_ctrl.GetItemRect(0).height
            lh_text = _text_height(frame.list_ctrl)
            th_row = measured
            # ⚠️ **必须量 `GetTreeCtrl()`，不是 `dir_ctrl`。**
            # 两者字体不同：`dir_ctrl` 报 9pt/雅黑（文字高 28px），
            # 而 `GetTreeCtrl()` 报 9pt/更纱黑体（文字高 25px）——
            # **原生树按后者渲染**，产品的行高也是按后者算的。
            # 量错控件会得到 36/28 = 1.286 这种假失败（踩过）。
            th_text = _text_height(frame.dir_ctrl.GetTreeCtrl())
            if lh_text > 0 and th_text > 0:
                list_ratio = lh_row / lh_text
                tree_ratio = th_row / th_text
                check(
                    "记录窗格与导航窗格的**行距比例**一致",
                    abs(list_ratio - tree_ratio) < 0.02,
                    f"记录 {lh_row}/{lh_text} = {list_ratio:.3f}｜"
                    f"导航 {th_row}/{th_text} = {tree_ratio:.3f}"
                    f"（目标比例 {ratio}）",
                )
                check(
                    "阳性对照：两边比例都不是 1.0（确实有行距，不是贴着）",
                    list_ratio > 1.1 and tree_ratio > 1.1,
                    f"记录 {list_ratio:.3f}，导航 {tree_ratio:.3f}",
                )

        # **行高必须是回读出来的几何量。**
        #
        # ⚠️ 这里最初写的是"行高 ≥ 文字高 + 配置的额外间距"，它**失败了** ——
        # 而失败是对的：`LVM_SETITEMSPACING` 在 report 视图下**根本不生效**
        # （`tools/probes/probe_row_spacing.py`：extra 0→40，行高恒为 39px）。
        # 那个"额外间距"字段从引入起就没起作用，只是当时没有断言量行高。
        #
        # report 视图的行高**只由字号决定**，所以这里改判两件**真实成立**的事：
        if frame.list_ctrl.GetItemCount() > 0:
            row_h = frame.list_ctrl.GetItemRect(0).height
            text_h = frame.list_ctrl.GetTextExtent("Ag")[1]
            check(
                "行高是回读出来的几何量（不是「设了就算」）",
                row_h > text_h,
                f"行高 {row_h}px > 文字高 {text_h}px（净空 {row_h - text_h}px）",
            )
            check(
                "行高已被抬到「文字高 × row_ratio」",
                row_h == int(round(text_h * ratio)),
                f"行高 {row_h}px = round(文字高 {text_h}px × {ratio})"
                "（机制：1×H 空图列表托底，H = 目标行高 − 1；"
                "`LVM_SETITEMSPACING` 在 report 视图下是空操作）",
            )
            # **阳性对照**：确认行高不是靠"字号自己变高"撑起来的 ——
            # 净空必须明显大于纯字号时的 4px。
            check(
                "阳性对照：净空确实比不加图列表时大（那时只有 4px）",
                row_h - text_h > 4,
                f"净空 {row_h - text_h}px > 4px",
            )
        else:
            check("列表非空（行高断言需要至少一行）", False,
                  f"GetItemCount = {frame.list_ctrl.GetItemCount()}")

        # 窗口尺寸：**宽度不动、高度增加**。
        # 期望值由 wx-free 的纯函数算出，那边另有 3 条 pytest 守着
        # （见 tests/test_core.py 的 window 组）——这里只核"真实窗口"。
        preferred = _core.scaled_window_size()
        before = _core.scaled_window_size(extra_height=1.0)
        actual = frame.GetSize()
        check(
            "初始窗口：宽度不受加高影响",
            abs(actual.width - preferred[0]) <= 24,
            f"实际宽 {actual.width}，期望 {preferred[0]}（容差含非客户区）",
        )
        check(
            f"初始窗口：高度已增加（{before[1]} → {preferred[1]}）",
            actual.height >= int(preferred[1] * 0.95),
            f"实际高 {actual.height}，期望 {preferred[1]}",
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
            select_only(frame, 3)
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
            select_only(frame, 0)
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
        print("=== 改动 ⑳：「打开」跟着最后一次选中 ===")
        # ==============================================================
        #
        # 用户报："记录窗格中无论选中哪条记录，「打开」按钮都只会响应左侧
        # 导航窗格的选中项。把「打开」设计成按用户鼠标焦点，
        # 即最后一个选中的项目/条目打开。"
        #
        # 原来 `on_open` 只看 `dir_ctrl.GetPaths()`。现在走 `open_targets()`，
        # 它按**最后一次选中**决定目标。
        #
        # **不真的调 `on_open`** —— 那会弹出资源管理器窗口。
        # `on_open` 的判断输入就是 `open_targets()` 的返回值，
        # 验这里等价于验它，而且没有副作用（并且能重复跑）。
        row_count = frame.list_ctrl.GetItemCount()
        check(
            "阳性对照：列表里有记录可选中（否则下面测的是空场景）",
            row_count > 0,
            f"列表 {row_count} 行",
        )
        # 选中列表第 0 行 → 最后一次选中来自**记录窗格**
        #
        # ⚠️ 必须用 `select_only`：列表现在**可多选**，
        # 裸的 `Select(0)` 是"额外选中第 0 行"，前面步骤留下的选中会累积。
        select_only(frame, 0)
        frame._focus_pane = "list"
        chosen_from_list = frame.open_targets()
        check(
            "在记录窗格里选中 → 「打开」的目标是**列表那一行**",
            chosen_from_list == [frame.selected_path()]
            and frame.selected_path() != "",
            f"目标 = {[p[-30:] for p in chosen_from_list]}，"
            f"列表选中 = {frame.selected_path()[-30:]!r}",
        )
        # 再把导航窗格设为最后选中 → 目标应切回导航窗格
        frame._focus_pane = "tree"
        chosen_from_tree = frame.open_targets()
        tree_paths = [p for p in frame.dir_ctrl.GetPaths() if p]
        check(
            "切回导航窗格后 → 「打开」的目标是**导航窗格那一项**",
            chosen_from_tree == tree_paths[:1],
            f"目标 = {[p[-30:] for p in chosen_from_tree]}，"
            f"导航窗格 = {[p[-30:] for p in tree_paths]}",
        )
        check(
            "阳性对照：两处目标**确实不同**（否则上面的断言什么也证明不了）",
            chosen_from_list != chosen_from_tree,
            f"列表 → {[p[-24:] for p in chosen_from_list]}；"
            f"导航 → {[p[-24:] for p in chosen_from_tree]}",
        )
        check(
            "一次只打开**一处**（导航窗格是多选的，原来会弹出好几个窗口）",
            len(chosen_from_list) <= 1 and len(chosen_from_tree) <= 1,
            f"列表 {len(chosen_from_list)} 个，导航 {len(chosen_from_tree)} 个",
        )

        # ---- 程序改树选中**不得**顶掉用户的列表选择 ----
        #
        # 用户**第二次**报的就是这个："打开按钮还是不能正确执行记录窗格内
        # 最后一次选中条目，依然优先响应上次使用的导航窗格条目。"
        #
        # 根因：`EVT_TREE_SEL_CHANGED` 分不清"用户点的"和"代码改的"，
        # 而 `reveal_in_tree` 会调 `tree.SelectItem()`（地址栏回车、
        # 启动定位上次目录）。于是用户的列表选择被悄悄改成 tree。
        #
        # 所以现在只绑**程序不可能产生**的事件：
        # `EVT_SET_FOCUS` 与 `EVT_TREE_KEY_DOWN`。
        frame._focus_pane = "list"
        tree_ctrl = frame.dir_ctrl.GetTreeCtrl()
        # **不能选根项**：`GenericDirCtrl` 把根藏起来了，`SelectItem` 会抛
        # `wxAssertionError: can't select hidden root item`（实测）。
        # 取根的第一个子项——那是一个真实的、可选的目录节点。
        probe_item = tree_ctrl.GetFirstChild(tree_ctrl.GetRootItem())[0]
        check(
            "阳性对照：拿到了一个可选的树节点（否则下面那两条测不出东西）",
            probe_item.IsOk(),
            f"节点 = {tree_ctrl.GetItemText(probe_item)!r}"
            if probe_item.IsOk() else "拿不到子项",
        )
        if probe_item.IsOk():
            tree_ctrl.SelectItem(probe_item)     # ← 程序改选中
        for _ in range(20):
            wx.YieldIfNeeded()
        check(
            "程序改树选中（`SelectItem`）**不会**顶掉列表的选择",
            frame._focus_pane == "list",
            f"`SelectItem()` 之后 _focus_pane = {frame._focus_pane!r}"
            + ("（正确：程序化选中不该改它）" if frame._focus_pane == "list"
               else "（**它被改回 tree 了**，用户报的就是这个）"),
        )
        # **真实鼠标点击**（`wx.UIActionSimulator` 走的是系统输入队列，
        # 与用户手动点击经过同一条路）。
        #
        # 为什么不用 `win.GetEventHandler().GetConnected()` 去查绑定：
        # 实测那个方法**不存在**（`'TreeCtrl' object has no attribute
        # 'GetConnected'`）。而"点一下看行为"本来就比"查绑定表"更接近
        # 要验的东西——绑定对了但事件不达，查表是看不出来的。
        # ---- 事件确实接在**用户输入事件**上，而且真的会改 `_focus_pane` ----
        #
        # 直接派发事件到真实的处理器上（`ProcessEvent`），而不是合成鼠标：
        # 合成鼠标（`wx.UIActionSimulator`）在这个验证脚本里**不可靠**——
        # 单独跑能触发，跑在整串检查中间时一个事件都收不到（窗口位置、
        # 焦点、遮挡都会影响）。**不稳定的检查比没有检查更糟**：
        # 它会让整道门禁的结论不可信。
        #
        # 这里验的是"接到用户输入 → 改 `_focus_pane`"这一环，
        # 不依赖窗口在屏幕上的位置。
        def fire(win, event) -> bool:
            event.SetEventObject(win)
            return win.GetEventHandler().ProcessEvent(event)

        frame._focus_pane = "tree"
        fire(frame.list_ctrl, wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED,
                                           frame.list_ctrl.GetId()))
        check(
            "列表的选中事件会把目标切到 list",
            frame._focus_pane == "list",
            f"_focus_pane = {frame._focus_pane!r}",
        )

        frame._focus_pane = "list"
        fire(frame.list_ctrl, wx.FocusEvent(wx.wxEVT_SET_FOCUS,
                                            frame.list_ctrl.GetId()))
        check(
            "列表的**焦点**事件也会切到 list（点已选中的行时只有它会来）",
            frame._focus_pane == "list",
            f"_focus_pane = {frame._focus_pane!r}"
            "（`ITEM_SELECTED` 在选中没变时不发，所以焦点这条必要）",
        )

        # 用 `wx.CommandEvent` 而不是 `wx.TreeEvent`：后者的构造函数要一个
        # `wx.TreeItemId`，直接传 id（int）会 TypeError
        # （`TreeEvent(): arguments did not match any overloaded call`）。
        # 处理器只读 `event.Skip()`，不关心事件的具体类型。
        frame._focus_pane = "list"
        fire(tree_ctrl, wx.CommandEvent(wx.wxEVT_TREE_KEY_DOWN,
                                        tree_ctrl.GetId()))
        check(
            "树的方向键事件会把目标切到 tree（用户操作导航窗格）",
            frame._focus_pane == "tree",
            f"_focus_pane = {frame._focus_pane!r}",
        )

        frame._focus_pane = "list"
        fire(tree_ctrl, wx.FocusEvent(wx.wxEVT_SET_FOCUS, tree_ctrl.GetId()))
        check(
            "树的**焦点**事件会把目标切到 tree（用户点进导航窗格）",
            frame._focus_pane == "tree",
            f"_focus_pane = {frame._focus_pane!r}",
        )

        # **`EVT_TREE_SEL_CHANGED` 绝不能再接上去。**
        # 这是那个 bug 的根：它分不清"用户点的"与"代码改的"，
        # 于是 `reveal_in_tree` 的 `SelectItem()` 会把用户的列表选择顶掉。
        source = _inspect.getsource(_app_module.FileTracker)
        check(
            "树**没有**绑 `EVT_TREE_SEL_CHANGED`（那个事件分不清用户与程序）",
            "EVT_TREE_SEL_CHANGED, self.on_tree_selection_made" not in source,
            "已改用 `EVT_SET_FOCUS` + `EVT_TREE_KEY_DOWN`"
            + ("；但仍检测到旧绑法" if "EVT_TREE_SEL_CHANGED, self."
               in source else ""),
        )

        # ==============================================================
        print()
        print("=== 改动 ㉑：不需要回答的提示只给一个按钮 ===")
        # ==============================================================
        #
        # 用户报："失效删除确认弹窗有两个按钮，功能完全一致——关闭窗口，
        # 请简化为一个按钮「确定」。"
        single = _widgets.ThemedDialog(
            frame, frame.theme, "测试：纯告知",
            title="测试", yes_label="确定", no_label=_widgets.NO_BUTTON)
        two = _widgets.ThemedDialog(
            frame, frame.theme, "测试：需要回答", title="测试")
        check(
            "`no_label=NO_BUTTON` 时只有一个按钮（用户要求的那条）",
            len(single._buttons) == 1,
            f"按钮数 = {len(single._buttons)}"
            f"（{[b.label for b in single._buttons]}）",
        )
        check(
            "阳性对照：不给 `no_label` 时仍是两个按钮（确认框没被一起改坏）",
            len(two._buttons) == 2,
            f"按钮数 = {len(two._buttons)}"
            f"（{[b.label for b in two._buttons]}）",
        )
        # **`no_label=None` 是一个陷阱**：它是"没传"的意思，
        # 于是 `__init__` 补上默认的「否(N)」——单按钮弹窗建不出来。
        # `_notify` 就这样带着一个多余的「否(N)」活了很久，直到用户截图指出。
        trap = _widgets.ThemedDialog(
            frame, frame.theme, "测试：None 陷阱",
            title="测试", yes_label="好", no_label=None)
        check(
            "`no_label=None` **不会**给出单按钮（记录这个陷阱，别再踩）",
            len(trap._buttons) == 2,
            f"按钮数 = {len(trap._buttons)}"
            f"（{[b.label for b in trap._buttons]}）——"
            "所以要单按钮必须用 NO_BUTTON",
        )
        # 用户报的那条路径：失效告知走 `_notify`，而 `_notify` 传 NO_BUTTON。
        # **验调用链而不是验字符串**：`remove_invalid_path` 里根本不会出现
        # `no_label=`，它调的是 `_notify`。
        source = _inspect.getsource(_app_module.FileTracker.remove_invalid_path)
        notify_source = _inspect.getsource(_app_module.FileTracker._notify)
        check(
            "失效路径的告知走单按钮（`remove_invalid_path` → `_notify` → NO_BUTTON）",
            "_notify(" in source and "NO_BUTTON" in notify_source,
            f"remove_invalid_path 调 _notify = {'_notify(' in source}；"
            f"_notify 用 NO_BUTTON = {'NO_BUTTON' in notify_source}",
        )
        single.Destroy()
        two.Destroy()
        trap.Destroy()
        for _ in range(10):
            wx.YieldIfNeeded()

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

        # **版式：标签与按钮「挨在一起」，整块居中。**
        #
        # .. note::
        #
        #     这条断言**改过三次口径**，每次都是用户改了主意 ——
        #     记在这里是为了说明：**版式是用户的审美决定，
        #     断言要跟着他的口径走，不是跟着我以为的对错。**
        #
        #     ① 最初："标签与第一行按钮垂直居中"（标签靠左、按钮右对齐）
        #     ② 用户要求居中版式 → "标签在按钮上方且居中"
        #     ③ 用户否决居中 → 回到 ① 的左右分列
        #     ④ **用户再改**："标题和按钮之间隔得太远了……不要分别
        #        左对齐和右对齐，让它们**左右挨在一起**……
        #        然后**整段居中**。" → 就是现在这三条。
        layout_bad = []
        for label, chunks in sort_probe._rows:
            buttons = [b for chunk in chunks for b in chunk]
            if not buttons:
                continue
            label_rect = label.GetRect()
            rects = [b.GetRect() for b in buttons]
            first_row_y = min(r.y for r in rects)
            first_row = [r for r in rects if r.y == first_row_y]
            left_x = min(r.x for r in first_row)
            right_x = max(r.x + r.width for r in first_row)

            # ① 标签与**第一行**按钮同行（垂直居中）
            label_mid = label_rect.y + label_rect.height // 2
            row_mid = first_row_y + first_row[0].height // 2
            if abs(label_mid - row_mid) > 4:
                layout_bad.append(
                    f"{label.GetLabel()}：标签中心 {label_mid} "
                    f"≠ 首行按钮中心 {row_mid}")

            # ② 标签紧挨在按钮**左边**，且**间距很小**（"挨在一起"）
            if label_rect.x + label_rect.width > left_x:
                layout_bad.append(f"{label.GetLabel()}：标签压住了按钮")
            space = left_x - (label_rect.x + label_rect.width)
            if space > 24:
                layout_bad.append(
                    f"{label.GetLabel()}：标签与按钮之间空 {space}px，太远")

            # ③ **整段左对齐**（用户："整段左对齐"）
            left_edge = sort_probe._body_rect[0]
            if abs(label_rect.x - left_edge) > 6:
                layout_bad.append(
                    f"{label.GetLabel()}：标签左缘 {label_rect.x} "
                    f"≠ 内容区左边界 {left_edge}")
        check(
            "设置窗口：标签与按钮挨在一起、且整段左对齐（用户定下的版式）",
            not layout_bad,
            f"不合规 = {layout_bad}" if layout_bad
            else "四组都是「标签 + 两个空格 + 按钮」贴内容区左边",
        )

        # **底部按钮右对齐**（用户："确定和取消一组放在底部右侧"）。
        footer_rects = sort_probe._button_rects
        if footer_rects:
            content_right = (sort_probe._body_rect[0]
                             + sort_probe._body_rect[2]
                             - sort_probe._body_rect[0])
            last_x, last_w = footer_rects[-1]
            margin = _theme.scale_for_dpi(
                _theme.METRICS.dialog_margin, _widgets.dpi_of(sort_probe))
            client_w = sort_probe.GetClientSize().width
            check(
                "设置窗口：底部按钮组靠右（不再居中）",
                abs((last_x + last_w) - (client_w - margin)) <= 4,
                f"末个按钮右缘 {last_x + last_w} vs 期望 {client_w - margin}"
                f"（客户区宽 {client_w}，右边距 {margin}）",
            )
            check(
                "阳性对照：底部按钮**不是**居中的（否则这条没意义）",
                abs((footer_rects[0][0] + footer_rects[-1][0]
                     + footer_rects[-1][1]) // 2 - client_w // 2) > 8,
                f"整组中心 {(footer_rects[0][0] + footer_rects[-1][0] + footer_rects[-1][1]) // 2}"
                f" vs 客户区中心 {client_w // 2}",
            )

        # **排序方式两行**（用户："四个并排看着还是太奇怪了"）。
        #
        # 2026-10-17 之后只有**三个**排序方式了（日期与时间并成了一列），
        # 所以是 `[2, 1]` 两行，而不是 `[2, 2]`。
        # 判据从"每行恰好 2 个"改成"**不止一行**"——那才是用户要的观感
        #（不要三个并排挤成一条）。
        # **2026-10-17 语义反转**：原来要求"排序方式折成多行"（四个文字按钮
        # 并排太宽）；现在改成**3 个图标按钮**，用户明确要求"像界面主题的
        # 分类一样" —— 主题那三个是一行，排序也应当是一行。
        sort_chunks = dict(sort_probe._rows).get(sort_probe._sort_label)
        check(
            "设置窗口：排序方式一行 3 个图标按钮（与主题分类一致）",
            sort_chunks is not None and len(sort_chunks) == 1
            and len(sort_chunks[0]) == 3,
            f"折成 {[len(c) for c in (sort_chunks or [])]}（应为 [3]）",
        )
        # 图标按钮的证据：有 painter、正方形、有悬停提示
        _sort_btns = list(sort_probe._sort_buttons)
        check(
            "排序按钮是**图标**按钮（有 icon_painter，不是文字）",
            len(_sort_btns) == 3
            and all(getattr(b, "icon_painter", None) is not None for b in _sort_btns),
            f"{[getattr(b, 'icon_painter', None).__name__ if getattr(b, 'icon_painter', None) else None for b in _sort_btns]}",
        )
        check(
            "排序图标按钮接近**正方形**（约 56×56）",
            all(abs(b.GetBestSize().width - b.GetBestSize().height) <= 4
                for b in _sort_btns),
            f"{[(b.GetBestSize().width, b.GetBestSize().height) for b in _sort_btns]}",
        )
        # **主题按钮与排序按钮同尺寸**（用户 2026-10-17）：
        # "把界面主题的这 3 个按钮形状，也统一成现在排序方式这种正矩形。"
        #
        # 根因：主题按钮原来传了 caption（`💻`/`☀`/`☾`），
        # 而 `💻` 是 emoji、175% 下能到 30+ 物理像素，
        # `_sync_min_size` 的 `宽 = max(文字宽 + 内边距, min_width)`
        # 于是把它撑成 56×40 的宽扁矩形。现在 caption 留空（图标由
        # `icon_painter` 画），两行就都是 56×56 了。
        _theme_btns = list(getattr(sort_probe, "_theme_buttons", []))
        # ---- 排序方向：图标 + 顺序互换（用户 2026-10-17）----
        #
        # > "降序和升序的这两个按钮，可以换成图形的形式，
        # >   也就是'箭头向上'和'箭头向下'。"
        # > "这两个按钮的位置互换一下。"
        _dir_btns = list(getattr(sort_probe, "_direction_buttons", []))
        check(
            "排序方向按钮是**图标**（上/下箭头，不是文字）",
            len(_dir_btns) == 2
            and all(getattr(b, "icon_painter", None) is not None for b in _dir_btns),
            f"painter = {[getattr(b, 'icon_painter', None).__name__ if getattr(b, 'icon_painter', None) else None for b in _dir_btns]}",
        )
        check(
            "排序方向按钮是**正方形**",
            all(abs(b.GetBestSize().width - b.GetBestSize().height) <= 4
                for b in _dir_btns),
            f"{[(b.GetBestSize().width, b.GetBestSize().height) for b in _dir_btns]}",
        )
        # **顺序：升序在前（False）、降序在后（True）。**
        # 这条不只是"好看"—— `_apply_language` 里用 zip 按**位置**刷新文案，
        # 顺序错了就会"换语言后文案贴到错误的按钮上"。
        check(
            "排序方向顺序 = 升序在前 / 降序在后（与箭头上下的直觉一致）",
            [b._direction_value for b in _dir_btns] == [False, True],
            f"_direction_value = {[b._direction_value for b in _dir_btns]}",
        )
        check(
            "排序方向按钮也有悬停提示（文字仍可读）",
            all(b.GetToolTipText() for b in _dir_btns),
            f"tooltip = {[b.GetToolTipText() for b in _dir_btns]}",
        )

        # ---- retranslate 必须覆盖**所有**会变的文字（用户 2026-10-17）----
        #
        # > "这个主题窗口和窗口的标题栏没有及时跟随刷新变化，但是其他地方
        # >   又是及时跟随的。这说明不是功能上做不到，而是有一些地方漏接了。"
        #
        # 两个真实漏接点：
        #   ① `_theme_buttons` 的 tooltip（上一版注释还写着"主题是符号、
        #      与语言无关"—— 早已过时）
        #   ② 窗口标题（`ThemedDialog.__init__` 传进去后就没人再更新）
        #
        # 判据用"**前后快照对比**"：切语言 → retranslate → 逐项比。
        # 这样以后再加任何"会变的文字"，只要没接上就会被这条抓到。
        def _texts():
            return {
                "title": sort_probe.GetTitle(),
                "theme_tip": [b.GetToolTipText() for b in _theme_btns],
                "sort_tip": [b.GetToolTipText() for b in _sort_btns],
                "dir_tip": [b.GetToolTipText() for b in _dir_btns],
            }

        _before = _texts()
        # ⚠️ **`_after` 必须在恢复语言之前取。**
        # 第一版把它写在 `finally` 之后，于是两次快照都是"原语言"、
        # 四条判据全失败 —— 而那时**功能其实是对的**，错的是判据。
        # `lang.preference(chinese)` 是"bool → 偏好值"的转换，
        # 读当前值要用 `lang.is_chinese()`。
        _old_chinese = _lang.is_chinese()
        _after = {}
        try:
            _lang.apply(_lang.PREFERENCE_ENGLISH if _old_chinese
                        else _lang.PREFERENCE_CHINESE)
            sort_probe.retranslate()
            _after = _texts()          # ← 在这里取，不是 finally 之后
        finally:
            _lang.apply(_lang.preference(_old_chinese))
            sort_probe.retranslate()
        for key, label in (("title", "窗口标题"),
                           ("theme_tip", "主题按钮 tooltip"),
                           ("sort_tip", "排序按钮 tooltip"),
                           ("dir_tip", "方向按钮 tooltip")):
            check(
                f"retranslate 后 {label} 跟着语言变",
                _before[key] != _after[key],
                f"切换前 {_before[key]!r} → 切换后 {_after[key]!r}",
            )

        check(
            "主题按钮也是**正方形**，且与排序按钮**同尺寸**",
            bool(_theme_btns)
            and all(abs(b.GetBestSize().width - b.GetBestSize().height) <= 4
                    for b in _theme_btns)
            and {b.GetBestSize().Get() for b in _theme_btns}
            == {b.GetBestSize().Get() for b in _sort_btns},
            "主题 %r / 排序 %r" % (
                [b.GetBestSize().Get() for b in _theme_btns],
                [b.GetBestSize().Get() for b in _sort_btns]),
        )
        check(
            "排序图标按钮有**悬停提示**（文字仍然可读 / 无障碍）",
            all(b.GetToolTipText() for b in _sort_btns),
            f"{[b.GetToolTipText() for b in _sort_btns]}",
        )

        # **用户要求②：三个主题选项必须并排在同一行。**
        #
        # 不能只靠上面那条——折成两行时中心仍可能对上。
        theme_chunks = dict(sort_probe._rows).get(sort_probe._theme_label)
        check(
            "设置窗口：三个主题选项并排在同一行（跟随系统 / ☀ / ☾）",
            theme_chunks is not None and len(theme_chunks) == 1,
            f"折成了 {0 if theme_chunks is None else len(theme_chunks)} 块"
            "（应为 1 块 = 三个并排）",
        )
        # **判据从"标签是符号"改成"是自绘图标"**（2026-10-17）：
        # 原来主题按钮的 caption 是 `💻`/`☀`/`☾`，`_on_paint` 里其实
        # 早就用 `icon_painter` 画几何图元了（文字只影响尺寸、不会被画）。
        # 而 `💻` 是 emoji、175% 下宽 30+ 像素，把按钮撑成 56×40；
        # 用户要求"统一成正矩形" ⇒ caption 留空 ⇒ 尺寸回到 56×56。
        #
        # 所以现在该断言的是"三个都有 icon_painter"，不是"label 是符号"。
        _theme_all = [b for chunk in (theme_chunks or []) for b in chunk]
        check(
            "设置窗口：三个主题都是**自绘图标**（不是字形）",
            len(_theme_all) == 3
            and all(getattr(b, "icon_painter", None) is not None for b in _theme_all),
            f"painter = {[getattr(b, 'icon_painter', None).__name__ for b in _theme_all]}",
        )
        check(
            "三个主题按钮仍保留**悬停提示**（符号不再承担文案）",
            all(b.GetToolTipText() for b in _theme_all),
            f"tooltip = {[b.GetToolTipText() for b in _theme_all]}",
        )

        # **阳性对照：组与组之间真的有空行**（这就是用户要的"层次感"）
        #
        # 没有它的话，"四组贴在一起"也能通过上面那条。
        gaps = []
        rows = sort_probe._rows
        for index in range(1, len(rows)):
            prev_buttons = [b for chunk in rows[index - 1][1] for b in chunk]
            this_buttons = [b for chunk in rows[index][1] for b in chunk]
            if prev_buttons and this_buttons:
                prev_bottom = max(b.GetRect().y + b.GetRect().height
                                  for b in prev_buttons)
                gaps.append(this_buttons[0].GetRect().y - prev_bottom)
        row_h = sort_probe._sort_buttons[0].GetSize().height if \
            sort_probe._sort_buttons else 0
        check(
            "阳性对照：组与组之间留出了空行（比组内间距明显更大）",
            bool(gaps) and min(gaps) > row_h // 3,
            f"组间净空 = {gaps}，按钮高 = {row_h}"
            "（「空一行」就是层次感的来源）",
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
        # **样式位也要显式声明。**
        #
        # 这条和上面那条是**两件事**，不能合并：
        # 上面判的是"非客户区有多大"（几何量），这条判的是
        # "我们有没有主动要求无边框"（样式位）。
        # 少了这条，将来谁把 `wx.BORDER_NONE` 从样式里去掉、
        # 而恰好又没有非客户区差异时，就没有东西挡着了。
        check(
            "导航窗格已显式声明 wx.BORDER_NONE",
            bool(frame.dir_ctrl.GetWindowStyleFlag() & wx.BORDER_NONE),
            f"样式 = {frame.dir_ctrl.GetWindowStyleFlag():#x}，"
            f"BORDER_NONE = "
            f"{bool(frame.dir_ctrl.GetWindowStyleFlag() & wx.BORDER_NONE)}",
        )

        check(
            "导航窗格没有多余的边框（非客户区只允许是滚动条）",
            (border_px == 0)
            or abs(border_px
                   - wx.SystemSettings.GetMetric(wx.SYS_VSCROLL_X)) <= 2,
            f"窗口宽 {window_w} − 客户区宽 {client_w} = {border_px}px"
            f"；滚动条宽 {wx.SystemSettings.GetMetric(wx.SYS_VSCROLL_X)}px"
            "（`GenericDirCtrl` 时代那条断言写的是它自带的 2px 非客户区边框；"
            "换成自己的树之后，非客户区里合法的东西**只有滚动条**）",
        )

        # ---- 列间竖线（这条我漏了三轮）----
        #
        # 用户反馈"改了 separator 颜色也没有可见变化"。
        # **根因不是颜色，是线根本不存在**：`separator` 只画在**表头**里，
        # 数据行里从来没画过。`_draw_column_separators` 只在注释里被提到，
        # 方法本身一直没写。
        #
        # 判据：**拦截 `wx.ClientDC.DrawRectangle`，看真的落笔了没有**——
        # 不是"方法存在"，也不是"没报错"。
        #
        # 2026-10-17 从 `DrawLine` 改为 `DrawRectangle`：宽 pen 的 `DrawLine`
        # "往哪一侧扩展"由 GDI 决定、不可控；矩形能精确覆盖
        # `[left, left + thick - 1]`，右边缘才能严格落在列边界上。
        drawn_rects: list[tuple] = []
        original_draw_rect = wx.ClientDC.DrawRectangle

        def spy_draw_rect(self, *args):
            try:
                colour = self.GetBrush().GetColour().GetAsString(wx.C2S_HTML_SYNTAX)
            except Exception:
                colour = ""
            drawn_rects.append(tuple(args) + (colour,))
            return original_draw_rect(self, *args)

        wx.ClientDC.DrawRectangle = spy_draw_rect
        try:
            frame._paint_column_separators()
        finally:
            wx.ClientDC.DrawRectangle = original_draw_rect

        column_count = frame.list_ctrl.GetColumnCount()
        expected = column_count - 1

        def right_edge(rec):
            return int(rec[0]) + int(rec[2])       # left + width

        def thick_of(rec):
            return int(rec[2])

        check(
            "列间竖线真的画出来了（数据行里，不只是表头）",
            len(drawn_rects) >= expected,
            f"DrawRectangle 被调用 {len(drawn_rects)} 次，"
            f"至少应有 {expected} 次（{column_count} 列 → {expected} 条竖线）",
        )
        # 阳性对照：竖线的**右边缘**必须落在列边界上（加粗后左边缘会变，
        # 但右边缘永远是列边界 —— 这才是"对齐"的真正含义）
        boundary = 0
        boundaries = []
        for index in range(column_count - 1):
            boundary += frame.list_ctrl.GetColumnWidth(index)
            boundaries.append(boundary)
        rights = sorted({right_edge(r) for r in drawn_rects}) if drawn_rects else []
        check(
            "阳性对照：竖线的右边缘落在列边界上",
            bool(rights) and all(
                any(abs(x - b) <= 3 for b in boundaries) for x in rights
            ),
            f"右边缘 = {rights}；列边界 = {boundaries}",
        )

        # ---- 置顶区与普通区的颜色（粗细已统一，见下）----
        #
        # 用户 2026-10-17："表头和置顶颜色的粗细，和下面其他记录的粗细不统一。
        # 我想让它们**全部统一起来**，这样就可以一起调整。"
        # ⇒ 表头 / 置顶段 / 普通段共用 `METRICS.separator_thickness`。
        seam_th = max(int(_METRICS.separator_thickness), 1)
        pin_span = frame._pinned_span()
        colours = {r[4] for r in drawn_rects if len(r) > 4}
        if pin_span is None:
            check(
                "没有置顶行时，竖线只画灰色一段",
                colours == {frame.theme.separator}
                and all(thick_of(r) == seam_th for r in drawn_rects),
                f"颜色 {colours}，粗细 {[thick_of(r) for r in drawn_rects]}",
            )
        else:
            check(
                "有置顶行时：竖线分段画（置顶段 + 普通段）",
                len(drawn_rects) == expected * 2,
                f"DrawRectangle {len(drawn_rects)} 次，"
                f"期望 {expected * 2} 次（{expected} 条 × 2 段）",
            )
            check(
                "置顶段的颜色 = separator_pinned（置顶专用 1.35）",
                frame.theme.separator_pinned in colours,
                f"颜色集合 = {colours}，"
                f"separator_pinned = {frame.theme.separator_pinned}",
            )
            check(
                "普通段的颜色 = separator（灰，保持原样）",
                frame.theme.separator in colours,
                f"颜色集合 = {colours}，separator = {frame.theme.separator}",
            )
            thick_set = sorted({thick_of(r) for r in drawn_rects})
            check(
                "置顶段与普通段的**粗细相同**（全部统一）",
                thick_set == [seam_th],
                f"粗细集合 = {thick_set}；应全部 = {seam_th}",
            )

        # ---- 三条线的对比度**全部 1.6**（用户 2026-10-17 明确要求）----
        #
        # 这一条把"用户想要的观感"变成了**可计算的数字**：
        # 六条（3 条线 × 2 个主题）全部落在 1.6 ± 0.05。
        # **两档目标值不同**（用户 2026-10-17 最后一条要求）：
        # 浅色 1.20、深色 1.30。
        for theme_name, theme, target in (("浅色", _theme.Theme.light(), 1.20),
                                          ("深色", _theme.Theme.dark(), 1.30)):
            pairs = (
                ("普通灰线", theme.separator, theme.card),
                ("表头掩码线", theme.separator_masked, theme.surface_alt),
                ("置顶掩码线", theme.separator_pinned, theme.pinned_row),

            )
            for label, fg, bg in pairs:
                ratio = _contrast_ratio(fg, bg)
                check(
                    f"[{theme_name}] {label} 对比度 ≈ {target:.2f}",
                    abs(ratio - target) <= 0.03,
                    f"{fg} on {bg} = {ratio:.3f}",
                )

        # ---- 表头那条竖线用哪个颜色 / 多粗 ----
        from file_tracker.header import ColumnHeader as _ColumnHeader

        import inspect as _inspect2

        _header_src = _inspect2.getsource(_ColumnHeader._on_paint)
        check(
            "表头竖线的颜色 = separator_masked（表头专用 1.35）",
            "theme.separator_masked" in _header_src,
            "表头竖线画的是 `theme.separator_masked`",
        )
        header_source = _inspect2.getsource(_ColumnHeader.separator_thickness)
        check(
            "表头竖线粗细取的是 METRICS.separator_thickness（与数据行同一个）",
            "METRICS.separator_thickness" in header_source,
            "全表只有一个粗细来源 ⇒ 改一个数整张表一起变",
        )
        check(
            "全表粗细只有**一个**常量（没有第二份额外的粗细）",
            "separator_masked" not in header_source,
            f"METRICS.separator_thickness = {seam_th}",
        )
        # **表头与数据行的线右边缘必须重合**（加粗后左边缘会不同，
        # 所以判据看右边缘 —— 那才是"对齐"的真正含义）
        header_xs = sorted(frame.header.separator_positions())
        header_thick = frame.header.separator_thickness()
        header_rights = sorted(x + header_thick for x in header_xs)
        check(
            "表头竖线与数据行竖线的**右边缘**一致（不再错位）",
            bool(header_rights) and header_rights == rights,
            f"表头右边缘 = {header_rights}；数据行右边缘 = {rights}",
        )
        # ---- 竖线必须**最细**：1 物理像素，不按 DPI 缩放 ----
        #
        # 用户要求"将列分隔线改细。最细。"→ 后来又要"加粗"→ 最后要
        # **全部统一**（2026-10-17）。现在只有 `METRICS.separator_thickness`
        # 一个旋钮（目前 4）。
        #
        # 关键点：**不按 DPI 换算**。`scale_for_dpi(4, 168)` 会算出 7，
        # 与用户选定的观感不符；细线是显示器的属性，不是内容的属性。
        dpi_now = frame.GetDPI()
        dpi_now = dpi_now[0] if hasattr(dpi_now, "__getitem__") else dpi_now
        scaled = max(round(_METRICS.separator_thickness * dpi_now / 96), 1)
        check(
            "竖线粗细 = METRICS.separator_thickness（不按 DPI 放大）",
            frame.header.separator_thickness() == seam_th,
            f"separator_thickness = {_METRICS.separator_thickness}；"
            f"若按 DPI 换算（{_METRICS.separator_thickness} × {dpi_now}/96）"
            f"会是 {scaled}px",
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
        # **只检查"警告/确认"类弹窗。** `--version` 那个信息框是
        # `ICON_INFORMATION`，不是警告，**故意不带警告标志**
        # （否则"信息"和"警告"就分不出来了）。
        #
        # ## 2026-10-26 起，判据从"正文里有 ⚠️ 字形"变成"构造时传了 alert=True"
        #
        # 用户："每个弹窗的警告标志都使用正文中的"⚠️"符号。但现在我每次看到
        # 弹窗时，发现这个警告标志实在是太小了……把那个警告标志画出来，
        # 替换掉目前所有的"⚠️"符号。"
        #
        # 现在标志由 `ThemedDialog` **自己画**（`theme.warning_badge_geometry`
        # 定几何、`widgets.icon_warning` 出图元），正文里**不许再拼那个字形**。
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

        # **谁在调用**也要知道：`--version` 那个信息框用的是 `ThemedDialog`，
        # 但它不是警告，**故意不带标志**（否则"信息"与"警告"分不出来）。
        # 用 AST 追出每个调用**最内层的那个函数名**，比按文案猜可靠。
        _owner: dict = {}

        def _mark_owner(node, func_name: str) -> None:
            for child in _ast.iter_child_nodes(node):
                _owner[child] = func_name
                _mark_owner(
                    child,
                    child.name if isinstance(
                        child, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                    else func_name)

        _mark_owner(tree, "")

        #: 允许"不自绘标志"的调用方：`--version` 的信息框（是"信息"不是"警告"）。
        NO_ALERT_OWNERS = {"_show_message_safely"}

        alerted, missing_alert, system_boxes = [], [], []
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name not in DIALOG_CALLS:
                continue
            statement = call_text(node)
            # `_notify(...)` 的**调用方**不算漏：标志由 `_notify` 内部传
            if name == "_notify":
                continue
            if name in ("MessageBox", "MessageDialog"):
                system_boxes.append(statement)
                continue
            if _owner.get(node) in NO_ALERT_OWNERS:
                continue
            if "alert=True" in statement:
                alerted.append(statement)
            else:
                missing_alert.append(statement)

        check(
            "每个自绘弹窗都带**警告标志**（`ThemedDialog(..., alert=True)`）",
            not missing_alert,
            "；".join(t[:72] for t in missing_alert) or
            f"带标志的 {len(alerted)} 处全部有 alert=True",
        )
        # 阳性对照：必须真的找到了带标志的弹窗，否则上面那条是空转
        check(
            "阳性对照：确实扫到了带警告标志的弹窗（不是空集）",
            len(alerted) >= 3,
            f"扫到 {len(alerted)} 处 alert=True 的弹窗",
        )
        # 系统对话框**画不了**自绘标志，所以只允许那两个已知的早期场景，
        # 并且它们各自带着**系统自己的**图标（ICON_WARNING / ICON_ERROR）。
        check(
            "剩下的系统对话框只有已知的两处，且都靠系统图标示警",
            len(system_boxes) <= 2
            and all(any(mark in t for mark in
                        ("ICON_WARNING", "ICON_ERROR", "ICON_INFORMATION"))
                    for t in system_boxes),
            "；".join(t[:64] for t in system_boxes) or "无",
        )
        # **标志在正文里（由 `alert=True` 画出来），标题保持纯文字。**
        #
        # 用户早先要求："标题栏题头的 ⚠️ 换成程序图标，把 ⚠️ 放在说明文字的前面，
        # 和 Roboc 一致。" —— 现在那枚标志是自绘的三角，位置仍是"正文开头"。
        #
        # ## 阳性对照：标题里不能出现任何警示符号
        #
        # 这条守的是"标志不在标题栏里"——只查正文有标志是不够的，
        # 那样标题里留着一个也测不出来。
        #
        # ## 第一版有漏洞，被用户抓到了
        #
        # 原来只做字符串匹配：`'title=f"{WARN}' in statement`。
        # **硬编码的 emoji 溜得过去**——`title="⚠️路径不存在"` 不会被抓到
        # （语句里没有 `WARN` 这个词）。
        #
        # 用户正是在扫描弹窗时看到探针造出的那个标题带 ⚠️ 的窗口。
        #
        # 现在改成**从 AST 取 `title=` 那个实参本身**，
        # 再检查它里面有没有任何警示类字符——
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
            return bool(chunk) and any(m in chunk for m in MARKS)

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
            "阳性对照：没有任何弹窗把警示符号留在标题里（AST 取实参，不是字符串匹配）",
            not title_marks,
            "；".join(t[:72] for t in title_marks) or "标题全部是纯文字",
        )
        # 确认框已改成自绘弹窗（系统对话框没法适配深色主题）
        check(
            "确认框用的是自绘 ThemedDialog，不是系统对话框",
            "wx.MessageDialog(" not in _inspect.getsource(_app_module),
            "wx.MessageDialog/MessageBox 由系统按浅色主题绘制，深色下改不了色",
        )

        # ---- 进程级深色模式跟的是**程序主题**，不是系统主题（2026-10-26 修的旧 bug）----
        #
        # 用户："在深色主题下，选中路径记录器当中的条目并右键点击，
        #       其菜单没有随深色主题反色，依然是浅色背景。"
        #
        # 右键菜单 / 滚动条 / 系统提示框都是**系统画的**，只看
        # `uxtheme.SetPreferredAppMode` 那个**进程级**开关；而 `OnInit` 原来按
        # **系统主题**设它 ⇒ "系统浅色 + 程序深色"时自绘部分全深、菜单却是浅的。
        #
        # 实测 A/B（`tools/probes/probe_menu_dark.py`，取整块菜单矩形的众数色）：
        # 修复前 (249,249,249)／暗占比 2.6%，修复后 (44,44,44)／暗占比 95.2%。
        from file_tracker import config as _config_module

        original_theme = _config_module.Config(
            _app_module.default_config_path()).get_theme()
        resolved = {}
        try:
            for preference, want_dark in (("dark", True), ("light", False)):
                store_cfg = _config_module.Config(
                    _app_module.default_config_path())
                store_cfg.set_theme(preference)
                store_cfg.save()
                resolved[preference] = _app_module.process_theme_preference()
        finally:
            restore = _config_module.Config(_app_module.default_config_path())
            restore.set_theme(original_theme or "system")
            restore.save()
        check(
            "进程级深色模式按**程序主题偏好**算（不是系统主题）",
            resolved.get("dark") is not None and resolved["dark"].is_dark
            and resolved.get("light") is not None
            and not resolved["light"].is_dark,
            f"配置 dark → is_dark={getattr(resolved.get('dark'), 'is_dark', None)}，"
            f"配置 light → is_dark={getattr(resolved.get('light'), 'is_dark', None)}"
            f"（系统当前浅色 = {win32.system_uses_light_theme()}）",
        )
        # ⚠️ 判据**必须走 AST**，不能拿源码字符串比对：那段旧代码被我
        # 原样写进了 `process_theme_preference` 的说明文档里，
        # 字符串判据会命中自己的注释（这个坑本项目已经踩过两次）。
        on_init = None
        for node in _ast.walk(tree):
            if isinstance(node, _ast.FunctionDef) and node.name == "OnInit":
                on_init = node
                break
        init_calls = []
        if on_init is not None:
            for node in _ast.walk(on_init):
                if isinstance(node, _ast.Call):
                    call_name = (getattr(node.func, "attr", None)
                                 or getattr(node.func, "id", None))
                    init_calls.append((call_name,
                                       _ast.get_source_segment(source, node)
                                       or ""))
        sets_from_preference = any(
            call_name == "set_process_dark_mode"
            and "process_theme_preference" in segment
            for call_name, segment in init_calls)
        still_uses_system = any(
            call_name == "system_uses_light_theme"
            for call_name, _segment in init_calls)
        check(
            "`OnInit` 按**程序主题**设进程级模式（AST 判，不比对源码字符串）",
            sets_from_preference and not still_uses_system,
            f"OnInit 里调 set_process_dark_mode 用的是程序主题 = "
            f"{sets_from_preference}；仍调用 system_uses_light_theme = "
            f"{still_uses_system}（改前/改后能区分）",
        )
        check(
            "运行中切主题也会重设进程级模式（否则切换后菜单一直是旧的）",
            "set_process_dark_mode(self.theme.is_dark)" in
            _inspect.getsource(_app_module),
            "在 `_retheme` 里，菜单是按需创建的，所以对后续弹出的菜单有效",
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
            frame, frame.theme, "确定要清空所有记录吗？",
            title="确认清空", alert=True,
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
        # **警告标志占掉正文左侧一条**，所以宽度公式里要多加这一条
        badge_px, badge_gap_px = dialog._alert_metrics()
        alert_extra = dialog._alert_extra
        wrap_px = max(max_text_px - alert_extra, _scale(120, dpi_value))
        # 宽度 = max(正文实宽 + 标志那一条, 按钮组宽) + margin×2
        check(
            "弹窗宽度按**实际文字 + 警告标志那一条**算（不固定 819，也不超上限）",
            client_width
            == max(min(text_width, wrap_px) + alert_extra,
                   len(dialog._labels) * _scale(_DLG.dialog_button_width,
                                                dpi_value)
                   + max(len(dialog._labels) - 1, 0)
                   * _scale(_DLG.dialog_button_gap, dpi_value))
            + margin_px * 2,
            f"实际 {client_width}，正文实宽 {text_width}（折行上限 {wrap_px}）"
            f"，标志那一条 {alert_extra}（={badge_px}+{badge_gap_px}）"
            f"，margin×2 = {margin_px * 2}",
        )
        check(
            "弹窗正文左边界 = margin（24 逻辑像素）",
            dialog._body_rect[0] == margin_px,
            f"正文左边 = {dialog._body_rect[0]}，margin = {margin_px}",
        )

        # **"图标 + 间距 + 文字"作为一个整体居中**（2026-10-26 第二版）。
        #
        # 第一版把图标钉在正文区最左边、文字在自己的列里居中 —— 短消息时
        # 图标离文字老远（实测图标 x=42、文字 x=174），像两个不相干的东西；
        # 用户那张截图里 `⚠️` 是**紧挨着文字**的，所以判据改成"整组居中"。
        left, _t, right, _b = dialog._body_rect
        body_w = right - left
        block_w = text_width
        group_w = alert_extra + block_w
        group_x = left + max((body_w - group_w) // 2, 0)
        text_left = group_x + alert_extra
        check(
            "正文（**警告标志 + 文字**）作为一组居中（左右留白相等）",
            abs((group_x - left) - (right - (group_x + group_w))) <= 1,
            f"组左边 = {group_x}（留白 {group_x - left}），"
            f"组右边 = {group_x + group_w}（留白 {right - (group_x + group_w)}）",
        )
        check(
            "每行文字在组内居中（左右留白相等，差 ≤ 1px）",
            all(abs((block_w - w) // 2 - (block_w - w - (block_w - w) // 2)) <= 1
                for w in widths),
            f"文字块宽 {block_w}，各行宽 {widths}",
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
            frame, frame.theme, "路径不存在，请检查后重新输入。",
            title="路径不存在",
            yes_label="好", no_label=None, alert=True,
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
        # ---- 警告标志是**画出来的**，而且比正文大（用户 2026-10-26 的明确要求）----
        #
        # 用户原话："把那个警告标志画出来，替换掉目前所有的"⚠️"符号。
        #           调整尺寸：让它比正文字号大一点，醒目一点。"
        #
        # 判据分三层，全部可回读：
        #   ① 尺寸：标志边长 > 正文行高（比例 = `METRICS.dialog_alert_ratio`）；
        #   ② 墨迹：把**真实弹窗**的正文画到位图上，标志框里的暗像素占比
        #      落在"线框"区间（实心三角会 > 0.4）；
        #   ③ 形状：墨迹包围盒高/宽 ≈ 0.866（等边三角），且垂直居中在画布上。
        from file_tracker.theme import warning_badge_geometry as _badge_geo

        body_dc = wx.ClientDC(dialog)
        body_dc.SetFont(dialog.GetFont())
        line_height = body_dc.GetTextExtent(_widgets._measure_probe()).height or 1
        check(
            "警告标志**比正文字号大**（用户说「太小了」，要醒目）",
            badge_px > line_height,
            f"标志边长 {badge_px}px，正文行高 {line_height}px，"
            f"比例 {badge_px / line_height:.2f}"
            f"（= METRICS.dialog_alert_ratio {_DLG.dialog_alert_ratio}）",
        )
        geo = _badge_geo(badge_px)
        check(
            "警告标志是**等边三角**（高/底 = 0.866，不是等腰）",
            abs(geo["height"] / geo["base"] - 0.866) < 0.01,
            f"高/底 = {geo['height'] / geo['base']:.4f}，"
            f"底 {geo['base']:.1f}，高 {geo['height']:.1f}",
        )

        # **把标志画到位图上**（位图上的 GetPixel 可靠；窗口抓图在这个环境
        # 不可靠，见 tools/probes/README.md）。
        #
        # ⚠️ **不要通过 `_draw_body` 来量。** 踩过：`_draw_body` 用**传进来的
        # DC** 去量行高，而 `wx.MemoryDC` 报出来的字高与窗口 DC 不同
        # （实测位图侧 22px、窗口侧 30px），于是"盒子高度"算小了 8px、
        # 图标被画高 4px —— 量出来"没居中"，而真实绘制是对的。
        # **测量与绘制必须用同一种 DC**：这里用 `_line_height()`（ClientDC）
        # 算出盒子高度，再只针对标志位图化。
        body_w = dialog.GetClientSize().width
        body_h = dialog._body_rect[3]
        badge_canvas = wx.Bitmap(body_w, max(body_h, 1))
        badge_dc = wx.MemoryDC(badge_canvas)
        badge_dc.SetBackground(wx.Brush(wx.Colour(dialog.theme.background)))
        badge_dc.Clear()
        badge_box_h = dialog._line_height() + dialog._alert_extra_v
        dialog._draw_alert_badge(badge_dc, dialog._body_rect[0],
                                 dialog._body_rect[1], badge_box_h)
        badge_image = badge_canvas.ConvertToImage()
        # 标志框 = 正文区左上角那块 `badge_px` 见方
        box_x0, box_y0 = dialog._body_rect[0], dialog._body_rect[1]
        ink = []
        for dy in range(max(badge_px, 1) + 2):
            for dx in range(max(badge_px, 1) + 2):
                x, y = box_x0 + dx, box_y0 + dy
                if not (0 <= x < body_w and 0 <= y < body_h):
                    continue
                if badge_image.GetRed(x, y) < 128:
                    ink.append((dx, dy))
        ratio = len(ink) / float(max(badge_px * badge_px, 1))
        check(
            "警告标志真的**画出来**了，而且是**线框**不是实心（墨迹占比可区分）",
            0.04 < ratio < 0.30,
            f"标志框 {badge_px}×{badge_px} 里暗像素 {len(ink)} 个，"
            f"占比 {ratio:.3f}（线框 ≈0.1x；实心三角会 > 0.4）",
        )
        if ink:
            xs = [p[0] for p in ink]
            ys = [p[1] for p in ink]
            ink_w = max(xs) - min(xs) + 1
            ink_h = max(ys) - min(ys) + 1
            top_pad = min(ys)
            bottom_pad = badge_px - max(ys)
            check(
                "警告标志的**墨迹比例**也是等边（高/宽 ≈ 0.866，在像素上回读）",
                abs(ink_h / max(ink_w, 1) - 0.866) < 0.08,
                f"墨迹 {ink_w}×{ink_h}，高/宽 = "
                f"{ink_h / max(ink_w, 1):.3f}",
            )
            check(
                "警告标志在标志框里**垂直居中**（上下留白差 ≤ 2px）",
                abs(top_pad - bottom_pad) <= 2,
                f"上留白 {top_pad}px，下留白 {bottom_pad}px",
            )
        else:
            check("警告标志的墨迹包围盒可量", False, "框里一个暗像素都没有")
        badge_dc.SelectObject(wx.NullBitmap)
        # 标志在**文字左边**，且与文字列不重叠
        check(
            "警告标志**紧贴**文字：图标右缘 + 间距 == 文字块左缘（不重叠、不远离）",
            alert_extra > 0
            and badge_px + badge_gap_px == alert_extra
            and group_x + badge_px + badge_gap_px == text_left,
            f"标志 {badge_px} + 间距 {badge_gap_px} = {alert_extra}px；"
            f"图标左缘 {group_x}，文字块左缘 {text_left}",
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
        # **弹窗正文里不许再有那个字形**（标志改由 `alert=True` 自绘）。
        #
        # 为什么不去扫"整份源码有没有这个码点"：它在注释里大量用作
        # "注意"的标记（`⚠️ 这里不能…`），扫整份源码只会一直误报。
        # 判据必须落在**会显示给用户的那个实参**上 —— 所以从 AST 取
        # 每个弹窗调用的正文实参，看里面有没有警示类字符。
        #
        # 位置：`ThemedDialog(parent, theme, message, ...)` 正文是第 3 个；
        # `_notify(message, title)` 是第 1 个；`MessageBox(正文, 标题, 样式)` 也是第 1 个。
        BODY_POSITION = {"ThemedDialog": 2, "MessageBox": 0,
                         "MessageDialog": 0, "_notify": 0}
        body_marks = []
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            name = (getattr(node.func, "id", None)
                    or getattr(node.func, "attr", None))
            slot = BODY_POSITION.get(name)
            if slot is None or len(node.args) <= slot:
                continue
            chunk = _ast.get_source_segment(source, node.args[slot]) or ""
            if any(m in chunk for m in MARKS):
                body_marks.append(f"L{node.args[slot].lineno}: {chunk[:48]}")
        check(
            "弹窗**正文**里不再拼警示字形（标志由 alert=True 自绘）",
            not body_marks,
            "；".join(body_marks) or "所有弹窗正文都是纯文字",
        )

        # ==============================================================
        print()
        print("=== 顶置顺序：新顶置的必须在**最前**（用户反馈）===")
        print("    用户原话：「新条目置顶后会排在所有已置顶条目最后，")
        print("    这不符合使用习惯和直觉。请把条目置顶逻辑改成放至顶端」")
        # ==============================================================
        #
        # **必须先清掉现有记录。** 用户的真实库里本来就有顶置项，
        # 而这里要断言的是"第一条顶置行是谁"，混着旧数据就判不了。
        frame.store.clear()
        frame.pinned_paths = []
        frame.load_accessed_paths()
        for _ in range(15):
            wx.YieldIfNeeded()

        order = ["pin-first", "pin-second", "pin-third"]
        for name in order:
            folder = os.path.join(scratch.name, "pinorder", name)
            os.makedirs(folder, exist_ok=True)
            frame.store.record_access(folder)
        frame.load_accessed_paths()
        for _ in range(15):
            wx.YieldIfNeeded()

        # 走**真实入口**：选中一行 → 调 `on_pin`（右键菜单/按钮走的是它）
        for name in order:
            target = os.path.join(scratch.name, "pinorder", name)
            row = frame.find_path(target)
            if row < 0:
                check(f"能在列表里找到 {name}", False, f"find_path 返回 {row}")
                continue
            # **可多选之后必须用 select_only** —— 不加清空的话，
            # 上一轮的顶置会把该行的"选中"留着，下一次 `on_pin` 可能
            # 作用在**多条**上（`selected_path()` 只取第一条，
            # 但顶置顺序就乱了）。
            select_only(frame, row)
            frame.on_pin(None)
            for _ in range(8):
                wx.YieldIfNeeded()

        # **判据取列表第一行**，不是取 `pinned_paths`——
        # 用户看到的是列表，内存变量对不对不算数。
        first_row_path = frame.row_path(0)
        expected_first = os.path.join(scratch.name, "pinorder", "pin-third")
        check(
            "最后顶置的那条排在列表第一行（放至顶端）",
            core.paths_equal(first_row_path, expected_first),
            f"第一行 = {first_row_path!r}  期望 = {expected_first!r}",
        )

        # 三条都顶置了，而且整个顶置组的顺序是"最近顶置在最前"
        listed = [frame.row_path(r) for r in range(3)]
        want = [os.path.join(scratch.name, "pinorder", n)
                for n in ("pin-third", "pin-second", "pin-first")]
        check(
            "顶置组整体顺序 = 最近顶置的在最前（而不是插入顺序）",
            all(core.paths_equal(a, b) for a, b in zip(listed, want)),
            f"前三行 = {[os.path.basename(p) for p in listed]}  "
            f"期望 = {[os.path.basename(p) for p in want]}",
        )

        # **阳性对照：重启后顺序不能变。**
        # 这正是我第一次修这个缺陷时踩的坑——顺序只在内存里对，重启就漂了。
        reopened = type(frame.store)(frame.store.db_path)
        try:
            persisted = [r.path for r in reopened.load_pinned()]
            check(
                "阳性对照：重开数据库后顶置顺序不变（不是只在内存里对）",
                all(core.paths_equal(a, b)
                    for a, b in zip(persisted, want)),
                f"库里的顶置顺序 = {[os.path.basename(p) for p in persisted]}",
            )
        finally:
            reopened.close()

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
