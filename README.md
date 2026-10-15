# :star: File Tracker
- 一个自动跟踪文件路径并根据使用频率和时间排序的工具

- **File Tracker v1.2.4 已发布** —— 更小的体积、可自定义的排序、中英双语界面。

<br>

- A tool for automatically tracking file paths and sorting them by usage frequency and time.

- **File Tracker v1.2.4 is out** — smaller, with configurable sorting and a bilingual (Chinese/English) UI.

<div align="center">

**浅色主题 | Light theme**

![File Tracker 浅色主题](https://raw.githubusercontent.com/Neus117/File-Tracker/main/images/FileTracker_v1.2.4-light.jpg)

**深色主题 | Dark theme**

![File Tracker 深色主题](https://raw.githubusercontent.com/Neus117/File-Tracker/main/images/FileTracker_v1.2.4-dark.jpg)

</div>

<br>

## 功能 | Features

**左侧文件选择器 | The file selector (Browser) on the left**
- 树状图浏览导航 | Tree-view navigation
- **地址栏：粘贴或输入路径后回车，直接跳到该位置并记录一次访问（Ctrl+L 聚焦）**
  | **Address bar: paste or type a path and press Enter to jump there and record one access (Ctrl+L to focus)**
- 同时支持选择文件夹或文件（选择文件可双击直接打开其父文件夹）
  | Select both folders and files (double-clicking a file opens its parent folder)
- 记忆上次浏览的视图位置 | Remembers the last viewed location
- 自动重置水平滚动条 | Automatically resets the horizontal scroll bar

**右侧路径记录器 | The path logger (Logger) on the right**
- 自动记录访问过的路径 | Automatically logs visited paths
- **点列头排序，并记住你的选择：下次启动就用它**
  | **Click a column header to sort; your choice is remembered and restored on next launch**
- **设置窗口：切换界面语言、选择排序方式（底部右侧的齿轮按钮）**
  | **Settings dialog: switch the UI language and pick the sort order (the gear button at the bottom right)**
- 中英双语：按 Windows 显示语言自动选择，也可手动指定
  | Bilingual: follows the Windows display language, or set it manually
- 频次列数字居中显示 | The frequency column is centre-aligned
- Ctrl+C 复制路径 | Copy a path with Ctrl+C
- 右键菜单展开功能选项 | Context menu with expanded options on right-click
- 路径顶置和取消顶置 | Pin and unpin paths
- 路径的单独或全量删除 | Delete individual records or clear all
- 浅色 / 深色主题跟随系统 | Light / dark theme follows the system setting

<br><br>

## :bulb: 使用说明 | How to Use
- 在 Releases 中下载并运行 `File.Tracker_v1.2.4.exe` 即可使用。
  （这个名字从 v1.2.0 起统一为 `File.Tracker_v<完整版本号>.exe`——
  此前四个版本的资产名各不相同，容易下错。）

- 程序运行后会在 `C:\Users\Currentuser` 下释放一个数据库文件（1.0+ 版本文件名为
  `file_access.db`，1.1+ 版本文件名为 `file_tracker.db`），用于储存路径信息。

- 在 Windows 系统中添加自启动任务的方法：WIN+R 打开运行，然后输入命令
  `shell:startup` 回车。之后将需要添加自启动任务的程序快捷方式放入弹出的窗口即可。

- 如何卸载：直接删除 `File.Tracker_v1.2.4.exe` 和 `file_tracker.db`（或 `file_access.db`）。

- **查看版本**：在命令行里运行 `File.Tracker_v1.2.4.exe --version`，
  它会打印形如 `File Tracker 1.2.4+a72aed5` 的版本串（`+` 后面是构建它的提交）。
  没有控制台时（例如双击）它会写一份到 `%APPDATA%\File Tracker\version.txt`，
  并弹一个 6 秒后自动关闭的提示框。

<br><br>

- Download and run `File.Tracker_v1.2.4.exe` from the Releases section to start using the program.
  (From v1.2.0 onward the asset name is uniformly `File.Tracker_v<full version>.exe` —
  the previous four releases each used a different name.)

- After the program launches, a database file is created under `C:\Users\Currentuser`
  (`file_access.db` for version 1.0+, `file_tracker.db` for version 1.1+), which stores path information.

- To add the program to startup in Windows: press WIN+R, type `shell:startup` and press Enter.
  Put a shortcut to the program into the folder that opens.

- To uninstall: simply delete `File.Tracker_v1.2.4.exe` and `file_tracker.db` (or `file_access.db`).

- **Check the version**: run `File.Tracker_v1.2.4.exe --version` in a terminal; it prints a string
  like `File Tracker 1.2.4+a72aed5` (the part after `+` is the commit it was built from).
  Without a console (e.g. a double-click) it also writes `%APPDATA%\File Tracker\version.txt`
  and shows a notice that closes itself after 6 seconds.

<br><br>

## 与两年前的 v1.1.0 相比 | Compared with v1.1.0 (two years ago)

| | v1.1.0（2024-10-14） | **v1.2.4（2026-10-16）** |
|---|---|---|
| 体积 | 15.76 MB | **13.31 MB** |
| 界面语言 | 仅中文 | **中英双语，可切换** |
| 排序 | 固定按频次，每次启动都一样 | **可选排序列与方向，跨重启记住** |
| 地址栏 | 有 | 有（并修好了"回车不打开资源管理器"） |
| 设置窗口 | 无 | **有**（语言 + 排序） |
| 深色主题 | 部分控件不跟随 | **自绘控件全程跟随** |
| 自动化测试 | **0 条**（且测试文件 import 的名字两个都不存在） | **186 条单元测试 + 155 项界面检查** |
| 构建流程 | **没有**（仓库里没有 `.spec`、没有脚本、没有 CI） | `build.ps1` + 9 道门禁 + GitHub Actions |
| 产物能自报版本 | 不能 | **能**（`--version` 给出名字/版本/提交） |
| 可执行文件版本信息 | 无（属性页几乎空白） | **有**（文件说明/版本/产品/版权） |
| 测试覆盖的模块边界 | 无 | 逻辑层与 wx 解耦，9 个模块不 import wx |

**体积从 15.76 MB 降到 13.31 MB**，是在**功能变多**的前提下做到的：

- 只打包运行时真正读取的资源（此前整个 `images/` 目录都被塞进去，
  包括 README 用的展示图）
- 排除只有标准库内部才用到的 `tarfile` / `hashlib` / `email`
  （它们会连带把 2.11 MB 的 `libcrypto-3-x64.dll` 拉进产物）

<br><br>

## 已知限制 | Known limitations

**记录条数很多时，"打开"一条记录会变慢。** 实测（本机，175% DPI）：

| 记录数 | 一次「打开」之后的完整刷新 |
|---|---|
| 200 | 约 0.12 秒 |
| 1000 | 约 0.39 秒 |
| 3000 | 约 0.99 秒 |
| 6000 | 约 1.9 秒 |

瓶颈是 `wx.ListCtrl` 逐行插入（6000 行里它占 1.53 秒），**不是**读数据库
（13 ms）也不是算列宽（61 ms）。所以**限制记录条数治不了根**——真正的解法是
改用虚拟列表，而那会动到整行高亮、悬停跟随、顶置底色三处显示逻辑，
需要单独一轮改造。

**日常使用（几十到几百条）完全感受不到。** 测量脚本与结论在
`tools/probes/probe_scale_cost.py`、`probe_scale_profile.py` 和
`tools/probes/README.md` 的「列表规模那一组」。

<br>

**Opening a record slows down once you have thousands of them.** Measured on this
machine at 175% DPI: 200 records ≈ 0.12 s, 1000 ≈ 0.39 s, 3000 ≈ 0.99 s,
6000 ≈ 1.9 s. The cost is `wx.ListCtrl`'s per-row insert (1.53 s of the 1.9 s),
not the database read (13 ms) nor the column-width pass (61 ms) — so capping the
number of records would not fix it. The real fix is a virtual list, which touches
row highlighting, hover tracking and the pinned-row tint, and deserves its own round.

**For everyday use (tens to hundreds of records) this is imperceptible.**

<br><br>

## 依赖 | Dependencies
- Python 3.11
- 1.1+ 版本依赖 wxPython；打包需要 PyInstaller。
  完整清单见 `requirements_v1.1+.txt`，开好环境的文件是 `environment_v1.1+.yml`。

> **Python 版本不能随便升。** `wxPython==4.2.2` 在 PyPI 上最高只提供到
> **cp313** 的 wheel（实测查询结果：cp38–cp313），本机 conda base 是 3.14，
> 装不上——必须用 `environment_v1.1+.yml` 建 3.11 环境。

<br>

- Python 3.11
- Version 1.1+ depends on wxPython; packaging requires PyInstaller.
  The full list is in `requirements_v1.1+.txt`, and the environment file is `environment_v1.1+.yml`.

> **Do not upgrade Python casually.** `wxPython==4.2.2` ships wheels for **cp313 at
> most** on PyPI (measured: cp38–cp313), while this machine's conda base is 3.14 —
> it will not install. Create the 3.11 environment from `environment_v1.1+.yml`.

<br><br>

## 开发者安装 | Developer Installation
1. 克隆此仓库 | Clone this repository

   ```bash
   git clone https://github.com/Neus117/File-Tracker.git
   cd File-Tracker
   ```

2. 创建环境 | Create the environment

   ```bash
   conda env create -f environment_v1.1+.yml
   conda activate ft_env
   ```

   两个环境文件里的环境名都是 `ft_env`，**不能同时装**。
   换版本前先 `conda env remove -n ft_env`。

3. 安装开发依赖（含测试）| Install development dependencies

   ```bash
   pip install -r requirements-dev.txt
   ```

<br><br>

## 开发者调试 | Developer Debugging
- 运行 `src/main.py` 启动应用 | Run `src/main.py` to start the application

  ```bash
  python src/main.py
  ```

- 打印版本（含构建它的提交） | Print the version (including the commit it was built from)

  ```bash
  python src/main.py --version
  ```

- 不创建窗口的自检 | Self-check that creates no window

  ```bash
  python src/main.py --selftest
  ```

- 跑测试 | Run the tests

  ```bash
  pytest
  ```

- 看目录树的真实结构（排查树形导航时用过）| Inspect the real widget structure

  ```bash
  python tools/probes/probe_tree_labels.py
  ```

- 接下来请开始您的自定义。 | From here, feel free to customize it as you like.

<br><br>

## 代码结构 | Code layout

```
src/
├── main.py                     入口：python src/main.py
└── file_tracker/
    ├── core.py        ─┐
    ├── store.py        │  不依赖 wx —— 可以在没有桌面会话的环境里测试
    ├── config.py       │
    ├── tree_nav.py     │
    ├── theme.py        │
    ├── win32.py       ─┘
    ├── lang.py           双语（L("中文","English") 写在调用点）
    ├── widgets.py        自绘控件
    ├── header.py         自绘列头
    └── app.py            主窗口
```

> 旧的 `src/File Tracker_v1.1.py` 兼容垫片已在 v1.2.4 删除。
> 它的文件名**带空格所以不可能被 import**，这也正是当初换掉它的原因。

**分层的目的是让判断可以自动验证。** 窗口尺寸的计算、路径规范化、目录树的
路径匹配这些以前埋在窗口类里、只能靠人眼看的逻辑，现在都在不依赖 wx 的模块里，
由 `tests/` 覆盖；`tests/test_core.py` 里有一条测试专门守着这条边界。

<br><br>

## 构建与验证 | Build and verify

```powershell
# 构建：环境检查 → 测试 → 打包 → 产物自检 → 报告哈希
powershell -File build.ps1

# 在真实桌面会话里核对界面改动（会开一个窗口，约 3-5 秒后自动关闭）
powershell -File tools/verify_gui.ps1

# 接线检查：找出"定义了却从来没有人读取"的东西
python tools/check_wiring.py
python tools/check_wiring_negative.py   # 它的阳性对照

# 对话框调用点检查：两按钮却没读返回值（用户报过"两个按钮功能完全一致"）
python tools/check_dialogs.py
python tools/check_dialogs_negative.py  # 它的阳性对照

# 重复方法检查：同名方法定义两次，Python 只用后一个，"改前一个"没有任何效果
python tools/check_duplicate_methods.py
python tools/check_duplicate_methods_negative.py

# 审计条目清账：44 条判据，逐项确认已处理
python tools/check_audit_items.py
```

**每个检查器都带一份阳性对照**（`*_negative.py`）——先造一个必然被拦的样本，
确认它真的会报错。**"返回通过"和"没有运行"在输出里长得一模一样**，
所以阴性的结果必须先证明检测器跑了。

`build.ps1` 最后会真的运行产物的 `--version`，确认它**自报的提交哈希**与本次
构建一致——"我以为我写进去了"和"它真的在里面"是两件事。它还会读回产物的
**版本资源**，确认属性页里那五项真的写进去了。

发版流程见 `docs/RELEASING.md`。

<br><br>

## 开发者贡献 | Developer Contributions
- 欢迎提交 issue 或 pull request！

<br>

- You are welcome to submit issues or pull requests!
