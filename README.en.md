<div align="center">

# ⭐ File Tracker

**Remembers the folders you visit — sorted by how often and how recently you use them. Double-click to jump straight there.**

[简体中文](README.md) ｜ [**English**](README.en.md)

![Light theme](https://raw.githubusercontent.com/Neus117/File-Tracker/main/images/FileTracker_v1.2.4-light.jpg)

![Dark theme](https://raw.githubusercontent.com/Neus117/File-Tracker/main/images/FileTracker_v1.2.4-dark.jpg)

[**Download latest**](https://github.com/Neus117/File-Tracker/releases/latest) ·
[All releases](https://github.com/Neus117/File-Tracker/releases) ·
[Known limitations](#known-limitations)

</div>

---

## Features

### Left pane · File browser

- Tree-view navigation
- **Address bar**: paste or type a path and press Enter to jump there **and record
  one visit** (`Ctrl+L` to focus)
- Select folders or files; double-clicking a file opens its parent folder
- Remembers the last location you browsed; resets the horizontal scroll bar

### Right pane · Path logger

- Automatically logs the paths you visit
- **Click a column header to sort — your choice is remembered** and restored on
  the next launch
- **Settings dialog** (the gear button at the bottom right): switch the UI
  language, pick the sort order
- Bilingual (Chinese/English): follows the Windows display language, or set it
  manually — switching takes effect immediately
- Pin / unpin paths — **a newly pinned entry goes to the top**
- `Ctrl+C` to copy a path · right-click context menu · delete one entry or clear all
- Light / dark theme follows the system setting

---

## How to use

| | |
|---|---|
| **Download** | Get `File.Tracker_v1.3.1.exe` from [Releases](https://github.com/Neus117/File-Tracker/releases/latest) and run it — portable, no installation |
| **Database** | On first launch it creates `file_tracker.db` under `C:\Users\<you>\` (named `file_access.db` back in v1.0) |
| **Run at startup** | Press `Win+R`, type `shell:startup`, press Enter, and drop a shortcut into the folder that opens |
| **Uninstall** | Delete the exe and `file_tracker.db` |
| **Check the version** | `File.Tracker_v1.3.1.exe --version` prints something like `File Tracker 1.3.1+ae4a6f4` — the part after `+` is the commit it was built from |

> **About the asset name**: from v1.2.0 onward it is uniformly
> `File.Tracker_v<full version>.exe`. The four earlier releases each used a
> different name (one was even missing a dot), which made it easy to download
> the wrong file.
>
> **Without a console** (for example when you double-click the exe), `--version`
> instead writes `%APPDATA%\File Tracker\version.txt` and shows a notice that
> closes itself after 6 seconds.

---

## Compared with v1.1.0

v1.1.0 shipped on 2024-10-14; v1.3.0 on 2026-10-16. **More features, smaller download.**

| | v1.1.0 | **v1.3.0** |
|---|---|---|
| Size | 15.76 MB | **12.96 MB** |
| UI language | Chinese only | **Chinese/English, switchable** |
| Sorting | Fixed to frequency | **Choose the column and direction; remembered across restarts** |
| Pin order | Newest pin went last, and moved after a restart | **Newest pin goes first, and stays there** |
| Settings dialog | None | **Yes** (language + sorting) |
| Dark theme | Some controls ignored it | **All custom-drawn controls follow it** |
| Address bar + Enter | Did not open Explorer | **Actually opens it** |
| Automated tests | **0** (and the test file imported two names that did not exist) | **192 unit tests + 186 GUI checks** |
| Build pipeline | **None** (no `.spec`, no script, no CI) | `build.ps1` + 9 gates + GitHub Actions |
| Binary reports its version | No | **Yes** (name / version / commit) |
| Version info in file properties | Nearly blank | **All five fields filled** |

**Where the size reduction comes from** — and it happened while *adding* features:

- Only runtime assets are bundled. Previously the whole `images/` folder was
  packed in, including the screenshots on this page.
- `tarfile`, `hashlib` and `email` are excluded — they are only used internally
  by the standard library, but pulling them in also dragged 2.11 MB of
  `libcrypto-3-x64.dll` into the build.

---

## Known limitations

**Opening a record gets slower once you have a lot of them.** Measured on this
machine at 175% DPI:

| Records | Full refresh after one "Open" |
|---|---|
| 200 | ~0.12 s |
| 1000 | ~0.39 s |
| 3000 | ~0.99 s |
| 6000 | ~1.9 s |

The cost is `wx.ListCtrl`'s per-row insert (1.53 s of that 1.9 s) — **not** the
database read (13 ms) and **not** the column-width pass (61 ms). So **capping the
number of records would not fix it.**

The real fix is a virtual list, but that touches row highlighting, hover
tracking and the pinned-row tint — it deserves its own round of work.

**For everyday use (tens to hundreds of records) this is imperceptible.**
The measurement scripts and full conclusions are in `tools/probes/README.md`,
under "list scale".

---

## Dependencies

- Python 3.11
- v1.1+ depends on wxPython; packaging needs PyInstaller
- Full list in `requirements_v1.1+.txt`; environment file is `environment_v1.1+.yml`

> **Do not upgrade Python casually.** `wxPython==4.2.2` ships wheels for
> **cp313 at most** on PyPI (measured: cp38–cp313), while this machine's conda
> base is 3.14 — **it will not install.** Create the 3.11 environment from
> `environment_v1.1+.yml`.

---

## For developers

### Setup

```bash
git clone https://github.com/Neus117/File-Tracker.git
cd File-Tracker
conda env create -f environment_v1.1+.yml
conda activate ft_env
pip install -r requirements-dev.txt
```

Both environment files use the same environment name, `ft_env`, so **they cannot
be installed side by side**. Run `conda env remove -n ft_env` before switching.

### Debugging

```bash
python src/main.py               # start the app
python src/main.py --version     # print the version (including the build commit)
python src/main.py --selftest    # self-check that creates no window
pytest                           # run the tests
```

There is a probe that prints the real widget structure, which was used while
debugging the tree navigation:

```bash
python tools/probes/probe_tree_labels.py
```

### Code layout

```
src/
├── main.py                     entry point: python src/main.py
└── file_tracker/
    ├── core.py        ─┐
    ├── store.py        │  no wx dependency — testable without a desktop session
    ├── config.py       │
    ├── tree_nav.py     │
    ├── theme.py        │
    ├── win32.py       ─┘
    ├── lang.py           bilingual (L("中文","English") at the call site)
    ├── widgets.py        custom-drawn controls
    ├── header.py         custom-drawn column header
    └── app.py            main window
```

**The layering exists so that judgements can be automated.** Window sizing, path
normalisation and directory-tree path matching used to be buried in the window
class where only a human eye could check them; they now live in wx-free modules
covered by `tests/` — and `tests/test_core.py` has a test that guards exactly
that boundary.

> The old `src/File Tracker_v1.1.py` shim was deleted in v1.2.4. Its filename
> **contains a space, so it could never be imported** — which is precisely why
> it was replaced.

### Build and verify

```powershell
# build: environment check → tests → package → artifact self-check → report hash
powershell -File build.ps1

# verify the UI in a real desktop session (opens a window, closes after ~3-5 s)
powershell -File tools/verify_gui.ps1
```

**Nine gates**, all wired into `build.ps1` and CI:

| Checker | What it catches |
|---|---|
| `pytest` | 192 unit tests, no GUI required |
| `check_wiring.py` | Things that are defined but never read |
| `check_dialogs.py` | Dialogs given two buttons whose return value is ignored (users once reported "both buttons do the same thing") |
| `check_duplicate_methods.py` | A method defined twice — Python silently keeps the last one, so **editing the first has no effect** |
| `check_audit_items.py` | Line-by-line audit sign-off (50 criteria) |
| `add_bom.py --check` | The UTF-8 BOM on `.ps1` files — editors strip it, and PowerShell 5.1 then reads Chinese as mojibake |

**Three of them ship with a negative control** (`*_negative.py`): a sample that
must be rejected, proving the checker really fires. **"Returned clean" and
"never ran" look identical in the output**, so a negative result has to be
proven first.

Finally, `build.ps1` actually runs the artifact's `--version` and confirms the
**commit hash it reports** matches this build — "I thought I wrote it in" and
"it is really in there" are two different things. It also reads back the
artifact's **version resource**, confirming those five fields were really
written.

The release process is documented in `docs/RELEASING.md`.

---

## Contributing

Issues and pull requests are welcome.
