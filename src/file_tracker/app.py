"""主窗口。

本模块是从 ``src/File Tracker_v1.1.py`` 迁移过来的，迁移时修掉了四组"静默失效"：

| 问题 | 原来 | 现在 |
|---|---|---|
| 资源加载必然失败 | 找 ``<repo>\\src\\images\\`` 与开发机 ``D:\\Work\\...`` | :func:`file_tracker.core.resource_path`，失败可见 |
| 两个方法各定义两次 | ``set_icon`` L189/L308、``load_last_directory`` L327/L654 | 各留一份 |
| 整表重写 | 退出时 ``DELETE`` 全表再从界面插回 | 由 :mod:`file_tracker.store` 直接增量写 |
| ``accessed_paths.json`` 死变量 | 构造了路径从未使用 | 删除 |

**顺序说明**：先删重复定义再改，否则会改到不生效的那一份——``set_icon`` 的
两份里，L189 用 ``print`` 吞异常、L308 用 ``wx.LogWarning``，
"为什么看不到错误"取决于哪一份生效。
"""

from __future__ import annotations

import ctypes
import os
import subprocess

import wx

from . import win32
from .config import Config, default_config_path
from .core import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_SORT_KEY,
    SORT_SPECS,
    app_data_dir,
    find_sort_spec,
    fit_window_size,
    normalize_path,
    resource_path,
    scaled_window_size,
    version_string,
)
from .store import TIME_FORMAT, PathRecord, PathStore, default_db_path, split_timestamp
from .header import ColumnHeader
from .lang import (L, PREFERENCE_CHINESE, PREFERENCE_ENGLISH,
                   apply as apply_language, is_chinese)
from .theme import METRICS, Theme, from_system as theme_from_system, scale_for_dpi
from .tree_nav import TreeWalker, build_walk_plan, find_child_by_label, pick_fallback_item
from .widgets import (BorderLine, IconButton, PathBar, RoundedButton,
                       NO_BUTTON, SettingsDialog, ThemedDialog, dpi_of)

#: 列表列定义：(标题, 初始宽, 是否居中)
#:
#: **"最后访问时间"拆成两列。** 用户反馈日期与时间挤在一起、不好区分；
#: 拆成"访问日期"+"访问时间"之后两者之间有真正的列间距，比换用任何分隔符
#: 都明确——同一个分隔符在不同字号、不同 DPI 下观感差别很大。
#: 数据库里仍存整串，只在显示时拆（见 :func:`store.split_timestamp`）。
#:
#: **宽度与居中标记是"结构"，列标题是"文案"——两者分开。**
#:
#: 标题不能写在这里：模块级常量在 **import 时**求值，而语言偏好要等
#: `lang.apply()`（启动早期、但晚于 import）才知道。写在模块级，
#: 双语判断就会永远用系统的默认答案，用户在设置里选了也不生效。
#: 所以标题走 `column_labels()`，**每次用的时候现取**。
COLUMNS = (
    (400, False),
    (90, True),
    (120, True),
    (110, True),
)

COLUMN_PATH, COLUMN_COUNT, COLUMN_DATE, COLUMN_CLOCK = 0, 1, 2, 3


def column_labels() -> tuple[str, ...]:
    """四个列标题（跟随当前语言）。

    **与 `SORT_SPECS` 同序**——列的顺序和可排序列的顺序是同一件事，
    验证脚本会断言两者长度一致、顺序对应。
    """
    return (
        L("访问的路径", "Path"),
        L("频次", "Count"),
        L("访问日期", "Date"),
        L("访问时间", "Time"),
    )


#: 列号 → 排序列标识。**与 `SORT_SPECS` 同序**，见 `column_labels()`。
#: 两张表必须同序：列的顺序就是可排序列的顺序。
#: 一致性由 `tests/test_sort_preference.py` 断言——**用测试而不是
#: 模块级 `assert`**：`-O` 会去掉 assert，而测试不会。
_COLUMN_SORT_KEYS = ("path", "count", "date", "clock")


def _column_of(sort_key: str) -> int:
    """排序列标识 → 列号；认不出返回默认列。"""
    try:
        return _COLUMN_SORT_KEYS.index(sort_key)
    except ValueError:
        return _COLUMN_SORT_KEYS.index(DEFAULT_SORT_KEY)


def _sort_key_of(column: int) -> str:
    """列号 → 排序列标识；认不出返回默认。"""
    if 0 <= column < len(_COLUMN_SORT_KEYS):
        return _COLUMN_SORT_KEYS[column]
    return DEFAULT_SORT_KEY
# 注：曾经还有一个 `COLUMN_TIME = COLUMN_DATE`，给"切换排序"按钮在两个
# 排序列之间切换用。那个按钮已按用户要求删除（"没什么用"），
# 排序列改由列头点击直接指定，所以这个别名没有读者了——已删。

#: 所有警告/确认弹窗标题的统一前缀。
#:
#: 用户要求："在所有警告弹窗的标题前加上 ⚠️，如 ⚠️确认清空？"
#:
#: **抽成常量而不是每处手写**：手写的话新增一个弹窗就会漏掉，
#: 而且以后要换符号（比如换成 ℹ️ 区分信息类）只改这一处。
#: 验证脚本会检查每一个弹窗标题都以它开头。
WARN = "\u26a0\ufe0f"


class FileTracker(wx.Frame):
    """文件访问追踪主窗口。"""

    def __init__(self):
        style = wx.DEFAULT_FRAME_STYLE | wx.WANTS_CHARS
        super().__init__(parent=None, title=APP_NAME, style=style)
        self.SetName("FileTrackerFrame")

        self.theme: Theme = theme_from_system()
        # **窗口自己的底色也要设。** 不设的话它用 wx 的默认灰
        # （实测 (171,171,171)），与"卡片浮在窗口底上"的分层对不上——
        # 用户会看到卡片周围一圈突兀的灰边。
        self.SetBackgroundColour(wx.Colour(self.theme.background))
        # 与 `config`/`store` 用**同一个**目录，而且不依赖 wx。
        #
        # 原来是 `wx.StandardPaths.Get().GetUserDataDir()`：这里的 App 已经
        # 存在所以能用，但它与 `default_config_path()` 是两套来源——
        # 一旦 `SetAppName` 与 `APP_NAME` 不一致，配置与日志就会分到两个目录。
        # 现在只有一处定义（`core.app_data_dir`）。
        self.app_data_dir = app_data_dir()
        if not os.path.exists(self.app_data_dir):
            os.makedirs(self.app_data_dir, exist_ok=True)
        # 走 `default_config_path()` 而不是在这里拼路径——
        # 测试与验证脚本要能把它换掉，否则会写进用户真实的配置。
        self.config = Config(default_config_path())
        # **语言必须在建任何界面之前定下来。**
        #
        # 按钮文字、列标题、提示都是建控件时按当时语言取的字面量；
        # 晚一步就会先看到中文、切主题或重开才变英文。
        # （`apply(None)` 表示"配置里没存过"，此时问系统。）
        apply_language(self.config.get_language())

        try:
            self.store = PathStore(default_db_path())
        except Exception as error:  # sqlite3.Error 及其它打开失败
            # **这里只能用 `wx.MessageBox`。**
            #
            # 这是 `__init__` 早期，`InitUI` 还没跑、`self` 还不是一个可用的
            # 窗口（没有 handle），所以 `ThemedDialog(self, ...)` 建不出来。
            # 而且数据库开不了是**致命错误**，弹完就 `raise`，
            # 用户根本看不到主界面——主题不一致在这里不是主要问题。
            # **不要为了统一外观把这条也换掉**：换了会连提示都弹不出来。
            # ⚠️ 同样放**正文**开头（与其余弹窗一致，见 `_notify`）。
            # 系统对话框只有正文与标题两个位置，这里沿用同一套约定。
            wx.MessageBox(
                f"{WARN} " + L("初始化数据库时发生错误: ",
                                 "Could not open the database: ") + str(error),
                L("数据库错误", "Database error"),
                          wx.OK | wx.ICON_ERROR)
            raise

        self.pinned_paths: list[str] = [r.path for r in self.store.load_pinned()]
        self.last_directory = self.config.get_last_directory()
        # **必须在 InitUI 之前调用**：窗口图标要在窗口显示前设好，
        # 否则任务栏上会先出现默认图标再被替换。
        # 这一行曾经漏掉——`set_icon` 于是成了死代码，"从源码运行有图标"
        # 这个缺陷修了却没有生效。接线检查把它抓了出来。
        self.set_icon()

        # 排序状态必须在 load_accessed_paths() 之前就位——它内部会调用排序。
        #
        # **读用户上次的选择。** 用户反馈："目前是每次启动默认频次排序，
        # 太死板，我希望用户能根据自己的习惯调节。"
        #
        # 没设过就还是"频次、降序"——那是 1.1 以来的行为，
        # 老用户升级后第一眼看到的东西不该变。
        sort_spec = find_sort_spec(self.config.get_sort_column())
        self.sort_key = sort_spec.key
        self.sort_column = _column_of(self.sort_key)
        direction = self.config.get_sort_direction(sort_spec.key)
        self.sort_reverse = (sort_spec.default_reverse
                             if direction is None else direction)
        # 界面当前显示的行（有序）。wx.ListCtrl 按行号取值，而排序在 Python 侧做，
        # 所以持有一份有序列表比每次回读控件更可靠。
        self._rows: list[PathRecord] = []
        # 列间竖线开关（画在客户区上的一层覆盖，见 _paint_column_separators）
        self.show_column_separators = True

        self.ignore_scroll_events = False
        self.scroll_timer = None
        self.initial_scroll_position = None

        # **顺序有讲究：先建界面，再设字体。**
        #
        # `set_global_font` 里要把列表控件**退回系统默认字体**（原版列表不在
        # 那三行显式设字体的代码里，用的是系统字体）。而窗口级 `SetFont`
        # 会向子控件传播，所以必须在列表**已经存在之后**才回退，
        # 否则那个回退落在一个还不存在的对象上——踩过一次：
        # 列表字体一直是 10pt（继承来的），列头因此比原版大一号。
        self.InitUI()
        self.apply_window_theme()
        # **字体必须最后设。** 见 set_global_font 的说明：
        # 它要把列表退回系统字体，而那要在窗口字体传播**之后**做。
        self.set_global_font()

        self.load_accessed_paths()
        self.sort_list_items(self.sort_column)

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_SIZE, self.on_window_resize)
        self.Bind(wx.EVT_ACTIVATE, self.on_activate)
        self.Bind(wx.EVT_SHOW, self.on_show)

        wx.CallAfter(self.restore_scroll_position)

    # ------------------------------------------------------------------
    # 资源
    # ------------------------------------------------------------------

    def set_icon(self, icon_name: str = "shell32_star.ico") -> bool:
        """设置窗口图标。

        **只有一份实现**（原来 L189 与 L308 各一份，后者生效）。
        失败路径是可见的：返回 ``False`` 并写入 stderr，而不是 ``print`` 到
        在 windowed 模式看不见的地方、也不是 ``wx.LogWarning``。
        """
        icon_path = resource_path(os.path.join("images", icon_name))
        if not os.path.exists(icon_path):
            self._report_resource_error(L(f"图标不存在：{icon_path}", f"Icon not found: {icon_path}"))
            return False
        try:
            self.SetIcon(wx.Icon(icon_path, wx.BITMAP_TYPE_ICO))
            return True
        except Exception as error:
            self._report_resource_error(L(f"图标加载失败：{icon_path}（{error}）",
                            f"Could not load icon: {icon_path} ({error})"))
            return False

    def load_bitmap(self, bitmap_name: str, size=None) -> wx.Bitmap | None:
        """加载 ``images/`` 下的位图。

        原实现在这一处**没有任何守卫**：``wx.Image(<不存在的路径>)`` 会得到一个
        无效图像，随后 ``wx.Bitmap(image)`` 得到无效位图，界面上表现为
        "按钮是空的"，而没有任何错误——正是最难查的那一类。

        :return: 成功返回位图；失败返回 ``None`` 并报告原因
        """
        bitmap_path = resource_path(os.path.join("images", bitmap_name))
        if not os.path.exists(bitmap_path):
            self._report_resource_error(L(f"图片不存在：{bitmap_path}", f"Image not found: {bitmap_path}"))
            return None

        image = wx.Image(bitmap_path, wx.BITMAP_TYPE_PNG)
        if not image.IsOk():
            self._report_resource_error(L(f"图片无法解码：{bitmap_path}",
                                    f"Could not decode image: {bitmap_path}"))
            return None
        if size:
            image = image.Scale(size[0], size[1], wx.IMAGE_QUALITY_HIGH)
        return wx.Bitmap(image)

    @staticmethod
    def _report_resource_error(message: str) -> None:
        """资源加载失败必须可见。

        规范要求"不能只 print / LogWarning"——单文件 exe 是 windowed 子系统，
        **既没有控制台也看不到日志窗口**。所以这里两个通道都试：

        * 写 stderr —— 从源码运行时可见
        * 追加到 ``%APPDATA%\\File Tracker\\resource-errors.log`` —— 打包运行时
          只有这个可靠

        用 ``try/except OSError`` 包住每一次写：**windowed 模式下 sys.stderr
        可能是 None 或者写进去就抛 OSError**，而"报告失败原因"这件事本身
        绝不能把原始问题盖掉。踩过一次——`print()` 在打包产物里直接抛
        ``OSError: [Errno 22] Invalid argument``。
        """
        from datetime import datetime

        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"

        try:
            import sys

            if sys.stderr is not None and not getattr(sys.stderr, "closed", True):
                print(line, file=sys.stderr)
        except (OSError, ValueError, AttributeError):
            pass

        try:
            # 走 `app_data_dir()` 而不是 `wx.StandardPaths`：
            # 同一个目录，但**不依赖 wx**（那句在没有 App 时弹断言框停住）。
            # 也顺带修掉"`SetAppName` 之前调用会写到 %APPDATA%\<产物名>"
            # 那个错位的毛病。
            log_dir = app_data_dir()
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "resource-errors.log"), "a",
                      encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            # 连日志都写不了时不再抛异常——否则会盖掉真正的原始问题
            pass

    def calculate_icon_size(self, original_size, target_size):
        """按原始宽高比等比缩放到目标长边。"""
        aspect_ratio = original_size[0] / original_size[1]
        if aspect_ratio > 1:
            return (target_size, int(target_size / aspect_ratio))
        return (int(target_size * aspect_ratio), target_size)

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------

    def InitUI(self) -> None:
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(self.theme.background))

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        splitter = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE | wx.SP_NOBORDER)
        splitter.SetBackgroundColour(wx.Colour(self.theme.background))
        # **sash 那 4 像素是 wx 自己画的，取系统色 `SYS_COLOUR_BTNFACE`
        # （本机 `#F0F0F0`），`SetBackgroundColour` 对它无效**——
        # 深色主题下它就是那条"仍旧发白的分界线"。
        # 隐藏掉，改用自己画的 BorderLine（见下）。
        # sash 仍然可以拖动，`SetSashInvisible` 只是不画它。
        splitter.SetSashInvisible(True)
        self.splitter = splitter

        # -- 左 pane：路径栏 + 目录树 --------------------------------------
        left_panel = wx.Panel(splitter)
        left_panel.SetBackgroundColour(wx.Colour(self.theme.background))
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        self.path_bar = PathBar(left_panel, self.theme, on_submit=self.on_path_submitted)
        left_sizer.Add(self.path_bar, 0, wx.EXPAND | wx.ALL, METRICS.padding_gap)

        # **必须加 `wx.BORDER_NONE`。**
        #
        # 用户反馈"导航窗格四周白色框线还在"。前两次我都判断错了：
        #   ① 以为是内层树的 `WS_EX_CLIENTEDGE` —— 去掉后白框还在
        #   ② 以为是 `wx.DIRCTRL_3D_INTERNAL` —— 实测与它无关
        #
        # 真正的来源：`wx.GenericDirCtrl` **默认带 2 像素非客户区边框**。
        # 实测四个变体（各自独立一个窗口，量"窗口宽 − 客户区宽"）：
        #
        # ========================================  ================
        # 样式                                       非客户区（每边）
        # ========================================  ================
        # `DIRCTRL_MULTIPLE`                         2 px
        # `DIRCTRL_MULTIPLE|DIRCTRL_3D_INTERNAL`     2 px  ← 与 3D 无关
        # **`DIRCTRL_MULTIPLE|BORDER_NONE`**         **0 px** ✅
        # `DIRCTRL_MULTIPLE|BORDER_SIMPLE`           1 px
        # ========================================  ================
        #
        # 那 2 像素由**系统按浅色主题绘制**，`SetBackgroundColour`
        # 对非客户区无效——所以深色下它一直是一圈白的。
        #
        # > 教训：查"某块颜色改不掉"时，先分清它属于**客户区**还是
        # > **非客户区**。非客户区不走 wx 的绘制，设色一律无效，
        # > 只能改样式位（`WS_BORDER` / `WS_EX_CLIENTEDGE` / `wx.BORDER_*`）。
        # > 判据要用"窗口矩形 − 客户区矩形"这种**几何量**，不要用像素取样
        # > （本环境下像素取样不可靠，我为此白跑了好几轮）。
        self.dir_ctrl = wx.GenericDirCtrl(
            left_panel, -1, dir=self.last_directory,
            style=wx.DIRCTRL_MULTIPLE | wx.BORDER_NONE,
        )
        self.dir_ctrl.ShowHidden(True)
        self.dir_ctrl.SetMinSize((METRICS.tree_min_width, -1))
        tree = self.dir_ctrl.GetTreeCtrl()
        tree.SetBackgroundColour(wx.Colour(self.theme.card))
        # **整行高亮**（Win11 资源管理器的做法：选中项铺满整行宽度）。
        # 用户反馈"导航窗格空白部分无法选中"——树条目下方的空白区
        # 原生 `SysTreeView32` 本来就不响应（那里没有节点），
        # 所以能改善的是**让选中状态更明显**，而不是让空白可点。
        self._enable_tree_row_highlight(tree)
        tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_dir_item_activated)
        tree.Bind(wx.EVT_SCROLLWIN, self.on_scroll)
        # 导航窗格里**用户操作**了 → 之后的「打开」以它为准。
        #
        # 只绑**程序不可能产生**的事件，不绑 `EVT_TREE_SEL_CHANGED`：
        # 后者会被 `reveal_in_tree` 里的 `SelectItem()` 触发，
        # 从而覆盖用户在记录窗格里的选择。完整理由见
        # `on_tree_selection_made`。
        #
        # 两个事件的选择是有讲究的：
        #   * `EVT_TREE_KEY_DOWN`      —— 方向键换选中。程序不会发键盘事件。
        #   * `EVT_SET_FOCUS`          —— 用户点进这个控件。**焦点是最可靠的
        #     "用户在这里"信号**：程序改选中不会给控件焦点。
        #
        # **不绑 `EVT_TREE_ITEM_ACTIVATED`**：`on_dir_item_activated`
        # 已经绑了它（双击/回车展开），再绑一个会重复处理同一个事件。
        # **也不绑 `EVT_TREE_ITEM_EXPANDING`**：`reveal_in_tree` 里的
        # `tree.Expand()` 会触发它——那正是要躲开的"程序化事件"。
        tree.Bind(wx.EVT_TREE_KEY_DOWN, self.on_tree_selection_made)
        tree.Bind(wx.EVT_SET_FOCUS, self.on_tree_selection_made)
        left_sizer.Add(self.dir_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                       METRICS.padding_gap)
        left_panel.SetSizer(left_sizer)

        # -- 右 pane：卡片（表头 + 列表）+ 按钮条 ---------------------------
        #
        # **卡片分层**：`right_panel` 是窗口底色，里面嵌一块 `card_panel`
        # 用卡片底色，表头与列表都画在卡片上。用户要的"卡片式分层
        # （面板底色 + 列表区域是另一层）"就是靠这层容器实现的——
        # 直接给列表设底色是看不出分层的（列表会占满整块 sizer）。
        right_panel = wx.Panel(splitter)
        right_panel.SetBackgroundColour(wx.Colour(self.theme.background))
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        card_panel = wx.Panel(right_panel)
        card_panel.SetBackgroundColour(wx.Colour(self.theme.card))
        card_sizer = wx.BoxSizer(wx.VERTICAL)

        # **用 wx.LC_NO_HEADER（0x800），不是原生的 LVS_NOCOLUMNHEADER。**
        #
        # 实测对比（同一次运行、只看第一行的 y 坐标）：
        #
        # ==========================  ============
        # 样式                         第一行 y
        # ==========================  ============
        # ``LC_REPORT``                36   ← 表头占着位置
        # ``LC_REPORT|LC_NO_HEADER``   **0** ← 表头不占位置
        # ==========================  ============
        #
        # 原生的 ``LVS_NOCOLUMNHEADER``(0x4000) **被 wx 丢掉了**：
        # 传进去之后原生 ``GWL_STYLE`` 里那一位并没有置起来，
        # 第一行仍在 y=36——表头窗口照样占着一条空白。
        # 那条空白就是用户看到的"双重顶栏"的第二条：
        # 深色下它因为反色 bug（白字浅底）看不见，浅色下才露出来，
        # 所以我一度误判"深色只有一条顶栏 = 没有重复"。
        self.list_ctrl = wx.ListCtrl(
            card_panel,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_NONE
            | wx.LC_NO_HEADER,
        )
        self.list_ctrl.SetBackgroundColour(wx.Colour(self.theme.card))
        for index, (width, _centered) in enumerate(COLUMNS):
            self.list_ctrl.InsertColumn(index, column_labels()[index],
                                        width=width)
        # **恢复原版 1.1 的三条接线。** 中间一版换成 DataViewListCtrl 时，
        # 列头点击排序被删掉了——用户实测指出"所有点击功能全部失效"。
        self.list_ctrl.Bind(wx.EVT_LIST_COL_CLICK, self.on_column_click)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_right_click)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_item_activated)
        # **记录"用户最后一次从哪里选的东西"。**
        #
        # 「打开」原来只看导航窗格（`dir_ctrl.GetPaths()`），
        # 所以在记录窗格里选哪一条都没用——用户报的就是这个：
        # "记录窗格中无论选中哪条记录，「打开」按钮都只会响应左侧导航窗格的选中项。"
        #
        # `_focus_pane` 记录"用户最后一次在哪一处操作"，`on_open` 按它取目标。
        #
        # 默认以导航窗格为准：刚启动时记录窗格里的选中是程序选的（或没有），
        # 而导航窗格停在"上次浏览的目录"——那是用户上回的意图。
        #
        # **判据只认"用户输入事件"**（`SET_FOCUS` / `ITEM_SELECTED` /
        # `TREE_KEY_DOWN`）。为什么不认 `EVT_TREE_SEL_CHANGED`、以及为什么
        # 焦点反而是可靠的信号，见 `on_tree_selection_made` ——那里记着
        # 用户为这个 bug 报过两次的完整原因。
        self._focus_pane = "tree"
        # 点了列表（含点已选中的那一行，此时 `ITEM_SELECTED` 不发）
        for list_event in (wx.EVT_LIST_ITEM_SELECTED, wx.EVT_SET_FOCUS):
            self.list_ctrl.Bind(list_event, self.on_list_selection_made)
        # **选中行整行高亮**（原生高亮被 item 底色压掉了，见
        # `_apply_selection_highlight`）。这几个事件都要接：
        # 点选、键盘上下、全选、以及"点空白处取消选中"。
        self._highlighted_row = -1
        for event in (wx.EVT_LIST_ITEM_SELECTED, wx.EVT_LIST_ITEM_DESELECTED,
                      wx.EVT_LIST_KEY_DOWN):
            self.list_ctrl.Bind(event, self.on_selection_changed)
        # **预选（悬停跟随）由本控件自绘**，不依赖原生热跟踪——
        # 实测原生那套随主题而变（用户那边"深色有、浅色没有"）。
        self._hover_row = -1
        self._hover_painted = -1
        self._paint_key = None
        self.list_ctrl.Bind(wx.EVT_MOTION, self.on_list_motion)
        self.list_ctrl.Bind(wx.EVT_LEAVE_WINDOW, self.on_list_leave)
        # 竖线是覆盖层，滚动/重绘会被擦掉，所以每次都要补画
        self.list_ctrl.Bind(wx.EVT_SCROLLWIN, self.on_list_scroll)
        self.list_ctrl.Bind(wx.EVT_PAINT, self.on_list_paint)

        # **自绘表头**：原生 SysHeader32 在深色主题下不采纳任何设色，见 header.py
        self.header = ColumnHeader(
            card_panel, self.theme,
            titles=list(column_labels()),
            widths=[width for width, _c in COLUMNS],
            on_column_click=self.on_header_clicked,
        )
        # 注意：**这里不能马上藏原生表头**——此刻它还没被创建。
        # 藏它的动作在 apply_window_theme 的最后（布局走完之后）。

        card_sizer.Add(self.header, 0, wx.EXPAND)
        card_sizer.Add(self.list_ctrl, 1, wx.EXPAND)
        card_panel.SetSizer(card_sizer)
        right_sizer.Add(card_panel, 1, wx.EXPAND | wx.ALL, METRICS.padding_gap)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.open_btn = RoundedButton(right_panel, L("打开", "Open"), self.theme,
                                      variant="accent", min_width=72,
                                      on_click=self.on_open)
        self.clear_btn = RoundedButton(right_panel, L("清空", "Clear"), self.theme,
                                       variant="danger", min_width=72,
                                       on_click=self.on_clear)

        # **按钮排布（用户指定）**：
        #
        #     [打开] ..... [清空] ..... [⚙设置] [📌顶置]
        #      最左         正中          最右（设置紧靠顶置左边）
        #
        # 中途试过一版"清空最左、打开正中"，用户要求换回来：
        # "打开和清空位置还是交换回来吧。"
        #
        # 「切换排序」按钮已被用户要求删除（"没什么用"）；
        # **排序入口没有丢**——列头点击排序一直是好的
        # （`wx.EVT_LIST_COL_CLICK` → `on_column_click`）。
        #
        # 设置按钮是 2026-10-16 加的，位置由用户指定：
        # "把设置按钮放在底部右侧、程序置顶按钮左边"。
        btn_sizer.Add(self.open_btn, 0, 0)
        btn_sizer.AddStretchSpacer()
        btn_sizer.Add(self.clear_btn, 0, 0)
        btn_sizer.AddStretchSpacer()
        self.settings_btn = self._build_icon_button(
            right_panel, "settings.png", L("设置", "Settings"),
            self.on_settings)
        btn_sizer.Add(self.settings_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        btn_sizer.AddSpacer(METRICS.padding_tight)

        self.pin_btn = self._build_pin_button(right_panel)
        btn_sizer.Add(self.pin_btn, 0, wx.ALIGN_CENTER_VERTICAL)

        right_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                        METRICS.padding_gap)
        right_panel.SetSizer(right_sizer)

        splitter.SplitVertically(left_panel, right_panel)
        splitter.SetMinimumPaneSize(METRICS.tree_min_width)
        splitter.SetSashPosition(METRICS.sash_position)

        # **自己画的分隔线。** sash 已被隐藏（见上），那条线改由
        # :class:`~file_tracker.widgets.BorderLine` 画，颜色取
        # ``theme.border``——这样深浅两套主题都跟着走。
        # self.pane_border = BorderLine(splitter, self.theme, vertical=True)

        main_sizer.Add(splitter, 1, wx.EXPAND | wx.ALL, 0)
        panel.SetSizer(main_sizer)

        # 分隔线的位置要跟着 sash 走：拖动、改尺寸、切主题都要重摆
        splitter.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGED, self._on_sash_moved)
        splitter.Bind(wx.EVT_SIZE, self._on_sash_moved)

        self._apply_initial_size()
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_press)

        self.Layout()
        # 布局走完才有真实的 sash 位置，这时摆分隔线
        self._position_pane_border()
        self.Refresh()

        self.adjust_column_widths()
        self.center_frequency_column()
        self.list_ctrl.Bind(wx.EVT_SIZE, self._on_list_resized)

    def _build_pin_button(self, parent):
        """构造顶置开关按钮。

        `_pin_is_text_button` 是给"图片缺失时退化成文字按钮"留的标记，
        测试与验证脚本靠它区分两种形态。
        """
        button = self._build_icon_button(
            parent, "pin_grey.png", L("顶置", "Pin"), self.on_always_on_top)
        self._pin_is_text_button = isinstance(button, RoundedButton)
        return button

    def _build_icon_button(self, parent, png_name: str, fallback_label: str,
                           handler):
        """构造一个图标按钮，**图片加载失败时退化成文字按钮**。

        ## 为什么必须有退化路径

        原来的写法会让"资源没找到"表现为"这里什么都没有"——
        用户看到的是一个空白的、也点不动的方块。退化成文字按钮，
        功能至少还在，而且"图标没加载"这件事是看得见的。

        ## 三个踩过的点，都还在

        1. **图标尺寸必须过 DPI。** 原来写死的 28 在 175% 缩放下偏大。
        2. **用 `self` 而不是 `parent` 算 DPI。** parent 此时可能还没绑定到
           顶层窗口，`FromDIP` 会退回 96（踩过：按钮因此变成 42 像素高）。
        3. **回调必须在这里传进去。** 曾经只造了控件、没有绑任何东西，
           于是"画得好好的、点了没反应"——用户报的"功能本身都失效了"。

        顶置与设置两个按钮**共用这一份实现**：原来只有顶置有这段逻辑，
        再抄一遍给设置就是把上面三个坑各踩第二次。
        """
        bitmap = self.load_bitmap(png_name)
        if bitmap is None:
            return RoundedButton(parent, fallback_label, self.theme,
                                 min_width=64, on_click=handler)

        dpi = dpi_of(self)
        icon_size = self.calculate_icon_size(
            bitmap.GetSize(), scale_for_dpi(METRICS.icon_target_size, dpi),
        )
        scaled = self.load_bitmap(png_name, icon_size) or bitmap
        side = scale_for_dpi(METRICS.button_height, dpi)
        return IconButton(parent, scaled, self.theme, (side, side),
                          on_click=handler)

    def _apply_initial_size(self) -> None:
        """改动 ①：初始窗口增大 15%，并按显示器工作区夹取。

        1280×720 → 1472×828（用户指定）。

        **为什么还要夹取**：``wx.Display.GetClientArea()`` 返回的是**物理像素**
        （本机实测 175% 缩放下是 2560×1516），而 ``SetSize`` 收的也是物理像素。
        在 1366×768 的笔记本上，1472×828 会超出屏幕——用户只能看到窗口的一部分，
        标题栏还可能被推到屏幕外而无法拖动。

        所以取 ``min(期望, 工作区 - 边距)``：**屏幕够大时就是用户要的 1472×828**
        （本机实测就是原样保留），小屏幕上至少保证整个窗口在屏幕内。

        ``SetSize`` 收的是**含边框与标题栏的整窗尺寸**，所以要把非客户区的高度
        从工作区里扣掉再加回来，否则又会超出去一点点。
        """
        preferred = scaled_window_size()
        work_area = None
        try:
            display = wx.Display(wx.Display.GetFromWindow(self))
            if display.IsOk():
                area = display.GetClientArea()
                if area.width > 0 and area.height > 0:
                    border = self.GetSize().width - self.GetClientSize().width
                    title = self.GetSize().height - self.GetClientSize().height
                    work_area = (area.width - border, area.height - title)
        except Exception:
            work_area = None

        # 边距按 DPI 换算：8 个逻辑像素在 175% 缩放下是 14 个物理像素，
        # 写死 8 的话高 DPI 上窗口会贴着屏幕边缘。
        # 用 dpi_of(self) 而不是 self.FromDIP：见 theme.dpi_of 的说明。
        margin = scale_for_dpi(METRICS.window_margin, dpi_of(self))
        self.SetSize(fit_window_size(preferred, work_area, margin))
        self.Centre()

    def apply_window_theme(self) -> None:
        """把主题应用到窗口本身，以及所有**能被设色**的原生控件。

        Roboc 视觉规范第十节：**客户区、非客户区、DWM 合成的圆角与阴影
        是三套彼此独立的机制**，改了客户区不等于改了整扇窗。
        标题栏必须在窗口显示前声明，否则会先闪一下浅色标题栏。

        ## 深色主题下逐个控件的处理

        用户 2026-10-15 反馈"深色主题下的表现很差"。逐个查清后分三类：

        **① 能设色的**（直接 SetBackgroundColour / SetForegroundColour）：
        窗口客户区、目录树、``wx.ListCtrl`` 的客户区。

        **② 需要走原生接口的**：

        * 列表**表头**：``wx.ListCtrl`` 有 ``GetHeaderCtrl()``，
          可以直接 ``SetHeaderAttr``；再用
          :func:`win32.find_child_window` 找到原生句柄套
          ``DarkMode_Explorer``（微软在资源管理器里用的做法）。
        * **标题栏**由 DWM 绘制，只能 ``DwmSetWindowAttribute``。

        **③ 需要进程级声明的**：滚动条、右键菜单、``MessageBox``。
        它们由系统绘制，逐个控件设色无效——解法是
        :func:`win32.set_process_dark_mode`（`uxtheme.SetPreferredAppMode`），
        **必须在创建窗口之前调用**（见 :meth:`FileTrackerApp.OnInit`）。

        > 这一条曾经被我写成"改不动、已接受的已知代价"。
        > **那不是已知代价，是当时还没找到接口。**
        > 写"做不到"之前先确认自己找过几种办法。

        **④ 非客户区一律设色无效**：`wx.BORDER_*` / `WS_BORDER` /
        `WS_EX_CLIENTEDGE` 画出来的边框属于**非客户区**，由系统绘制，
        `SetBackgroundColour` 对它没有任何作用——只能改**样式位**。
        导航窗格那圈白框就是这么来的（见 ``InitUI`` 里
        ``wx.DIRCTRL_MULTIPLE | wx.BORDER_NONE`` 的说明）。
        """
        dark = self.theme.is_dark
        handle = self.GetHandle()
        win32.apply_rounded_corners(handle, True)
        win32.set_title_bar_dark(handle, dark)

        # ① 目录树：**客户区**设色
        #
        # 注意这里只能管客户区。那只 2 像素的边框属于**非客户区**，
        # 设色对它无效，靠 `wx.BORDER_NONE` 从样式上去掉（见 InitUI）。
        tree = self.dir_ctrl.GetTreeCtrl()
        self.dir_ctrl.SetBackgroundColour(wx.Colour(self.theme.card))
        tree.SetBackgroundColour(wx.Colour(self.theme.card))
        tree.SetForegroundColour(wx.Colour(self.theme.text))

        # 内层原生树还带 ``WS_EX_CLIENTEDGE``（另一圈系统绘制的边框），
        # 也属于非客户区，一并去掉。
        self._remove_tree_client_edge()

        # 自绘分隔线也跟着主题换色
        border_line = getattr(self, "pane_border", None)
        if border_line is not None:
            border_line.apply_theme(self.theme)
            self._position_pane_border()

        # ① 列表客户区
        self.list_ctrl.SetBackgroundColour(wx.Colour(self.theme.card))
        self.list_ctrl.SetForegroundColour(wx.Colour(self.theme.text))

        # ② 表头
        self._theme_header(dark)

        # ② 滚动条 / 原生边框：套 Explorer 的深色样式
        #
        # 注意：``wx.ListCtrl`` **没有** ``GetHeaderCtrl()``（只有
        # ``SetHeaderAttr``）。要拿表头的原生句柄，只能自己去找子窗口。
        theme_name = "DarkMode_Explorer" if dark else None
        win32.set_window_theme(self.list_ctrl.GetHandle(), theme_name)
        native_header = win32.find_child_window(self.list_ctrl.GetHandle(),
                                                "SysHeader32")
        if native_header:
            win32.set_window_theme(native_header, theme_name)
        tree_native = win32.find_child_window(handle, "SysTreeView32")
        if tree_native:
            win32.set_window_theme(tree_native, theme_name)

        self._apply_list_spacing()
        self.list_ctrl.Refresh()
        self._hide_native_header()
        self._sync_header()

    def _on_sash_moved(self, event) -> None:
        """把自绘分隔线摆到 sash 所在的位置。

        **不能只靠分割条自己的事件。** 实测
        （`tools/probes/probe_sash_drag.py`）：调 ``SetSashPosition(520)``
        之后 ``EVT_SPLITTER_SASH_POS_CHANGED`` 与 ``..._CHANGING``
        **一个都没来**——那次只有 ``FRAME_SIZE`` 来了，于是线留在旧位置
        （sash 520、线还在 399）。

        所以除了这里，``on_window_resize`` 里也摆一次；
        两条路都走，线才不会落后。
        """
        self._position_pane_border()
        if event is not None:
            event.Skip()

    def _position_pane_border(self) -> None:
        """按当前 sash 位置摆放那条自绘分隔线。幂等，可重复调用。"""
        border = getattr(self, "pane_border", None)
        splitter = getattr(self, "splitter", None)
        if border is None or splitter is None:
            return
        thickness = max(border.GetMinSize().width, 1)
        # 线骑在 sash 位置上（左右各占一半）
        x = splitter.GetSashPosition() - thickness // 2
        height = splitter.GetClientSize().height
        border.SetSize(x, 0, thickness, height)
        border.Refresh()

    def _enable_tree_row_highlight(self, tree) -> bool:
        """让目录树的选中项**铺满整行**（Win11 资源管理器的观感）。

        用户反馈："导航窗格空白部分无法选中。"

        ## 那条"空白"本来就不该能选中

        实测（`tools/probes/probe_tree_blank.py`）：条目的最后一个像素
        在 y=811，而客户区高 830——**下面 19 像素是真正的空白**。
        `SysTreeView32` 在无节点处点击**不会选中任何东西**，这是原生行为，
        资源管理器也一样（点文件夹列表下方的空白不会选中文件夹）。
        **所以不去"修"它**——加一个假的点击行为只会与系统不一致。

        能改善的是**选中状态不够显眼**：加 ``wx.TR_FULL_ROW_HIGHLIGHT``，
        选中项从"只有文字有底色"变成"整行一条底色"，
        与资源管理器一致，也让"我选中了哪个"一目了然。
        """
        try:
            style = tree.GetWindowStyleFlag()
            if style & wx.TR_FULL_ROW_HIGHLIGHT:
                return True
            tree.SetWindowStyleFlag(style | wx.TR_FULL_ROW_HIGHLIGHT)
            tree.Refresh()
            return True
        except Exception as error:
            self._report_resource_error(L(f"设置目录树整行高亮失败：{error}",
                f"Could not enable full-row highlight: {error}"))
            return False

    def _remove_tree_client_edge(self) -> bool:
        """去掉导航窗格内层原生树的 ``WS_EX_CLIENTEDGE``。

        实测（`tools/probes/probe_sash_border.py`）：``GenericDirCtrl``
        内层的 ``SysTreeView32`` 带着 ``WS_EX_CLIENTEDGE``（``0x00000200``）——
        那是 **Windows 按系统主题绘制的下凹边框**，属于**非客户区**，
        ``SetBackgroundColour`` 对它无效。

        ## 但它不是那圈白框的真正来源

        去掉它之后用户反馈"白色框线还在"。**真正的原因是
        ``wx.GenericDirCtrl`` 自己那 2 像素非客户区边框**，
        靠 ``wx.BORDER_NONE`` 解决（见 ``InitUI`` 里的实测表）。

        这条**保留**是因为它确实去掉了另一圈多余的边
        （``WS_EX_CLIENTEDGE`` 会让树看起来是下凹的）。失败时记日志，不静默。
        """
        tree = self.dir_ctrl.GetTreeCtrl()
        if tree is None or not tree.GetHandle():
            return False
        if win32.remove_client_edge(tree.GetHandle()):
            return True
        self._report_resource_error(
            L("去掉导航窗格的原生边框失败（WS_EX_CLIENTEDGE）——"
              "深色主题下它会显示为一圈白线。",
              "Could not remove the navigation pane's native border "
              "(WS_EX_CLIENTEDGE) — it shows as a white ring in dark mode.")
        )
        return False

    def _hide_native_header(self) -> None:
        """确认原生表头**不占位置**。

        ``wx.LC_NO_HEADER`` 已在 ``wx.ListCtrl`` 构造时拼进 style
        （见 ``InitUI``），表头因此不再占布局空间。

        **判据是"第一行的 y 坐标接近 0"，不是"表头窗口看不见"。**
        用户点破过我的一个错误判断：我拿"深色下只数到一条顶栏"当作
        "没有双重顶栏"的证据，但那是因为深色下表头反色错了（白字浅底）
        根本看不见——**把渲染 bug 当成了功能正确**。
        表头窗口本身依然存在（``SysHeader32`` 会被创建），
        所以"窗口在不在""可不可见"都不是判据，**占不占位置**才是。

        这个方法只是保险：真的发现有残留空间就再藏一次表头窗口。
        """
        handle = self.list_ctrl.GetHandle()
        if not handle:
            return
        if self._header_reserves_space():
            win32.hide_child_window(handle, "SysHeader32")
            wx.CallLater(60, self._hide_native_header_now)

    def _header_reserves_space(self) -> bool:
        """原生表头是否还在占用列表顶部的空间。

        用"第一行相对客户区的 y 坐标"判断：表头不占位时它是 0。
        行数为 0 时退回查表头窗口的矩形高度。
        """
        try:
            if self.list_ctrl.GetItemCount() > 0:
                return self.list_ctrl.GetItemRect(0).y > 2
            handle = self.list_ctrl.GetHandle()
            native = win32.find_child_window(handle, "SysHeader32")
            if not native:
                return False
            return win32.window_height(native) > 0
        except Exception:
            return False

    def _hide_native_header_now(self) -> None:
        """保险的后半段：``Show()`` 之后再看一眼是否仍占位置。"""
        if not self._header_reserves_space():
            return
        handle = self.list_ctrl.GetHandle()
        win32.hide_child_window(handle, "SysHeader32")
        self._report_resource_error(
            L("原生表头仍在占用列表顶部空间——自绘表头下方会多出一条空白。",
                  "The native header still occupies space at the top of the "
                  "list — a blank strip appears under the self-drawn header.")
        )

    def on_header_clicked(self, column: int) -> None:
        """自绘表头被点击：按该列切换排序方向。

        与原来的 ``wx.EVT_LIST_COL_CLICK`` 等价，只是事件源换成了自绘控件。

        两条接线**共用** :meth:`apply_sort`——排序是同一件事，
        两份实现迟早会在分叉处不一致（本项目已经因为这类重复修过好几次）。
        """
        self.apply_sort(column, toggle=True)

    def _sync_header(self) -> None:
        """把列表的列宽同步给自绘表头，并标出排序列。

        列表改过列宽（``adjust_column_widths``）或改过尺寸之后必须调一次，
        否则自绘表头与下面的列会对不齐。
        """
        header = getattr(self, "header", None)
        if header is None:
            return
        header.sync_from_list(self.list_ctrl)
        header.set_sort_indicator(self.sort_column, self.sort_reverse)

    def _apply_list_spacing(self) -> None:
        """设置列表的扩展样式与行距。

        ## 三个扩展样式，每一个都对应一次真实的用户反馈

        ``LVS_EX_FULLROWSELECT``
            **点击整行任意位置都能选中。** 用户反馈"原本路径记录任意位置都可以
            点击选中，现在只有选中路径记录的文字部分才能点击"——
            就是这个位丢了。没有它时只有文字本身可点，右侧那些列全是死区。

        ``LVS_EX_GRIDLINES``
            用户反馈"每个类别（列）之间的三条间隔线在浅色背景下不可见"。
            **注意：用户后来又说"路径记录之间（上下）不需要间隔线"**——
            他要的是**列与列之间**的竖线，不是行与行之间的横线。
            原生 ``LVS_EX_GRIDLINES`` 是**横竖都画**的，做不到只画竖线。
            所以这里**不开启它**，改由 :meth:`_draw_column_separators`
            在客户区自绘竖线。

        ``LVS_EX_DOUBLEBUFFER``
            减少滚动闪烁。

        ``LVS_EX_TWOCLICKACTIVATE`` —— **预选跟随（热跟踪）**

            用户解释得很准确："假设选中色有两档，高亮和次级高亮，
            鼠标左键单击后为高亮，鼠标移到目标上方不单击为次级高亮，
            这就是预选状态。"

            官方术语这叫 **hot tracking**。去查了
            [Extended List-View Styles](https://learn.microsoft.com/en-us/windows/win32/controls/extended-list-view-styles)，
            两个标志的措辞**完全不同**：

            * ``LVS_EX_TRACKSELECT`` —— "an item is **automatically selected**
              when the cursor remains over the item **for a certain period of
              time**"
            * ``LVS_EX_TWOCLICKACTIVATE`` —— "This style **also enables
              _hot tracking_** ... Hot tracking means that when the cursor moves
              over an item, **it is highlighted but not selected**"

            ## 我第一版用错了标志，用户一眼看出

            我上一版开的是 ``LVS_EX_TRACKSELECT``。用户实测反馈：
            "反应特别慢，有近一秒的延迟，这是严重的性能问题，说明方法不对。"

            **他判断得对。** `TRACKSELECT` 是**带定时器**的
            （`LVM_SETHOVERTIME` / 系统默认 `SPI_GETMOUSEHOVERTIME`），
            而且悬停久了会**真的选中**——把"预选"和"选中"混成了一档，
            正好是用户说的"两档"里少掉的那一档。

            正确的做法是 `TWOCLICKACTIVATE`：它带来热跟踪，
            且**只高亮、不选中**，于是"两档"天然分开：
            预选由控件画、选中由我们的 `_apply_selection_highlight` 画。

            ## 为什么不用 `LVS_EX_ONECLICKACTIVATE`

            它同样 "also enables hot tracking"，但会把**单击**变成激活
            （直接打开文件夹），改掉用户习惯的单击选中。用户要求的是
            "双击/打开"才打开，所以取两击那一档。

            > 悬停是**热跟踪**，只在真实鼠标移动时生效；
            > `SendMessage(WM_MOUSEMOVE)` 模拟不出来。自动化只能验证
            > "样式位开了、且没带来副作用"，**预选的观感要人眼确认**。

        ## 行距

        ``LVM_SETITEMSPACING`` 的 ``lparam`` 是 ``MAKELPARAM(cx, cy)``：
        取 -1 表示该维不变，所以只加高度。
        """
        handle = self.list_ctrl.GetHandle()
        if not handle:
            return

        # **FULLROWSELECT 必须开**，否则点空白处选不中行。
        win32.set_extended_style(
            handle,
            win32.LVS_EX_FULLROWSELECT | win32.LVS_EX_DOUBLEBUFFER,
        )
        # 网格线：**只保留竖线**由自绘负责，这里确保原生横线是关的
        win32.clear_extended_style(handle, win32.LVS_EX_GRIDLINES)
        # **原生热跟踪全部关掉——预选由本项目自绘。**
        #
        # 三个标志都被排除，理由各不同（顺序就是我踩坑的顺序）：
        #
        # * `LVS_EX_TRACKSELECT` —— "悬停一段时间后自动**选中**"。
        #   带定时器 → 用户实测"反应特别慢"；而且它把"预选"和"选中"
        #   混成一档，不是用户要的两档。
        # * `LVS_EX_TWOCLICKACTIVATE` / `LVS_EX_ONECLICKACTIVATE` ——
        #   官方说它们 "also enables hot tracking"，但我换上之后
        #   **用户实测浅色主题依旧没有预选**（深色有）。
        #   热跟踪的绘制随主题而变，第三方既拿不到也改不了那个颜色。
        #   所以不再依赖它，改用 `_apply_selection_highlight` 自绘
        #   （颜色取 `theme.row_hover`，两个主题必然一致）。
        #
        # `ONECLICKACTIVATE` 另外还会把单击变成直接打开，**更要关**。
        win32.clear_extended_style(
            handle,
            win32.LVS_EX_TRACKSELECT
            | win32.LVS_EX_TWOCLICKACTIVATE
            | win32.LVS_EX_ONECLICKACTIVATE,
        )
        leftover = win32.get_extended_style(handle) & (
            win32.LVS_EX_TRACKSELECT
            | win32.LVS_EX_TWOCLICKACTIVATE
            | win32.LVS_EX_ONECLICKACTIVATE)
        if leftover:
            self._report_resource_error(
                L(f"列表扩展样式没清干净（{leftover:#x}）——"
                  "热跟踪会让预选色随主题而变，"
                  "ONECLICKACTIVATE 还会让单击直接打开",
                  f"List extended styles not cleared ({leftover:#x}) — "
                  "hot tracking makes the hover colour theme-dependent, "
                  "and ONECLICKACTIVATE opens on a single click"))

        dpi = dpi_of(self)
        extra = scale_for_dpi(METRICS.list_item_extra_height, dpi)
        if not win32.set_item_spacing(handle, -1, extra):
            self._report_resource_error(L("设置列表行距未生效（LVM_SETITEMSPACING）",
                                              "Row spacing was not applied (LVM_SETITEMSPACING)"))
        # 行距变了，竖线要按新行高重画
        self._draw_column_separators()

    def _draw_column_separators(self) -> None:
        """在列表**数据行**里画列与列之间的竖线。

        ## 这里曾经是一个空头支票

        上面的 :meth:`_apply_list_spacing` 早就写了"改由
        ``_draw_column_separators`` 在客户区自绘竖线"——
        **但那个方法我一直没写**。结果就是：

        * 表头里有竖线（``header.py`` 画的）
        * **数据行里一条都没有**
        * 用户改 `theme.separator` 的颜色**当然没有可见变化**

        用户为此反馈了三次"列分隔线不可见"。**根因不是颜色，是线根本不存在。**

        > 教训：注释里写"改由 X 负责"之后，**必须确认 X 真的存在**。
        > 一句没兑现的注释比没有注释更糟——它会让下一个人（包括我自己）
        > 以为问题已经处理过了。接线检查能抓"方法没人调用"，
        > 但抓不住"注释里提到了一个不存在的方法"。

        ## 为什么用 ``CallAfter``

        `wx.ListCtrl` 是原生控件：它的行由**系统**绘制，
        在 ``EVT_PAINT`` 里画会被系统随后覆盖。
        所以排在本次绘制**之后**再画（``CallAfter``），并且只画可见区域。
        """
        wx.CallAfter(self._paint_column_separators)

    def _paint_column_separators(self) -> None:
        """真正落笔：按当前列宽在可见行区域画竖线（**只画竖线，不画横线**）。"""
        if not getattr(self, "show_column_separators", True):
            return
        try:
            handle = self.list_ctrl.GetHandle()
            if not handle:
                return
            # **物理像素，不按 DPI 缩放** —— 与 `header.separator_thickness()`
            # 同一规则。用户要求"最细"，1 物理像素已是极限；
            # 若按 DPI 换算，本机 175% 下会变成 2（正是嫌粗的那个）。
            thickness = max(int(METRICS.separator_thickness), 1)
            client = self.list_ctrl.GetClientSize()
            if client.width <= 0 or client.height <= 0:
                return

            # 四条列宽（PathBar 之外的都算上）
            widths = [
                self.list_ctrl.GetColumnWidth(i)
                for i in range(self.list_ctrl.GetColumnCount())
            ]
            if len(widths) < 2:
                return

            # 可见行的范围：避开顶部（表头已隐藏，所以从 0 开始）
            top = 0
            bottom = client.height
            dc = wx.ClientDC(self.list_ctrl)
            dc.SetPen(wx.Pen(wx.Colour(self.theme.separator), thickness))
            x = 0
            for index, width in enumerate(widths[:-1]):
                x += width
                if x <= 0 or x >= client.width:
                    continue
                dc.DrawLine(x - thickness, top, x - thickness, bottom)
        except Exception:
            # 自绘失败不该让整个列表坏掉
            pass

    def _theme_header(self, dark: bool) -> bool:
        """给自绘表头配色。

        **不再碰原生表头**——实测 ``SetHeaderAttr()`` 与 ``SetWindowTheme``
        在深色主题下都不生效（`tools/probes/probe_round6.py`、
        `probe_header_dark_route.py`）。表头由
        :class:`~file_tracker.header.ColumnHeader` 自己画，颜色直接来自主题，
        所以这里只需要让它重画。
        """
        header = getattr(self, "header", None)
        if header is None:
            return False
        header.theme = self.theme
        header.SetBackgroundColour(wx.Colour(self.theme.surface_alt))
        header.Refresh()
        return True

    def center_frequency_column(self) -> bool:
        """改动 ③：确认"频次"列的数字是居中的。

        **判据是"最宽的频次值与列宽的关系"**，不是调用某个 API 有没有报错。
        原生 ``LVM_SETCOLUMN`` 在本环境上完全不可用
        （见 :meth:`_center_text`），所以居中靠补前导空格实现。
        这里算出一份"当前最大位数"供 :meth:`_center_text` 使用，
        并确认列宽装得下。
        """
        self._center_field_width = max(
            (len(str(r.access_count)) for r in self._rows), default=1,
        )
        column = COLUMN_COUNT
        needed = self.list_ctrl.GetTextExtent("8" * self._center_field_width).width + 20
        current = self.list_ctrl.GetColumnWidth(column)
        if current < needed:
            self.list_ctrl.SetColumnWidth(column, needed)
            return True
        return True

    def adjust_column_widths(self) -> None:
        """按内容与可用宽度重算各列宽度（原版逻辑，列数从 3 增到 4）。"""
        list_width = self.list_ctrl.GetSize().width
        if list_width <= 0:
            return

        extent = self.list_ctrl.GetTextExtent

        def fitted(column: int, header: str, extra: int = 40) -> int:
            """列宽 = max(表头宽, 各单元格宽) + 边距。"""
            widths = [extent(header).width]
            for row in range(self.list_ctrl.GetItemCount()):
                widths.append(extent(self.list_ctrl.GetItemText(row, column)).width)
            return max(widths) + extra

        # 列宽按**当前语言**的表头量。`COLUMNS` 里现在只有宽度与居中标记，
        # 标题要从 `column_labels()` 取——用 `COLUMNS[i][0]` 会拿到一个整数
        # （实测报 `GetTextExtent(): argument 1 has unexpected type 'int'`）。
        labels = column_labels()
        frequency_width = fitted(COLUMN_COUNT, labels[COLUMN_COUNT])
        date_width = fitted(COLUMN_DATE, labels[COLUMN_DATE])
        clock_width = fitted(COLUMN_CLOCK, labels[COLUMN_CLOCK])

        self.list_ctrl.SetColumnWidth(COLUMN_COUNT, frequency_width)
        self.list_ctrl.SetColumnWidth(COLUMN_DATE, date_width)
        self.list_ctrl.SetColumnWidth(COLUMN_CLOCK, clock_width)

        # 路径列吃掉剩下的宽度，但保留一个可读的下限（原版是 300）
        path_min_width = 300
        fixed_total = frequency_width + date_width + clock_width
        path_width = max(list_width - fixed_total - 24, path_min_width)
        self.list_ctrl.SetColumnWidth(COLUMN_PATH, path_width)
        # 列宽变了，自绘表头必须跟着同步，否则与下面的列对不齐
        self._sync_header()
        # **列间竖线也要按新列宽重画**（它画在行的客户区上，不随列宽自动更新）
        self._draw_column_separators()

    def _on_list_resized(self, event) -> None:
        self.adjust_column_widths()
        event.Skip()

    def _painted_widgets(self) -> list:
        """本项目里所有自绘控件。

        它们派生自 ``wx.Control`` 而不是 ``wx.Button``，**wx 的字体传播
        不覆盖它们**（传播走的是 `wx.Button` / `wx.StaticText` / `wx.TextCtrl`
        那几条显式调用），所以要单独 `SetFont`。
        """
        widgets = []
        for name in ("open_btn", "clear_btn", "pin_btn", "path_bar"):
            widget = getattr(self, name, None)
            if widget is not None:
                widgets.append(widget)
        return widgets

    def _apply_body_font(self) -> None:
        """把 body 字号应用到"窗口默认字体"以及三类控件上。

        原版（v1.1 L709-714）就是这四行。**列表不在其中**——
        所以列表与列头用的是系统默认字体，这是原版的观感，
        不是疏漏，不要"顺手补上"。
        """
        body = self.body_font
        self.SetFont(body)
        wx.Button.SetFont(self, body)
        wx.StaticText.SetFont(self, body)
        wx.TextCtrl.SetFont(self, body)

    def set_global_font(self) -> None:
        """全局字体：**与原版 1.1 完全一致**。

        ## 这里踩过一次，用户直接看出来了

        原版是：

        ```python
        self.SetFont(new_font)              # 设"本窗口默认字体"，向子控件传播
        wx.Button.SetFont(self, new_font)
        wx.StaticText.SetFont(self, new_font)
        wx.TextCtrl.SetFont(self, new_font)
        ```

        **关键点：列表控件不在那三行里。** 所以原版的列表与它的列头用的是
        **系统默认字体**（9pt），只有按钮/标签/输入框是 +1（10pt）。

        我第一版把 `self.SetFont(new_font)` 保留着，于是字体传播到**所有**
        子控件，列头也变成 10pt——用户反馈"我明明规定了字体，为什么变更了
        ……现在它们的字体好难看"，就是这个。

        ## 顺序上的坑

        窗口级 `SetFont` 会传播给**当时已存在**的子控件。所以必须：

        1. 先确认界面已经建好（`InitUI` 已跑过）
        2. 再 `SetFont(body)` 让传播发生
        3. **最后**把列表按回系统字体

        把第 3 步放在第 2 步之前，"回退"会立刻被传播覆盖——
        实测列表字体一直是 10pt，"我明明设了却没生效"。

        ## 自绘控件要单独处理

        按钮等自绘控件用的是 `wx.Control`，wx 的字体传播不覆盖它们，
        所以显式 `SetFont` 一遍（见 :meth:`_apply_body_font`）。
        """
        default_font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        body = wx.Font(
            default_font.GetPointSize() + 1,
            default_font.GetFamily(),
            default_font.GetStyle(),
            wx.FONTWEIGHT_NORMAL,
            False,
            default_font.GetFaceName(),
        )
        self.body_font = body

        wx.SystemOptions.SetOption("msw.staticbox.optimized-paint", 0)
        self._apply_body_font()

        # 列表退回到"系统默认 + list_font_point_delta"。
        #
        # 原版列表用的是系统默认字体（9pt）；用户反馈"路径记录的字体请增加 1pt"，
        # 所以这里是 9+1=10pt。**它和 body_font（也是 10pt）是两条独立的链**：
        # body_font 服务按钮/标签/输入框，这个服务列表——不要合并，
        # 否则以后单独调列表字号又会牵动按钮。
        if getattr(self, "list_ctrl", None) is not None:
            list_font = wx.Font(
                default_font.GetPointSize() + METRICS.list_font_point_delta,
                default_font.GetFamily(),
                default_font.GetStyle(),
                wx.FONTWEIGHT_NORMAL,
                False,
                default_font.GetFaceName(),
            )
            self.list_ctrl.SetFont(list_font)
            self.list_ctrl.Refresh()

        # 自绘控件不受传播影响，显式应用
        for widget in self._painted_widgets():
            widget.SetFont(body)
            widget.Refresh()

        # 地址栏输入框用**正文**字号（**必须在 body 确定之后再设**，
        # 否则基准偏小——实测会算成 8pt 而不是 10pt）
        path_bar = getattr(self, "path_bar", None)
        if path_bar is not None:
            path_bar.apply_body_font(body)

    # ------------------------------------------------------------------
    # 目录树
    # ------------------------------------------------------------------

    def restore_scroll_position(self) -> None:
        try:
            v_relative = self.config.get_scroll_position()
            if v_relative <= 0:
                return
            tree = self.dir_ctrl.GetTreeCtrl()
            total_height = tree.GetScrollRange(wx.VERTICAL)
            v_pos = int(v_relative * total_height)
            self.ignore_scroll_events = True
            self.initial_scroll_position = v_pos
            tree.SetScrollPos(wx.VERTICAL, v_pos)
            tree.Refresh()
            wx.CallLater(50, self.finalize_scroll_restore)
        except Exception as error:
            self._report_resource_error(L(f"恢复滚动位置时出错: {error}",
                              f"Could not restore the scroll position: {error}"))

    def finalize_scroll_restore(self) -> None:
        tree = self.dir_ctrl.GetTreeCtrl()
        if tree.GetScrollPos(wx.VERTICAL) != self.initial_scroll_position:
            tree.SetScrollPos(wx.VERTICAL, self.initial_scroll_position)
            tree.Refresh()
        self.ignore_scroll_events = False

    def save_scroll_position(self) -> None:
        tree = self.dir_ctrl.GetTreeCtrl()
        total_height = tree.GetScrollRange(wx.VERTICAL)
        v_pos = tree.GetScrollPos(wx.VERTICAL)
        self.config.set_scroll_position(v_pos / total_height if total_height > 0 else 0.0)

    def on_scroll(self, event) -> None:
        if self.ignore_scroll_events:
            return
        if self.scroll_timer:
            self.scroll_timer.Stop()
        self.scroll_timer = wx.CallLater(200, self.save_scroll_position)
        event.Skip()

    def on_list_scroll(self, event) -> None:
        """列表滚动后重画列间竖线。

        竖线是画在客户区上的**一层覆盖**，原生控件滚动/重绘时会把它擦掉，
        所以每次滚动都要补画一次。
        """
        event.Skip()
        self._draw_column_separators()

    def on_list_paint(self, event) -> None:
        """列表重绘后补画竖线（选中变化、数据刷新等都会走到这里）。"""
        event.Skip()
        self._draw_column_separators()

    def reset_dir_ctrl_scroll(self) -> None:
        tree = self.dir_ctrl.GetTreeCtrl()
        wx.CallAfter(self._do_reset_horizontal_scroll, tree)

    def _do_reset_horizontal_scroll(self, tree) -> None:
        tree.SetScrollPos(wx.HORIZONTAL, 0)
        first_visible = tree.GetFirstVisibleItem()
        if first_visible.IsOk():
            tree.EnsureVisible(first_visible)
        tree.Refresh()

    # ------------------------------------------------------------------
    # 改动 ④：路径栏
    # ------------------------------------------------------------------

    def on_path_submitted(self, raw_path: str) -> None:
        """地址栏回车的处理。

        流程：规范化 → 判断存在性（纯逻辑，见 :func:`build_walk_plan`）
        → 展开树到该路径 → **打开资源管理器** → **记一次访问**。

        "计入频次"是用户 2026-10-15 明确的选择：**输入并回车与双击完全等同**。
        所以这里调用 :meth:`record_accessed_path` 与 :meth:`open_folder`，
        与双击列表项走的是同两个方法——两条路径分头维护迟早会不一致。

        **"打开资源管理器"这一步原来漏了。** 用户反馈"回车后只是在左边的
        导航窗格中定位了，并没有真正打开 Explorer 窗口并完成记录，
        还要用户手动点'打开'"。原实现只做了 `reveal_in_tree` + `record_accessed_path`，
        少了 `open_folder`——而地址栏的语义就是"去这个地方"。
        """
        plan = build_walk_plan(raw_path, self.last_directory)

        if plan["status"] == "empty":
            self.path_bar.focus()
            return

        if plan["status"] == "missing":
            self._notify(plan["hint"], L("路径不存在", "Path not found"))
            self.path_bar.focus()
            return

        folder = plan["folder"]
        # 用户的输入是文件夹还是文件，都记"实际访问的那个文件夹"——
        # 与 on_dir_item_activated 对文件的处理保持一致
        self.reveal_in_tree(folder, plan)
        self.open_folder(folder)
        self.record_accessed_path(folder)
        self.path_bar.set_value(folder)
        self.path_bar.select_all()

    def reveal_in_tree(self, folder: str, plan: dict | None = None) -> bool:
        """展开目录树到 ``folder`` 并选中它。

        :return: 是否在树里找到了对应节点（找不到时已尽力展开并给出兜底选择）
        """
        tree = self.dir_ctrl.GetTreeCtrl()
        names = (plan or build_walk_plan(folder, self.last_directory))["names"]

        self.dir_ctrl.Freeze()
        try:
            walker = TreeWalker(tree)
            item = walker.find_by_names(names)
            if item is not None and not item.IsOk():
                item = None

            if item is None:
                # 逐级匹配失败：可能树的层级与盘符假设不一致。
                # 在已展开部分按完整路径兜底扫描一次。
                item = walker.bfs_find_by_path(folder, self.dir_ctrl.GetPath)

            if item is None:
                item = self._reveal_by_ancestor(tree, folder)

            if item is None or not item.IsOk():
                return False

            tree.Expand(item)
            # **必须先 UnselectAll。** 目录树带了 wx.DIRCTRL_MULTIPLE，
            # 是**多选**控件，而 SelectItem 在多选树上是"追加"而不是"替换"：
            # 不清空的话，树里原有选中项（通常是当前盘符）会一直留着，
            # 于是"导航到某路径"之后有两项同时高亮。
            # 实测见 `tools/probes/probe_multiselect.py` 场景 C。
            tree.UnselectAll()
            # 这一次选中是**程序改的**，不是用户点的。
            # 它不再需要任何"闸门"：`_focus_pane` 只由**用户输入事件**
            # （`EVT_SET_FOCUS` / `EVT_TREE_KEY_DOWN`）改写，而
            # `SelectItem()` 一个都触发不了。完整理由见
            # `on_tree_selection_made`。
            tree.SelectItem(item)
            tree.EnsureVisible(item)
            tree.Refresh()
            return True
        finally:
            self.dir_ctrl.Thaw()

    def _reveal_by_ancestor(self, tree, folder: str):
        """兜底：从"最深的、包含目标路径的已展开祖先"继续逐级展开下去。"""
        anchor, anchor_path = pick_fallback_item(tree, folder, self.dir_ctrl.GetPath)
        if anchor is None:
            return None

        # 从锚点出发，用相对路径继续向下匹配
        remainder = normalize_path(folder)
        if anchor_path and remainder.casefold().startswith(anchor_path.casefold()):
            remainder = remainder[len(anchor_path):].strip("\\")

        walker = TreeWalker(tree)
        current = anchor
        for part in [p for p in remainder.split("\\") if p]:
            # 同样必须先展开再取子项——树是懒加载的
            found = find_child_by_label(walker._children(current, expand=True), part)
            if found is None:
                break
            current = found

        return current

    def on_dir_item_activated(self, event) -> None:
        tree = self.dir_ctrl.GetTreeCtrl()
        item = event.GetItem()
        path = self.dir_ctrl.GetPath(item)

        if os.path.isfile(path):
            folder_to_open = os.path.dirname(path)
            if os.path.exists(folder_to_open):
                self.open_folder(folder_to_open)
                self.record_accessed_path(folder_to_open)
                wx.CallLater(100, self.reset_dir_ctrl_scroll)
            else:
                # **先问用户**（见 confirm_remove_invalid_path）
                self.confirm_remove_invalid_path(folder_to_open)
            event.Veto()
        else:
            event.Skip()

    # ------------------------------------------------------------------
    # 记录与列表
    # ------------------------------------------------------------------

    def record_accessed_path(self, path: str) -> None:
        """记一次访问，并刷新界面。"""
        self.store.record_access(path)
        self.load_accessed_paths()
        self.sort_list_items(self.sort_column)

    def load_accessed_paths(self) -> None:
        """从数据库重建列表：先顶置项，再按频次降序的其余项。"""
        self._rows = self._ordered_records()
        self._render_rows()
        self.adjust_column_widths()

    def _render_rows(self) -> None:
        """把 :attr:`_rows` 画到列表上。

        ``_rows`` 是界面里的**真相来源**：``wx.ListCtrl`` 按行号取值，
        而排序在 Python 这边做，所以排序后行号会变——持有一份有序列表
        比"每次都去控件里读回来"更可靠。

        ## 字体层级

        用户要求"主信息/次要信息区分"：路径用**正文 + 粗体**，
        频次与时间用**小一号 + 次要色**。这三条 ``SetItemTextColour``
        都包在 ``try`` 里——原生控件对项级字体/颜色支持因版本而异，
        不支持时**退化成无层级**，而不是让整个列表画不出来。
        """
        self.list_ctrl.DeleteAllItems()
        pinned_set = set(self.pinned_paths)
        for record in self._rows:
            date_text, clock_text = split_timestamp(record.last_access_time)
            index = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(),
                                              record.path)
            self.list_ctrl.SetItem(index, COLUMN_COUNT,
                                   self._center_text(str(record.access_count)))
            self.list_ctrl.SetItem(index, COLUMN_DATE, date_text)
            self.list_ctrl.SetItem(index, COLUMN_CLOCK, clock_text)
            colour = self.theme.pinned_row if record.path in pinned_set \
                else self.theme.card
            self.list_ctrl.SetItemBackgroundColour(index, wx.Colour(colour))
            try:
                # **整行用纯黑/纯白**（`theme.list_text`）。
                #
                # 用户要求："把所有路径记录条目文字颜色恢复为纯黑（浅色主题）/
                # 纯白（深色主题），灰色实在是不方便观察。"
                #
                # ## 为什么是"整行"而不是"只有路径列"
                #
                # `wx.ListCtrl.SetItemTextColour(item, colour)` 是**按行**的，
                # **没有按列的版本**。实测（`tools/probes/probe_item_colour.py`）：
                #
                #   * 连续两次 `SetItemTextColour(1, ...)` 只有**最后一次**生效
                #   * `wx.ItemAttr.SetTextColour(colour)` 也没有列参数
                #   * 虚拟列表的 `OnGetItemAttr(item)` 同样只有 item、没有 column
                #   * `wx.ListCtrl` 里不存在含 "Column"+"Attr" 的方法
                #
                # 所以做不到"路径列黑、其余列灰"。
                # **这也顺带修掉了一个真 bug**：之前先设路径列、再循环设
                # 频次/日期/时间列，后者把前者**覆盖**了——整行其实都是灰的，
                # 正是用户抱怨的那个"灰"。
                self.list_ctrl.SetItemTextColour(
                    index, wx.Colour(self.theme.list_text),
                )
            except Exception:
                # 项级颜色不被支持时退化成默认色，而不是整个列表画不出来
                pass
        # **重建之后行号全变了，高亮账本必须作废。**
        # 不作废的话，下一次选中会去"恢复"一个已经不存在（或已换成
        # 另一条记录）的行号——用户看到的就是"某一行莫名其妙一直变色"。
        self._highlighted_row = -1
        self.list_ctrl.Refresh()
        # 重建后可能有残留选中，重新套一次高亮
        self._apply_selection_highlight()

    def on_selection_changed(self, event) -> None:
        """选中状态变了 → 重画整行高亮。

        **`event.Skip()` 必须调**：不放手的话原生控件收不到这次事件，
        选中动作本身会被吞掉（那一行根本选不上）。
        """
        event.Skip()
        self._apply_selection_highlight()

    # -- 预选（悬停跟随）--------------------------------------------------

    def on_list_motion(self, event) -> None:
        """鼠标在列表上移动 → 更新"预选"行（次级高亮）。

        ## 为什么自己做，不用原生热跟踪

        用户："假设选中色有两档，高亮和次级高亮，鼠标左键单击后为高亮，
        鼠标移到目标上方不单击为次级高亮，这就是预选状态。"

        原生有热跟踪（`LVS_EX_TRACKSELECT` / `LVS_EX_*CLICKACTIVATE`），
        但实测它的表现**随主题而变**——用户那边"深色有、浅色没有"，
        我换了一轮标志也没修掉。原因大概率是系统按主题取不同的
        热跟踪色，第三方拿不到、也改不了。

        所以改成**自己画**：颜色取 `theme.row_hover`，
        两个主题都是同一个字段说了算，不再有"哪个主题有没有"的问题。

        ## 性能

        用户上一轮指出过"反应特别慢，有近一秒的延迟"。
        这里只在**行号真的变了**的时候才动颜色——
        鼠标在同一行内移动是零成本的，不会每移动一像素就重画整个列表。
        """
        event.Skip()
        try:
            x, y = self.list_ctrl.ScreenToClient(wx.GetMousePosition())
            index, _flags = self.list_ctrl.HitTest((x, y))
            # `HitTest` 越界时会返回上一行的行号，所以要自己核对矩形
            if index != -1:
                rect = self.list_ctrl.GetItemRect(index)
                if not (0 <= y < self.list_ctrl.GetClientSize().height
                        and rect.y <= y < rect.y + rect.height):
                    index = -1
        except Exception:
            return
        self._set_hover_row(index)

    def on_list_leave(self, event) -> None:
        """鼠标离开列表 → 收掉预选高亮。"""
        event.Skip()
        self._set_hover_row(-1)

    def _set_hover_row(self, index: int) -> None:
        """只在行号**真的变了**时改颜色（性能，见 `on_list_motion`）。"""
        if index == getattr(self, "_hover_row", -1):
            return
        self._hover_row = index
        self._apply_selection_highlight()

    def _apply_selection_highlight(self) -> None:
        """一次把**两档**都画对：预选（次级高亮）与选中（高亮）。

        ## 两档的定义（用户原话）

        > 假设选中色有两档，高亮和次级高亮，鼠标左键单击后为高亮，
        > 鼠标移到目标上方不单击为次级高亮，这就是预选状态。

        | 档 | 触发 | 底色 | 文字 |
        |---|---|---|---|
        | 预选（次级高亮） | 鼠标悬停 | `theme.row_hover` | `theme.list_text` |
        | 选中（高亮） | 单击 / 键盘 | `SYS_COLOUR_HIGHLIGHT` = `#0078D7` | `theme.list_text` |

        **选中优先于预选**：鼠标停在被选中的那一行时，看到的仍是选中色。

        ## 为什么整件事都得自己做

        实测（`tools/probes/probe_row_selected_pixels.py`）：选中一行后
        **底色完全不变**（浅色 `#FFFFFF`、深色 `#242424`，与未选中一样）。
        原因是每行都被 `SetItemBackgroundColour` 显式设过，
        **原生高亮就不画了**。

        ## 为什么不另开一本"原始颜色"的账

        底色**按 :attr:`_rows` 与 :attr:`pinned_paths` 现算**
        （顶置行 `pinned_row`、其余 `card`）。
        账本一旦和渲染逻辑不同步，就会留下永远不变色的行——
        这正是最初那个 bug 的成因。

        实测（`tools/probes/probe_row_colour_set.py`）：这样设的颜色
        在选中状态下也保得住（回读 `#0078D7`），取消后也能还原。
        """
        try:
            count = self.list_ctrl.GetItemCount()
            if count <= 0:
                self._highlighted_row = self._hover_row = -1
                return
            selected = self.list_ctrl.GetFirstSelected()
            hovered = getattr(self, "_hover_row", -1)
            if not 0 <= hovered < count:
                hovered = -1

            # **行号没变就什么都不做**——这是性能的关键。
            # 鼠标在同一行内移动、或选中项没动时，不再重画整个列表。
            key = (selected, hovered)
            if key == getattr(self, "_paint_key", None):
                return
            self._paint_key = key

            highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
            hover_colour = wx.Colour(self.theme.row_hover)
            normal_text = wx.Colour(self.theme.list_text)
            pinned_set = set(self.pinned_paths)

            def base_colour(row: int) -> wx.Colour:
                if not 0 <= row < len(self._rows):
                    return wx.Colour(self.theme.card)
                name = (self.theme.pinned_row
                        if self._rows[row].path in pinned_set
                        else self.theme.card)
                return wx.Colour(name)

            # 只重画"受影响的那些行"，不是整表
            touched = {selected, hovered,
                       getattr(self, "_highlighted_row", -1),
                       getattr(self, "_hover_painted", -1)}
            for row in sorted(r for r in touched if 0 <= r < count):
                if row == selected:
                    background, text = highlight, normal_text
                elif row == hovered:
                    background, text = hover_colour, normal_text
                else:
                    background, text = base_colour(row), normal_text
                self.list_ctrl.SetItemBackgroundColour(row, background)
                self.list_ctrl.SetItemTextColour(row, text)
            self._highlighted_row = selected
            self._hover_painted = hovered
            self.list_ctrl.Refresh()
        except Exception as error:
            self._report_resource_error(L(f"设置行高亮失败：{error}",
                              f"Could not apply the row highlight: {error}"))

    def _center_text(self, text: str) -> str:
        # 把公式改成按真实列宽算
        column_px = self.list_ctrl.GetColumnWidth(COLUMN_COUNT)
        text_px   = self.list_ctrl.GetTextExtent(text).width
        space_px  = max(self.list_ctrl.GetTextExtent(" ").width, 1)
        pad = max(column_px - text_px, 0) // space_px // 2
        return " " * pad + text

    def _ordered_records(self) -> list[PathRecord]:
        pinned_order = {path: index for index, path in enumerate(self.pinned_paths)}
        pinned = [r for r in self.store.load_pinned() if r.path in pinned_order]
        pinned.sort(key=lambda r: pinned_order[r.path])
        return pinned + self.store.load_unpinned()

    def row_path(self, row: int) -> str:
        """取某一行的路径；行号越界返回空串。"""
        if row is None or row < 0 or row >= self.list_ctrl.GetItemCount():
            return ""
        return self.list_ctrl.GetItemText(row)

    def selected_path(self) -> str:
        """当前选中行的路径；没有选中返回空串。

        ``wx.ListCtrl`` 是单选的（``LC_SINGLE_SEL``），所以用 ``GetFirstSelected``。
        """
        return self.row_path(self.list_ctrl.GetFirstSelected())

    def find_path(self, path: str) -> int:
        """按路径找行号；找不到返回 -1。"""
        for row in range(self.list_ctrl.GetItemCount()):
            if self.list_ctrl.GetItemText(row) == path:
                return row
        return -1

    def remove_invalid_path(self, path: str) -> None:
        """把一条失效路径从记录里删掉（**不询问**，调用方负责先征得同意）。"""
        index = self.find_path(path)
        if index != -1:
            self.list_ctrl.DeleteItem(index)
        self.store.remove(path)
        if path in self.pinned_paths:
            self.pinned_paths.remove(path)
        self._rows = [r for r in self._rows if r.path != path]
        # **走 `_notify`（单按钮），不要自己建两按钮的确认框。**
        #
        # 用户报的："失效删除确认弹窗有两个按钮，功能完全一致——关闭窗口，
        # 请简化为一个按钮「确定」。"
        #
        # 原来这里直接建了个默认的 `ThemedDialog`，于是它带上了
        # 「好 / 否(N)」两个按钮，而**两个都只是关掉它**——这是一条"已完成"
        # 的通知，不是需要回答的问题。给一个不需要回答的提示配一个
        # "否"按钮，是在骗用户以为还有得选。
        self._notify(
            L(f"路径 '{path}' 已失效，已从记录中删除。",
              f"The path '{path}' no longer exists; it has been removed."),
            L("路径失效", "Path missing"))

    def confirm_remove_invalid_path(self, path: str) -> bool:
        """失效路径：**先问用户**要不要删，返回是否真的删了。

        用户反馈："路径记录窗格中双击/打开一条失效路径，现在我希望把选择权
        交给用户：提示用户，等用户确认是否删除，而不是现在的双击/打开
        就直接删除然后弹窗提示用户已经删除。"

        ## 为什么改成"先问"

        原来的行为是**先删再报**（`remove_invalid_path` 末尾那个
        `_notify`）——用户点一下，记录就没了，只能看到一个"已删除"的通知。
        **不可撤销、且没有问过。** 这与"危险操作要二次确认"这条基本规矩相悖，
        也和本项目里"清空/删除记录"都要确认的做法不一致。

        删除是不可逆的（数据库那一行直接没了），所以必须问。
        """
        dialog = ThemedDialog(
            self, self.theme,
            f"{WARN} "
            + L("这条路径已失效：", "This path no longer exists:")
            + f"\n\n{path}\n\n"
            + L("要从记录中删除它吗？", "Remove it from the records?"),
            title=L("路径已失效", "Path missing"),
            yes_label=L("删除", "Delete"), no_label=L("保留", "Keep"),
        )
        try:
            answer = dialog.ShowModal()
        finally:
            dialog.Destroy()
        if answer != wx.ID_YES:
            # 用户选择保留：什么都不做，包括**不弹**"已删除"的提示
            self.Refresh()
            return False
        self.remove_invalid_path(path)
        self.load_accessed_paths()
        self.sort_list_items(self.sort_column)
        return True

    # ------------------------------------------------------------------
    # 排序
    # ------------------------------------------------------------------

    def on_column_click(self, event) -> None:
        """列头点击：按该列切换排序方向。

        **这是原版 1.1 就有的功能**（``wx.EVT_LIST_COL_CLICK``），
        ``wx.ListCtrl`` 的事件里带 ``GetColumn()``。
        中间一版换成 ``DataViewListCtrl`` 时我把它删了——
        **那是一次功能倒退**，用户实测指出"所有点击功能全部失效"。
        """
        self.apply_sort(event.GetColumn(), toggle=True)

    def apply_sort(self, column: int, *, toggle: bool = False,
                   reverse: bool | None = None) -> bool:
        """切换/设置排序，并**记住**这次选择。返回是否真的改了。

        两个入口都走这里——自绘表头（`on_header_clicked`）与原生表头
        （`on_column_click`，原版 1.1 就有的那条接线）。

        ## 换列时用**那一列自己的**方向

        原来是无条件 `not self.sort_reverse`。只用一个全局方向时，
        "在频次上按了一次升序，再点路径"就会得到 Z→A —— 不是第一眼想要的
        结果。现在每列记住自己的方向，没设过就用该列的默认
        （见 :class:`~file_tracker.core.SortSpec`）。

        ``toggle=True`` 表示"点同一列就翻方向"（表头的行为）；
        设置窗口改方向时传 ``reverse`` 直接指定。
        """
        if column not in (COLUMN_PATH, COLUMN_COUNT, COLUMN_DATE, COLUMN_CLOCK):
            return False
        key = _sort_key_of(column)

        if reverse is not None:
            self.sort_reverse = bool(reverse)
        elif toggle and column == self.sort_column:
            self.sort_reverse = not self.sort_reverse
        elif column != self.sort_column:
            remembered = self.config.get_sort_direction(key)
            spec = find_sort_spec(key)
            self.sort_reverse = (spec.default_reverse
                                 if remembered is None else remembered)
        # 同一列且没要求 toggle、也没给方向 → 什么都不用改

        self.sort_column = column
        self.sort_key = key
        self.sort_list_items(column)
        # 顺手记住：用户刚表达了自己的偏好，下次启动就照这个来。
        self._remember_sort()
        return True

    def _remember_sort(self) -> None:
        """把当前排序写进配置（下次启动就用它）。

        ## 为什么"点表头"也写配置

        用户要的是"能根据自己的习惯调节"。设置窗口是**显式**调节，
        而点表头是**顺手**表达同一个偏好——如果只有设置窗口算数，
        用户点了一整天的路径排序、重启后又被弹回频次排序，
        那正是他抱怨的"太死板"。

        两处都写，谁最后动谁生效，符合直觉。

        ⚠️ **这个方法在这个类里只能有一份。**

        审计查出过它被定义了**两次**（一次在这里、一次在 `on_open` 附近）。
        函数体完全一样，所以行为没出错；但 Python **只用后一个**，
        于是改前一个**不会有任何效果**——而且不报错。
        本模块开头那段"同一功能定义两次、后一个静默生效"的教训，
        就是这么重新长出来的。

        `tests/test_no_duplicate_methods.py` 现在会静态拦住这一类。
        """
        self.config.set_sort_column(self.sort_key)
        self.config.set_sort_direction(self.sort_key, self.sort_reverse)
        try:
            self.config.save()
        except OSError as error:
            self._report_resource_error(
                L(f"无法保存排序偏好: {error}",
                  f"Could not save the sort preference: {error}"))

    def sort_list_items(self, column: int) -> None:
        """排序：顶置项始终在最前（按顶置顺序），其余按所选列排序。

        **排序的入口只有列头点击**（`on_column_click`）。
        原来还有一个「切换排序」按钮（`on_toggle_sort`），
        用户 2026-10-15 要求删掉："没什么用"。已删。

        排序在 Python 侧完成、然后整体重画：``DataViewListCtrl`` 没有
        "交换两行"的接口，而记录量级是几十到几百条，重建比增量维护简单可靠得多。
        """
        from datetime import datetime

        pinned_set = set(self.pinned_paths)
        records = list(self._rows)
        pinned = [r for r in records if r.path in pinned_set]
        unpinned = [r for r in records if r.path not in pinned_set]

        if column == COLUMN_PATH:
            unpinned.sort(key=lambda r: r.path.lower(), reverse=self.sort_reverse)
        elif column in (COLUMN_DATE, COLUMN_CLOCK):
            def time_key(record: PathRecord):
                try:
                    return datetime.strptime(record.last_access_time, TIME_FORMAT)
                except (ValueError, TypeError):
                    # 时间戳格式异常时排到最后，而不是让整个排序抛异常
                    return datetime.min

            unpinned.sort(key=time_key, reverse=self.sort_reverse)
        else:
            unpinned.sort(key=lambda r: r.access_count, reverse=self.sort_reverse)

        pinned.sort(key=lambda r: self.pinned_paths.index(r.path))
        self._rows = pinned + unpinned
        self._render_rows()
        self.adjust_column_widths()
        # 排序会重建全部行，列属性随之重置——重新确认一次居中
        self.center_frequency_column()
        # 排序列变了，自绘表头要更新那个小三角
        self._sync_header()

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------

    def on_list_selection_made(self, event) -> None:
        """记录窗格里**用户操作**了 → 之后的「打开」以它为准。

        绑了两个事件，各有各的必要：

        * ``EVT_LIST_ITEM_SELECTED`` —— 换了选中行
        * ``EVT_SET_FOCUS``          —— 用户点进了列表

        只绑前者会漏掉一种很常见的情况：**点已经选中的那一行**。
        选中没变，`ITEM_SELECTED` 就不发（wx 只在变化时发），
        于是 `_focus_pane` 还停在上一次的 "tree"，按「打开」开的是导航窗格。
        """
        self._focus_pane = "list"
        # 列表还挂着整行高亮的处理（`on_selection_changed`），
        # 不 `Skip()` 会把那次事件吞掉，那一行根本选不上
        event.Skip()

    def on_tree_selection_made(self, event) -> None:
        """导航窗格里选中了某项 → 之后的「打开」以它为准。

        ## 为什么绑的是**用户输入事件**而不是 `EVT_TREE_SEL_CHANGED`

        这是用户第二次报同一个问题之后找到的真正原因。

        `EVT_TREE_SEL_CHANGED` **分不清"用户点的"和"代码改的"**。
        而 :meth:`reveal_in_tree` 会调 ``tree.SelectItem()``
        （地址栏回车、启动时定位上次目录都走那里）。于是：

            ① 用户在记录窗格里选了一条 → `_focus_pane = "list"`   ✅
            ② 程序改树选中 → `SEL_CHANGED` 触发（**可能是迟到的**）
               → `_focus_pane = "tree"`   ❌ 用户的意图被悄悄覆盖
            ③ 按「打开」→ 打开的是导航窗格那一项

        **一个"忽略程序化选中"的布尔闸挡不住它**：wx 的事件可能被推迟到
        闸门落下之后才派发（探针里就抓到过两条迟到的 `SEL_CHANGED`）。

        所以改成绑**只可能由用户输入产生**的那些事件：

        * ``EVT_TREE_ITEM_ACTIVATED`` —— 双击/回车展开
        * ``EVT_TREE_KEY_DOWN``        —— 方向键换选中
        * ``EVT_TREE_ITEM_EXPANDING``  —— 点展开箭头

        ``SelectItem()`` **一个都触发不了**，所以不可能再把用户的意图顶掉。
        这条判据是"事件来源"层面的，不依赖时序——而时序正是前面两次都错的地方。
        """
        self._focus_pane = "tree"
        event.Skip()

    def open_targets(self) -> list[str]:
        """「打开」该打开的路径：**用户最后一次选中的那一处**。

        ## 这一版修的是什么

        用户报的："记录窗格中无论选中哪条记录，「打开」按钮都只会响应左侧
        导航窗格的选中项。"

        原来这里写的是 `self.dir_ctrl.GetPaths()` ——**只看导航窗格**，
        记录窗格里选了什么完全没读。所以右边选哪一条都白选。

        用户要的是"按用户鼠标焦点，即最后一个选中的项目/条目打开"。

        ## 判据为什么是"选中"而不是"焦点"

        `EVT_SET_FOCUS` 看着更直接，但它会撒谎：点列表**空白处**、
        按 Tab、`Show()` 之后焦点都会跳，而用户**选中的东西没变**。
        按焦点决定打开哪个，会在这些时刻突然换目标。

        "选中事件"只在选择真的变了时候来，与用户的意图一致。

        ## 为什么每次只返回**一个**

        打开是"打开这一处"，不是"打开所有选中"。原来那个 `for` 循环
        会一次弹出好几个资源管理器窗口（导航窗格是多选的）——
        那是另一个没人要的行为，一并收掉。

        选中的那一处若为空，**回退到另一处**：用户在右边点了空白取消选中
        之后按「打开」，打开左边选中的目录，比什么都不做合理。
        """
        if self._focus_pane == "list":
            path = self.selected_path()
            if path:
                return [path]
            return [p for p in self.dir_ctrl.GetPaths() if p]
        paths = [p for p in self.dir_ctrl.GetPaths() if p]
        if paths:
            return paths[:1]
        path = self.selected_path()
        return [path] if path else []

    def on_open(self, event) -> None:
        for path in self.open_targets():
            if os.path.exists(path):
                self.record_accessed_path(path)
                self.open_folder(path)
            else:
                # **先问用户**，不再直接删（见 confirm_remove_invalid_path）
                self.confirm_remove_invalid_path(path)
        wx.CallLater(100, self.reset_dir_ctrl_scroll)

    def open_folder(self, path: str) -> None:
        folder_to_open = os.path.dirname(path) if os.path.isfile(path) else path
        self._open_in_explorer(folder_to_open)

    @staticmethod
    def _open_in_explorer(folder: str) -> None:
        """用资源管理器打开一个文件夹。

        取 ``os.startfile`` 而不是 ``subprocess.Popen(f'explorer "{folder}"')``：
        后者经过 shell 解析，**路径里含 ``&`` 或引号时会被当成命令分隔符**，
        而在 Windows 上走 ``ShellExecute`` 既能正确传参，也能复用已打开的窗口。
        """
        try:
            os.startfile(folder)  # noqa: S606 - Windows 专用，且这正是期望行为
        except (OSError, AttributeError):
            subprocess.Popen(["explorer", folder])

    def on_item_activated(self, event) -> None:
        path = self.selected_path()
        if not path:
            return
        if os.path.exists(path):
            self.open_folder(path)
            self.record_accessed_path(path)
            wx.CallLater(100, self.reset_dir_ctrl_scroll)
        else:
            # **先问用户**（见 confirm_remove_invalid_path）
            self.confirm_remove_invalid_path(path)

    def on_open_selected(self, event) -> None:
        path = self.selected_path()
        if not path:
            return
        if os.path.exists(path):
            self.open_folder(path)
            self.record_accessed_path(path)
            wx.CallLater(100, self.reset_dir_ctrl_scroll)
        else:
            # **先问用户**（见 confirm_remove_invalid_path）
            self.confirm_remove_invalid_path(path)

    def _notify(self, message: str, title: str) -> None:
        """弹一个**跟主题一致**的提示框（单按钮）。

        用 :class:`~file_tracker.widgets.ThemedDialog` 而不是
        `wx.MessageBox`——后者是系统对话框，深色主题下永远是浅色面板。

        **只给一个按钮**（`no_label=NO_BUTTON`）。这是一条"已经做完了"的
        告知，不是问题；给不需要回答的提示配一个"否"，会让用户以为还有得选
        ——那正是用户报的"两个按钮功能完全一致"。

        ⚠️ **不能写 `no_label=None`。** `None` 在这套 API 里是"没传，
        用默认的否(N)"，于是弹窗照样有两个按钮——这个坑我踩过，
        `_notify` 一直带着一个多余的「否(N)」，直到用户截图指出。
        所以"不要第二个按钮"必须用一个明确的哨兵值。
        """
        dialog = ThemedDialog(self, self.theme, f"{WARN} {message}",
                              title=title, yes_label=L("好", "OK"),
                              no_label=NO_BUTTON)
        dialog.ShowModal()
        dialog.Destroy()
        self.Refresh()

    def on_copy(self, event) -> None:
        path = self.selected_path()
        if path and wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(path))
            wx.TheClipboard.Close()

    def on_delete_selected(self, event) -> None:
        path = self.selected_path()
        if not path:
            return
        # **用自绘的 ThemedDialog，不用 wx.MessageDialog。**
        #
        # `wx.MessageDialog` 在 Windows 上是**系统对话框**，由系统主题绘制，
        # 深色下永远是浅色面板——用户反馈"警告弹窗的深色主题适配失败"。
        # 系统对话框没有受支持的换肤接口，**只能换成自己画的**。
        dialog = ThemedDialog(self, self.theme,
                              f"{WARN} " + L("确定要删除这条记录吗？", "Delete this record?"),
                              title=L("确认删除", "Confirm delete"))
        if dialog.ShowModal() == wx.ID_YES:
            self.store.remove(path)
            if path in self.pinned_paths:
                self.pinned_paths.remove(path)
            self.load_accessed_paths()
        dialog.Destroy()
        self.Refresh()

    def on_clear(self, event) -> None:
        dialog = ThemedDialog(self, self.theme,
                              f"{WARN} " + L("确定要清空所有记录吗？", "Clear all records?"),
                              title=L("确认清空", "Confirm clear"))
        if dialog.ShowModal() == wx.ID_YES:
            self.store.clear()
            self.list_ctrl.DeleteAllItems()
            self._rows = []
            self.pinned_paths.clear()
            self.adjust_column_widths()
        dialog.Destroy()
        self.Refresh()

    def on_pin(self, event) -> None:
        path = self.selected_path()
        if path and path not in self.pinned_paths:
            self.pinned_paths.insert(0, path)
            self.store.set_pinned(path, True)
            self.sort_list_items(self.sort_column)

    def on_unpin(self, event) -> None:
        path = self.selected_path()
        if path and path in self.pinned_paths:
            self.pinned_paths.remove(path)
            self.store.set_pinned(path, False)
            self.sort_list_items(self.sort_column)

    def on_right_click(self, event) -> None:
        # 右键点在某一行上时，控件会先把它选中；没有选中就不弹菜单
        path = self.selected_path()
        if not path:
            return
        is_pinned = path in self.pinned_paths

        menu = wx.Menu()
        entries = [
            (L("复制路径", "Copy path"), self.on_copy),
            # 顶置与取消顶置共用一格，按当前状态决定绑哪个处理函数
            (L("取消顶置", "Unpin") if is_pinned else L("顶置", "Pin"),
             self.on_unpin if is_pinned else self.on_pin),
            (L("打开", "Open"), self.on_open_selected),
            (L("删除", "Delete"), self.on_delete_selected),
        ]
        for label, handler in entries:
            item = menu.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, handler, item)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_always_on_top(self, event) -> None:
        """切换窗口置顶，并同步按钮图标。"""
        if self.GetWindowStyle() & wx.STAY_ON_TOP:
            self.SetWindowStyle(self.GetWindowStyle() & ~wx.STAY_ON_TOP)
            bitmap_name = "pin_grey.png"
        else:
            self.SetWindowStyle(self.GetWindowStyle() | wx.STAY_ON_TOP)
            bitmap_name = "pin_red.png"

        if getattr(self, "_pin_is_text_button", False):
            self.pin_btn.SetLabel(
                L("取消顶置", "Unpin")
                if self.GetWindowStyle() & wx.STAY_ON_TOP
                else L("顶置", "Pin"))
            return

        bitmap = self.load_bitmap(bitmap_name)
        if bitmap is None:
            return
        dpi = dpi_of(self)
        icon_size = self.calculate_icon_size(
            bitmap.GetSize(), scale_for_dpi(METRICS.icon_target_size, dpi),
        )
        scaled = self.load_bitmap(bitmap_name, icon_size)
        if scaled is not None:
            self.pin_btn.SetBitmap(scaled)

    def on_key_press(self, event) -> None:
        if event.ControlDown() and event.GetKeyCode() == ord("C"):
            # 焦点在路径栏输入框里时，Ctrl+C 是"复制文本"，不是"复制列表路径"
            if not isinstance(wx.Window.FindFocus(), wx.TextCtrl):
                self.on_copy(event)
                return
        if event.ControlDown() and event.GetKeyCode() == ord("L"):
            # Ctrl+L 聚焦路径栏——沿用了浏览器/资源管理器的习惯
            self.path_bar.focus()
            return
        event.Skip()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def on_window_resize(self, event) -> None:
        self.adjust_column_widths()
        # 分隔线也要重摆：分割条自己的事件不一定会来（实测），
        # 而窗口尺寸事件是可靠的
        self._position_pane_border()
        event.Skip()

    def on_activate(self, event) -> None:
        """窗口被激活时重读系统主题，并重绘自绘控件。

        系统主题可以在程序运行期间被改掉；**不自绘的控件会自动跟随，
        自绘的不会**——这正是"改了系统主题但按钮还是旧配色"的来源。
        """
        new_theme = theme_from_system()
        if new_theme != self.theme:
            self.theme = new_theme
            self._retheme()
        self.Refresh()
        for button in (self.open_btn, self.clear_btn, self.path_bar):
            if hasattr(button, "Refresh"):
                button.Refresh()
        wx.CallAfter(self.reset_dir_ctrl_scroll)
        event.Skip()

    def _retheme(self) -> None:
        """系统主题变了之后重新上色。

        **自绘控件不会自己跟随系统主题**——这正是"改了系统主题但按钮还是
        旧配色"的来源。所以这里显式地把新配色推给每一个自绘控件，
        并重画列表（行底色是按当前配色算出来的）。
        """
        self.SetBackgroundColour(wx.Colour(self.theme.background))
        for child in (self.open_btn, self.clear_btn):
            child.apply_theme(self.theme)
        self.path_bar.apply_theme(self.theme)
        self.apply_window_theme()
        self._render_rows()
        self.Layout()
        # apply_window_theme 里已经重摆过分隔线，但 Layout 可能又改了尺寸，
        # 所以这里再摆一次（幂等，代价是两次 SetSize）
        self._position_pane_border()

    def on_settings(self, event) -> None:
        """打开设置窗口；用户点确定且语言变了就**立刻**生效并持久化。

        ## 为什么"立刻生效"值得做

        让用户"改完重启才看到英文"是最省事的做法，但那等于没验证——
        他看不到自己选的东西，也就无从判断选对没有。
        Roboc 切换语言时是即时重画的（`SettingsWindow` 里改完
        `Lang.Apply` 直接 `Invalidate`），这里跟随同样的做法。
        """
        # 当前生效值：配置里存过就用存的，没存过就是系统检测出来的那个。
        before = self.config.get_language() or (
            PREFERENCE_CHINESE if is_chinese() else PREFERENCE_ENGLISH)
        dialog = SettingsDialog(self, self.theme, before,
                               sort_key=self.sort_key,
                               sort_reverse=self.sort_reverse)
        # 把各列"上次用的方向"灌进去，这样在窗口里换列时能带出那一列自己的
        # 方向，与点表头的行为一致（见 `SettingsDialog._choose_sort`）。
        for spec in SORT_SPECS:
            remembered = self.config.get_sort_direction(spec.key)
            if remembered is not None:
                dialog._sort_directions[spec.key] = remembered
        try:
            if dialog.ShowModal() != wx.ID_YES:
                return
            chosen = dialog.selected_preference()
            sort_key, sort_reverse = dialog.selected_sort()
        finally:
            dialog.Destroy()

        language_changed = chosen != before
        self.config.set_language(chosen)
        if language_changed:
            # `apply_language` 必须在 `retranslate` 之前——
            # retranslate 里每一次 `L(...)` 读的都是它刚设下的那个值。
            apply_language(chosen)

        # **排序**交给 `apply_sort`：它自己写配置（见 `_remember_sort`）
        # 并按新顺序重排列表。这里不重画整个界面——
        # 排序只影响列表内容，改语言才需要动全部文案。
        self.apply_sort(_column_of(sort_key), reverse=sort_reverse)

        if language_changed:
            self.retranslate()
        try:
            self.config.save()
        except OSError as error:
            self._report_resource_error(
                L(f"无法保存设置: {error}",
                  f"Could not save the settings: {error}"))

    def retranslate(self) -> None:
        """把界面上所有文案按**当前语言**重取一遍。

        ## 只改文字，不动尺寸

        按钮宽度是按文字算的不是写死的（`RoundedButton` 会 `SetMinSize`），
        所以换语言后 `Layout()` 一次就够，不需要重建控件。
        重建会丢掉选中行、滚动位置和目录树的展开状态——
        为了几个字付这个代价不值得。

        **原生 `wx.ListCtrl` 的列标题改不了**（`SetColumn` 的 `LVCOLUMN`
        只支持改文字，但 wx 的 `InsertColumn` 是追加语义，原地改要靠
        `SetColumnText`）——所以列表那四列直接调它，表头是自绘的、
        改 `titles` 再 `Refresh` 即可。
        """
        labels = column_labels()
        for index, title in enumerate(labels):
            # **`wx.ListCtrl` 没有 `SetColumnText`**（实测 `hasattr` 为 False）。
            # 早先写了个 `try: SetColumnText ... except: pass`，于是
            # `AttributeError` 被静默吞掉、原生列标题**永远不变**——
            # 看上去像"改语言没生效"。正确写法是取回列表项、改文字、再写回。
            column = self.list_ctrl.GetColumn(index)
            if column is None:
                continue
            column.SetText(title)
            self.list_ctrl.SetColumn(index, column)
        self.header.set_titles(labels)

        self.open_btn.SetLabel(L("打开", "Open"))
        self.clear_btn.SetLabel(L("清空", "Clear"))
        # 只让路径栏**自己重取**提示，不由这里传文案——
        # 传文案就意味着"文案"有两份来源，迟早有一处忘了跟着语言走。
        self.path_bar.refresh_hint()
        self._refresh_pin_label()
        self.Layout()
        self.Refresh()

    def _refresh_pin_label(self) -> None:
        """顶置按钮的两种形态都要跟着语言走。

        图标形态没有可见文字（`IconButton` 只画位图），但**文字兜底形态**
        有——图片缺失时那个按钮就是靠文字表达的，不刷新它就会中英混排。
        """
        pinned = bool(self.GetWindowStyle() & wx.STAY_ON_TOP)
        if getattr(self, "_pin_is_text_button", False):
            self.pin_btn.SetLabel(
                L("取消顶置", "Unpin") if pinned else L("顶置", "Pin"))

    def on_show(self, event) -> None:
        if event.IsShown():
            # 每次显示窗口都要重藏原生表头——`Show()` 会把它翻出来
            # （实测，见 _hide_native_header）
            self._hide_native_header()
            wx.CallAfter(self.reset_dir_ctrl_scroll)
        event.Skip()

    def on_close(self, event) -> None:
        """退出：保存配置、提交数据库、关闭连接。

        **顺序有讲究**：先落配置与数据库，最后才 ``Skip()`` 真正销毁窗口。
        旧实现在这里调 ``save_accessed_paths`` 整表重写（先 ``DELETE FROM paths``
        再从界面把所有行插回去），现在不需要了——数据库本身就是真相来源。
        """
        try:
            current_dir = self.dir_ctrl.GetPath()
            if current_dir and os.path.exists(current_dir):
                self.config.set_last_directory(current_dir)
            self.save_scroll_position()
            self.config.save()
        except OSError as error:
            wx.LogError(L(f"无法保存配置: {error}", f"Could not save the config: {error}"))

        try:
            self.store.close()
        except Exception as error:
            wx.LogError(L(f"关闭数据库时出错: {error}", f"Error while closing the database: {error}"))

        event.Skip()


class FileTrackerApp(wx.App):
    """应用程序对象。

    DPI 感知必须在**创建任何窗口之前**设置，否则窗口按 96 DPI 定尺寸、
    字体按真实 DPI 定大小，两者对不上（Roboc 视觉规范第一节）。

    深色模式同理，而且**必须在进程级声明**——见
    :func:`file_tracker.win32.set_process_dark_mode`。
    """

    def OnInit(self) -> bool:  # noqa: N802 - 跟随 wx 命名
        if "wxMSW" in wx.PlatformInfo:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
            except (OSError, AttributeError):
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except (OSError, AttributeError):
                    pass

        # **这一步决定深色主题成不成立。**
        #
        # 调用 `uxtheme` 的 `SetPreferredAppMode(ForceDark/Default)`，
        # 之后**滚动条、列表表头、菜单、MessageBox 这些由系统绘制的控件**
        # 才会按深色渲染。不做这一步，`SetBackgroundColour` 对它们无效，
        # 深色主题下会留下大片白底——用户反馈的"深色主题下的表现很差"就是这个。
        #
        # 必须在窗口创建之前调用，所以放在这里而不是 apply_window_theme 里。
        try:
            dark = win32.system_uses_light_theme() is False
            win32.set_process_dark_mode(dark)
        except Exception:
            pass

        self.SetAppName(APP_NAME)
        self.frame = FileTracker()
        self.frame.Show()
        self.SetTopWindow(self.frame)
        return True


def _emit(text: str) -> bool:
    """把一行文字写到 stdout；写不出去返回 ``False``。

    **打包成 windowed 程序后 stdout 是不存在的**：``console=False`` 的 exe
    没有控制台，``print()`` 会抛 ``OSError: [Errno 22] Invalid argument``。
    踩过一次——``--version`` 在构建脚本里输出为空，而脚本当时没有断言输出非空，
    于是一次"成功"的构建掩盖了"产物不会自报版本"这个事实。

    :return: 是否真的送出去了
    """
    import sys

    stream = sys.stdout
    if stream is None or getattr(stream, "closed", True):
        return False
    try:
        stream.write(text + "\n")
        stream.flush()
        return True
    except (OSError, ValueError, AttributeError):
        return False


def _emit_or_log(text: str) -> None:
    """写到 stdout；写不出去就落到日志文件，并在窗口模式弹一个提示框。

    规则二要求"产物必须能自报是哪个提交构建的"。windowed 产物没有控制台，
    所以**必须有一个不依赖控制台的通道**，否则用户报障时拿不到这一行。

    ## 这里**不能**碰 wx

    原来这一行是 ``wx.StandardPaths.Get().GetUserDataDir()``。
    那句在没有 `wx.App` 时会触发 wx 断言，而 **wx 断言失败是弹一个模态框
    等人点**，不是抛异常——命令行场景没有人点，**进程就停死在那里**。
    外面那个 `except (OSError, ValueError)` 因此形同虚设
    （它不抛这两种异常，它只是停住）。

    用户报障时踩到过：没有控制台时跑 ``--version`` 会挂住。
    现在走 :func:`~file_tracker.core.app_data_dir`，**完全不依赖 wx**。
    """
    if _emit(text):
        return

    try:
        log_dir = app_data_dir()
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "version.txt")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        log_path = None

    if log_path:
        _show_message_safely(
            f"{text}\n\n"
            + L(f"（已写入 {log_path}）", f"(written to {log_path})"))


def _show_message_safely(text: str) -> None:
    """弹一个**跟主题一致**的提示框；任何失败都吞掉，不影响退出码。

    `--version` 是命令行用法，这里没有主窗口。
    :class:`~file_tracker.widgets.ThemedDialog` 允许 `parent=None`，
    所以照样能弹出一个配色正确的框——**不必退回系统对话框**。

    ## 为什么必须**自动关闭**

    原来是 `ShowModal()` 一直等——**没有人点就永远不退**。
    于是这个"友好的提示"变成了一个卡死点：任何无人值守的调用
    （脚本、自动化、CI）跑 `--version` 都会挂在那里。

    用户已经因为这个吃过一次苦（审计里那条 C1）。

    现在挂一个 `wx.Timer`，到时自己关。想早点关掉就按键或点「好」。
    """
    #: 自动关闭的等待时间（毫秒）。
    #:
    #: 取值权衡：**必须足够长到让人看清一行版本号**，又**必须足够短到
    #: 不像卡死**。6 秒够读一行；再长，无人值守的调用就会明显变慢。
    auto_close_ms = 6000
    try:
        import wx as _wx

        app = _wx.App(redirect=False)
        dialog = ThemedDialog(None, theme_from_system(), text,
                              title=L(f"{APP_NAME} 版本", f"{APP_NAME} version"),
                              yes_label=L("好", "OK"),
                              no_label=NO_BUTTON)
        dialog.CentreOnScreen()

        # 到点自己关。`wx.Timer` 在 `MainLoop` 里跑，所以会把模态循环关掉。
        timer = _wx.Timer(dialog)
        dialog.Bind(_wx.EVT_TIMER, lambda _event: dialog.EndModal(_wx.ID_YES),
                    timer)
        timer.StartOnce(auto_close_ms)

        dialog.ShowModal()
        # **先停表再销毁。** 让计时器活过它所属的窗口，
        # 事件就会打到已释放的对象上。
        timer.Stop()
        dialog.Destroy()
        app.Destroy()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    """程序入口。

    ``--version`` 打印自报版本串后退出。**产物必须能自报"是哪个提交构建的"**：
    用户报障时，这一行决定你能不能判断他装的是哪一个。
    ``--selftest`` 做一次不创建窗口的冒烟检查，供 CI 使用。
    """
    import sys

    args = list(sys.argv[1:] if argv is None else argv)

    if "--version" in args:
        _emit_or_log(version_string())
        return 0

    if "--selftest" in args:
        return _run_selftest()

    app = FileTrackerApp(redirect=False)
    app.MainLoop()
    return 0


def _run_selftest() -> int:
    """不创建主窗口的自检：资源、数据库、消息号封装是否就位。

    刻意**不创建窗口**——CI 上没有桌面会话，创建窗口会挂住。
    真正需要窗口的验证由 ``tools/verify_gui.py`` 在真实桌面会话里做。
    """
    import tempfile

    problems: list[str] = []

    icon = resource_path("images/shell32_star.ico")
    if not os.path.exists(icon):
        problems.append(L(f"图标缺失: {icon}", f"Icon missing: {icon}"))
    # **每一个图标按钮用到的图都要在这里。**
    # 漏掉一个，`_build_icon_button` 就会静默退化成文字按钮——
    # 构建仍然全绿，用户看到的是"设置按钮没有图标"。
    for name in ("pin_grey.png", "pin_red.png", "settings.png"):
        path = resource_path(os.path.join("images", name))
        if not os.path.exists(path):
            problems.append(L(f"图片缺失: {path}", f"Image missing: {path}"))

    with tempfile.TemporaryDirectory() as scratch:
        store = PathStore(os.path.join(scratch, "selftest.db"))
        store.record_access("C:\\selftest")
        store.record_access("C:\\selftest")
        record = store.get("C:\\selftest")
        if record is None or record.access_count != 2:
            problems.append(L(f"频次自增不正确: {record}", f"Access count did not increment: {record}"))
        store.close()

    status = "OK" if not problems else "FAIL"
    _emit(f"{APP_VERSION} selftest: {status}")
    for problem in problems:
        _emit(f"  - {problem}")

    if problems:
        # 失败时也要留痕：windowed 产物里 stdout 是空的。
        # **同样不能用 `wx.StandardPaths`**——`--selftest` 也没有
        # `wx.App`，那句会弹断言框把进程停住（见 `_emit_or_log`）。
        try:
            log_dir = app_data_dir()
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "selftest.log"), "w",
                      encoding="utf-8") as handle:
                handle.write(f"{APP_VERSION} selftest: FAIL\n")
                for problem in problems:
                    handle.write(f"  - {problem}\n")
        except OSError:
            pass
    return 0 if not problems else 1
