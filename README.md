# :star: File Tracker
- 一个自动跟踪文件路径并根据使用频率和时间排序的工具

- File Tracker_v1.2.0 发布！！！更小的体积，更快的响应速度，更方便的功能实现！！！

<br>

- A tool for automatically tracking file paths and sorting them by usage frequency and time.

- File Tracker_v1.2.0 Grand Release!!! Smaller size, faster response time, and more convenient functionality!!!

<div align="center">

![File Tracker 概览](https://raw.githubusercontent.com/Neus117/File-Tracker/main/images/FileTracker_v1.1-Overview.jpg)

</div>

## 功能 | Features
左边的文件选择器(Browser)支持
- 树状图浏览导航
- **地址栏：粘贴或输入路径后回车，直接跳到该位置并记录一次访问（Ctrl+L 聚焦）**
- 同时支持选择文件夹或文件(选择文件可双击直接打开其父文件夹)
- 记忆上次浏览的视图位置
- 自动重置水平滚动条

右边的路径记录器(Logger)支持
- 自动记录路径
- 按使用频率或时间排序（点列头或"切换排序"按钮）
- 频次列数字居中显示
- Ctrl C 复制路径
- 右键菜单展开功能选项
- 路径顶置和取消顶置
- 路径的单独或全量删除
- 置顶和取消置顶用户图形界面

<br><br>

The file selector (Browser) on the left supports:
- Tree-view navigation
- **An address bar: paste or type a path and press Enter to jump there and record one access (Ctrl+L to focus)**
- Ability to select both folders and files (double-clicking a file allows direct access to its parent folder)
- Memory of the last viewed location
- Automatic reset of the horizontal scroll bar

The path logger (Logger) on the right supports:
- Automatic path logging
- Sorting based on frequency of use or time (click a column header or the "切换排序" button)
- The frequency column is centre-aligned
- Path copying via Ctrl + C
- Context menu with expanded options on right-click
- Pinning and unpinning of paths
- Individual or bulk deletion of paths
- Pinning and unpinning of the user interface elements

<br><br>

## :bulb: 使用说明 | How to Use
- 在 Releases 中下载并运行 `File.Tracker_v1.2.0.exe` 即可使用。
  （这个名字从 v1.2.0 起统一为 `File.Tracker_v<完整版本号>.exe`——
  此前四个版本的资产名各不相同，容易下错。）

- 程序运行后会在 "C:\Users\Currentuser" 下释放一个数据库文件(1.0+ 版本文件名为 file_access.db，1.1+ 版本文件名为 file_tracker.db)，用于储存路径信息。

- 在 Windows 系统中添加自启动任务的方法：WIN+R 打开运行，然后输入命令 shell:startup 回车。之后将需要添加自启动任务的程序快捷方式放入弹出的窗口即可。

- 如何卸载：直接删除 File.Tracker_v1.2.0.exe 和 file_tracker.db(或 file_access.db)。

<br><br>

- Download and run `File.Tracker_v1.2.0.exe` from the Releases section to start using the program.
  (From v1.2.0 onward the asset name is uniformly `File.Tracker_v<full version>.exe` —
  the previous four releases each used a different name.)

- After the program is launched, a database file will be created under "C:\Users\Currentuser" (file name for version 1.0+ is file_access.db, and for version 1.1+ it is file_tracker.db), which will store path information.

- To add the program to startup in Windows: Press WIN+R to open the Run dialog, then type the command shell:startup and press Enter. Add the shortcut of the program that you want to start automatically to the folder that opens.

- To uninstall: Simply delete File Tracker.exe and file_tracker.db (or file_access.db).

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

> 旧的 `src/File Tracker_v1.1.py` 兼容垫片已在 v1.2.5 删除。
> 它的文件名**带空格所以不可能被 import**，这也正是当初换掉它的原因。

**分层的目的是让判断可以自动验证。** 窗口尺寸的计算、路径规范化、目录树的
路径匹配这些以前埋在窗口类里、只能靠人眼看的逻辑，现在都在不依赖 wx 的模块里，
由 `tests/` 覆盖；`tests/test_core.py` 里有一条测试专门守着这条边界。

<br><br>

## 构建与验证 | Build and verify

```powershell
# 构建：环境检查 → 测试 → 打包 → 产物自检 → 报告哈希
powershell -File build.ps1

# 在真实桌面会话里核对四项界面改动（会开一个窗口，约 3-5 秒后自动关闭）
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
```

`build.ps1` 最后会真的运行产物的 `--version`，确认它**自报的提交哈希**与本次
构建一致——"我以为我写进去了"和"它真的在里面"是两件事。

发版流程见 `docs/RELEASING.md`。

<br><br>

## 开发者贡献 | Developer Contributions
- 欢迎提交 issue 或 pull request！

<br>

- You are welcome to submit issues or pull requests!
