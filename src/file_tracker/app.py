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
from .store import (TIME_FORMAT, PathRecord, PathStore, default_db_path,
                    format_time_cell)
from .dir_tree import DirectoryTree
from .header import ColumnHeader, sort_arrow_width
from . import paint_trace
from .lang import (L, PREFERENCE_CHINESE, PREFERENCE_ENGLISH,
                   apply as apply_language, is_chinese)
from .theme import (METRICS, THEME_CHOICES, THEME_SYSTEM,
                    Theme, from_preference as theme_from_preference,
                    from_system as theme_from_system, scale_for_dpi)
from .tree_nav import TreeWalker, build_walk_plan, find_child_by_label, pick_fallback_item
from .widgets import (BorderLine, IconButton, PathBar, RoundedButton,
                      NO_BUTTON, SettingsDialog, ThemedDialog, dpi_of)
from .widgets import body_font as widgets_body_font

#: 列表列定义：(初始宽, 是否居中)
#:
#: **"最后访问时间"曾经拆成两列**（2026-10-15，为了让日期与时间能区分），
#: **2026-10-17 又并回一列** —— 用户指出"日期和时间本来就是一回事，
#: 不该分成两列"，而当年那个"分不清"的问题，**一个 3 空格的分隔就能解决**。
#: 合并后显示成 `14:43   26-10-17`（见 :func:`store.format_time_cell`）。
#: 数据库里始终存整串 `2026-10-17 14:43:27`，**排序用完整值**。
#:
#: **宽度与居中标记是"结构"，列标题是"文案"——两者分开。**
#:
#: 标题不能写在这里：模块级常量在 **import 时**求值，而语言偏好要等
#: `lang.apply()`（启动早期、但晚于 import）才知道。写在模块级，
#: 双语判断就会永远用系统的默认答案，用户在设置里选了也不生效。
#: 所以标题走 `column_labels()`，**每次用的时候现取**。
COLUMNS = (
    (400, False),   # 路径 —— 数据左对齐（左边距靠文本前缀实现，见 `PATH_LEFT_PAD`）
    (90, True),     # 频次 —— **数据居中**（原生 `LVCFMT_CENTER`）
    (190, True),    # 访问时间 —— 日期并进来了；**数据也居中**（用户 2026-10-17）
)

#: 第 2 个元素 = "**这一列的**数据是否居中"。它直接变成 `InsertColumn` 的
#: `format` 位（`wx.LIST_FORMAT_CENTER`），**不再靠补前导空格**。
#:
#: 只有频次列是 `True`：频次是纯数字、宽度固定，居中好看。
#: 日期/时间数据明确左对齐 —— 用户 2026-10-17："数据也居中三列之间的间隔
#: 看着就不均衡了。"
#:
#: ## 从四列并成三列（用户 2026-10-17）
#:
#: > "时间和日期本身就是一类的东西，最开始就不应该分成两列。
#: >   只保留'访问时间'这一列，把日期并进去。具体格式：`14:43   26-10-17`，
#: >   时间和日期之间用 3 个空格隔开，秒数在用户界面隐藏掉，
#: >   后端计算排序就行了。"
#:
#: 原来 `访问日期` + `访问时间` 两列：两者的**排序键完全一样**、
#: 又都只服务于"这条是什么时候访问的"这一个问题 —— 拆开是当年为了
#: "日期与时间分不清"（2026-10-15），而**一个 3 空格的分隔已经解决那件事**。
#:
#: 显示格式见 `store.format_time_cell()`。

COLUMN_PATH, COLUMN_COUNT, COLUMN_TIME = 0, 1, 2

#: **时间列（居中）的左右内边距**，以"几个空格宽"为单位。
#:
#: 时间列的数据是**居中**的，所以"列宽 − 数据宽"会平均分到左右两侧。
#: `extra = 2 × CELL_PADDING_SPACES × 空格宽` ⇒ 每侧正好
#: `CELL_PADDING_SPACES` 个空格宽。
#:
#: **为什么以"空格"而不是逻辑像素为单位**：与之对齐的路径列左内边距
#: 只能用**整数个前导空格**实现（原生 `LVM_SETITEMINDENT` 返回 1 却不生效），
#: 空格是它的最小刻度。用像素定值会落在一个加不出来的位置上。
CELL_PADDING_SPACES = 2

#: **路径列的左内边距**用几个空格。**与时间列共用同一个数**。
#:
#: ## 这一条来回改过一次，最终定为"与时间列相等"
#:
#: 用户先要求"路径左边距 == 时间左右边距"（为了微调时视觉规整）⇒ 设 2；
#: 随后他指着列表最左边那条空白问"这是什么，能去掉吗" ⇒ 归零；
#: 但那条空白**其实不是它**（是 `card_panel` 的四周留白，见下面 `InitUI`
#: 里 `right_sizer.Add(...)` 的注释），所以去掉它只是让路径文字贴了边、
#: 反而破坏了与时间列的一致性。用户看了效果后要求回到这一版。
#:
#: ⇒ **恢复成 2，与 `CELL_PADDING_SPACES` 相等**。两个常量仍然分开写着
#: （而不是直接复用），因为将来"路径列左边是列表边界、不需要呼吸感"
#: 这个判断可能又成立；那时只改这一个数即可。
PATH_LEFT_PAD_SPACES = 2

#: 路径列数据的**左内边距**（用前导空格实现）。
#:
#: ## 为什么不用原生缩进
#:
#: 用户 2026-10-17："访问路径（path）列的数据左边增加一点间距，
#: 怎么实现（直接加空格还是其他方式）你来定。"
#:
#: 试过 `LVM_SETITEMINDENT`（Win32 的"项缩进"）：**返回 1（成功），
#: 但 `LVM_GETITEMRECT` 回读的文本矩形 `left` 一直是 2 —— 根本没生效。**
#: 又一个"看起来成功"（同类：`SetHeaderAttr` 返回 True 但表头不变色）。
#:
#: 所以用**前导空格**。代价是控件里存的文本不再等于路径，
#: 所有"从控件读路径"的地方都要走 :meth:`FileTracker._path_from_cell`。
#: **这个代价是可控的**：全项目只有三处读它（`row_path` / `_selected_paths`
#: / `find_path`），都列在下面那个方法的 docstring 里。
#:
#: 用**固定前缀**（而不是 `ljust`）：读取时按同样的前缀剥掉，
#: 不会误伤"真实路径本身以空格开头"的极端情况（Windows 允许，但罕见）。
PATH_LEFT_PAD = " " * PATH_LEFT_PAD_SPACES


def column_labels() -> tuple[str, ...]:
    """四个列标题（跟随当前语言）。

    **与 `SORT_SPECS` 同序**——列的顺序和可排序列的顺序是同一件事，
    验证脚本会断言两者长度一致、顺序对应。
    """
    return (
        L("访问路径", "Path"),
        L("频次", "Count"),
        L("访问时间", "Time"),
    )


#: 列号 → 排序列标识。**与 `SORT_SPECS` 同序**，见 `column_labels()`。
#: 两张表必须同序：列的顺序就是可排序列的顺序。
#: 一致性由 `tests/test_sort_preference.py` 断言——**用测试而不是
#: 模块级 `assert`**：`-O` 会去掉 assert，而测试不会。
_COLUMN_SORT_KEYS = ("path", "count", "time")


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


# 关于那枚 `⚠️`：**它已经退役了**（2026-10-26）。
#
# 原来这里是 `WARN = "\u26a0\ufe0f"`，各处弹窗在正文开头拼它。
# 用户："每个弹窗的警告标志都使用正文中的"⚠️"符号。但现在我每次看到弹窗时，
# 发现这个警告标志实在是太小了……把那个警告标志画出来，替换掉目前所有的"⚠️"符号。"
#
# 现在标志由 `ThemedDialog(..., alert=True)` **自绘**
# （几何在 `theme.warning_badge_geometry`，图元在 `widgets.icon_warning`）。
#
# ⚠️ **不要再把那个码点拼回任何正文里**：弹窗上会变成"自绘三角 + 巨型 emoji"
# 两枚标志。`verify_gui` 有一条判据扫描整个 `src/` 禁止它出现。


class FileTracker(wx.Frame):
    """文件访问追踪主窗口。"""

    def __init__(self):
        style = wx.DEFAULT_FRAME_STYLE | wx.WANTS_CHARS
        super().__init__(parent=None, title=APP_NAME, style=style)
        self.SetName("FileTrackerFrame")

        # **必须一开始就有值**：`dir_ctrl.populate(expand_path=...)` 会同步派发
        # `EVT_TREE_ITEM_EXPANDED`，那时 `on_tree_expanded` 已经会被调用 ——
        # 而 `__init__` 里那些标志位要到很下面才赋值。
        # 实测（2026-10-25）：放在下面 ⇒ 启动时立刻
        # `AttributeError: 'FileTracker' object has no attribute '_trim_pending'`，
        # 而**它被 wx 的事件处理器吞掉了**（只在 stderr 一行），
        # 门禁照样全绿 —— 这类"看不见的异常"只能靠"把 stderr 一起看"发现。
        self._trim_pending = False

        # 先按**系统**取一次：下面马上要用它设窗口底色，
        # 而 `config` 要再往下才建出来。
        #
        # ⚠️ 这里**不能**直接读偏好——踩过：写成
        # `theme_from_preference(self.config.get_theme())` 会抛
        # `AttributeError: 'FileTracker' object has no attribute 'config'`，
        # 整个窗口起不来。偏好稍后覆盖（见 `self.config = Config(...)` 之后）。
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
        # **建目录失败要报清楚，不能抛一个裸回溯。**
        #
        # 审计查出的问题：这是文件里**四处 `makedirs` 中唯一没有保护**的一处
        # （另外三处见 `_report_resource_error` / `--selftest`）。
        # `%APPDATA%` 写不了是真实场景（漫游配置损坏、组策略限制、
        # 磁盘满），而那时用户看到的是一个 Python 回溯对话框，
        # 而不是下面那句"打不开数据库"的说明。
        try:
            if not os.path.exists(self.app_data_dir):
                os.makedirs(self.app_data_dir, exist_ok=True)
        except OSError as error:
            wx.MessageBox(
                f"{L('无法创建数据目录', 'Could not create the data folder')}: "
                f"{self.app_data_dir}\n\n{error}\n\n"
                + L("程序会继续运行，但设置与记录可能无法保存。",
                    "The app will continue, but settings and records may not "
                    "be saved."),
                L("数据目录错误", "Data folder error"),
                wx.OK | wx.ICON_WARNING)
        # 走 `default_config_path()` 而不是在这里拼路径——
        # 测试与验证脚本要能把它换掉，否则会写进用户真实的配置。
        self.config = Config(default_config_path())

        # **现在才读偏好**（`config` 刚建出来）。
        # 偏好是"跟随系统"时这一步等于重算一次，代价可忽略。
        self.theme = theme_from_preference(self.config.get_theme())
        self.SetBackgroundColour(wx.Colour(self.theme.background))
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
            # 早先这里还在正文开头拼那枚 ⚠️ 字形；现在警示标志只由
            # `ThemedDialog(alert=True)` 画得出来，而这条**只能用系统对话框**，
            # 所以警示意图交给系统的 `wx.ICON_ERROR`（它自带一枚图标）。
            wx.MessageBox(
                L("初始化数据库时发生错误: ",
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

        self._call_after(self.restore_scroll_position)

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
            log_path = os.path.join(log_dir, "resource-errors.log")
            FileTracker._append_capped(log_path, line)
        except OSError:
            # 连日志都写不了时不再抛异常——否则会盖掉真正的原始问题
            pass

    #: 日志文件的上限。超过就把它截到最近的一半。
    #:
    #: 审计查出的问题：这个文件**只增不减、没有轮转**。而它的写入点里有
    #: 一些是重复路径（窗口每次显示、主题每次应用）——虽然最吵的那一处
    #: （鼠标移动）已经改成静默了，但"某个失败每帧重试"这类情形迟早会再出现，
    #: 而日志把用户磁盘写满是最难查的一种故障。
    #:
    #: 256 KB 够存几千行，对排查足够；超出时留最近的一半而不是清空——
    #: **刚发生的那次失败才是有用的那次**，把历史全丢掉等于下次还得再复现一遍。
    MAX_LOG_BYTES = 256 * 1024

    @staticmethod
    def _append_capped(path: str, line: str) -> None:
        """追加一行；文件超过上限时**只留最近的一半**。"""
        limit = FileTracker.MAX_LOG_BYTES
        try:
            if os.path.exists(path) and os.path.getsize(path) > limit:
                with open(path, "r", encoding="utf-8",
                          errors="replace") as handle:
                    kept = handle.read()[-(limit // 2):]
                # 截断处可能落在半行中间——丢掉第一段（它不完整）
                newline = kept.find("\n")
                if newline != -1:
                    kept = kept[newline + 1:]
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(L("[日志超过上限，已保留最近的部分]",
                                   "[log exceeded its cap; kept the recent part]")
                                 + "\n")
                    handle.write(kept)
        except OSError:
            # 轮转失败不该阻止写日志（宁可文件大一点，也别丢信息）
            pass
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

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
        # 留 `self.` 句柄：`_retheme()` 要够得到它（见那里的说明）
        self._shell_panel = panel = wx.Panel(self)
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
        self._left_panel = left_panel = wx.Panel(splitter)
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
        # **不用 `wx.GenericDirCtrl` 了。**
        #
        # 它的图标固定 16×16，而树行高被调到 50px ⇒ 图标/行高 = **0.32**，
        # 对比 Explorer 的约 0.73「看着真的很费劲」（用户）。
        # 而它**没有暴露任何图列表 API**（实测 `dir()` 里一个都没有），
        # 换不了图标尺寸 —— 只能换控件。
        #
        # `DirectoryTree` 继承 `wx.TreeCtrl` 并实现了 `GenericDirCtrl`
        # 被用到的那几个方法（`GetTreeCtrl` / `GetPath` / `GetPaths` /
        # `ShowHidden`），所以**下面那几十处调用一行都不用改**。
        self.dir_ctrl = DirectoryTree(left_panel, show_hidden=True)
        # **把树的错误上报接到项目的资源错误通道上。**
        #
        # 审计查出的缺陷：`_populate_item` 展开失败时原来既不重试也不报错，
        # 用户只看到"这个目录点不开、里面什么都没有"。
        # `dir_tree` 不能反向 import `app`（循环依赖），所以用**注入回调**。
        self.dir_ctrl.on_error = self._report_resource_error
        self.dir_ctrl.SetMinSize((METRICS.tree_min_width, -1))
        tree = self.dir_ctrl.GetTreeCtrl()
        tree.SetBackgroundColour(wx.Colour(self.theme.card))
        # **整行高亮**（Win11 资源管理器的做法：选中项铺满整行宽度）。
        # 用户反馈"导航窗格空白部分无法选中"——树条目下方的空白区
        # 原生 `SysTreeView32` 本来就不响应（那里没有节点），
        # 所以能改善的是**让选中状态更明显**，而不是让空白可点。
        self._enable_tree_row_highlight(tree)
        # **两个事件都要绑，少一个就少一条路。**
        #
        # * `EVT_TREE_ITEM_ACTIVATED` —— **键盘回车**激活（事件自带节点）
        # * `EVT_LEFT_DCLICK`          —— **鼠标双击**（实测**不发**上面那个事件！）
        #
        # ⚠️ 2026-10-17 实测（`tools/probes/probe_tree_events.py`）：
        # 给树的窗口发真的 `WM_LBUTTONDOWN/UP/DBLCLK/UP`，收到的是
        # `EVT_LEFT_DOWN / LEFT_UP / **LEFT_DCLICK** / LEFT_UP` ——
        # **`EVT_TREE_ITEM_ACTIVATED` 一次都不发。**
        #
        # 只绑前者时，"双击导航窗格里的文件"这条路上
        # `on_dir_item_activated` **根本不会被调用**：不打开、不记录、
        # 焦点也不转移 —— 正是用户报的"焦点一直停留在导航窗格"。
        tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_dir_item_activated)
        tree.Bind(wx.EVT_LEFT_DCLICK, self.on_dir_item_activated)
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
        # **用户自己在树里展开目录 → 顺手检查一次节点总量。**
        #
        # 这是"手动浏览"那条路的兜底：`reveal_in_tree` 里的检查只在
        # 地址栏回车 / 双击文件时跑，而用户完全可以只用树浏览几小时
        # （他的原话就是"从左边导航窗格打开"）。节点只增不减 ⇒ 关闭十几秒。
        tree.Bind(wx.EVT_TREE_ITEM_EXPANDED, self.on_tree_expanded)
        # **填充并展开到上次的目录。**
        #
        # `GenericDirCtrl` 是构造时用 `dir=` 一次搞定的；换成自己的树之后
        # 要显式做这一步。**放在所有 Bind 之后**：填充会触发
        # `EVT_TREE_ITEM_EXPANDING`（懒加载），早于 Bind 的话
        # 那些事件没人处理。
        self.dir_ctrl.populate(expand_path=self.last_directory)
        left_sizer.Add(self.dir_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                       METRICS.padding_gap)
        left_panel.SetSizer(left_sizer)

        # -- 右 pane：卡片（表头 + 列表）+ 按钮条 ---------------------------
        #
        # **卡片分层**：`right_panel` 是窗口底色，里面嵌一块 `card_panel`
        # 用卡片底色，表头与列表都画在卡片上。用户要的"卡片式分层
        # （面板底色 + 列表区域是另一层）"就是靠这层容器实现的——
        # 直接给列表设底色是看不出分层的（列表会占满整块 sizer）。
        self._right_panel = right_panel = wx.Panel(splitter)
        right_panel.SetBackgroundColour(wx.Colour(self.theme.background))
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        self._card_panel = card_panel = wx.Panel(right_panel)
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
            style=wx.LC_REPORT | wx.BORDER_NONE | wx.LC_NO_HEADER,
        )
        # **允许多选（Ctrl / Shift 点击）。**
        #
        # ⚠️ 构造时**不传** `wx.LC_SINGLE_SEL` 还不够 ——
        # 实测（`tools/probes/probe_multiselect_native.py`）：
        # 只改 wx 侧时"API 多选能用、真 Ctrl 点击仍然只选一行"。
        # 决定鼠标行为的是**原生** `LVS_SINGLESEL` 位，
        # 所以这里再按原生口径清一次。
        #
        # 清掉之后实测：Ctrl 点击 → `[1, 4]`，Shift 点击 → `[2,3,4,5,6]`，
        # 都是**原生支持**的，不用自己实现。
        win32.enable_list_multi_select(self.list_ctrl.GetHandle())
        self.list_ctrl.SetBackgroundColour(wx.Colour(self.theme.card))
        for index, (width, centered) in enumerate(COLUMNS):
            # **列对齐用原生格式位**（用户 2026-10-17 报"居中算法不对"）。
            #
            # 历史：本项目长期用"补前导空格"实现频次列居中，理由是
            # "原生 `LVM_SETCOLUMN` 在本环境不可用（一律返回 0）"。
            # **但那条测的是"修改已存在列"**（`LVM_SETCOLUMN`），
            # 而 `InsertColumn` 走的是**另一条消息**（`LVM_INSERTCOLUMN`）——
            # 它在创建时就带上 `fmt`，实测**完全可用**：
            #
            #   `tools/probes/probe_native_center.py`（ctypes 回读 `LVM_GETCOLUMN`）
            #   左列 0x4000 / 居中列 0x4002（LVCFMT_CENTER）/ 右列 0x4001
            #   渲染层交叉验证：居中列文字左边距 74，左对齐列 9
            #
            # 用空格凑居中的问题是**量化误差**：空格是离散单位，
            # 只能对齐到它的整数倍，再加上两次整除的取整误差，
            # 最多偏半个空格 —— 而中文列宽是奇数时（89）误差最明显。
            self.list_ctrl.InsertColumn(
                index, column_labels()[index],
                format=(wx.LIST_FORMAT_CENTER if centered
                        else wx.LIST_FORMAT_LEFT),
                width=width,
            )
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
        # 关闭时用来停掉挂起回调（见 `on_close` / `_call_later`）
        self._closing = False
        self._pending_timers: list = []
        # 点了列表（含点已选中的那一行，此时 `ITEM_SELECTED` 不发）
        for list_event in (wx.EVT_LIST_ITEM_SELECTED, wx.EVT_SET_FOCUS):
            self.list_ctrl.Bind(list_event, self.on_list_selection_made)
        # **选中行整行高亮**（原生高亮被 item 底色压掉了，见
        # `_apply_selection_highlight`）。这几个事件都要接：
        # 点选、键盘上下、全选、以及"点空白处取消选中"。
        self._highlighted_row = -1
        #: **上一次画过的整个选中集**（多选之后必须有这个）。
        #: 取消选中时要靠它把那些行还原成底色 —— 只记一条的话，
        #: 其余行会留着上一次的蓝，擦不掉。
        self._highlighted_rows: tuple = ()
        # 列宽重入标志（见 `adjust_column_widths`）：`SetColumnWidth` 会触发
        # `EVT_SIZE` 打回自己，靠它只让最外层那一次做完。
        self._adjusting_columns = False
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
        # **拖拽多选**（用户 2026-10-17 要的）。
        #
        # ⚠️ 原生拖拽框选在这个控件上**用不了**：实测 7 种组合
        #    （`SendMessage` 各种 flags/步数/`SetCapture`/预选/双缓冲）
        #    拖动之后都只选中按下那一行 —— 见
        #    `tools/probes/probe_multiselect_drag.py`。
        #    所以这一条**自己实现**：按下记起点，移动超阈值就按行区间选中。
        #
        # 三个状态位：
        #   `_drag_origin_row`  按下时的行（-1 = 没在拖）
        #   `_drag_origin_pos`  按下的客户区坐标（判断"是拖还是点"）
        #   `_dragging`         是否已经进入拖拽（超了阈值）
        self._drag_origin_row = -1
        self._drag_origin_pos = None
        self._dragging = False
        self.list_ctrl.Bind(wx.EVT_LEFT_DOWN, self.on_list_left_down)
        self.list_ctrl.Bind(wx.EVT_LEFT_UP, self.on_list_left_up)
        # **竖线是覆盖层，滚动/重绘会被擦掉，所以每次都要补画**
        self.list_ctrl.Bind(wx.EVT_SCROLLWIN, self.on_list_scroll)
        self.list_ctrl.Bind(wx.EVT_PAINT, self.on_list_paint)

        # **行底色诊断（默认关闭）。**
        #
        # 用户报"从导航窗格打开之后那条是浅灰而不是蓝色"，
        # 而探针里怎么复现都是蓝的 —— 差别在**他的环境**里。
        # `FT_DEBUG_PAINT=1` 时把每一次"谁把哪一行改成了什么色"
        # 记进 `%APPDATA%\File Tracker\paint-trace.txt`，关窗时落盘。
        # 不看这个环境变量时 `install()` 立刻返回，**一行都不包装**。
        self._paint_tracer = paint_trace.install(self)

        # **自绘表头**：原生 SysHeader32 在深色主题下不采纳任何设色，见 header.py
        self.header = ColumnHeader(
            card_panel, self.theme,
            titles=list(column_labels()),
            widths=[width for width, _c in COLUMNS],
            on_column_click=self.on_header_clicked,
            # **三个列标题全部居中**（用户 2026-10-17）：
            # "访问路径 / 频次 / 访问时间 每个列标题全部居中"。
            #
            # 注意：这是**标题**居中，数据各自另有对齐方式
            #（频次与时间居中、路径左对齐，见 `COLUMNS` 的第 2 个元素）。
            centered_titles=(COLUMN_PATH, COLUMN_COUNT, COLUMN_TIME),
        )
        # 注意：**这里不能马上藏原生表头**——此刻它还没被创建。
        # 藏它的动作在 apply_window_theme 的最后（布局走完之后）。

        card_sizer.Add(self.header, 0, wx.EXPAND)
        card_sizer.Add(self.list_ctrl, 1, wx.EXPAND)
        card_panel.SetSizer(card_sizer)
        # ## 卡片四周的留白：**左边那份去掉了**（用户 2026-10-17）
        #
        # 原来四边各 `padding_gap`（8 逻辑像素），左右对称。
        #
        # 用户指着列表左缘问："这条空出来的边是什么？……以前是一条黑色的
        # 竖线，上一个智能体把它修掉了，但只是把它隐藏了，实际上它还存在。"
        #
        # **实测澄清**（`splitter.GetSashSize()` 等）：
        #
        # ```
        # sash 宽 = 0            ← 那条"黑线"真的没了，不是隐藏
        # 右窗格 [400, 1076)
        # card_panel 在右窗格内 (8, 8)，宽 660
        # ⇒ 左 8、上 8、右 8  —— 四边对称的**卡片留白**
        # ```
        #
        # 所以用户看到的是**卡片留白**，不是残留的 line。它四边都有，
        # 只是左侧紧邻导航窗格、旁边没有滚动条遮挡，所以最显眼。
        #
        # **最终：恢复默认（四边各 `padding_gap`）** —— 用户 2026-10-17
        # 看过"只去左边"的效果之后要求回默认对称留白。
        #
        # 中间试过 `wx.EXPAND | wx.TOP | wx.BOTTOM | wx.RIGHT`（去掉左那份）：
        # 卡片贴到左窗格、左右不对称，观感并不更好。
        # ⇒ 回到 `wx.ALL`，四边相等。
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

        # **这一行是用户要求注释掉的，不要"顺手恢复"。**
        #
        # 原文写着"自己画的分隔线，改由 BorderLine 画" —— 读起来像"它正在生效"，
        # 但下面那行是**注释掉的**，所以 `self.pane_border` **根本不存在**。
        #
        # 三处读取点都用 ``getattr(self, "pane_border", None)`` 兜着，
        # 所以不会崩；`tools/verify_gui.py` 还**专门断言**了它不存在
        # （"sash 与分隔线都不画"是当时定下的外观）。
        #
        # 之所以把这段说明补上：审计发现注释与实际行为相反，
        # 而下一个人看到"改由 BorderLine 画"会以为线是在的——
        # 于是要么去删一段没生效的代码，要么去"修"一个本来就没画的东西。
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
        # **句柄直接取，不要去找内层的 `SysTreeView32`。**
        #
        # 换成 `DirectoryTree` 之后，`dir_ctrl` **本身就是那棵树** ——
        # 没有"内层控件"可找。实测：继续用
        # `find_child_window(..., "SysTreeView32")` 会返回 `None`，
        # 于是行高**一次都没设上**（验证器报「实测 0px」）。
        tree_native = (self.dir_ctrl.GetHandle()
                       if getattr(self, "dir_ctrl", None) is not None
                       else win32.find_child_window(handle, "SysTreeView32"))
        if tree_native:
            win32.set_window_theme(tree_native, theme_name)
            self._apply_tree_row_height(tree_native)

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
            self._call_later(60, self._hide_native_header_now)

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

        # ── 行高：用一张 1×H 的**空图列表**抬起来 ──
        #
        # ## 为什么不是 `LVM_SETITEMSPACING`
        #
        # 那个消息在 report（详细信息）视图下**是空操作**。实测
        # （`tools/probes/probe_row_spacing.py`）：把它从 0 设到 40，
        # 行高**恒为 39px，纹丝不动**；MSDN 也写明它只对 icon /
        # small-icon 视图有意义。**所以那个开关从引入起就没生效过**，
        # 只是当时没有断言量行高。
        #
        # ## 现在这条：让"行高"由小图标高度托底
        #
        # report 视图的行高 = `max(字号决定的高度, 小图标高 + 1)`。
        # 挂一张**只有 1 像素宽**的透明空图，就只影响高度、不影响内容。
        # 实测（`tools/probes/probe_row_height.py`）：H=40 → 行高 41、
        # H=48 → 行高 49。字号 11pt 时文字高 35px，所以按
        # `文字高 + extra` 取 H，行高就落在 `文字高 + extra + 1`。
        #
        # ## 代价（实测过，见下面 `_measure_path_text_shift` 的注释）
        #
        # report 视图会给第 0 列留出图标位，**路径文字会右移几像素**。
        # 这是这条路的固有代价，不是 bug——README 的「已知限制」不需要提，
        # 但**改这里的人要知道**。
        self._apply_row_height()

        # 竖线要按**新的真实行高**重画
        self._draw_column_separators()

    def _apply_tree_row_height(self, tree_native: int) -> None:
        """把导航窗格的行高设成"文字高 × `row_ratio`"。

        ## 与列表那条**不是一回事**

        列表的 `LVM_SETITEMSPACING` 在 report 视图下是空操作（实测）；
        树控件的 `TVM_SETITEMHEIGHT` **实测一一对应**：设 20/24/28/32/40，
        回读就是 20/24/28/32/40（`tools/probes/probe_dialog_fonts.py` 第 ④ 段）。

        ## ⚠️ 它收的是**绝对高度** —— 所以**不要**去读"当前高度"再往上加

        第一版就是那么写的（"自然高 + 固定像素"，并把自然高缓存起来）。
        **它是错的**：高度一旦被改过，`TVM_GETITEMHEIGHT` 读回来的是
        **改后的值**，不是自然高。缩字号时我清掉缓存想重算，
        读回的却是上一步设的 40，于是行高变成 50、**比例从 1.429 漂到 2.000**。

        **正确做法：完全不用管"自然高"，直接从文字高按比例算目标。**
        字号怎么变，比例都锁死 —— 这也正是用户要的"同一种呼吸感"。
        """
        tree = self.dir_ctrl.GetTreeCtrl()
        dc = wx.ClientDC(tree)
        dc.SetFont(tree.GetFont())
        # 用 "Ag" 而不是含中文的串：**高度只由字体度量决定，与字符无关**；
        # 而带中文的字面量会被"漏掉 L() 的中文字符串"那条门禁拦下
        # （它不是界面文案，不该走翻译）。
        text_height = dc.GetTextExtent("Ag")[1]
        if text_height <= 0:
            return                      # 量不到就什么都不做，别写坏它

        target = int(round(text_height * METRICS.row_ratio))
        if not win32.set_tree_item_height(tree_native, target):
            # **判据是回读**（`set_tree_item_height` 里就是那么判的）：
            # 这一族消息"送达"与"生效"是两回事。
            self._report_resource_error(
                L(f"导航窗格行距没设上（量到 "
                  f"{win32.get_tree_item_height(tree_native)}px，"
                  f"期望 {target}px）",
                  f"Navigation pane row height not applied (measured "
                  f"{win32.get_tree_item_height(tree_native)}px, "
                  f"expected {target}px)"))

    def _apply_row_height(self) -> None:
        """用空图列表把列表行高抬到"文字高 × `row_ratio`"。

        见调用点那段注释：`LVM_SETITEMSPACING` 在 report 视图下无效，
        这是唯一能在**不改字号**的前提下加高行的办法。

        ## 为什么按**比例**算，不按"文字高 + 固定像素"

        用户指定的验收口径是"**视觉上的间隔比例**和导航窗格同步"，
        而两个窗格字号不同（列表 11pt、树 9pt），固定像素增量在视觉上
        并不等价。所以两边共用 :data:`METRICS.row_ratio`：

        ```
        目标行高 = round(文字高 × row_ratio)
        ```

        实测：列表 35 × 1.429 ≈ 50px、树 28 × 1.429 ≈ 40px ——
        正是用户认可的那两个值。

        ## ⚠️ 调用时机决定它有没有用

        行高按**本控件的文字高**算，所以**必须在列表字体设好之后调用**。
        踩过：`apply_window_theme()` 在 `set_global_font()` **之前**跑
        （`__init__` 里 227 行 vs 230 行），于是这里量到的是**系统默认字体**
        的高度（28px），算出 28+10=38 —— 而行高本来就是 39，
        **图列表小到不起作用，现象是"改了跟没改一样"**。

        所以 `set_global_font` 里设完列表字体之后**要再调一次**。
        """
        ctrl = getattr(self, "list_ctrl", None)
        if ctrl is None:
            return

        text_height = ctrl.GetTextExtent("Ag").height
        if text_height <= 0:
            return
        # 行高 = max(字号决定的高度, 图列表高 + 1)，所以图列表要比目标矮 1。
        icon_height = max(int(round(text_height * METRICS.row_ratio)) - 1, 1)

        # **这张位图必须是"全透明"的。**
        #
        # 它的**唯一作用是把行撑高**（report 视图的行高 = max(文字高, 小图标高)），
        # 内容本身不该被看见。而 `wx.Bitmap(1, H)` **创建后内容未定义**
        # （实测是黑的）——直接 Add 进去，report 视图就会给第 0 列
        # **每一行画一条 1px 宽的黑竖线**（用户报的"最左边有一条黑线"）。
        #
        # 修法：填成一个遮罩色并把它声明为遮罩 ⇒ 整张透明。
        #
        # ⚠️ 遮罩色用**洋红 `#FF00FF`**，不是黑色：
        # 黑色是真实内容里也会出现的颜色，拿它当遮罩会连正文里的黑点一起挖空。
        # 洋红在界面里不存在，是 Windows 图标遮罩的传统约定。
        blank = wx.Bitmap(1, icon_height)
        blank_dc = wx.MemoryDC(blank)
        blank_dc.SetBackground(wx.Brush(wx.Colour(255, 0, 255)))
        blank_dc.Clear()
        blank_dc.SelectObject(wx.NullBitmap)

        # **必须留住引用。** wx 的图列表是引用计数的，`SetImageList` 之后
        # 本地的 `wx.ImageList` 一旦被 GC，原生那边就指向一块已释放的内存。
        image_list = wx.ImageList(1, icon_height)
        image_list.Add(blank, wx.Colour(255, 0, 255))
        ctrl.SetImageList(image_list, wx.IMAGE_LIST_SMALL)
        self._row_height_image_list = image_list

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
        self._call_after(self._paint_column_separators)

    def _paint_column_separators(self) -> None:
        """真正落笔：按当前列宽在可见行区域画竖线（**只画竖线，不画横线**）。

        ## ⚠️ 第一件事是"窗口还活着吗"（2026-10-17 加的防御）

        用户看到测试时偶尔弹：

        > "python has stopped working / Error launching CrashSender.exe"

        `CrashSender.exe` 不是本项目带的（环境里搜不到），它是
        **Windows 错误报告**在进程真的崩了之后尝试启动的收集器 ——
        它启动失败才弹那个框。**那是"崩了"的二次症状。**

        真实链路：本方法由 `wx.CallAfter` 异步调度，而 `Destroy()`
        也是异步的 —— 排队的回调可能**在窗口销毁之后**才跑。
        那时 `wx.ClientDC(self.list_ctrl)` 拿到已失效的 HWND，
        GDI 调用触发**访问违例**（C 层崩溃，`except Exception` 抓不住）。

        所以进来先做两道检查：`_closing`（业务层已关闭）+ `IsBeingDeleted()`
        （窗口正在销毁）。**两道都要**：前者管"用户关了程序"，
        后者管"控件已提到销毁队列里"。
        """
        if not getattr(self, "show_column_separators", True):
            return
        # ① 业务层已关闭（`on_close` 设的）
        if getattr(self, "_closing", False):
            return
        # ② 控件已在销毁队列里 / 已经没了
        try:
            control = self.list_ctrl
            if control is None or control.IsBeingDeleted():
                return
            if not control.GetHandle():
                return
        except RuntimeError:
            # wx 的 C++ 对象已释放 —— 正是这里要防的那种情况
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

            # ## 颜色按区域区分 + 掩码线加粗（用户 2026-10-17 的最终形态）
            #
            # > "置顶条目和标题栏之间的分隔线、以及置顶条目的分隔线，
            # >   改成背景色……其他条目的分隔线就保持灰色不变。"
            # > "掩码线 vs 表头、置顶、普通灰线，它们的对比度我想全部统一成 1.6。"
            # > "请将掩码线适当加粗。"
            #
            # 于是竖线**按区域分段**，两段**只有颜色不同、粗细完全相同**：
            #
            # ==========  =====================  ========================
            # 区域        颜色                    粗细
            # ==========  =====================  ========================
            # 置顶段      `separator_pinned`      `METRICS.separator_thickness`
            # 普通段      `separator`             `METRICS.separator_thickness`
            # ==========  =====================  ========================
            #
            # **粗细统一是用户 2026-10-17 明确要求的**：
            # "表头和置顶颜色的粗细，和下面其他记录的粗细不统一。
            #  我想让它们全部统一起来，这样就可以一起调整。"
            # ⇒ 全表只有一个 `separator_thickness` 旋钮。
            #
            # ## 为什么用 `DrawRectangle` 而不是 `DrawLine`
            #
            # `DrawLine` 用宽 pen 时"往哪一侧扩展"由 GDI 决定、不可控。
            # 矩形能精确覆盖 `[left, left + thickness - 1]`，而 `left` 取
            # `列边界 − thickness` ⇒ **右边缘严格落在列边界上**。
            #
            # 这对加粗尤其重要：线宽 ≥ 2 时覆盖
            # `[列边界-thick, 列边界-1]`，**正好盖住那里露出的 1 像素
            # `theme.card` 杂色**（实测见 `probe_edge_pixel.py`）。
            # **粗细全部统一**（用户 2026-10-17）：
            # 表头、置顶段、普通段都用 `METRICS.separator_thickness`，
            # 改一个数整张表一起变。
            seam_th = thickness
            pin_span = self._pinned_span()

            def paint(left: int, y1: int, y2: int, colour: str, thick: int):
                if y2 <= y1:
                    return
                c = wx.Colour(colour)
                dc.SetPen(wx.Pen(c, 1))
                dc.SetBrush(wx.Brush(c))
                dc.DrawRectangle(left, y1, thick, y2 - y1)

            x = 0
            for index, width in enumerate(widths[:-1]):
                x += width
                if x <= 0 or x >= client.width:
                    continue
                if pin_span is None:
                    # 没有置顶行 ⇒ 一整条灰线，与旧行为一致
                    paint(x - seam_th, top, bottom,
                          self.theme.separator, seam_th)
                    continue
                pinned_top, pinned_bottom = pin_span
                # 置顶段（裁到可见范围）：掩码色
                seg_top = max(pinned_top, top)
                seg_bottom = min(pinned_bottom, bottom)
                paint(x - seam_th, seg_top, seg_bottom,
                      self.theme.separator_pinned, seam_th)
                # 普通段：灰色
                rest_top = max(pinned_bottom, top)
                paint(x - seam_th, rest_top, bottom,
                      self.theme.separator, seam_th)
        except Exception:
            # 自绘失败不该让整个列表坏掉
            pass

    def _pinned_span(self) -> tuple[int, int] | None:
        """置顶行在列表客户区里的**像素范围** ``(top, bottom)``；没有置顶行返回 None。

        用于 :meth:`_paint_column_separators` 分段画竖线：置顶段用置顶底色
        （线看不见），其余段用灰色。

        ## 为什么不用"行号 × 行高"算

        行高由系统决定（`LVS_GETITEMSPACING`），而且**滚动之后第一行的 y
        不再是 0**。直接用 `GetItemRect` 拿首尾两行的真实矩形最稳。

        ## 置顶行一定在顶部且连续

        `_ordered_records()` 保证：先 pinned、再 unpinned。所以只需从第 0 行
        往后找到**最后一个属于置顶集的连续行**，遇到非置顶就停 ——
        扫描次数上界是 `len(self.pinned_paths)`（通常个位数），不是 6000。
        """
        pinned = set(self.pinned_paths)
        if not pinned:
            return None
        total = self.list_ctrl.GetItemCount()
        if total <= 0:
            return None
        limit = min(len(pinned), total)
        last = -1
        for row in range(limit):
            if self.row_path(row) in pinned:
                last = row
            else:
                break
        if last < 0:
            return None
        first_rect = self.list_ctrl.GetItemRect(0)
        last_rect = self.list_ctrl.GetItemRect(last)
        if not first_rect or not last_rect or last_rect.height <= 0:
            return None
        return first_rect.y, last_rect.y + last_rect.height

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
        """确认"频次"列的**对齐方式**与列宽都合适。

        ## 对齐：原生格式位（不再补空格）

        用户 2026-10-17："频次这一列的数据是需要居中的，但是目前的算法不是
        真正的居中算法……切换中英文的时候会特别明显。"

        根因是"补前导空格"这个做法本身有**量化误差**：空格是离散单位，
        只能对齐到它的整数倍，再加上两次整除的取整 —— 中文列宽是奇数（89）时
        偏差最明显。

        现在居中由 `InsertColumn(format=wx.LIST_FORMAT_CENTER)` 的**格式位**
        负责，精确到像素。实测（`probe_native_center.py`，用 `LVM_GETCOLUMN`
        回读）：居中列 `0x4002`（`LVCFMT_CENTER`）、左列 `0x4000`、右列 `0x4001`
        —— 三种格式能区分，且渲染层文字位置确实不同。

        **历史上放弃原生居中的理由不成立**：当年测的是
        `LVM_SETCOLUMN`（改**已存在**的列，本环境返回 0），
        而 `InsertColumn` 走 `LVM_INSERTCOLUMN`，**创建时就带上 fmt，可用**。

        ## 列宽：仍要保证装得下最宽的频次值

        这条与对齐无关，是"数字不能被截断"。居中的列更不该被截断
        （截断会从右侧切掉，看着像偏了）。
        """
        widest = max((len(str(r.access_count)) for r in self._rows), default=1)
        needed = self.list_ctrl.GetTextExtent("8" * widest).width + 20
        if self.list_ctrl.GetColumnWidth(COLUMN_COUNT) < needed:
            self.list_ctrl.SetColumnWidth(COLUMN_COUNT, needed)
        return True

    #: 量列宽时**最多采样多少行**。
    #:
    #: 审计查出的性能问题：`fitted()` 对**每一行**调
    #: `GetItemText` + `GetTextExtent`（3 列 × N 行 = 3N 次跨语言原生调用），
    #: 而它**每次打开路径都要跑两遍**。记录数只增不减，几千条就是每点一下
    #: 上万次原生调用。
    #:
    #: 取前 N 行的最大值就够了：日期/时间的格式是固定的，宽度不会变；
    #: 频次列顶多位数不同，而"最宽的那一行"在前 200 行里几乎必然出现
    #: （列表本身按频次降序，最常访问的就在最前面）。
    #: 采样上限让这一步从 O(N) 变成 O(1)，代价是极端情况下列宽少几个像素
    #: ——列宽只是观感，不影响任何数据。
    COLUMN_WIDTH_SAMPLE = 200

    def adjust_column_widths(self) -> None:
        """按内容与可用宽度重算各列宽度（原版逻辑，列数从 3 增到 4）。

        ## 为什么要防重入

        审计实测：一次"打开一条记录"里这个方法被调 **5 次**，
        调用链是

            adjust_column_widths
              → SetColumnWidth
                → EVT_SIZE（列表内容宽度变了）
                  → _on_list_resized
                    → adjust_column_widths      ← 回到自己

        也就是说它**自己触发自己**，来回几轮直到宽度收敛。

        采样上限（见 `COLUMN_WIDTH_SAMPLE`）让每一轮都便宜，
        所以这不是性能问题；**问题是正确性**：内层那几轮是在
        列宽还没设完的状态下量出来的，量了也会被外层覆盖。

        加一个标志位，内层直接返回，只让最外层那一次做完。
        用 `try/finally` 而不是"设了记得还原"——中途抛异常时标志位
        要是留着的，这个方法就再也不会生效了，而且不会有任何报错。
        """
        if self._adjusting_columns:
            return
        self._adjusting_columns = True
        try:
            self._adjust_column_widths()
        finally:
            self._adjusting_columns = False

    def _adjust_column_widths(self) -> None:
        """真正做事的那个（**不要直接调它**，走 `adjust_column_widths`）。"""
        list_width = self.list_ctrl.GetSize().width
        if list_width <= 0:
            return

        extent = self.list_ctrl.GetTextExtent
        row_count = self.list_ctrl.GetItemCount()
        sample = min(row_count, self.COLUMN_WIDTH_SAMPLE)

        def fitted(column: int, header: str, extra: int = 40) -> int:
            """列宽 = max(表头宽, 采样到的单元格宽) + 边距。

            ## ⚠️ 表头宽**必须连"排序三角"一起量**（用户报的 2026-10-17）

            用户截图：英文界面下 `Count` 是当前排序列，标题后面那个 `▼`
            **压在了"Count"与"Date"之间的分隔线上**，甚至更右。

            **根因不是文案长**，是两处口径不一致：

            * 表头绘制那边：三角是**拼进文字**画的
              （`header._on_paint` 里 `label += " ▼"`）
            * 列宽计算这边：只量了**标题本身**

            ⇒ 三角那一段宽度**从来没进过列宽预算**。

            **为什么中文下看不出来**：中文"频次"只有 26px，英文"Count" 有 38px
            （100% DPI），而三角要再加 17px。所以列宽一紧，先溢出的总是英文。

            **为什么在高 DPI 更严重**：`extra` 是**固定物理像素**，
            而文字宽度随 DPI 线性放大。实测（本机两档对照）：

            ========  ======  ======  ======
            DPI       列宽    需要    余量
            100%      78      62      **+16**
            175%      106     108     **−2** ← 溢出
            ========  ======  ======  ======

            ⇒ 两个 DPI 下"看起来一样紧"，实际 175% 已经越界了。

            **修法必须动"量什么"，不能只改文案**：把标题换成更短的词
            （`Count` → `Freq`）只是**碰巧**盖住这 −2px，换个语言或调大字号
            就会再露出来。下面改为量"标题 + 三角"——**任何一列都可能变成
            排序列**，所以每一列都预留这段宽度。

            ## ⚠️ 但 `extra` 不能太大（用户随即报的第二个问题）

            > "可是现在 Count 这列又太宽了，会挤占本就很长的 Path 空间。
            >   中文'频次'本就很短，为英文多留的列宽换中文后就显得多余。"

            **`extra` 的几何含义就是"三角右缘到分隔线的空白"**
            （列宽 = `缩进 + 标题+三角 + extra`，余量恰等于 `extra`）。
            原来的物理 **40 ≈ 23 逻辑像素**，视觉上就是空了一大块，
            而这一列的数据只有 1~3 位数字，本不需要那么宽。

            实测（175% DPI，`probe_column_extra.py`）：

            ======  ==========  ==========  ======  ==============
            extra   英文频次宽   中文频次宽   余量    三列合计让给 Path
            40      137         116         28      0（原值）
            **20**  **117**     **96**      8       **80 物理像素**
            16      113         92          4       96
            12      109         88          0（贴线）112
            ======  ==========  ==========  ======  ==============

            取 **20**：余量 8 物理像素（≈5 逻辑）仍能呼吸、不贴线；
            三列合计还给 Path **80 物理像素（≈46 逻辑）**。
            再小三角就要贴着分隔线了 —— 那是拿观感换空间，不值。
            """
            # 三角的宽度取 `header.sort_arrow_width()` —— **唯一来源**。
            #
            # 早先这里是 `extent(header + " ▼")`，即"把字符三角拼进标题一起量"。
            # 那有两个问题：
            #   ① 字符宽度由字体决定（本机 23 物理 + 空格 7 = **30**），
            #      是纯开销，而且完全改不动；
            #   ② 一旦表头改成"画出来的三角"（`header.SORT_ARROW_SIZE`），
            #      这里就与绘制**不是同一个数**了 —— 两处口径再次分叉。
            #
            # **为什么必须压掉这 30 像素**（用户 2026-10-17）：
            # 中文"访问时间"(92) + 三角(30) = 122 → 时间列由**标题**定宽；
            # 英文 "Time"(54) + 三角(30) = 84 < 数据(90) → 由**数据**定宽。
            # 于是中文的这一列比英文宽 32 像素，**把频次列省下的宽度全吃掉**，
            # 切到中文时路径列反而变窄 —— 用户一眼就看出来了。
            # 三角现在是**字符**（用户要求换回，见 `header.SORT_ARROW_GLYPH`），
            # 宽度只能靠字体量 —— 所以把量具传进去。
            header_width = (extent(header).width
                            + sort_arrow_width(self.list_ctrl, dpi_of(self)))
            widths = [header_width]
            for row in range(sample):
                widths.append(extent(self.list_ctrl.GetItemText(row, column)).width)
            return max(widths) + extra

        # 列宽按**当前语言**的表头量。`COLUMNS` 里现在只有宽度与居中标记，
        # 标题要从 `column_labels()` 取——用 `COLUMNS[i][0]` 会拿到一个整数
        # （实测报 `GetTextExtent(): argument 1 has unexpected type 'int'`）。
        labels = column_labels()
        # **每列给不同的边距**（用户 2026-10-17 报的第二轮问题）。
        #
        # 余量（三角右缘到分隔线）= `extra − 左缩进`。所以：
        #
        # * 频次列的数据只有 1~3 位数字、标题也短 ⇒ 边距可以小
        #   （用 24：右留白 12，与左缩进 12 对称）
        # * **日期列不能跟着降** —— 它的数据本身就宽，边距一缩就
        #   "数据贴着分隔线、两列挤在一起"（用户原话"这两列的数据挨太近
        #   不能呼吸了"）
        #
        # 一刀切改 `extra` 正是我上一版犯的错：**为了让频次列变窄，
        # 把另外两列的呼吸空间也砍了。**
        #
        # ## 时间列是**最右一列**，右边没有分隔线要避让（用户 2026-10-17）
        #
        # > "访问时间（time）后面不需要留余量，因为这个数据本身就是最靠边的。
        # >   如果一定要留余量，也要留窄一些（比如只留 2 个或 4 个像素）。"
        #
        # 它右边是列表边缘（滚动条），不像其它列那样需要"别贴着竖线"。
        # 拿掉这 40 物理像素的留白，**全部让给路径列**（路径是唯一
        # "吃掉剩余宽度"的列，所以这里省下的会原样转到它身上）。
        #
        # ⚠️ **`extra` 不等于右留白**：`extra = 左缩进 + 右留白`
        # （列宽 = 内容 + extra，而内容从"左缩进"处开始画）。
        # 所以这里必须写成 `缩进 + 想要的留白`，直接写 4 会让
        # `右留白 = 4 − 12 = −5` —— **内容反而越界**，只是被绘制时的
        # 钳制掩盖了（三角被拉回列内、与标题重叠）。
        # 实测踩过：`probe_header_final` 的判据 2/4 同时报错才暴露出来。
        edge_pad = scale_for_dpi(METRICS.header_text_inset + 4, dpi_of(self))
        frequency_width = fitted(COLUMN_COUNT, labels[COLUMN_COUNT],
                                 extra=24)
        # 时间列现在同时含日期（`14:43   26-10-17`），并且**数据也居中了**。
        #
        # ## 边距与路径列**共用同一个单位**（用户 2026-10-17）
        #
        # 路径列靠"前导空格"撑出左边距、时间列靠"居中后自动对半分"，
        # 两套机制各算各的必然跑偏（实测 14 vs 15 像素）。
        #
        # 所以都以 `CELL_PADDING_SPACES` 个**空格宽**为单位：
        #
        # ```text
        # 路径左内边距 = 1 × pad        （PATH_LEFT_PAD 就是那么多个空格）
        # 时间列 extra = 2 × pad        （居中 ⇒ 左右各一半 = 1 × pad）
        # ```
        #
        # ⇒ 两边**恒等**。改 `CELL_PADDING_SPACES` 一个数，两处同时缩放。
        #
        # 注：`fitted` 的 extra 是"内容宽 + extra = 列宽"，而时间列的内容
        # 取 `max(标题+三角, 数据)`。实测两档语言下都是**数据更宽**，
        # 所以"居中后左右各 extra/2"这个推算是成立的。
        cell_pad = max(extent(" ").width * CELL_PADDING_SPACES, 1)
        time_width = fitted(COLUMN_TIME, labels[COLUMN_TIME],
                            extra=2 * cell_pad)

        self.list_ctrl.SetColumnWidth(COLUMN_COUNT, frequency_width)
        self.list_ctrl.SetColumnWidth(COLUMN_TIME, time_width)

        # 路径列吃掉剩下的宽度，但保留一个可读的下限（原版是 300）
        path_min_width = 300
        fixed_total = frequency_width + time_width
        path_width = max(list_width - fixed_total - 24, path_min_width)
        self.list_ctrl.SetColumnWidth(COLUMN_PATH, path_width)
        # 列宽变了，自绘表头必须跟着同步，否则与下面的列对不齐
        self._sync_header()
        # **列间竖线也要按新列宽重画**（它画在行的客户区上，不随列宽自动更新）
        self._draw_column_separators()
        # 注：频次列的居中现在由**原生列格式位**负责（`InsertColumn` 的
        # `format`），改列宽之后原生会自己按新宽度重新居中 ——
        # 不再需要"作废居中缓存"这一步（补空格的实现已删除）。

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
        # **正文/按钮/弹窗的字号只有一处定义**（`widgets.body_font`）。
        #
        # 以前这段 `+ 1` 是写在这里的，于是弹窗拿不到它——`wx.Dialog` 是独立
        # 顶层窗口，`SetFont` 传播过不去，回落到系统默认、比按钮小 1pt。
        # 用户实测看出来了。**不要再把这段算法抄回来。**
        body = widgets_body_font()
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
            # **设完字体必须重算行高。**
            #
            # `_apply_list_spacing` 里已经调过一次，但那时列表还是系统默认字体
            # （`apply_window_theme` 在 `set_global_font` 之前跑）——
            # 量到的文字高偏小，图列表就小到抬不动行高。
            # 现象是"我改了行距，看起来跟没改一样"。
            self._apply_row_height()

        # 自绘列头：**第三条独立的链**（正文 / 列表 / 列头）。
        #
        # 用户要求"访问的路径、频次、访问日期、访问时间这一栏的标题
        # 统一增大 1pt"——它原来跟的是 body_font（10pt），现在 11pt。
        #
        # **必须在 `_apply_body_font()` 之后设**：窗口级 `SetFont` 会向
        # 已存在的子控件传播，先设会被它覆盖（这个顺序坑踩过一次，
        # 见 `set_global_font` 的 docstring）。
        header = getattr(self, "header", None)
        if header is not None:
            header.SetFont(wx.Font(
                default_font.GetPointSize() + METRICS.header_font_point_delta,
                default_font.GetFamily(),
                default_font.GetStyle(),
                wx.FONTWEIGHT_NORMAL,
                False,
                default_font.GetFaceName(),
            ))
            header.Refresh()

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
            self._call_later(50, self.finalize_scroll_restore)
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
        self.scroll_timer = self._call_later(200, self.save_scroll_position)
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
        self._call_after(lambda: self._do_reset_horizontal_scroll(tree))

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
        # **声明"这次是用户在导航侧发起的操作"。**
        #
        # ⚠️ 2026-10-17 用户实测报回来的（与"双击树里的文件"是同一个根因）：
        #
        # > "现在**输入路径回车也是这个问题**，一并修了"
        #
        # `record_accessed_path` 里"把键盘焦点交给记录列表 + 把选中换到这条"
        # **整块都由 `from_tree` 把关**：
        #
        # ```python
        # from_tree = getattr(self, "_focus_pane", "") == "tree"
        # if from_tree:
        #     self.list_ctrl.SetFocus()      # ← 焦点转移只在这里面
        # ```
        #
        # 而**地址栏回车时焦点在地址栏的 TextCtrl 上**，`reveal_in_tree`
        # 只 `SelectItem` 树节点、**不碰焦点**（`SelectItem` 也触发不了
        # `EVT_SET_FOCUS`）⇒ `_focus_pane` 保持上一次的残留值（多半是 `"list"`）
        # ⇒ `from_tree` 为假 ⇒ **选中与焦点转移一起被跳过**。
        #
        # 实测（`tools/probes/probe_pathbar_enter_focus.py`）：回车后
        # 列表行数 +1（记录成功了）**但选中 = -1、一个像素都没上色、
        # 焦点仍在 TextCtrl** —— 与用户的描述一致。
        #
        # **必须写在 `reveal_in_tree` / `record_accessed_path` 之前**：
        # 后者读的是调用那一刻的值。
        self._focus_pane = "tree"
        # 用户的输入是文件夹还是文件，都记"实际访问的那个文件夹"——
        # 与 on_dir_item_activated 对文件的处理保持一致
        self.reveal_in_tree(folder, plan)
        # **打开了才记这次访问**（理由见 `on_open` 的 docstring）
        if self.open_folder(folder):
            self.record_accessed_path(folder)
        else:
            self._report_resource_error(
                L(f"打不开：{folder}（资源管理器拒绝了这次请求，"
                  f"或该位置已不可用）",
                  f"Could not open: {folder} (Explorer refused the request, "
                  f"or the location is unavailable)"))
        # **这两句不能把焦点抢回来。**
        # `set_value` 只改内容；`select_all` 是**故意**不抢焦点的那个
        # （区别于 `path_bar.focus()`，见 widgets.py 里它的 docstring）——
        # 所以焦点留在记录列表上，用户可以立刻用方向键。
        self.path_bar.set_value(folder)
        self.path_bar.select_all()

    def reveal_in_tree(self, folder: str, plan: dict | None = None) -> bool:
        """展开目录树到 ``folder`` 并选中它。

        :return: 是否在树里找到了对应节点（找不到时已尽力展开并给出兜底选择）

        ## ⚠️ 整段都包在 `quiet_expand()` 里（2026-10-25）

        `wx.TreeCtrl.Expand()` 会**同步**回调 `EVT_TREE_ITEM_EXPANDING`
        （`DirectoryTree._on_expanding`），而那个回调默认要把子项
        **连文件一起**建出来。沿路径展开一个像 ``C:\\Windows\\System32``
        那样的目录（4907 个条目、4708 个文件、192 ms）就是这么来的 ——
        而它只是为了把下面三级的 ``etc`` 显示出来。

        `quiet_expand()` 让这一整段里的展开都算"程序发起的"，
        于是大目录只建子文件夹（见 `tree_nav.DIRS_ONLY_ENTRY_THRESHOLD`）。
        **不要只包 `expand_to`**：下面 `tree.Expand(item)` 和 `TreeWalker`
        里那几处 `Expand` 是同一个机制（`Expand` 一被调用就同步回调）。
        """
        tree = self.dir_ctrl.GetTreeCtrl()
        names = (plan or build_walk_plan(folder, self.last_directory))["names"]

        self.dir_ctrl.Freeze()
        try:
            with self.dir_ctrl.quiet_expand():
                # **先试"沿路径展开"这条路。**
                #
                # 本树是懒加载的，深层节点在展开之前根本不存在 ——
                # 只靠下面的 `TreeWalker`（`GenericDirCtrl` 时代写的、
                # 假设树是 eager 的）会**半路停下**（实测只到 `C:\\Users`）。
                item = None
                if hasattr(self.dir_ctrl, "expand_to"):
                    item = self.dir_ctrl.expand_to(folder, select=False)
                walker = TreeWalker(tree)
                if item is None:
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

                # **只在"已经建出真实子项"时才展开。**
                # 程序主动不建的超大目录（`too_many_to_expand`）要**收起来** ——
                # 否则用户看到"展开着、下面只有一行空白"（2026-10-26 截图）。
                # 为什么是 Collapse 而不是"不 Expand"：兜底扫描
                # （`TreeWalker._children(expand=True)`）也会把节点展开，那时
                # "不展开"拦不住它 —— 收一次才能保证最终状态一致。
                if self.dir_ctrl.has_children_ready(item):
                    tree.Expand(item)
                else:
                    tree.Collapse(item)
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
        finally:
            self.dir_ctrl.Thaw()
        # **节点太多就整体重建一次，只保留当前这条路径。**
        #
        # 必须放在导航**结束之后**（`Freeze`/`Thaw` 之外、没有 item 还活着的时候）：
        # 重建会把所有旧 item 一次性作废，正在用的 item 不能还在手里。
        #
        # 为什么必须做（2026-10-25 实测，`tools/probes/probe_tree_inflate.py`）：
        # 6295 节点关闭 352 ms，**45746 节点关闭 10941 ms** ——
        # 用户"开着用几小时之后关程序要等十几秒"就是这个。
        if self.dir_ctrl.needs_trim():
            self._trim_tree()
        return True

    def _trim_tree(self) -> None:
        """整体重建目录树，只保留当前这条路径展开。

        ## 为什么"整体重建"是唯一安全的那种回收

        `populate()` 先 `DeleteChildren(root)`，所有旧 item **一次性**作废 ——
        此时没有代码还攥着它们（导航刚结束，选中与日志都在它之后按路径重新解析）。
        而"删一部分、留一部分"正是悬空句柄（`0xC0000005`）的来源：
        前一个人 6 次失败全在这一件事上（见交接文档第 4 节）。

        重建后 `populate(expand_path=...)` 会重新展开并选中当前路径，
        所以用户看到的是"其余分支收起来了"，而不是"树空了"。
        """
        path = self.dir_ctrl.GetPath()
        if not path:
            return
        self.dir_ctrl.populate(expand_path=path)
        # 重建后横向滚动条回到初始位置 —— 与 `reset_dir_ctrl_scroll` 一致
        self.reset_dir_ctrl_scroll()

    def on_tree_expanded(self, event) -> None:
        """用户自己在树里展开一个目录**之后**，检查一次节点总量。

        ## ⚠️ 必须推到下一轮事件循环

        `EVT_TREE_ITEM_EXPANDED` 是**同步**派发的（与 `EXPANDING` 一样，见
        `DirectoryTree.quiet_expand` 的说明）。在这里直接重建树，等于把
        **正在处理的这个节点本身**删掉 —— wx 处理完事件还会接着用它，
        那就是 `0xC0000005`。所以只**排一个**回调（`_trim_pending` 去重），
        真正重建在事件处理之外做。

        为什么需要它：`reveal_in_tree` 里那次检查只在"地址栏回车 / 双击文件"
        时跑，而用户完全可以只用左边的树浏览几小时 —— 他那次"关程序十几秒"
        就是这么来的（节点只增不减）。
        """
        event.Skip()
        if self._trim_pending or not self.dir_ctrl.needs_hard_trim():
            return
        self._trim_pending = True
        self._call_after(self._run_scheduled_trim)

    def _run_scheduled_trim(self) -> None:
        """`on_tree_expanded` 排下的那次重建（回调里再确认一遍条件）。"""
        self._trim_pending = False
        if self.dir_ctrl.needs_hard_trim():
            self._trim_tree()

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
        """导航窗格里的条目被激活（**双击鼠标 / 回车**）→ 文件则打开并记录其父目录。

        ## ⚠️ 为什么必须同时绑两个事件（2026-10-17 实测）

        用户报："**双击**导航窗格里的文件之后，焦点没有转移到记录窗格。"
        而我上一轮改的那一行**根本执行不到**，因为：

        **`wx.EVT_TREE_ITEM_ACTIVATED` 在 Windows 上双击时根本不发。**

        实测（`tools/probes/probe_tree_events.py`：给树的窗口发真的
        `WM_LBUTTONDOWN/UP/DBLCLK/UP`）：

        ```
        真双击收到的事件 = EVT_LEFT_DOWN, EVT_LEFT_UP, **EVT_LEFT_DCLICK**, EVT_LEFT_UP
        会发 EVT_TREE_ITEM_ACTIVATED 吗？   **不会**
        ```

        ⇒ 这条路原来**根本没接线**：双击文件既不打开、也不记录、焦点也不动 ——
        与用户描述的现象（"焦点一直停留在导航窗格"）完全一致。

        ## 为什么用 `HitTest` 取节点

        鼠标事件（`wx.MouseEvent`）**没有 `GetItem()`**（实测返回 `None`），
        节点只能由位置反查：

        ```
        ev.GetItem()                    → None
        tree.HitTest(ev.GetPosition())  → 正确的 TreeItemId   ✅
        ```

        所以两个事件共用本方法：带节点的（键盘激活）直接问，不带节点的走 `HitTest`。
        """
        tree = self.dir_ctrl.GetTreeCtrl()
        item = self._tree_item_of_event(tree, event)
        if item is None:
            event.Skip()
            return
        path = self.dir_ctrl.GetPath(item)

        if os.path.isfile(path):
            # **必须在 `record_accessed_path` 之前设。**
            # 它读的是调用那一刻的值，之后再设就晚了。
            self._focus_pane = "tree"
            folder_to_open = os.path.dirname(path)
            if os.path.exists(folder_to_open):
                # **打开了才记这次访问**（理由见 `on_open` 的 docstring）
                if self.open_folder(folder_to_open):
                    self.record_accessed_path(folder_to_open)
                else:
                    self._report_resource_error(
                        L(f"打不开：{folder_to_open}（资源管理器拒绝了这次请求，"
                          f"或该位置已不可用）",
                          f"Could not open: {folder_to_open} (Explorer refused "
                          f"the request, or the location is unavailable)"))
                self._call_later(100, self.reset_dir_ctrl_scroll)
            else:
                # **先问用户**（见 confirm_remove_invalid_path）
                self.confirm_remove_invalid_path(folder_to_open)
            # ## `Veto()` 只对 `wx.TreeEvent` 有（2026-10-17 修）
            #
            # 用户实测报错：
            #
            # ```text
            # File "app.py", line 2301, in on_dir_item_activated
            #     event.Veto()
            # AttributeError: 'MouseEvent' object has no attribute 'Veto'
            # ```
            #
            # 根因：本方法被**两个事件**共用（见它的 docstring）：
            #
            # * `EVT_TREE_ITEM_ACTIVATED`（键盘回车）→ `wx.TreeEvent`，**有** `Veto`
            # * `EVT_LEFT_DCLICK`（鼠标双击）→ `wx.MouseEvent`，**没有** `Veto`
            #
            # 结果：**每次双击文件都往 PowerShell 打一段 traceback**，
            # 但双击本身是好的（打开、记录都执行了，`Veto` 只是最后一句）。
            # 所以这是"噪音级"缺陷 —— 不影响功能，但会让人以为出事了，
            # 而且真出别的问题时会被这段刷掉的异常掩盖。
            #
            # `Veto()` 的意图是"别让树再做默认处理"。鼠标事件没有这个能力，
            # 也不需要有：文件节点没有子节点，"展开"本身无副作用。
            if hasattr(event, "Veto"):
                event.Veto()
        else:
            event.Skip()

    @staticmethod
    def _tree_item_of_event(tree, event):
        """从事件里取出被作用的树节点；取不到返回 `None`。

        两种来源**必须都支持**：

        * `EVT_TREE_ITEM_ACTIVATED`（键盘回车）—— 事件自带节点
        * `EVT_LEFT_DCLICK`（鼠标双击）—— 事件没有节点，只能 `HitTest` 反查
        """
        try:
            item = event.GetItem()
            if item is not None and getattr(item, "IsOk", lambda: False)():
                return item
        except (AttributeError, TypeError):
            pass
        try:
            found, _flags = tree.HitTest(event.GetPosition())
            if found is not None and getattr(found, "IsOk", lambda: False)():
                return found
        except (AttributeError, TypeError):
            pass
        return None

    # ------------------------------------------------------------------
    # 记录与列表
    # ------------------------------------------------------------------

    def record_accessed_path(self, path: str) -> None:
        """记一次访问，并刷新界面。

        ## 为什么是"读一次、排序一次"

        审计查出的性能问题：原来是

            self.load_accessed_paths()          # 读库 + 渲染 + 量列宽
            self.sort_list_items(self.sort_column)  # 再渲染一遍 + 再量一遍

        —— `sort_list_items` 内部已经会重新读库、重排、重画、重量列宽，
        所以第一句是**纯粹的多余工作**：整个列表被清空重建两次。
        每次双击/回车都要付这份代价，而记录数只增不减。

        `sort_list_items` 就是"读库 → 排序 → 渲染 → 量列宽"的完整入口，
        所以这里只要调用它一次（`reload_from_store=True` 让它先重读数据库）。
        """
        self.store.record_access(path)
        # **从导航窗格打开的：选中落到这条记录上，但视角不动。**
        #
        # 用户："聚焦对从导航窗格打开并记录的条目不生效。"
        # 他选定 B："列表视角保持不动，只要**选中对上**就行。"
        #
        # ⚠️ **把范围限死在 `"tree"`。**
        # 双击**列表**里那条路是已经验收过的行为（"位置完全不动、选中不丢"），
        # 不能顺手改掉。`on_dir_item_activated`（双击树里的文件）也是 `"tree"`，
        # 两种情况本来就该一致。
        from_tree = getattr(self, "_focus_pane", "") == "tree"
        # ── 开关式诊断（只在 FT_DEBUG_FOCUS 存在时打印）──
        #
        # 让**程序自己在真实环境里**说出状态，而不是我在探针里复刻场景。
        # 已经猜了六轮探针，每一轮都"绿"，而用户看到的始终不变 ——
        # 说明差别藏在我没想到的地方。
        #
        # ⚠️ **诊断的文案写在 `paint_trace` 里**，这里只留调用。
        # 原因是 `tools/verify_gui.py` 会扫本文件里"没包 `L()` 的中文"，
        # 而诊断输出是开发者看的、不该进双语表；把它放在专管诊断的模块里，
        # 两边都干净。
        paint_trace.focus_before(self, path, from_tree)
        if from_tree:
            self._keep_scroll_row = True          # 视角：行号口径，不动
            self._select_path_after_render = path  # 选中：换到这一条
        self.sort_list_items(self.sort_column, reload_from_store=True)
        # **把键盘焦点给"记录列表"，不是导航树。**
        #
        # ## 为什么不能给树
        #
        # **只有一个控件能拥有键盘焦点**，而没有焦点的列表控件，
        # Windows 会把选中行画成浅灰（inactive selection）——
        # **而且那个灰盖过我们用 `SetItemBackgroundColour` 设的底色。**
        #
        # | 谁有焦点 | 记录列表那条 | 导航树那条 |
        # |---|---|---|
        # | **列表** | **蓝** | 灰 |
        # | 树 | 灰 | 蓝 |
        #
        # 我上一轮为了让树的灰变蓝，给树 `SetFocus()` ——
        # **那正好把焦点从列表拿走，让记录器里那条变成了灰。**
        # 用户报的"从导航窗格打开后那条没有变蓝"就是这么来的。
        #
        # ## 为什么选列表
        #
        # 记录器那条**变蓝是"记录成功了没有"的反馈**，比树的选中更重要；
        # 而树失去焦点显示灰色，**是 Windows 标准行为**（资源管理器也一样）。
        #
        # ## ⚠️ 这一条只能靠实物判断，探针测不到
        #
        # `GetItemBackgroundColour()` 读的是**存进去的颜色**（永远是 `#0078D7`），
        # **与焦点无关** —— 所以四个探针全绿，用户看到的却始终是灰。
        # **仪器读的是"存了什么"，用户看的是"画成什么"。**
        if from_tree:
            try:
                self.list_ctrl.SetFocus()
            except (AttributeError, RuntimeError) as _error:
                paint_trace.focus_set_focus_failed(_error)
            paint_trace.focus_after(self)

    def load_accessed_paths(self) -> None:
        """从数据库重建列表：先顶置项，再按所选列排序的其余项。

        ## 为什么它只是"转调" `sort_list_items`

        审计查出的性能问题：这个方法原来做的是

            self._remember_view()
            self._rows = self._ordered_records()
            self._render_rows()
            self.adjust_column_widths()

        而 `sort_list_items` 做的是

            self._remember_view()
            self._rows = ...排序...
            self._render_rows()
            self.adjust_column_widths()
            self.center_frequency_column()
            self._sync_header()

        —— **后者是前者的超集**。于是"记一次访问"那段代码连续调两个，
        整个列表被**清空重建两遍**、列宽被量两遍。实测每次 500 行时
        约 12N 次跨语言原生调用，而记录数只增不减。

        现在只留一条路：`sort_list_items(reload_from_store=True)`。
        它做的比原来多出的两步（频次列居中、表头同步）本来就是
        重建之后该做的事——原来只有"点列头"那条路会做，
        "记一次访问"那条路漏了，于是**新记录上屏后频次列没有居中**。
        合并顺带修掉了这个不一致。
        """
        self.sort_list_items(self.sort_column, reload_from_store=True)

    def _top_visible_path(self) -> str:
        """最上面那一行对应的路径；列表为空或取不到时返回空串。

        `GetTopItem()` 在 report 视图下返回最上方**可见**行的索引。
        索引到路径的映射就是 `self._rows` —— 列表是照它建的。
        """
        try:
            index = self.list_ctrl.GetTopItem()
            if 0 <= index < len(self._rows):
                return self._rows[index].path
        except (AttributeError, IndexError):
            pass
        return ""

    def _selected_path(self) -> str:
        """当前**第一条**选中行对应的路径；没有选中返回空串。"""
        paths = self._selected_paths()
        return paths[0] if paths else ""

    def _selected_paths(self) -> list[str]:
        """当前**所有**选中行的路径（升序），从**控件自己的文本**取。

        ## ⚠️ 为什么不能用 `self._rows[index]`（2026-10-17 审计实测的 bug）

        原来这里写的是 `self._rows[index].path` —— 而 `index` 是**控件的行号**。
        一旦 `self._rows` 已经被换成新表、而控件还没重建，两者就**错位**：

        ```
        顶置一条记录（它被挪到第 0 行）
          → `sort_list_items` 先换 `self._rows`（第 0 行已是它）
          → 再调 `_render_rows`
            → 这里读控件选中 = 166，却去查**新** `_rows[166]`
              = 原来第 167 行的那条  ⇒ **选中差了一整行**
        ```

        实测（`tools/probes/probe_pin_focus.py`）：
        `顶置前 sel=166 dir-0166` → `顶置后 sel=166 **dir-0165**`。
        后果不只是高亮停在错的记录上 —— 之后右键「删除」删的是**隔壁那条**。

        ## 为什么"从控件读文本"是对的

        路径与行号的**权威映射就在控件里**：控件第 i 行显示的就是那条路径。
        `GetItemText` 拿到的是控件**当前真实显示**(的内容)，所以
        "行号 → 路径"这个转换天然自洽，不依赖 `self._rows` 是否已经换过。

        本方法只在"布局稳定"时被调（重建**之前**记锚点、或排序之后取集合），
        那时控件内容与 `self._rows` 最多差一次重建，而文本口径两种情况下都对。

        反过来说：**只有"行号 → 行号"的转换才怕错位**，
        `_index_of_path()`（路径 → 新行号）按定义就该用**新**表，那个不用改。
        """
        control = self.list_ctrl
        paths: list[str] = []
        try:
            index = control.GetFirstSelected()
            total = control.GetItemCount()
            while index != -1:
                if 0 <= index < total:
                    # **必须剥掉左内边距**（见 `_path_from_cell`）
                    text = self._path_from_cell(control.GetItemText(index))
                    if text:
                        paths.append(text)
                index = control.GetNextItem(
                    index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
        except (AttributeError, IndexError, RuntimeError):
            pass
        return paths

    def _index_of_path(self, path: str) -> int:
        """路径在新列表里的行号；找不到返回 -1。"""
        if not path:
            return -1
        for index, record in enumerate(self._rows):
            if record.path == path:
                return index
        return -1

    def _remember_view(self) -> None:
        """**在 `self._rows` 被替换之前**记下视角锚点。

        ## 为什么必须单独一步

        实测调用序：

        ```
        self._rows = self._ordered_records()   ← 已经是新顺序
        self._render_rows()                    ← 这里才取锚点就晚了
        ```

        `_top_visible_path()` 是 `self._rows[旧索引].path` ——
        **拿旧的视觉行号去查新的记录列表**。顺序一变就锚到别的记录上。

        ⇒ 调用方在改 `self._rows` **之前**调本方法。
        `_render_rows()` 消费它之后会清掉，不会串到下一次。
        """
        # **幂等：已经有锚点就不覆盖。**
        #
        # 探针实测（`tools/probes/probe_open_anchor.py`）：
        # `record_accessed_path` 里**两个分支各记了一次**，而第二次跑的时候
        # `self._rows` **已经被换掉了** —— `GetFirstSelected()` 还是 89，
        # 但行号 89 已经指向**另一条记录**，于是把第一次记对的那个覆盖成错的。
        #
        # ⇒ 第一次记的**一定**是"改动前"的视角（调用方都写在 `_rows`
        #   赋值之前）；第二、三次只可能更晚、更不可信。
        #
        # **与其去追"到底有几处会多调一次"，不如让"多调"本身无害。**
        # `_render_rows()` 消费之后会清掉，下一次循环照常重新记。
        if getattr(self, "_view_anchor", None) is not None:
            return
        self._view_anchor = (self._top_visible_path(),
                             self._selected_path())
        # **同时记下"当时的顶行行号"。**
        #
        # 取消置顶走"按行号保持"（见 `_keep_scroll_row`）——
        # 路径口径在那时会跟着记录跑到字母序原位，把整块置顶项带出屏幕。
        try:
            self._view_anchor_row = self.list_ctrl.GetTopItem()
        except (AttributeError, IndexError):
            self._view_anchor_row = 0

    def _render_rows(self) -> None:
        """重建列表，**保持视角与选中**，并尽量**不让用户看到中间过程**。

        ## 三段的分工（这个切分是踩出来的）

        ====================  ============================================
        段                    为什么在这儿
        ====================  ============================================
        取锚点                 必须在 `self._rows` 换掉**之前**
        `Freeze` + 重建        最重、最容易闪（`DeleteAllItems` + N 次插入）
        `Thaw` 后：选中 + 回位   **必须解冻后才能做**，见下
        ====================  ============================================

        ## ⚠️ 回位为什么不能在冻结里

        用户报过："**原本搞好的聚焦和准确选中，这下全乱了**" ——
        那一版我把整段都包进了 `Freeze`/`Thaw`。

        原因是控件冻结期间：

        * `GetTopItem()` 返回**冻结前的旧值**
        * `ScrollLines()` **不真正滚动**（滚动状态要等解冻才更新）

        ⇒ 回位那一段**静默失效**：不报错，但什么也没做。

        而"选中 + 回位"只改两个属性、不做重活，**本身不会闪** ——
        把它们放到解冻之后，既保住了效果，又不影响"隐藏中间过程"。

        **判据**：`Freeze` 里只允许**改内容**，不允许**读写滚动状态**。
        """
        anchor, selected = getattr(self, "_view_anchor", None) or (
            self._top_visible_path(), self._selected_path())
        self._view_anchor = None
        # **把选中换到指定的一条**（用于"从导航窗格打开并记录"）。
        #
        # 前三个动作（双击列表、置顶、取消置顶）里，
        # "选中的那条"和"动作作用的那条"本来就是同一个；
        # 只有从导航窗格打开时不是 —— 用户在左边点的路径，
        # 在右边可能是任意一行。用户要的是"**选中对上就行**"（他选的 B）。
        #
        # ⚠️ **必须写在外壳这一层**（`_render_rows`）。
        # 下面恢复选中用的是**外壳的** `selected`；
        # 我第一次把它写进了内层 `_render_rows_body`，
        # 那里只是改了个**用不到的局部变量** ——
        # 探针显示"覆盖值设了、数据也在、选中却没换"，就是这么来的。
        override = getattr(self, "_select_path_after_render", None)
        self._select_path_after_render = None
        if override:
            selected = override

        # **把"要恢复的选中集"先算出来（用路径，不是行号）。**
        #
        # 重建之后行号会变，所以锚点与选中一律走**路径**口径。
        # `_select_path_after_render`（从导航窗格打开）是**明确只要一条**的
        # 意图 ⇒ 它覆盖掉多选集，符合用户选的"打开时选中对上就行"。
        keep_paths = [selected] if override else self._selected_paths()
        target_rows = [index for index in
                       (self._index_of_path(path) for path in keep_paths)
                       if index >= 0]

        # **只冻结"重建"这一段。**
        # `try/finally` 是必须的：`Thaw()` 漏掉的话控件会**永久冻结**，
        # 那比闪烁严重得多。
        self.list_ctrl.Freeze()
        try:
            self._render_rows_now()
        finally:
            self.list_ctrl.Thaw()

        # **解冻之后**才恢复选中与视角 —— 见 docstring 里那段说明。
        # **顺序有讲究**：先恢复选中，再恢复视角。
        # 反过来做的话，`EnsureVisible(选中行)` 可能又把视角拉走。
        #
        # ⚠️ **"全清"必须无条件执行，不能只在 `target_rows` 非空时做。**
        #
        # 用户 2026-10-17 报的 bug：
        #
        # > "多选并删除后，多选状态会**偏移到另外多条记录**上，不会自然消失。"
        #
        # 根因就是原来这两段共用了一个 `if target_rows:`：
        # 删除之后，原来那些选中行的**路径已经不在库里**了 ⇒
        # `target_rows` 是**空的** ⇒ 连带"全清"也被跳过 ⇒
        # 原生控件里那些**陈旧的选中行号**留了下来，而行号已经平移
        # （后面的行往上补），于是"选中框跑到了隔壁几条记录上"。
        #
        # ⇒ 拆开：**先无条件全清**（重建之后任何残留选中都是陈旧的），
        #   **再**决定要不要恢复。
        #
        # ⚠️ 这里**不能**用 `unselect_all_rows()`（那个只清"当前选中的"）——
        # 重建之后原生控件的选中可能与我们的认知不一致，
        # 所以这里要**逐行核对**：凡是不在 `wanted` 里的，一律清掉。
        # 但仍然先问 `GetItemState`（只读、便宜），避免对没选中的行白调 API。
        #
        # **拖拽期间要挂起事件**：否则 6000 行里清掉 6000 个选中时，
        # 每一个 DESELECTED 都可能引起一轮重画。
        total = self.list_ctrl.GetItemCount()
        wanted = set(target_rows)
        selected_state = wx.LIST_STATE_SELECTED
        self._suspend_selection_events = True
        try:
            for index in range(total):
                if index in wanted:
                    continue
                if self.list_ctrl.GetItemState(index, selected_state) & selected_state:
                    self.list_ctrl.Select(index, False)
        finally:
            self._suspend_selection_events = False
        if target_rows:
            # **用 `SetItemState` 一次设好"选中 + 焦点"，不要用 `Focus()`。**
            #
            # ## 探针实测：`Focus()` 会把视角滚走
            #
            # `tools/probes/probe_scroll_anchor.py` 逐步量过：
            #
            # ```
            # ① 重建之后          top=0    sel=-1
            # ② 全清之后          top=0    sel=-1
            # ③ Focus 之后        top=262  sel=285   ← 视角被挪走 262 行
            # ④ ScrollLines(-2)   top=260  sel=285   ← 又拉回来
            # ```
            #
            # `wx.ListCtrl.Focus(i)` 会**把第 i 项滚动到可见**。而"选中项"
            # （用户双击的那条）与"视角锚点"（他看到的顶行）本来就是
            # **两个不同的位置** —— 于是列表先跳到选中项、再被拉回来，
            # 用户看到一次明显的跳动（他说的"**聚焦偏移加大**"）。
            #
            # `SetItemState` 直接写项状态，**不触发 ensure-visible**。
            # 焦点仍然要设 —— 它决定**方向键从哪儿继续**，
            # 只是不能用 `Focus()` 那个会滚动的接口去设。
            #
            # **多选：每一条都要设，但 `FOCUSED` 只给一条。**
            # 原生 ListView 里 `LVIS_FOCUSED` 是**单选**语义（焦点框只有一个），
            # 全给上会互相顶掉；`SELECTED` 才是可以多条的。
            focus_row = target_rows[-1]
            for row in target_rows:
                states = wx.LIST_STATE_SELECTED
                if row == focus_row:
                    states |= wx.LIST_STATE_FOCUSED
                self.list_ctrl.SetItemState(row, states, states)
            # **设完选中要再画一次高亮。**
            #
            # 这个项目的蓝色选中**不是原生画的** —— 是
            # `_apply_selection_highlight()` 用 `SetItemBackgroundColour`
            # 自己画的（原生高亮被逐行显式底色压掉了）。
            # 而它在**重建过程中**跑，那时上面这个选中还没设。
            #
            # 不补这一句的后果：**选中状态对了，但没有蓝色** ——
            # 用户报的"记录器中这条变更的条目没有被选中为蓝色"。
            # ⚠️ **先清掉它的记忆键，否则这一句会被早退吃掉。**
            #
            # `_apply_selection_highlight()` 里有：
            #
            #     key = (selected, hovered)
            #     if key == self._paint_key:
            #         return            # ← 一个像素都不画
            #
            # 它假设"key 一样 ⇒ 画面已经对了"。但**实际底色会被重建、
            # Refresh、换主题等重置**，而账本不会 —— 一旦不同步，
            # 那一行就**永远不变色**。它的 docstring 自己写着：
            # "账本一旦和渲染逻辑不同步，就会留下永远不变色的行"。
            #
            # 用户报的正是这个："选中确实在它身上，但高亮被盖掉了。"
            #
            # ⇒ 我这一次调用**明确知道账本可能过期**，所以先清键。
            # 保留记忆化本身（它挡的是悬停时的高频重设，有必要）。
            self._paint_key = None
            try:
                self._apply_selection_highlight()
            except (AttributeError, RuntimeError):
                pass
        # **精确滚回原位，不要用 `EnsureVisible`。**
        #
        # `EnsureVisible` 是"保证可见"（最小滚动）：锚点落在视野**下方**时，
        # 它只滚到锚点**刚从底边露出来**为止 —— 用户看到的就是"跳了一下"。
        #
        # 用户要的原话："**它的位置是完全不动的**。"
        # 所以直接算差值滚回去：`delta = 锚点行号 − 当前顶部行号`。
        # **顺序没变时 delta == 0，一行都不滚** —— 那正是理想效果。
        # **取消置顶走这条：按"行号"保持，不跟路径。**
        #
        # 用户："A，这就是 1.3.0 的取消置顶聚焦状态。"
        # 他要的是**视角完全不动**，而不是跟着那条记录跑到字母序原位
        # —— 那会把整块置顶项带出屏幕（他报的"大幅变动"）。
        #
        # **不能"什么都不做"**：`DeleteAllItems` + 重建本身就把滚动清零了，
        # 不做等于跳回最顶端，更糟。所以显式把行号设回去。
        row_mode = bool(getattr(self, "_keep_scroll_row", False))
        if row_mode:
            self._keep_scroll_row = False
            self._focus_path_after_render = None   # 行号口径下不叠加"聚焦到某条"
            try:
                want = max(int(getattr(self, "_view_anchor_row", 0)), 0)
                delta = want - self.list_ctrl.GetTopItem()
                if delta:
                    self.list_ctrl.ScrollLines(delta)
            except (AttributeError, IndexError, TypeError, ValueError):
                pass

        # 按行号保持时**跳过**路径口径 —— 两个口径只能生效一个
        anchor_index = -1 if row_mode else self._index_of_path(anchor)
        if anchor_index >= 0:
            try:
                delta = anchor_index - self.list_ctrl.GetTopItem()
                if delta:
                    self.list_ctrl.ScrollLines(delta)
            except (AttributeError, IndexError):
                # 取不到顶部行号就退回"保证可见"，总比跳回顶部好
                self.list_ctrl.EnsureVisible(anchor_index)

        # **"强制聚焦到某条"要放在最后 —— 它是覆盖，不是并列。**
        #
        # 用于**置顶**：条目跳到了最顶端，光"保持视角"会让用户以为没置顶成功
        # （他得往上翻才看得见）。所以置顶要走这一条：
        # 视角**跟着条目走**，落到它现在的位置上。
        #
        # **取消顶置不设这个意图** —— 那时条目还在附近，位置不该跳。
        focus_path = getattr(self, "_focus_path_after_render", None)
        self._focus_path_after_render = None
        if focus_path:
            focus_index = self._index_of_path(focus_path)
            if focus_index >= 0:
                try:
                    # 滚到"该行贴顶"。`EnsureVisible` 只会把它拉进视野
                    # （可能贴着底边），而置顶后它就在最前面，贴顶才对。
                    delta = focus_index - self.list_ctrl.GetTopItem()
                    if delta:
                        self.list_ctrl.ScrollLines(delta)
                except (AttributeError, IndexError):
                    self.list_ctrl.EnsureVisible(focus_index)



    def _render_rows_body(self) -> None:
        """重建列表、恢复选中、回位 —— **不要在未冻结时调用它**。

        ## 用户报的现象

        "双击打开一条路径之后……记录窗格**又回到最开头了**。
        这是因为程序刷新时，会把用户所在的视角一并刷新。"

        **重排本身是对的**（频次和时间确实变了），问题在于重建之后
        视角被重置。翻到下半页双击一条，回来就跳回顶部 —— 很难用。

        ## 怎么做到"刷新前后不要有太大变化"

        1. 重建**前**记下最上面那一行的**路径**（不是行号 —— 行号会变）
        2. 重建**后**按路径找到它的新行号
        3. `EnsureVisible()` —— **它只做最小滚动**：
           那一行还在视野里就**一动不动**；被排出去了才滚到刚好可见

        所以用户看到的是"列表内容更新了，但我的位置没变"，
        而不是"页面跳回顶部"。

        选中行也一并保住 —— 用户刚双击打开的那条不该失去高亮。
        """
        # 优先用调用方**提前**记下的锚点（那才是"改动之前"的视角）；
        # 没提前记就现取 —— 那种情况下至少不比什么都不做强。
        anchor, selected = getattr(self, "_view_anchor", None) or (
            self._top_visible_path(), self._selected_path())
        self._view_anchor = None
        self._render_rows_now()
    def _render_rows_now(self) -> None:
        """把 :attr:`_rows` 画到列表上。

        ``_rows`` 是界面里的**真相来源**：``wx.ListCtrl`` 按行号取值，
        而排序在 Python 这边做，所以排序后行号会变——持有一份有序列表
        比"每次都去控件里读回来"更可靠。

        ## ⚠️ 已知：记录数大时这一段是瓶颈（**尚未解决**）

        实测（`tools/probes/probe_scale_profile.py`，6000 行）：

        ==========================  ==========  ==========
        分段                         耗时        调用次数
        ==========================  ==========  ==========
        **`InsertItem`**            **1533 ms**  **6000**
        `SetItem`                     104 ms       18000
        `SetItemBackgroundColour`      80 ms        6000
        量列宽（已有采样上限）            61 ms           2
        读库 `load_unpinned`            13 ms           1
        ==========================  ==========  ==========

        总计约 **2 秒**，而每次双击/回车都要付一次；规模-耗时近线性
        （200 行 124 ms → 3000 行 994 ms → 6000 行 1906 ms）。

        **瓶颈是逐行 `InsertItem`（约 0.26 ms/行），不是读库、不是量列宽。**
        所以"限制记录条数"治不了根：5000 行仍要 1.3 秒。

        真正的解法是**虚拟列表**（``wx.LC_VIRTUAL`` + ``OnGetItemText``），
        只渲染可见行。但那是一次**有风险的改造**：虚拟列表**不支持**逐项
        ``SetItemBackgroundColour`` / ``SetItemTextColour``——而整行高亮、
        预选跟随、顶置黄底全都依赖它们。本方法、`_apply_selection_highlight`、
        `_paint_column_separators` 都要跟着改，属于"改完必须全面重验"的那一类。

        所以这里**先把测量结果留下来**，不动手——不为了"看起来做完了"
        而做一个改坏外观的改动。要动的话，先读
        `tools/probes/README.md` 里"列表规模那一组"。

        ## 字体层级

        用户要求"主信息/次要信息区分"：路径用**正文 + 粗体**，
        频次与时间用**小一号 + 次要色**。这三条 ``SetItemTextColour``
        都包在 ``try`` 里——原生控件对项级字体/颜色支持因版本而异，
        不支持时**退化成无层级**，而不是让整个列表画不出来。
        """
        self.list_ctrl.DeleteAllItems()
        pinned_set = set(self.pinned_paths)
        for record in self._rows:
            # **日期并进时间列**（用户 2026-10-17）：
            # `2026-10-17 14:43:27` → `14:43   26-10-17`
            # （秒隐藏、两位年份、3 空格分隔 —— 见 `store.format_time_cell`）
            time_text = format_time_cell(record.last_access_time)
            index = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(),
                                              PATH_LEFT_PAD + record.path)
            self.list_ctrl.SetItem(index, COLUMN_COUNT,
                                   str(record.access_count))
            self.list_ctrl.SetItem(index, COLUMN_TIME, time_text)
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
        # **`_paint_key` 也必须一起作废。**
        #
        # 审计查出的问题：`_apply_selection_highlight` 用
        # ``(selected, hovered)`` 做记忆，两者都没变就**整段跳过**
        # （那是性能优化，见那里的注释）。而重建之后
        # **行号相同、内容却换了一条**——于是那个"没变"的判断是假的，
        # 高亮会被跳过，直到鼠标移动才补上。
        # 用户看到的是"某一行的底色不对，动一下鼠标才好"。
        self._paint_key = None
        self.list_ctrl.Refresh()
        # 重建后可能有残留选中，重新套一次高亮
        self._apply_selection_highlight()

    def on_selection_changed(self, event) -> None:
        """选中状态变了 → 重画整行高亮。

        **`event.Skip()` 必须调**：不放手的话原生控件收不到这次事件，
        选中动作本身会被吞掉（那一行根本选不上）。

        ## 拖拽期间挂起

        拖拽时 `_select_range()` 会**逐行** `Select()`，每一行都发一次
        `EVT_LIST_ITEM_SELECTED` / `DESELECTED` ⇒ 这个方法被连着叫很多次，
        而它每次都重画一轮（虽然 `_paint_key` 会挡住重复的，但事件处理
        本身有开销）。拖拽结束时由 `on_list_left_up` 统一补一次重画。
        """
        event.Skip()
        if getattr(self, "_suspend_selection_events", False):
            return
        self._apply_selection_highlight()

    # -- 预选（悬停跟随）--------------------------------------------------

    def on_list_motion(self, event) -> None:
        """鼠标在列表上移动 → **拖拽选择**（按住左键时）或更新"预选"行。

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

        ## 拖拽选择也走这里（2026-10-17）

        原生拖拽框选在本控件上不可用（见 `on_list_left_down` 的说明），
        所以"按住左键拖动 = 选中一个行区间"由这里实现。
        **拖拽期间不再画预选**：那一刻用户要的是选中，不是预选。
        """
        event.Skip()
        if getattr(self, "_drag_origin_row", -1) >= 0:
            self._handle_drag_motion(event)
            return
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
        """鼠标离开列表 → 收掉预选高亮（**拖拽中不处理**，见下）。"""
        event.Skip()
        if getattr(self, "_drag_origin_row", -1) >= 0:
            # 拖拽时鼠标很容易滑出控件边界（尤其往边上拖），
            # 这时候收掉预选没有任何意义，而且会打断拖拽的视觉反馈。
            return
        self._set_hover_row(-1)

    # -- 拖拽多选（自己实现）-----------------------------------------------

    #: 判定"这是拖拽"而不是"这是单击"的像素阈值。
    #: 手会抖，取 4 像素：小于它算单击（交给原生），大于它算拖拽。
    DRAG_THRESHOLD_PX = 4

    def on_list_left_down(self, event) -> None:
        """记下拖拽的起点。**不移交事件** —— 单击选择仍由原生处理。

        ## ⚠️ 为什么要自己做

        用户要"按住 CTRL 多选，**并且不止可以点击多选，还可以拖动多选**"。

        Ctrl / Shift 点击是**原生支持**的（清掉 `LVS_SINGLESEL` 之后实测
        `[1, 4]` / `[2,3,4,5,6]`）。但**拖动框选不行**：

        `tools/probes/probe_multiselect_drag.py` 试了 7 种组合
        （`MK_LBUTTON` 有无、步数与延时、`SetCapture`、预先选中起点、
        `LVS_EX_DOUBLEBUFFER`、混合）——**每一种都只选中按下那一行**。

        ⇒ 所以拖拽这一段自己实现：**按下记起点，移动超过阈值后
        按行区间选中**。单击（没超阈值）时**什么都不做**，
        让原生的单击/Ctrl 点击/Shift 点击照常工作 —— 两边不打架。

        阈值用**像素距离**而不是"是否移动过"：手会抖，
        用"移动过就算拖"会把每次单击都变成拖拽。
        """
        try:
            position = event.GetPosition()
            row, _flags = self.list_ctrl.HitTest(position)
        except Exception:
            row, position = -1, None
        self._drag_origin_row = row
        self._drag_origin_pos = position
        self._dragging = False
        # **差集法要有个干净的起点**：不清的话，上一次拖拽留下的区间
        # 会被当成"上一帧"，新拖拽第一帧就会去取消一批早就没选中的行
        # （功能仍对，但白跑一趟，而且拖回头时可能把不该取消的取消掉）。
        self._drag_prev_rows = None
        event.Skip()

    def on_list_left_up(self, event) -> None:
        """结束拖拽；**没进入拖拽就什么都不做**（让原生单击照常）。"""
        was_dragging = getattr(self, "_dragging", False)
        self._drag_origin_row = -1
        self._drag_origin_pos = None
        self._dragging = False
        self._drag_prev_rows = None
        if was_dragging:
            # 拖拽结束后重画一次：拖拽期间我们直接改了选中集，
            # 而没有走 `_apply_selection_highlight` 的常规入口。
            self._paint_key = None
            self._apply_selection_highlight()
        event.Skip()

    def _handle_drag_motion(self, event) -> None:
        """按住左键移动 → 按"起点行 .. 当前行"选中整个区间。"""
        try:
            position = event.GetPosition()
            # **判断"左键还按着"要用事件自带的标志位，不能用
            # `wx.GetMouseState()`。**
            #
            # ⚠️ 实测（2026-10-17）：`wx.GetMouseState()` 读的是**系统级
            # 真实鼠标状态**，而 `SendMessage` 发的 `WM_MOUSEMOVE`
            # 并不会改变它 —— 于是拖拽的第一帧就被当成"左键已松开"，
            # `_drag_origin_row` 被清成 -1，拖拽整个过程一次都没跑起来
            # （探针读数：`_dragging` 始终 False、只选中按下那一行）。
            #
            # 但**真实拖动**时这个标志位是对的：
            # 真实拖动产生的消息会更新系统鼠标状态，两者一致；
            # 而探针发的消息不改系统状态，所以只有事件标志位可信。
            # ⇒ 取事件标志位，取不到再退回系统状态。
            left_down = None
            try:
                left_down = event.LeftIsDown()
            except Exception:
                left_down = None
            if left_down is None:
                try:
                    left_down = wx.GetMouseState().LeftIsDown()
                except Exception:
                    left_down = True
            if not left_down:
                # 左键已经松开（`LEFT_UP` 可能没送到我们这里）——
                # 收尾，避免"状态卡在拖拽中"导致以后每次移动都在选中。
                self._drag_origin_row = -1
                self._drag_origin_pos = None
                self._dragging = False
                return
            origin = self._drag_origin_pos
            if not self._dragging:
                if origin is None:
                    return
                moved = (abs(position.x - origin.x) + abs(position.y - origin.y))
                if moved < self.DRAG_THRESHOLD_PX:
                    return
                self._dragging = True
            row, _flags = self.list_ctrl.HitTest(position)
            if row < 0:
                return
            self._select_range(self._drag_origin_row, row)
        except Exception:
            # 拖拽是纯交互增强：出错时退化成"原生单击"，不把异常抛到事件循环里
            self._drag_origin_row = -1
            self._dragging = False

    def unselect_all_rows(self) -> None:
        """取消**当前真正被选中**的那些行（不是盲扫全表）。

        ## 为什么不能盲扫全表

        项目的做法原来是"`for i in range(GetItemCount()): Select(i, False)`" ——
        对于**没选中**的行，这一次调用是纯浪费，而它是**跨语言原生调用**。

        更糟的是：`Select()` 会触发 `EVT_LIST_ITEM_DESELECTED` / `SELECTED`，
        挂在上面的 `on_selection_changed` 就会去重画高亮。6000 行里只有 3 行
        选中时，那 5997 次调用**每一次都可能引发一轮重画**。

        ⇒ 先问一句 `GetItemState`（只读、便宜），**只对选中的行**动手。
        选中集通常是个位数，于是这一步从 O(全表) 降到 O(选中数)。

        ## ⚠️ 但"选中集很大"时上一条还不够（2026-10-17 实测）

        `Ctrl+A` 全选之后，选中集就是全表 —— 那 6000 次 `Select(False)`
        每一次都会触发 `on_selection_changed` → 重画全表 = **O(n²)**。
        实测 **166414 ms（166 秒）**，表现为"Ctrl+A 之后按 Esc 卡死三分钟"。

        ⇒ 循环期间挂起选中事件（与 `_select_range` 同一个标志），
        循环结束**统一重画一次**。修完降到 **约 200 ms**（三个数量级）。
        """
        control = self.list_ctrl
        self._suspend_selection_events = True
        try:
            total = control.GetItemCount()
            selected_state = wx.LIST_STATE_SELECTED
            for index in range(total):
                if control.GetItemState(index, selected_state) & selected_state:
                    control.Select(index, False)
        except Exception:
            # 纯外观操作：失败时退化成"没清掉"，不影响数据
            pass
        finally:
            # **必须复位**：留着的话之后所有点击都不再重画高亮（且不报错）
            self._suspend_selection_events = False
        # 挂起期间没人重画 —— 这里补一次，否则那几行的蓝底会留在屏上
        self._apply_selection_highlight()

    def _select_range(self, row_a: int, row_b: int) -> None:
        """把 `row_a..row_b` 这一整段设成"选中"，其余取消选中。

        ## ⚠️ 只动"和上一帧不一样"的那几行（性能，2026-10-17 实测）

        第一版是"**每次都把全表 `Select()` 一遍**"（先全清、再选区间）。
        功能对，但**拖动时每一帧都要全表走一次** —— 6000 行实测：

        ```
        拖拽一帧 = 888.8ms      ← 一帧 0.9 秒，拖起来是卡死的
        ```

        优化成"**只改差集**"：维护 `_drag_prev_rows`（上一帧画成选中的行），
        这一帧只调**需要翻转状态**的那些行。

        * 用户慢慢往下拖：每帧只多一行 ⇒ **O(1)**
        * 用户往回拖：每帧只少几行 ⇒ O(几行)
        * 跳着拖（快速划过一大段）：O(那一段)

        ⇒ 复杂度从 **O(全表)** 降到 **O(这一帧真正变化的行数)**。

        ## 为什么不用"先全清再选区间"

        `wx.ListCtrl.Select(i, on)` 底层是 `LVM_SETITEMSTATE` ——
        **不碰别的行**。所以"取消选中"必须自己逐行做，不能靠一次全清。
        差集法正好：要取消的本来就只有"上一帧选了、这一帧不该选"的那几行。

        ## 为什么不能只"画颜色"不改选中

        选中状态是**原生的**（Ctrl 点击、Shift 点击都靠它），
        右键菜单、`selected_paths()` 读的也是它 ——
        只改颜色会让"看起来选中了、实际没选中"。
        """
        total = self.list_ctrl.GetItemCount()
        low, high = min(row_a, row_b), max(row_a, row_b)
        low, high = max(low, 0), min(high, total - 1)
        if low > high:
            return
        want = set(range(low, high + 1))
        previous = getattr(self, "_drag_prev_rows", None) or set()
        if want == previous:
            # 区间没变（同一帧内多次移动、或原地抖动）—— 一行都不用碰
            return
        # ## ⚠️ 取消与选中**必须一起挂起**（2026-10-17 性能缺陷）
        #
        # 上一版只把 `Select(True)` 那半包进了挂起，`Select(False)` 那半
        # 留在**外面** —— 于是"缩小选区"这一支是 **O(k × n)**：
        # 每取消一行都触发一次 `on_selection_changed` → 重画全表。
        #
        # 实测（6000 行）：全选后再清空要 **166414 ms（166 秒）**。
        # 而"全选"只有 209 ms —— 两支差了三个数量级，差别就在这个标志。
        #
        # 现在两支都挂起，循环结束后由调用方统一重画一次。
        # 用 try/finally：中途抛异常时标志位必须复位，
        # 否则之后所有点击都不会再重画高亮（而且不会有任何报错）。
        self._suspend_selection_events = True
        try:
            for row in previous - want:
                self.list_ctrl.Select(row, False)
            for row in want - previous:
                self.list_ctrl.Select(row, True)
        finally:
            self._suspend_selection_events = False
        self._drag_prev_rows = want
        # 焦点行给区间末端（决定方向键从哪儿继续）
        self.list_ctrl.SetItemState(
            high, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
            wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
        # 拖拽期间不走 `on_selection_changed`（上面挂起了），所以这里直接重画。
        self._paint_key = None
        self._apply_selection_highlight()

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
            # **多选：一次要画一整**集**，不能只看第一条。**
            #
            # 2026-10-17 用户要 Ctrl 多选之后，这里原来那一句
            # `selected = GetFirstSelected()` 会让**除第一行外的选中行
            # 全部不上色** —— 而且不报错（用户看到的是"选了却没变蓝"）。
            selected_rows = self.selected_rows()
            selected = selected_rows[0] if selected_rows else -1
            selected_set = set(selected_rows)
            hovered = getattr(self, "_hover_row", -1)
            if not 0 <= hovered < count:
                hovered = -1

            # **行号没变就什么都不做**——这是性能的关键。
            # 鼠标在同一行内移动、或选中项没动时，不再重画整个列表。
            #
            # 键必须用**整个选中集**：只比第一条的话，
            # "第一条没变、用户又 Ctrl 点了别的行"会被误判成"没变"而跳过重画。
            key = (tuple(selected_rows), hovered)
            if key == getattr(self, "_paint_key", None):
                return

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

            # 只重画"受影响的那些行"，不是整表。
            # **上一次画过的选中行也要一起进来** —— 否则取消选中时
            # 那一行会留着上次的蓝，擦不掉。
            touched = set(selected_set)
            touched.update({hovered,
                            getattr(self, "_highlighted_row", -1),
                            getattr(self, "_hover_painted", -1)})
            touched.update(getattr(self, "_highlighted_rows", ()) or ())
            for row in sorted(r for r in touched if 0 <= r < count):
                if row in selected_set:
                    background, text = highlight, normal_text
                elif row == hovered:
                    background, text = hover_colour, normal_text
                else:
                    background, text = base_colour(row), normal_text
                self.list_ctrl.SetItemBackgroundColour(row, background)
                self.list_ctrl.SetItemTextColour(row, text)
            self._highlighted_row = selected
            # **整集**也要记住：取消选中时靠它把旧的那些行还原。
            self._highlighted_rows = tuple(selected_rows)
            self._hover_painted = hovered
            self.list_ctrl.Refresh()
            # **记账必须放在"真的画完"之后。**（理由见下面那段长注释）
            self._paint_key = key
        except Exception:
            # **这里必须静默，不能写日志。**
            #
            # 审计查出的问题：这个方法挂在**鼠标移动**路径上
            # （`on_list_motion` → `_apply_selection_highlight`），
            # 于是"每次换一个悬停行"就可能往
            # `%APPDATA%\File Tracker\resource-errors.log` 写一行。
            # 鼠标在列表上来回划几下就能刷出几百行，而那个文件只增不减。
            #
            # 行高亮是**纯外观**：失败时退化成"没有悬停高亮"，
            # 不影响任何数据与操作。同一个调用在 `_render_rows` 里
            # 本来就是静默处理的（那里注释写着"退化成无层级，而不是让整个
            # 列表画不出来"）——两处判断不一致本身就是个缺陷。
            pass

    # 【已删除】_center_text / _text_width / _centre_cache / invalidate_centre_cache
    #
    # 频次列的居中改由**原生列格式位**负责（`InsertColumn(format=LIST_FORMAT_CENTER)`，
    # 见 `InitUI` 与 `COLUMNS` 的注释）：不补前导空格 ⇒ 没有量化误差，
    # 也省掉每行两次 `GetTextExtent`（曾是重建里 26% 的耗时）。
    # 实测依据：`tools/probes/probe_native_center.py`。

    def _ordered_records(self) -> list[PathRecord]:
        pinned_order = {path: index for index, path in enumerate(self.pinned_paths)}
        pinned = [r for r in self.store.load_pinned() if r.path in pinned_order]
        pinned.sort(key=lambda r: pinned_order[r.path])
        return pinned + self.store.load_unpinned()

    @staticmethod
    def _path_from_cell(text: str) -> str:
        """把控件里的路径单元格文本还原成**真正的路径**（剥掉左内边距）。

        ## 为什么需要它

        路径列的"左内边距"是用**前导空格**实现的（见 :data:`PATH_LEFT_PAD`
        的长注释：原生 `LVM_SETITEMINDENT` 返回成功但不生效）。
        于是控件里的文本是 `"  D:\\Folder"` 而不是 `"D:\\Folder"`。

        **凡是"从控件读路径"的地方都必须过这一道**，否则拿到的是带空格的串
        —— 拿它去 `store.get()` / `os.path.exists()` / 比较，全都会失败，
        而且**不会报错**（只是"找不到"）。

        全项目只有三处读路径单元格，都已改为走这里：

        * :meth:`row_path`
        * :meth:`_selected_paths`
        * :meth:`find_path`

        （`:meth:`selected_paths`` 走的是 `_selected_paths`，间接覆盖。）
        """
        if text.startswith(PATH_LEFT_PAD):
            return text[len(PATH_LEFT_PAD):]
        return text

    def row_path(self, row: int) -> str:
        """取某一行的路径；行号越界返回空串。"""
        if row is None or row < 0 or row >= self.list_ctrl.GetItemCount():
            return ""
        return self._path_from_cell(self.list_ctrl.GetItemText(row))

    def selected_rows(self) -> list[int]:
        """当前**所有**选中行的行号（升序）。没有选中返回空列表。

        ## 为什么不能再用 `GetFirstSelected()`

        列表在 1.3.x 之前是 `LC_SINGLE_SEL`（单选），到处写
        `GetFirstSelected()` 就够了。2026-10-17 用户要"按住 Ctrl 多选"
        之后，**单选假设会静默出错**：高亮只画第一行、删除只删一条、
        `_render_rows` 重建后只剩一条选中 —— 每一样都不报错。

        ⇒ 凡是要"选中集"的地方一律走这里；只有
        "**就要一条**"（双击、顶置这种明确单值语义）才用
        :meth:`selected_path`。
        """
        control = self.list_ctrl
        rows: list[int] = []
        try:
            index = control.GetFirstSelected()
        except Exception:
            return rows
        while index != -1:
            rows.append(index)
            index = control.GetNextItem(index, wx.LIST_NEXT_ALL,
                                        wx.LIST_STATE_SELECTED)
        return rows

    def selected_paths(self) -> list[str]:
        """当前选中行对应的路径（按行号顺序）。没有选中返回空列表。

        多选场景（右键「删除」/「打开」）用它；
        :meth:`selected_path` 是它的"只要第一条"版本。
        """
        paths: list[str] = []
        for row in self.selected_rows():
            path = self.row_path(row)
            if path:
                paths.append(path)
        return paths

    def selected_path(self) -> str:
        """当前**第一条**选中行的路径；没有选中返回空串。

        ⚠️ **这是"只要一条"的口径**（双击、顶置、取消顶置、复制路径用）。
        多选时要"所有选中"的地方请用 :meth:`selected_paths` ——
        用本方法会静默只处理第一条。
        """
        rows = self.selected_rows()
        return self.row_path(rows[0]) if rows else ""

    def find_path(self, path: str) -> int:
        """按路径找行号；找不到返回 -1。"""
        for row in range(self.list_ctrl.GetItemCount()):
            # **必须剥掉左内边距再比**（见 `_path_from_cell`）——
            # 不剥的话 `"  D:\Folder" == "D:\Folder"` 永远为假，
            # 于是 `find_path` 恒返回 -1（选中、删除、顶置全都会找不到行）。
            if self._path_from_cell(self.list_ctrl.GetItemText(row)) == path:
                return row
        return -1

    def remove_invalid_path(self, path: str) -> None:
        """把一条失效路径从记录里删掉（**不询问**，调用方负责先征得同意）。

        ## 只有**真的删到了**才说"已删除"

        审计查出的缺陷：这里原来无条件弹"已从记录中删除"，
        而 `store.remove` 返回什么都无所谓——**改到 0 行与改成功看起来一样**。

        可达路径：导航窗格里留着一个失效选中（比如拔掉的 U 盘 `E:\\Backup`），
        它**从来就不是一条记录**。用户点「打开」→ 弹确认 → 点「删除」→
        程序说"已从记录中删除"，**而实际什么都没删**。

        现在按 `store.remove` 的返回值分两种说法。删不到不是错误
        （那条记录本来就不在），所以用**告知**而不是报错。
        """
        index = self.find_path(path)
        if index != -1:
            # **删之前先清选中**（与 `_remove_paths` 同一个道理）。
            #
            # `DeleteItem(index)` 会让**后面所有行的行号往前挪一格**，
            # 而控件里的选中是按行号记的 —— 清掉之前，那些陈旧行号
            # 会指向**隔壁的记录**（用户报的"选中偏移到别的记录上"）。
            self.unselect_all_rows()
            self.list_ctrl.DeleteItem(index)
        removed_a_row = self.store.remove(path)
        if path in self.pinned_paths:
            self.pinned_paths.remove(path)
        self._remember_view()
        self._rows = [r for r in self._rows if r.path != path]

        # **重画一次高亮。**
        #
        # 这里走的是"删一行、不整表重建"，所以 `_render_rows` 那套
        # 清账本 + 重画的逻辑**不会跑**。不补这一句的话：
        # 删掉的那一行的**蓝色会留着**，而且 `_highlighted_rows` /
        # `_paint_key` 还指着已经不存在的行号 —— 下一次高亮
        # 会按陈旧的账本去"还原"一堆错位的行。
        # 实测（`tools/probes/probe_remove_invalid_row.py`）：
        # 不修时删完那 30 行里会**留下一条错误的蓝色**。
        self._highlighted_row = -1
        self._highlighted_rows = ()
        self._paint_key = None
        self._apply_selection_highlight()

        if not removed_a_row and index == -1:
            # 界面上没有这一行、数据库里也没有 —— 它从来就不是一条记录。
            # 说"已删除"是错的，用户会以为自己刚删掉了什么东西。
            self._notify(
                L(f"'{path}' 不在记录里，无需删除。",
                  f"'{path}' is not in the records; nothing to remove."),
                L("路径失效", "Path missing"))
            return
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
            L("这条路径已失效：", "This path no longer exists:")
            + f"\n\n{path}\n\n"
            + L("要从记录中删除它吗？", "Remove it from the records?"),
            title=L("路径已失效", "Path missing"),
            yes_label=L("删除", "Delete"), no_label=L("保留", "Keep"),
            alert=True,
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
        # **只重建一次。**
        #
        # `load_accessed_paths()` 内部就是 `sort_list_items(reload_from_store=True)`
        # —— "读库 → 排序 → 渲染 → 量列宽"的完整入口。原来这里紧跟着
        # 又调了一次 `sort_list_items(self.sort_column)`，等于**同一份数据重建两遍**
        # （几千行时每次数百毫秒白付一遍），而且让"选中按行号恢复"那一步
        # 多错位一次。见 `load_accessed_paths` 的 docstring ——
        # 那里已经把"连着调两个"明确记为已修缺陷，这里是漏网的一处。
        self.load_accessed_paths()
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
        if column not in (COLUMN_PATH, COLUMN_COUNT, COLUMN_TIME):
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

    def sort_list_items(self, column: int, reload_from_store: bool = False) -> None:
        """排序：顶置项始终在最前（按顶置顺序），其余按所选列排序。

        :param reload_from_store: 先从数据库重新读一遍再排。
            **刚改过数据库的调用方必须传 True**——否则排的是内存里那份
            过期的 `_rows`，新记录不会出现。列头点击不需要重读
            （那一列的数据没变），所以默认 False。

        排序的入口有两个：列头点击（`on_column_click` / `on_header_clicked`）
        与"记一次访问之后"（`record_accessed_path`）。
        原来还有一个「切换排序」按钮（`on_toggle_sort`），
        用户 2026-10-15 要求删掉："没什么用"。已删。

        排序在 Python 侧完成、然后整体重画：``DataViewListCtrl`` 没有
        "交换两行"的接口，而记录量级是几十到几百条，重建比增量维护简单可靠得多。
        """
        # **在动  之前**记下视角锚点（见 ）。
        self._remember_view()
        from datetime import datetime

        if reload_from_store:
            self._rows = self._ordered_records()

        pinned_set = set(self.pinned_paths)
        records = list(self._rows)
        pinned = [r for r in records if r.path in pinned_set]
        unpinned = [r for r in records if r.path not in pinned_set]

        if column == COLUMN_PATH:
            unpinned.sort(key=lambda r: r.path.lower(), reverse=self.sort_reverse)
        elif column == COLUMN_TIME:
            # **时间列同时管日期**（两列已合并，见 `COLUMNS` 的注释）。
            # 排序用 `last_access_time` 的**完整值**——界面上隐藏的秒
            # 与年份都在里面，所以同一分钟内访问的两条也能排对。
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
        self._remember_view()
        self._rows = pinned + unpinned
        self._render_rows()
        # **不在这里再调 `adjust_column_widths()`。**
        #
        # 探针实测：`_render_rows()` 里 `DeleteAllItems()` + 逐行插入会改变
        # 列表的内容宽度，于是**同步**触发 `EVT_SIZE` → `_on_list_resized`
        # → `adjust_column_widths()`。也就是说这一步**已经做过了**，
        # 返回之后紧跟着再调一次是纯粹的重复（一次 500 行要多付
        # 约 3N 次跨语言原生调用，而记录数只增不减）。
        #
        # 保留 `_on_list_resized` 那条路是有意的：它同时也服务
        # "用户拖动窗口改变列表宽度"，那条路上没有别人会量列宽。
        #
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

        ## 为什么记录窗格那条分支**要返回全部选中**

        用户 2026-10-17 要"多选打开"，并选定"**打开所有选中项**"：
        多选了 3 条就打开 3 个资源管理器窗口。
        单条时它当然只返回一条 —— 与改动前完全一致。

        （导航窗格那条分支仍然**只取第一条**：那是 v1.1 起就验收过的行为，
        用户没要求改，动它属于"顺手改掉已经验收的东西"。）
        """
        # **导航树的选中项若是"文件"，换成它所在的文件夹。**
        #
        # 用户："路径记录的规则是：当你**选中导航窗格里面的文件**时，
        # 记录的是这个文件的**父级文件夹**。"
        #
        # 放在这里是因为 `open_targets()` 是「打开」的唯一取值处，
        # 它返回什么，`record_accessed_path()` 就记什么 ——
        # **不需要动 `record_accessed_path` 本身**（那会影响记录窗格那条路）。
        #
        # ⚠️ **只换"来自导航树"的路径**：记录窗格里存的本来就是文件夹路径，
        # 用户在那选什么就打开什么。
        def _from_tree() -> list[str]:
            return [self.dir_ctrl.folder_for(p)
                    for p in self.dir_ctrl.GetPaths() if p]

        if self._focus_pane == "list":
            paths = self.selected_paths()
            if paths:
                return paths
            return _from_tree()
        paths = _from_tree()
        if paths:
            return paths[:1]
        return self.selected_paths()

    def on_open(self, event) -> None:
        """「打开」= 用资源管理器打开目标（多选时逐个打开）。

        ## ⚠️ 顺序：**先打开成功、再记这次访问**（审计查出的缺陷）

        原来是

        ```python
        if os.path.exists(path):
            self.record_accessed_path(path)   # ← 先记
            self.open_folder(path)            # ← 再打开（失败也没人管）
        ```

        `open_folder` 的失败信号被丢掉，于是"**没打开成功**"的路径
        照样 +1 上屏、还可能把一条失效记录重新写回库里 ——
        用户看到的却是"点了打开，什么都没发生"。

        ⇒ 改成：**打开了才记**。打不开就如实告诉用户，
        并且**不**记这一次访问（没到达的地方不该算访问过）。
        """
        # 「打开」的目标是不是**导航窗格**给出来的 —— 决定"要不要收起旧链"。
        #
        # 用户 2026-10-26："用户在浏览导航窗格时，选中路径，然后点击「打开」
        # 按钮来打开对应的文件夹。在这个操作过程中，它没有把以前在导航窗格上
        # 浏览的那些路径收起来。" ⇒ 与地址栏回车保持同一套规则。
        tree_supplied = (self._focus_pane != "list"
                         and bool([p for p in self.dir_ctrl.GetPaths() if p]))
        for path in self.open_targets():
            if not os.path.exists(path):
                # **先问用户**，不再直接删（见 confirm_remove_invalid_path）
                self.confirm_remove_invalid_path(path)
                continue
            if self.open_folder(path):
                self.record_accessed_path(path)
            else:
                self._report_resource_error(
                    L(f"打不开：{path}（资源管理器拒绝了这次请求，"
                      f"或该位置已不可用）",
                      f"Could not open: {path} (Explorer refused the request, "
                      f"or the location is unavailable)"))
        if tree_supplied:
            # 把用户选中的那一项当成"当前路径"，其余由程序展开过的链收起来
            self.dir_ctrl.focus_chain(self.dir_ctrl.GetTreeCtrl().GetSelection())
        self._call_later(100, self.reset_dir_ctrl_scroll)

    def open_folder(self, path: str) -> bool:
        """用资源管理器打开 ``path``（是文件就打开它所在的文件夹）。

        :return: **是否真的打开了。**

        ## ⚠️ 返回值得有人读（审计查出的缺陷，2026-10-17）

        `_open_in_explorer` 的 docstring 早就写着"两条路都如实回报"，
        但它返回的 `bool` 被 `open_folder` **丢掉了**，
        而四个调用点又全是裸语句：

        ```
        self.open_folder(folder)      # ← False 没人看
        ```

        ⇒ "打开失败静默"这一条**其实从来没修好过** ——
        用户看到的是"点了打开，什么都没发生"，而程序认为成功。
        更糟的是 `on_open` 那时是**先记一次访问、再打开**，
        于是"没打开"的路径照样 +1 上屏。

        现在把结果返回给调用方，由调用方决定怎么提示 / 要不要记这次访问。
        """
        folder_to_open = os.path.dirname(path) if os.path.isfile(path) else path
        return self._open_in_explorer(folder_to_open)

    @staticmethod
    def _open_in_explorer(folder: str) -> bool:
        """用资源管理器打开一个文件夹。返回是否成功。

        取 ``os.startfile`` 而不是 ``subprocess.Popen(f'explorer "{folder}"')``：
        后者经过 shell 解析，**路径里含 ``&`` 或引号时会被当成命令分隔符**，
        而在 Windows 上走 ``ShellExecute`` 既能正确传参，也能复用已打开的窗口。

        ## 回退路径必须**报错**，不能静默

        审计查出的问题：原来是

            except (OSError, AttributeError):
                subprocess.Popen(["explorer", folder])

        —— `Popen` 在**路径不存在时并不抛异常**（它只是启动一个 explorer
        进程，由 explorer 自己去报错），所以失败了也没人知道。
        用户看到的是"点了打开，什么都没发生"，而程序认为成功了。

        现在两条路都如实回报。
        """
        try:
            os.startfile(folder)  # noqa: S606 - Windows 专用，且这正是期望行为
            return True
        except (OSError, AttributeError):
            # 回退：`explorer` 对不存在的路径不抛异常，所以只能**先自己检查**
            if not os.path.isdir(folder):
                return False
            try:
                subprocess.Popen(["explorer", folder])
                return True
            except OSError:
                return False

    def on_item_activated(self, event) -> None:
        """**双击**记录列表里的一条 → 打开它。

        ## 多选时双击怎么办（用户 2026-10-17 选定）

        > "只打开双击的那一条，并**重置为单选**。"

        所以这里先用 `_focus_pane = "list"` + `_collapse_selection_to()`
        把选中收成"就这一条"，再走原来的单条逻辑。
        双击的语义是"**就这一条**"，不该一次弹出 N 个窗口。
        """
        path = self.selected_path()
        if not path:
            return
        # 双击 = "就这一条"：把它收成唯一的选中（多选状态随之取消）
        self._collapse_selection_to(path)
        if os.path.exists(path):
            # **打开了才记这次访问**（理由见 `on_open` 的 docstring）
            if self.open_folder(path):
                self.record_accessed_path(path)
            else:
                self._report_resource_error(
                    L(f"打不开：{path}（资源管理器拒绝了这次请求，"
                      f"或该位置已不可用）",
                      f"Could not open: {path} (Explorer refused the request, "
                      f"or the location is unavailable)"))
            self._call_later(100, self.reset_dir_ctrl_scroll)
        else:
            # **先问用户**（见 confirm_remove_invalid_path）
            self.confirm_remove_invalid_path(path)

    def _collapse_selection_to(self, path: str) -> None:
        """把选中收成"只有 `path` 这一条"（双击时用）。

        `_focus_pane` 一起设成 `"list"`：双击已经表明用户此刻在记录窗格操作，
        而且 `record_accessed_path` 里"给焦点 + 换选中"那一块由它把关 ——
        不设的话，多选后双击会走成"从导航树发起"，焦点跑到别处。
        """
        row = self._index_of_path(path)
        if row < 0:
            return
        # 只清"真正选中的"那些（通常就一两条），不盲扫全表
        self.unselect_all_rows()
        self.list_ctrl.SetItemState(
            row, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
            wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
        self._focus_pane = "list"
        self._paint_key = None
        self._apply_selection_highlight()

    def on_open_selected(self, event) -> None:
        """右键菜单里的「打开」——**多选时打开所有选中项**。

        用户 2026-10-17 选定："打开所有选中项"（与「多选打开」的名字一致）。

        实现上**不要再写一遍打开逻辑**：`open_targets()` 已经在
        `_focus_pane == "list"` 时返回记录窗格的选中集，`on_open` 又是
        "遍历并打开"——所以直接把 `_focus_pane` 声明成 `"list"` 再转调它。
        **两条路分头维护迟早会不一致**（本项目已经吃过这个亏）。
        """
        if not self.selected_paths():
            return
        self._focus_pane = "list"
        self.on_open(event)

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
        dialog = ThemedDialog(self, self.theme, message,
                              title=title, yes_label=L("好", "OK"),
                              no_label=NO_BUTTON, alert=True)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()
        self.Refresh()

    def on_copy(self, event) -> None:
        """复制选中行的路径到剪贴板。

        ## 为什么需要 `try/finally` 与返回值检查

        审计查出两个问题：

        ① 原来是 ``if ... Open(): SetData(...); Close()``——中间任何一步
           抛异常，`Close()` 就不会执行，**剪贴板会一直开着**。
           `wx.TheClipboard` 是**整个桌面共享**的资源：不关掉的话，
           别的程序读写剪贴板都会失败，而用户完全不知道是本程序干的。
        ② `SetData` 的返回值被丢掉了。它失败时返回 `False`（不抛异常），
           于是"复制成功"与"复制失败"在用户看来完全一样——
           他去别处粘贴，什么也贴不出来，也不知道为什么。
        """
        path = self.selected_path()
        if not path:
            return
        copied = False
        try:
            if wx.TheClipboard.Open():
                try:
                    copied = bool(
                        wx.TheClipboard.SetData(wx.TextDataObject(path)))
                finally:
                    # **必须在 finally 里**：上面任何一步抛异常都要关掉，
                    # 否则剪贴板会被本程序占住直到退出。
                    wx.TheClipboard.Close()
        except Exception as error:
            self._notify(
                L(f"复制失败：{error}", f"Could not copy: {error}"),
                L("复制", "Copy"))
            return
        if not copied:
            self._notify(
                L("复制失败：剪贴板被别的程序占用。",
                  "Could not copy: the clipboard is held by another program."),
                L("复制", "Copy"))

    def on_delete_selected(self, event) -> None:
        """删除当前选中的记录 —— **多选时一次删掉全部**。

        ## 为什么必须先把"要删哪几条"取下来再弹窗

        弹窗期间用户还能动界面（拖动、点别的行），模态框关掉之后
        再去读 `selected_paths()` 可能已经不是原来那批了 ——
        **删错东西是不可逆的**，所以先取快照。
        """
        paths = self.selected_paths()
        if not paths:
            return
        # **用自绘的 ThemedDialog，不用 wx.MessageDialog。**
        #
        # `wx.MessageDialog` 在 Windows 上是**系统对话框**，由系统主题绘制，
        # 深色下永远是浅色面板——用户反馈"警告弹窗的深色主题适配失败"。
        # 系统对话框没有受支持的换肤接口，**只能换成自己画的**。
        if len(paths) == 1:
            prompt = L("确定要删除这条记录吗？", "Delete this record?")
            title = L("确认删除", "Confirm delete")
        else:
            # **多选时把条数写进文案**：用户得知道这一下要删掉几条。
            prompt = L(f"确定要删除这 {len(paths)} 条记录吗？",
                       f"Delete these {len(paths)} records?")
            title = L(f"确认删除 {len(paths)} 条", f"Delete {len(paths)} records")
        dialog = ThemedDialog(self, self.theme, prompt,
                              title=title, alert=True)
        # **`try/finally` 保证弹窗一定会被销毁。**
        # `ShowModal()` 抛异常时（少见但不是不可能）原来的写法会把
        # 弹窗留在屏幕上，而且后面的 `Refresh()` 也不会执行。
        try:
            confirmed = dialog.ShowModal() == wx.ID_YES
        finally:
            dialog.Destroy()
        if confirmed:
            self._remove_paths(paths)
        self.Refresh()

    def _remove_paths(self, paths: list[str]) -> bool:
        """把若干条路径从"记录 + 顶置列表"里删掉，然后重建列表。

        :return: 是否真的删掉了至少一条。

        **只在真的删到东西时才重建**：`store.remove` 返回 False 说明
        那一行早就不在库里（例如另一个实例删过），
        此时重建只会让界面闪一下，数据没有任何变化。

        ## ⚠️ 重建之前**必须先清掉陈旧选中**（用户 2026-10-17 报的 bug）

        > "多选并删除后，多选状态会**偏移到另外多条记录**上，不会自然消失。"

        排查出来的机制（`_selected_paths()` 被调了两次，读数不同）：

        ```
        要删                = [d002, d004, d006]
        _selected_paths() #1 = [d002, d004, d006]   ← 删除**前**，对的
        （数据已经删掉）
        _selected_paths() #2 = [d003, d007, d009]   ← 行号 [2,4,6] 还在，
                                                      而内容已经平移了
        ```

        **行号是控件的，路径是 `self._rows` 的** —— 数据一删，两者就错位：
        控件的选中行号还是 `[2, 4, 6]`，而 `_rows[2]` 已经从 `d002`
        变成 `d003`（后面的行往上补）。

        ⇒ `_render_rows()` 拿到的 `keep_paths` 是**相邻那几条的路径**，
        它们当然还在库里、当然匹配得上 ⇒ **选中框"跳"到了旁边几条记录上**。

        所以这里在**删完数据之后、重建之前**先清掉选中：
        让 `_selected_paths()` 返回空 ⇒ `keep_paths` 为空 ⇒
        重建后就是"干干净净没有选中"（正是用户要的"自然消失"）。

        **顺带记一笔**：我第一版把修复写在 `_render_rows` 里
        （"没有可恢复的选中时也要全清"），那一版**不够** ——
        因为 `keep_paths` 根本不为空，它拿着一批**错位的、却真实存在**的路径。
        **光清控件清不掉，得让"要恢复什么"这个输入本身变干净。**

        ## ⚠️ 整批一个事务（审计查出的缺陷，2026-10-17）

        原来是 `for path in paths: self.store.remove(path)` —— 而
        `remove()` **每次自己 commit**。中途失败（磁盘满 / 库被锁 / 只读）
        会留下"**前面几条已经删掉、撤不回来**，而界面还显示着它们"，
        用户再点「打开」时 `record_access` 会把它们**重新写回库里**
        （`access_count` 归 1、顶置状态丢失）。

        现在走 `store.remove_many()` —— 一个事务，要么全成、要么全不成；
        并且**无论成败都重建列表**，保证界面与库一致。
        """
        try:
            removed_count = self.store.remove_many(paths)
        except Exception as error:
            # **失败要说出来**：静默的话界面与库会长期不一致。
            self._report_resource_error(
                L(f"删除记录失败：{error!r}（这次删除没有生效）",
                  f"Could not delete the records: {error!r} (nothing was deleted)"))
            # 事务已回滚 ⇒ 内存里的顶置列表也不用动，直接重建刷新界面
            self.load_accessed_paths()
            return False
        if not removed_count:
            # 一条都没删到（库里本来就没有）—— 不重建，省一次全表刷新
            return False
        # 内存里的顶置列表跟着库走（库已经提交成功，这里不会再失败）
        for path in paths:
            if path in self.pinned_paths:
                self.pinned_paths.remove(path)
        # **先清陈旧选中，再重建**（理由见 docstring）
        self.unselect_all_rows()
        self.load_accessed_paths()
        return True

    def on_clear(self, event) -> None:
        dialog = ThemedDialog(self, self.theme,
                              L("确定要清空所有记录吗？", "Clear all records?"),
                              title=L("确认清空", "Confirm clear"),
                              alert=True)
        try:
            confirmed = dialog.ShowModal() == wx.ID_YES
        finally:
            dialog.Destroy()
        if confirmed:
            self.store.clear()
            self.list_ctrl.DeleteAllItems()
            self._rows = []
            self.pinned_paths.clear()
            # 账本一起清：列表空了，"上一次高亮的行号"与
            # `(selected, hovered)` 记忆都不再有任何意义。
            self._highlighted_row = -1
            self._paint_key = None
            self.adjust_column_widths()
        self.Refresh()

    def on_pin(self, event) -> None:
        """顶置当前行。**新顶置的排在最前。**

        ## 这一处我改错过一次，两次都是"顺序来源"没想清楚

        **第一次**：``insert(0, path)``（最前），而启动时读的是
        ``ORDER BY id``（首次访问的先后）。两者不一致 ⇒ 用户刚顶置的那条
        **重启后会跳到它原本的位置**。这是真缺陷。

        **第二次（我的错）**：为了"不需要迁移"，我改成 ``append`` 并把
        数据库也当成"追加序"，还在注释里论证"这样两处本来就是同一个顺序"。
        **那治好了重启漂移，却弄坏了用户看得见的行为**——用户反馈：

        > 记录窗格条目置顶逻辑现在有点问题，新条目置顶后会排在所有已顶置
        > 条目最后，这不符合使用习惯和直觉。请把条目置顶逻辑改成放至顶端。

        ## 正确的做法：把顺序**真的存下来**

        问题的根子是**一直没有"顶置顺序"这个东西**——只有"首次访问的先后"
        （`id`）。两者是**两件不相干的事**，硬拿 `id` 当顶置顺序，
        必然在"新顶置排哪"和"重启后不变"之间二选一。

        现在 `paths` 表有了 `pin_order`（越大越靠前），
        老数据由 `store._migrate_add_pin_order()` 按**用户当前看到的顺序**回填
        ——所以升级不会让顶置列表重排。之后：

        * 顶置 → `pin_order` 取最大值 +1 ⇒ **排最前**（用户要的）
        * 重启 → `load_pinned()` 按 `pin_order DESC` ⇒ **顺序不变**
        * 内存里的 `pinned_paths` 也用 `insert(0, ...)`，与库一致

        **顺序只保存在一个地方（`pin_order`）**，内存那份是它的映像，
        不构成第二个"权威来源"。
        """
        path = self.selected_path()
        if not path or path in self.pinned_paths:
            return
        # **先写库再改内存**：写不进去就不该在界面上显示成已顶置
        # （否则重启后它会消失，而中间没有任何提示——审计里的 M4）。
        if not self.store.set_pinned(path, True):
            self._notify(
                L(f"'{path}' 不在记录里，无法顶置。",
                  f"'{path}' is not in the records; cannot pin it."),
                L("顶置失败", "Pin failed"))
            return
        # `insert(0, ...)` 与库里的 `pin_order` 最大者一致 —— 都表示"最前"
        self.pinned_paths.insert(0, path)
        # **置顶之后，视角要跟着它走。**
        #
        # 用户报："条目从普通状态变为置顶，现在会因为聚焦而**不同步变化**
        # —— 用户会疑惑：我置顶的条目呢？怎么不见了？往上翻才看见已经成功置顶了。"
        #
        # 根因：`sort_list_items()` 里会 `_remember_view()` 把视角**保持在原处**，
        # 而置顶把这条记录挪到了**最顶端** —— 两件事方向相反。
        #
        # ⚠️ **只有置顶设这个意图。取消顶置不设** ——
        # 那时条目还在附近，保持视角才是对的（用户明确说过别动它）。
        self._focus_path_after_render = path
        self.sort_list_items(self.sort_column)

    def on_unpin(self, event) -> None:
        path = self.selected_path()
        if not path or path not in self.pinned_paths:
            return
        if not self.store.set_pinned(path, False):
            # 行已经不在库里了（例如另一个实例删过它）。
            # 内存里也不该再留着，否则它会一直在顶置组里显示。
            self._notify(
                L(f"'{path}' 已不在记录里，已从顶置列表移除。",
                  f"'{path}' is no longer in the records; removed from pins."),
                L("取消顶置", "Unpin"))
        self.pinned_paths.remove(path)
        # **取消置顶：视角完全不动（按行号保持）。**
        #
        # 用户报："我一取消置顶，视角突然就进行了一个**大幅的变动**。"
        # 根因：置顶把视角和那条记录绑在了一起（它此刻正是第 0 行），
        # 取消置顶时它回到字母序原位，视角就跟着往下走 ——
        # 整块置顶项因此滚出屏幕。
        #
        # 用户选定 A："**这就是 1.3.0 的取消置顶聚焦状态**" —— 即视角不动。
        self._keep_scroll_row = True
        self.sort_list_items(self.sort_column)

    def on_right_click(self, event) -> None:
        """右键菜单。

        ## 用户定的规则（2026-10-17）

        > "多选后点击右键，**只保留两个选项**，那就是「打开」和「删除」。"

        口径是**只在多选时精简**（用户选的那个）：
        单选时保持原来的四项（复制路径 / 顶置 / 打开 / 删除）——
        那四项是已验收的行为，不能顺手砍掉。
        """
        # 右键点在某一行上时，控件会先把它选中；没有选中就不弹菜单
        if not self.selected_paths():
            return
        selected_paths = self.selected_paths()
        multiple = len(selected_paths) > 1

        menu = wx.Menu()
        if multiple:
            # **多选：只有两项**（用户明确要求的）
            entries = [
                (L(f"打开 {len(selected_paths)} 项",
                   f"Open {len(selected_paths)} items"), self.on_open_selected),
                (L(f"删除 {len(selected_paths)} 项",
                   f"Delete {len(selected_paths)} items"), self.on_delete_selected),
            ]
        else:
            path = selected_paths[0]
            is_pinned = path in self.pinned_paths
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
        # **只有"跟随系统"才重读注册表。**
        # 用户明确选了浅色/深色时，窗口一激活就被系统主题覆盖回去，
        # 是那种"我明明选了却不生效"的缺陷。
        #
        # ⚠️ **设置对话框开着的时候不能重读**（用户 2026-10-17 报的闪烁）：
        #
        # 用户原话："一旦从**跟随系统主题**开始，变成与系统主题不同的主题状态，
        # 那么你在点**确定**的时候，大概率会观察到部分组件的**二次刷新**。"
        #
        # 机制（`tools/probes/probe_retheme_twice.py` 实测）：
        #
        # ```
        # ① 预览选了深色        → 界面变深（正确，所见即所得）
        # ② 点「确定」→ 对话框关闭 → 主窗口重获激活
        #    → on_activate 跑到这里，而**配置还没落盘、仍是 "system"**
        #    → 重读系统主题（浅色）⇒ **把界面改回浅色**
        # ③ on_settings 的自愈再把它改回深色
        #    ⇒ 中间那次就是用户看到的"二次刷新"
        # ```
        #
        # 而"深浅互切"（配置里本来就是明确的 light/dark）不会走到这里，
        # **所以只有从"跟随系统"出发时才闪** —— 与用户的观察完全吻合。
        #
        # 修法：预览期间挂起。真正的系统主题变化会在关闭设置后补上
        # （`_resume_system_theme_watch`），所以不丢功能。
        #
        # ⚠️ **不要 `return`** —— 本方法后面还有 `Refresh()`、
        # 按钮重画、以及 `reset_dir_ctrl_scroll()`（`_call_after`）。
        # 提前返回会把它们一起跳过，那是另一个 bug。
        if not getattr(self, "_suspend_system_theme", False):
            if self.config.get_theme() in (None, THEME_SYSTEM):
                new_theme = theme_from_system()
                if new_theme != self.theme:
                    self.theme = new_theme
                    self._retheme()
                # **顺手更新"挂起前的基准值"。**
                #
                # `_theme_before_settings` 是给 `_resume_system_theme_watch`
                # 做对比用的。这里的 `self.theme` 已经是"跟随系统应有的值"，
                # 所以它天然就是正确的基准 —— 系统主题在程序运行期间变化时
                # 基准跟着走，关闭设置后的"补一次"才不会误判。
                self._theme_before_settings = new_theme
        self.Refresh()
        for button in (self.open_btn, self.clear_btn, self.path_bar):
            if hasattr(button, "Refresh"):
                button.Refresh()
        self._call_after(self.reset_dir_ctrl_scroll)
        event.Skip()

    def _retheme(self) -> None:
        """换主题之后重新上色（系统主题变了，或用户在设置里切了主题）。

        **自绘控件不会自己跟随系统主题**——这正是"改了系统主题但按钮还是
        旧配色"的来源。所以这里显式地把新配色推给每一个自绘控件，
        并重画列表（行底色是按当前配色算出来的）。

        ## ⚠️ 容器也要重新上色，否则"面板部分不跟着反色"

        用户报（原话）："切换主题后，**面板部分不会立即正确反色**。
        老问题了，关闭程序再启动才正确反色。"

        **根因**：`InitUI` 里的 `panel` / `left_panel` / `right_panel` /
        `card_panel` 原来都是**局部变量** —— 创建时 `SetBackgroundColour`
        上过一次色，之后**再也没有任何代码够得到它们**。
        主题一变，窗口和控件都换了色，唯独这几层容器还是旧的，
        于是"左边一整块不跟着反色"。

        `wx.SplitterWindow` 的 sash 是 wx 自己画的（取系统色），
        所以它本来就不该在这里处理——本项目已经把它 `SetSashInvisible`
        并改用自绘的 `BorderLine`（见 `InitUI` 与 `_position_pane_border`）。

        **判据**：这一组必须有 `self.` 句柄才可能被重上色。
        新增容器时**照着这里加一行**，否则同一个缺陷会再长出来一次。
        """
        self.SetBackgroundColour(wx.Colour(self.theme.background))
        for holder in (self._shell_panel, self._left_panel,
                       self._right_panel, self.splitter):
            holder.SetBackgroundColour(wx.Colour(self.theme.background))
        self._card_panel.SetBackgroundColour(wx.Colour(self.theme.card))
        # **进程级深色模式也要跟着改。**
        #
        # 右键菜单、滚动条、系统提示框这些是**系统画的**，它们只看
        # `SetPreferredAppMode` 那个进程级开关；不重设的话，
        # "启动时是浅色、运行中切成深色"之后菜单会一直是浅的。
        # 官方说这个开关"对已经创建的控件无效"——菜单是**按需创建**的，
        # 所以对后续弹出的菜单仍然有效（实测：切换后再右键，菜单是深的）。
        try:
            win32.set_process_dark_mode(self.theme.is_dark)
        except Exception:
            pass
        for child in (self.open_btn, self.clear_btn):
            child.apply_theme(self.theme)
        self.path_bar.apply_theme(self.theme)
        self.apply_window_theme()
        self._render_rows()
        self.Layout()
        # apply_window_theme 里已经重摆过分隔线，但 Layout 可能又改了尺寸，
        # 所以这里再摆一次（幂等，代价是两次 SetSize）
        self._position_pane_border()

    def _repaint_all(self, window=None) -> None:
        """**递归重画**每一扇子窗口。

        ## 为什么需要它

        用户报（截图）："每次点击更换主题后，**主界面的面板部分
        不能及时刷新**。"

        `_retheme()` 已经改对了各层容器的**底色**，问题在**没有让它们重画**：
        此刻模态设置窗口盖在上面，主窗口的重绘请求被压后，
        不显式 `Update()` 就会看到"改了一半"的样子。

        **为什么递归**：漏掉哪一个，哪一个就留旧色 ——
        "刷新不完整"就是这么来的。递归遍历不会漏，
        代价只是几次 `Refresh()`（它们本身会被合并成一次重绘）。
        """
        target = window if window is not None else self
        target.Refresh()
        for child in target.GetChildren():
            self._repaint_all(child)
        target.Update()

    def _suspend_system_theme_watch(self) -> None:
        """**设置对话框打开期间**挂起"激活时重读系统主题"。

        见 :meth:`on_activate` 里那段 —— 不挂起的话，
        对话框关闭（主窗口重获激活）时会把用户刚预览的主题**改回系统主题**，
        然后 `on_settings` 的自愈再改回来，用户就看到一次闪烁。
        """
        self._suspend_system_theme = True
        # 记下挂起**之前**那个"跟随系统"的主题值。
        #
        # 设置期间系统主题可能真的被改了（用户切到系统设置去改了主题），
        # 这个是拿来做"关闭后要不要补一次"的对比基准 ——
        # 用预览中途的 `self.theme` 会误判（那时可能已经是用户选的主题）。
        self._theme_before_settings = (
            self.theme
            if self.config.get_theme() in (None, THEME_SYSTEM)
            else theme_from_system()
        )

    def _resume_system_theme_watch(self) -> None:
        """设置对话框关闭后恢复，并**补上**期间真正发生的系统主题变化。

        ## 为什么要补

        挂起是为了不覆盖用户的预览选择。但如果用户在设置期间
        **真的去系统里改了主题**，那次变化在挂起期间被忽略了 ——
        不补的话，界面会一直停在旧主题，直到下次窗口激活才纠正。

        ## 怎么判断"真的发生了"

        只有当用户**最终仍选了"跟随系统"**时才需要补 ——
        他明确选了浅色/深色的话，系统主题本来就不该影响界面
        （这正是 `on_activate` 里那个 `if` 的用意）。
        """
        self._suspend_system_theme = False
        try:
            if self.config.get_theme() not in (None, THEME_SYSTEM):
                return
            current = theme_from_system()
            if current != getattr(self, "_theme_before_settings", None):
                self.theme = current
                self._retheme()
        except Exception:
            # 纯外观纠正：失败时留着旧主题，不影响任何数据
            pass

    def _preview_theme(self, dialog, preference: str) -> None:
        """设置窗口里点了主题按钮 —— **立刻换**（用户要求"所见即所得"）。

        两件事都要做，缺一不可：

        1. **主窗口**换主题并重上色（`_retheme` 会把新配色推给每个自绘控件）
        2. **设置窗口自己**也要换 —— 只换主窗口的话，他会看到
           "外面暗了、设置窗口还是亮的"，那反而不像生效了。
        """
        self.theme = theme_from_preference(preference)
        self._retheme()
        dialog.apply_theme(self.theme)
        # **显式重画整扇窗**（含每一层子窗口）——
        # 否则模态弹窗压着，主窗口只刷一部分（用户报的"刷新不及时"）。
        self._repaint_all()
        dialog.Refresh()
        dialog.Update()

    def _preview_sort(self, key: str, reverse: bool) -> None:
        """设置窗口里点了排序按钮 —— **立刻重排列表**。

        用户报："排序方式、排序方向**没有及时生效**。"
        主题与语言都接了预览回调，**只有排序漏了**。

        排序与那两者不同：它不改配色、也不改文案，只改**列表内容的顺序**，
        所以调 `apply_sort` 就够，不必重上色。
        """
        self.apply_sort(_column_of(key), reverse=reverse)
        self._repaint_all()

    def _preview_language(self, dialog, preference: str) -> None:
        """设置窗口里点了语言按钮 —— **立刻换**。

        `apply_language` 必须在 `retranslate` 之前：后者每一次 `L(...)`
        读的都是它刚设下的那个值（与确认路径同一条纪律）。
        """
        apply_language(preference)
        self.retranslate()
        dialog.retranslate()

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
        theme_before = self.config.get_theme() or THEME_SYSTEM
        # 排序的"打开设置之前"状态 —— 取消时要还原
        sort_before = (self.sort_key, self.sort_reverse)
        dialog = SettingsDialog(
            self, self.theme, before,
            sort_key=self.sort_key,
            sort_reverse=self.sort_reverse,
            theme_preference=theme_before,
            # **点了就生效**（用户要求"所见即所得"）。
            # 用 lambda 延迟取 `dialog` —— 传的时候它还没建好。
            on_theme_preview=lambda value: self._preview_theme(dialog, value),
            on_language_preview=lambda value: self._preview_language(dialog, value),
            on_sort_preview=lambda key, rev: self._preview_sort(key, rev),
        )
        # 把各列"上次用的方向"灌进去，这样在窗口里换列时能带出那一列自己的
        # 方向，与点表头的行为一致（见 `SettingsDialog._choose_sort`）。
        for spec in SORT_SPECS:
            remembered = self.config.get_sort_direction(spec.key)
            if remembered is not None:
                dialog._sort_directions[spec.key] = remembered
        # **挂起"激活时重读系统主题"** —— 见 `on_activate` 里那段说明。
        # 必须在 `ShowModal()` **之前**：对话框一关，主窗口立刻重获激活。
        self._suspend_system_theme_watch()
        confirmed = False
        try:
            confirmed = dialog.ShowModal() == wx.ID_YES
            if confirmed:
                chosen = dialog.selected_preference()
                sort_key, sort_reverse = dialog.selected_sort()
                theme_chosen = dialog.selected_theme()
        finally:
            # ⚠️ **顺序**：先恢复、再 `Destroy()`。
            #
            # `Destroy()` 会让主窗口重获激活 ⇒ 触发 `on_activate`。
            # 若那时还挂着，恢复逻辑要等到下一次激活才跑；
            # 而"先恢复再销毁"能让紧随其后的那次激活按**最终配置**正确判断。
            self._resume_system_theme_watch()
            dialog.Destroy()

        if not confirmed:
            # **取消 = 什么都没发生。**
            #
            # 预览已经改过界面了，不还原的话：界面停在他最后点的那个，
            # 而配置里还是旧的 —— 重启一次又跳回去，
            # 是最难查的那类不一致。
            if self.config.get_theme() != theme_before \
                    or self.theme != theme_from_preference(theme_before):
                self.theme = theme_from_preference(theme_before)
                self._retheme()
            if self.config.get_language() != before:
                apply_language(before)
                self.retranslate()
            # **排序也要还原** —— 预览已经重排过列表了
            if (self.sort_key, self.sort_reverse) != sort_before:
                self.apply_sort(_column_of(sort_before[0]),
                                reverse=sort_before[1])
                self._repaint_all()
            return

        # **确定：只落盘，不重新应用。**
        #
        # 用户报："选好之后点确定，导航窗格、记录窗格以及整个界面都会
        # **再刷新一次**……因为设置里已经及时生效了，所以我认为
        # 点击确定**不应该在用户面前再刷新一次**。"
        #
        # 根因是这里原来**把每一项又应用了一遍**，而判据
        # （`language_changed` / `theme_chosen != theme_before`）
        # 比的是"打开设置之前"的值 —— 预览早就改过界面了，
        # 所以条件必然成立，于是全部重跑一次，用户就看到界面抖了一下。
        #
        # ⇒ 落盘归落盘；界面**只在真的不一致时**才动。
        self.config.set_language(chosen)
        self.config.set_theme(theme_chosen)

        # **自愈**：正常路径下这几条都是空操作（预览已经改好了），
        # 但万一将来某条预览没接上，界面也不会停在旧值。
        # 比"无条件应用"好（那会抖），也比"完全不应用"稳（那会留旧值）。
        if is_chinese() != (chosen == PREFERENCE_CHINESE):
            # `apply_language` 必须在 `retranslate` 之前——
            # retranslate 里每一次 `L(...)` 读的都是它刚设下的那个值。
            apply_language(chosen)
            self.retranslate()
        if self.theme != theme_from_preference(theme_chosen):
            self.theme = theme_from_preference(theme_chosen)
            self._retheme()
        if (self.sort_key, self.sort_reverse) != (sort_key, sort_reverse):
            # 排序交给 `apply_sort`：它自己写配置（见 `_remember_sort`）
            self.apply_sort(_column_of(sort_key), reverse=sort_reverse)
        try:
            self.config.save()
        except OSError as error:
            self._report_resource_error(
                L(f"无法保存设置: {error}",
                  f"Could not save the settings: {error}"))

    def retranslate(self) -> None:
        """把界面上所有文案按**当前语言**重取一遍，**并重算列宽**。

        ## 只改文字，不动控件结构

        按钮宽度是按文字算的不是写死的（`RoundedButton` 会 `SetMinSize`），
        所以换语言后 `Layout()` 一次就够，不需要重建控件。
        重建会丢掉选中行、滚动位置和目录树的展开状态——
        为了几个字付这个代价不值得。

        **原生 `wx.ListCtrl` 的列标题改不了**（`SetColumn` 的 `LVCOLUMN`
        只支持改文字，但 wx 的 `InsertColumn` 是追加语义，原地改要靠
        `SetColumnText`）——所以列表那四列直接调它，表头是自绘的、
        改 `titles` 再 `Refresh` 即可。

        ## ⚠️ 但列宽**必须重算**（用户 2026-10-17 报的）

        > "英文启动：Count 列计算得比较宽。此时换成中文，程序没有重新计算，
        >   就会导致切换后的中文界面里'频次'这一列**过宽**。
        >   中文启动再换成英文，同样不会重新测量，英文的 Count
        >   **和三角重叠在一起**。"

        **这确实是"只在启动时算一次"的缺陷**：原来这里只换了标题文字
        （`set_titles`），列宽还是**上一种语言**算出来的。于是两边的错都出现：

        | 切换方向 | 现象 |
        |---|---|
        | 英文（宽 121）→ 中文 | "频次"占着 `Count` 的宽度 ⇒ **过宽、空一大块** |
        | 中文（窄 100）→ 英文 | `Count` 装不下自己的宽度+三角 ⇒ **重叠/压线** |

        ⇒ 换完标题**必须重算列宽**（`adjust_column_widths` 会同时刷新
        自绘表头、列间竖线、居中缓存，这几件事是绑在一起的）。

        **这一条也是前面几轮"三角压线"反复出现的真凶之一**：
        我用探针量的是"启动后立刻"的几何，而用户是**切换语言之后**看的。
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

        # **换语言 ⇒ 列宽要按新语言的标题重新量。**
        #
        # 顺序：先换标题（上面），再重算（这里）——
        # `_adjust_column_widths` 里的 `fitted()` 读的是 `column_labels()`，
        # 所以它量到的一定是新语言的文字。
        self.adjust_column_widths()

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
            self._call_after(self.reset_dir_ctrl_scroll)
        event.Skip()

    def on_close(self, event) -> None:
        """退出：**先取消挂起的回调**，再保存配置、提交数据库、关闭连接。

        **顺序有讲究**：先落配置与数据库，最后才 ``Skip()`` 真正销毁窗口。
        旧实现在这里调 ``save_accessed_paths`` 整表重写（先 ``DELETE FROM paths``
        再从界面把所有行插回去），现在不需要了——数据库本身就是真相来源。

        ## 为什么要先取消挂起的回调

        审计查出的问题：窗口里散着十几处 `wx.CallLater` / `wx.CallAfter`
        （延迟量列宽、复位滚动、`_hide_native_header_now` 等），
        而**没有任何一处在关闭时取消**。

        它们排队等着执行，而窗口正在被销毁——回调一旦跑到，
        碰的就是已经释放的 wx 对象（`self.dir_ctrl.GetTreeCtrl()` 之类）。
        后果通常只是退出时冒一段回溯，但那是**碰运气**：
        同一段代码在别的时机可能就崩在退出路径上，而"退出时崩溃"
        会把本该保存的数据一起带走，是最难查的一类。

        取消是廉价的：`wx.CallLater` 有 `Stop()`；`CallAfter` 没法取消，
        所以用 `_closing` 标志让那些回调**自己检查后直接返回**。
        """
        self._closing = True
        for timer in list(self._pending_timers):
            try:
                timer.Stop()
            except Exception:
                pass
        self._pending_timers.clear()

        # **行底色诊断出报告。** 必须在窗口还活着的时候做——
        # 报告里要读控件的选中行、顶行、以及那三个记忆账本。
        if getattr(self, "_paint_tracer", None) is not None:
            try:
                self._paint_tracer.dump()
            except Exception as error:      # pragma: no cover - 诊断不能拖垮退出
                paint_trace.report_failed(error)

        try:
            current_dir = self.dir_ctrl.GetPath()
            if current_dir and os.path.exists(current_dir):
                self.config.set_last_directory(current_dir)
            self.save_scroll_position()
            self.config.save()
        except Exception as error:
            # ⚠️ **这里要兜 `Exception`，不能只兜 `OSError`**（审计查出的
            # 结构性问题，2026-10-17）：
            #
            # 上面这几步（`GetPath` / `save_scroll_position` / `config.save`）
            # 任何一个抛出**非 OSError** 的异常（典型是 wx 的
            # `RuntimeError: wrapped C/C++ object ... has been deleted`），
            # 控制流就会直接跳出本函数 —— 于是：
            #
            #   * `event.Skip()`（本函数最后一句）**不执行 ⇒ 窗口关不掉**
            #   * `self.store.close()` 不执行 ⇒ **数据库连接不关**
            #
            # 同一个函数里另外两段（诊断出报告、关库）都用 `except Exception`
            # 兜住了，唯独这段只兜 `OSError` —— **判据不一致本身就是缺陷**。
            wx.LogError(L(f"无法保存配置: {error}", f"Could not save the config: {error}"))

        try:
            self.store.close()
        except Exception as error:
            wx.LogError(L(f"关闭数据库时出错: {error}", f"Error while closing the database: {error}"))

        # **`event.Skip()` 放最后且不可跳过** —— 它是"真的关掉窗口"那一步。
        event.Skip()

    def _call_later(self, delay_ms: int, callback):
        """`wx.CallLater` 的包装：**登记下来，好在关闭时取消**。

        两重保护，缺一不可：

        * 登记进 `_pending_timers`，`on_close` 会依次 `Stop()`——
          这是主要手段。
        * **回调自己也检查 `_closing`**：`Stop()` 只能拦住"还没到期"的；
          如果定时器**已经到期、事件已经排进队列**，`Stop()` 就无效了，
          回调照样会跑。而它跑的时候窗口可能已经销毁。

        只用 `wx.CallLater` 就没法在 `on_close` 里统一停掉——
        那正是审计查出的问题（十几个挂起回调，一个都没取消）。
        **新代码一律走这里。**

        ## ⚠️ 跑完要把自己从账上划掉（审计查出的内存泄漏，2026-10-17）

        原来 `_pending_timers` **只加不减**（全文只有 `append` 与 `on_close`
        里的 `clear()`）。而 `on_scroll` 那种去抖每滚一下就建一个新定时器、
        旧的只是 `Stop()` 掉、**对象仍留在列表里** ⇒ 长会话里无限增长
        （每个都持有闭包 + 对 frame 的引用），`on_close` 还要逐个 `Stop()`。

        ⇒ 回调跑完（无论是否因 `_closing` 提前返回）就把自己移除。
        `Stop()` 过的那些由 `on_close` 的 `clear()` 收尾。
        """

        def guarded():
            # **先把自己划掉，再干活** —— 干活时抛异常也不能留垃圾
            try:
                self._pending_timers.remove(timer)
            except ValueError:
                pass
            if self._closing:
                return
            callback()

        timer = wx.CallLater(delay_ms, guarded)
        self._pending_timers.append(timer)
        return timer

    def _call_after(self, callback) -> None:
        """`wx.CallAfter` 的包装：**窗口关闭后不再执行**。

        `wx.CallAfter` 没有取消接口，所以只能让回调自己检查 `_closing`。
        包一层，调用方就不必每次记得写那个判断。
        """

        def guarded():
            if self._closing:
                return
            callback()

        wx.CallAfter(guarded)


def process_theme_preference() -> Theme:
    """**进程级**深色模式该按什么来 —— 答案是"程序的主题偏好"，不是系统主题。

    ## 这一条修的是用户 2026-10-26 报的旧 bug

    > "在深色主题下，选中路径记录器当中的条目并右键点击，
    >   其菜单没有随深色主题反色，依然是浅色背景。"

    右键菜单是系统绘制的（`#32768` 类窗口），它跟的是
    `uxtheme.SetPreferredAppMode` 那个**进程级**开关。而原来这里写的是：

    ```python
    dark = win32.system_uses_light_theme() is False      # ← 按**系统**主题
    ```

    于是"系统是浅色、用户把程序设成深色"时，进程级开关是**浅色** ——
    程序自绘的部分全是深的，唯独菜单、滚动条、表头、系统提示框是浅的。
    反过来（系统深色、程序设成浅色）也一样。

    实测（`tools/probes/_probe_menu_dark.py`，取整块菜单矩形的众数色）：
    强制进程深色后菜单 **95% 像素是 (44,44,44)**；进程浅色时是 (249,249,249)。

    **必须在创建任何窗口之前调用**（所以由 `FileTrackerApp.OnInit` 先用它取主题）。
    取不到配置时退回系统主题，与"跟随系统"的语义一致。
    """
    try:
        preference = Config(default_config_path()).get_theme()
    except Exception:
        preference = None
    return theme_from_preference(preference)


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
        # ⚠️ **按"程序的主题偏好"决定，不是按系统主题**（2026-10-26 修）：
        # 原来写的是 `system_uses_light_theme() is False`，于是"系统浅色 +
        # 程序设成深色"时进程级开关仍是浅色 —— 自绘部分全深、菜单却是浅的
        # （用户报的"右键菜单没跟着反色"）。见 `process_theme_preference`。
        #
        # 必须在窗口创建之前调用，所以放在这里而不是 apply_window_theme 里。
        applied = False
        try:
            applied = win32.set_process_dark_mode(
                process_theme_preference().is_dark)
        except Exception:
            applied = False
        if not applied:
            # **不能静默失败**：进程级开关设不上，菜单/滚动条/系统提示框就会
            # 一直是浅色，而界面上只看得到"它们是浅的"、看不到原因。
            # 源码运行（`run.ps1`）时这行会出现在终端里。
            print("[dark-mode] " + L(
                "进程级深色模式设置失败：右键菜单与系统控件将保持系统主题颜色",
                "Process dark mode unavailable: menus and system controls "
                "will follow the system theme"), file=sys.stderr)

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
