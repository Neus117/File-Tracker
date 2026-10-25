<div align="center">

# ⭐ File Tracker

**Remembers the folders you visit — sorted by how often and how recently you use them. Double-click to jump straight there.**

[简体中文](README.md) ｜ [**English**](README.en.md)

![Light theme](https://raw.githubusercontent.com/Neus117/File-Tracker/main/images/FileTracker_v1.4.0-light.jpg)

![Dark theme](https://raw.githubusercontent.com/Neus117/File-Tracker/main/images/FileTracker_v1.4.0-dark.jpg)

[**Download latest**](https://github.com/Neus117/File-Tracker/releases/latest) ·
[All releases](https://github.com/Neus117/File-Tracker/releases) ·
[Known limitations](#known-limitations)

</div>

---

## Features

### Left pane · File browser

- Tree-view navigation
- **Address bar**: paste or type a path and press Enter to jump there **and record
  one visit** (`Ctrl+L` to focus); big folders **along the way** list their
  subfolders first and fill in files when you expand them; **navigating somewhere
  new collapses the previous path** (only the current one stays expanded)
- Select folders or files; double-clicking a file opens its parent folder
- Remembers the last location you browsed; resets the horizontal scroll bar

### Right pane · Path logger

- Automatically logs the paths you visit, in **three columns**: path / count / last visit
- **Date and time share one column** — one line tells the whole story
- **Click a column header to sort — your choice is remembered** and restored on
  the next launch (the header shows a ▲/▼ indicator)
- **Settings dialog** (the gear button at the bottom right): UI language,
  theme (follow system / light / dark), sort key, sort direction —
  **every control is a self-drawn icon button** with its own tooltip
- Bilingual (Chinese/English): follows the Windows display language, or set it
  manually — **switching takes effect immediately**, down to the window title and
  the icon tooltips, without pressing OK first
- Pin / unpin paths — **a newly pinned entry goes to the top**, and pinned rows
  get their own background colour
- `Ctrl+C` to copy a path · right-click context menu · delete one entry or clear all
- Light / dark theme follows the system setting, and every self-drawn control
  follows it too

---

## How to use

| | |
|---|---|
| **Download** | Get `File.Tracker_v1.4.3.exe` from [Releases](https://github.com/Neus117/File-Tracker/releases/latest) and run it — portable, no installation |
| **Database** | On first launch it creates `file_tracker.db` under `C:\Users\<you>\` (named `file_access.db` back in v1.0) |
| **Run at startup** | Press `Win+R`, type `shell:startup`, press Enter, and drop a shortcut into the folder that opens |
| **Uninstall** | Delete the exe and `file_tracker.db` |
| **Check the version** | `File.Tracker_v1.4.3.exe --version` prints something like `File Tracker 1.4.3+035231a` — the part after `+` is the commit it was built from |
| **Multi-select** (since v1.3.3) | Hold **Ctrl** and click to pick several rows, or **hold the left button and drag** across a range; **Shift**-click selects a run. With several rows selected, the context menu keeps only "Open N items" and "Delete N items" |

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

v1.1.0 shipped on 2024-10-14; v1.4.3 on 2026-10-26. **More features, smaller download.**

| | v1.1.0 | **v1.4.3** |
|---|---|---|
| Size | 15.76 MB | **12.73 MB** |
| UI language | Chinese only | **Chinese/English, switchable** |
| Sorting | Fixed to frequency | **Choose the column and direction; remembered across restarts** |
| Pin order | Newest pin went last, and moved after a restart | **Newest pin goes first, and stays there** |
| Settings dialog | None | **Yes** (language / theme / sort key / sort direction, all icon buttons) |
| Dark theme | Some controls ignored it | **All custom-drawn controls follow it** |
| Address bar + Enter | Did not open Explorer | **Actually opens it** |
| Automated tests | **0** (and the test file imported two names that did not exist) | **220 unit tests + 257 GUI checks** |
| Build pipeline | **None** (no `.spec`, no script, no CI) | `build.ps1` + 4 build checks + 9 gates in CI |
| Binary reports its version | No | **Yes** (name / version / commit) |
| Version info in file properties | Nearly blank | **All five fields filled** |

### What v1.4.3 is about — one thing: the dialog body layout

**The same dialog used to look right with one line and wrong with several.**
In a multi-paragraph message the warning badge floated to the left of the text
block while the first (shortest) line sat in the middle of the column, leaving a
wide gap between icon and text.

There is now one rule that does not depend on the text:

- "badge + gap + the widest line" is centred **as a group**;
- **every line inside the group shares one left edge** — no per-line centring;
- the badge is centred on the **first line** and hugs the text column;
- **no blank line between paragraphs** — only line spacing, so the dialog got
  shorter (the missing-path one went from 529×356 to 529×296).

A single-line dialog renders **byte-identical** before and after (same bitmap
sha256).

### What v1.4.2 is about — four things

1. **Enter in the address bar is 4–10× faster** — for a path like
   `C:\Windows\System32\drivers\etc`: **296 → 70 ms**, and the tree grows by
   **5789 → 614** nodes. The cause was that expanding along the path built every
   file of every ancestor as a tree node (`System32` alone has 4708), just to show
   one level further down. Big folders now list sub-folders first; files appear
   when you open them.

2. **A whole day of use no longer slows the app down** — previously every opened
   folder stayed expanded and nodes were never reclaimed, so after a few hours
   closing took a dozen seconds (measured: 45746 nodes → **11 s** to close). Now:
   navigating collapses the previous path, the tree is rebuilt once it exceeds
   4000 nodes, and folders like `WinSxS` (19727 entries) are **paged**
   (800 at a time plus a last row saying how many are left; collapse and expand
   again to load the next page).

3. **Three dark-theme holes closed** — system-drawn parts (context menus, scroll
   bars) followed the **system** theme, so "system light + app dark" still got a
   white menu; the light setting was also sent as "follow the system", so a light
   app on a dark system got a dark menu; and switching theme at runtime did not
   update menus (they need an extra flush of the menu theme). All three fixed.

4. **The dialog warning badge is now drawn, not typed** — the old `⚠️` was a font
   glyph whose size is decided by the font and **cannot be made larger than the
   body text**. It is now an equilateral outlined triangle with an exclamation
   mark built from geometry (spec: `Icons-Drawing.md` → `warning`), sized at
   **1.8× the body line height** and tucked right next to the first line.

### What v1.4.0 is about — three things

1. **A lot of visual tuning** — column widths and separators after merging to three
   columns, header sort arrows, row padding, and every colour pair checked for
   contrast in both themes. The settings dialog now uses **self-drawn icon buttons**
   (eight glyphs: monitor / sun / moon / folder / bars / clock / ↑ / ↓).

2. **Three defects fixed** —
   - **Clearing a large selection froze the app**: 6000 rows went from **166 s** to
     **0.2 s**. The cause was a per-row "repaint the whole table" cascade — about
     36 million native calls.
   - **Double-clicking a record raised `AttributeError`**: `event.Veto()` does not
     exist on mouse events.
   - **Switching language left two things stale**: the window title and the icon
     tooltips (every other string did update).

3. **Date and time merged into one column** — they used to be separate; now one
   line tells the whole story, and clicking that header sorts by it.

**Where the size reduction comes from** — and it happened while *adding* features:

- Only runtime assets are bundled. Previously the whole `images/` folder was
  packed in, including the screenshots on this page.
- `tarfile`, `hashlib` and `email` are excluded — they are only used internally
  by the standard library, but pulling them in also dragged 2.11 MB of
  `libcrypto-3-x64.dll` into the build.

---

## Known limitations

**The navigation tree has three limits**, all of them there to keep a whole day of use
from getting slower:

1. **The folder you navigate to must be complete** — but the program will not expand a
   folder with **more than 2500 entries** for you: `C:\Windows\WinSxS` has 19727
   subfolders and takes **2.7 s** to expand. When **you** expand it, **800 are shown
   at a time** and the last row says how many are left — **collapse and expand again**
   to load the next page (about 0.1 s each).
2. **Navigating somewhere new collapses the previous path** — only the current path
   stays expanded. It used to stay expanded forever, so nodes piled up over hours.
   **Opening with the Open button counts too** (the old path collapses as well).
3. **The tree is rebuilt once it exceeds 4000 nodes** (still keeping only the current
   path). Closing time grows **super-linearly** with node count: measured 6295 nodes
   → **0.35 s**, 45746 nodes → **11 s**.

Along the way, big folders that are merely **passed through** (say `System32` on the
way to `…\drivers\etc`) no longer build file nodes, so that Enter goes from
**296 ms to about 70 ms** and the tree shrinks from **5789 to roughly 600** nodes.

**Opening a record still rebuilds the list when you have a lot of them.**
v1.3.3 cut that roughly in half:

| Records | Full refresh after one "Open" (v1.3.2 → **v1.3.3**) |
|---|---|
| 200 | 0.070 → **0.063 s** |
| 1000 | 0.136 → **0.099 s** |
| 3000 | 0.418 → **0.309 s** |
| 6000 | 1.180 → **0.626 s** |

(Repeat runs on the same machine vary by ±15%; the 6000-row figure measured
between 0.63 s and 0.79 s — so "roughly half" is the conservative claim.)

The database read is only a dozen milliseconds — the cost is `wx.ListCtrl`'s
per-row insert and attribute writes: about 30 000 cross-language native calls
for 6000 rows. So **capping the number of records would not fix it.** The real
fix is a virtual list (`wx.LC_VIRTUAL`), but it does **not** support per-item
background colours — and full-row highlighting, hover tracking and the pinned
tint all rely on those. That deserves its own round of work.

**For everyday use (tens to hundreds of records) this is imperceptible.**
The measurement scripts and full conclusions are in `tools/probes/README.md`:
`probe_perf_baseline.py` times each operation, and `probe_perf_detail.py`
breaks the rebuild down to the call level.

> One road that was tried and **does not work**: the multi-column overload of
> `wx.ListCtrl.InsertItem` matches none of its four overloads in wxPython
> 4.2.2 (wx does not expose it), so the three `SetItem` calls per row
> (count / date / time) cannot be saved. See `probe_insertitem_overload.py`.

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
| `pytest` | 220 unit tests, no GUI required |
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

**The release chain** (version-bump commit → rebuild → tag → push → create the
release → download it back and verify the hash) is baked into the scripts and
checks above, with the rules stated as hard criteria:

- The tag must point at a **code commit**, not a documentation commit.
- The hash the artifact reports must equal `git rev-parse --short=7 HEAD`.
- **"Upload succeeded" and "what is online is this exact build" are two
  different things** — you must download it back and recompute the SHA256.
- The release notes body has to be **pulled back and compared word for word**
  with the local copy (once only 2% made it: 1731 characters locally, 42
  online, and the command still reported success).

> The repository used to carry three **working documents** (a theming/layout
> cheat sheet, a handover note, and a development log). They recorded *the
> facts of the moment* rather than *rules* — line numbers drift and version
> numbers go stale, so **keeping them in the repository is worse than not
> having them** (the next person edits against outdated line numbers). They
> have been archived to a development notes collection outside this
> repository, and `tools/check_doc_lines.py` — written solely to verify those
> line numbers, and never invoked by any script — was removed along with them.
> **The `docs/` directory itself is gone**: the release and verification
> rules now live in the scripts and checkers, whose criteria are
> **executable** rather than written down in a document that can go stale.

---

## Contributing

Issues and pull requests are welcome.
