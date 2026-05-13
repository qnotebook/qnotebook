# AGENTS.md

## Project

**qnotebook** — a PyQt6 wiki editor with true WYSIWYG editing over markdown
files on disk. Heavily inspired by Zim Desktop Wiki, but written from scratch — no code shared,
Python + PyQt6 + `markdown-it-py`.

## Scope (v0.4)

- Open a notebook: any directory with `.md` files.
- Tree of pages with lazy-loaded children (directory hierarchy).
- **Single-surface WYSIWYG editor** — one `QTextEdit` subclass that renders
  markdown as styled rich text and re-serializes on save.
- Markdown formatting toggles (bold / italic / strike / inline code),
  heading levels 1–6 via block kind, paragraph toggle.
- Wikilinks (`[[Page]]`, `[[Foo:Bar]]`, `[[Target|alias]]`) render as
  clickable anchors. Regular markdown links too.
- Task lists (`- [ ]` / `- [x]`) — click to toggle.
- Tables, blockquotes, fenced code, ordered/unordered/nested lists,
  horizontal rules.
- Backlinks dock — SQLite-backed index query.
- Back/forward navigation (Alt+Left / Alt+Right), `QSettings` remembers
  the last opened notebook.
- Save (Ctrl+S), New Page (Ctrl+N), Open Notebook (Ctrl+O).
- **Find-in-page** (Ctrl+F) — inline toolbar bar below the editor with
  next/prev buttons, match count, and a case-sensitive toggle. Ctrl+G /
  F3 jump to the next match, Shift+F3 to previous, Esc closes the bar
  and returns focus to the editor.
- **Link rewrite on rename** — `Index.rename_page_and_rewrite(old, new)`
  performs the filesystem rename, relabels pages/links rows (including
  descendants), and walks every inbound page to rewrite `[[old]]` →
  `[[new]]` (slash and colon forms are treated equivalently; aliases
  are preserved). `MainWindow.rename_page` wraps this and reloads the
  editor if the currently-open page moved or was rewritten.
- **Image insertion.** Toolbar button + Ctrl+V paste + drag-and-drop of
  local image files. Images live in a `_resources/` subdirectory next
  to the page that inserted them; filename collisions append `-1`, `-2`,
  etc. The markdown source uses standard `![alt](_resources/name.ext)`
  syntax. Pasted `QImage` data is saved as
  `pasted-YYYYMMDD-HHMMSS.png`. Rendering is capped at 600px wide with
  aspect ratio preserved.

## Notebook layout

```
MyNotebook/
  .qnotebook/
    index.sqlite           # backlinks + page index
  Home.md
  Sub.md                   # optional parent page
  Sub/
    Child.md               # Sub:Child in the API; [[Sub/Child]] or [[Sub:Child]] as link
  Other.md
  _resources/              # images attached to Home.md / Other.md live here
    logo.png
  Sub/
    _resources/            # images attached to Sub:Child live here
      diagram.png
```

**Image storage convention.** Each page's inserted images live in a
`_resources/` directory that is a *sibling* of the markdown file (i.e.
for `Sub/Child.md`, images live in `Sub/_resources/`). Image references
in markdown are always relative (`_resources/foo.png`).

The `:` in the page-path API (`Foo:Bar`) maps to a path separator on
disk (`Foo/Bar.md`). Both `[[Foo:Bar]]` and `[[Foo/Bar]]` resolve to the
same target — wikilink extraction normalizes `/` to `:`.

## Markdown flavor (supported subset)

- Headings H1–H6 (ATX: `# ... ######`, single space after `#`)
- Paragraphs (blank line separated)
- Emphasis: `**bold**`, `_italic_`, `~~strike~~`
- Inline code: `` `code` ``
- Fenced code: ```` ```lang ... ``` ````
- Links: `[text](url)`
- Wikilinks: `[[Target]]`, `[[Target|alias]]`, `[[Foo:Bar]]`, `[[Foo/Bar]]`
- Bullet lists (`-`), ordered lists (`1.`), nested (2-space indent)
- Task lists: `- [ ]` / `- [x]`
- Blockquotes: `> ...`
- Tables (GFM pipe syntax, header row required)
- Horizontal rules: `---`

**Canonical emission.** The serializer always uses `-` for bullets, `**`
for bold, `_` for italic, `~~` for strike, ATX headings with a single
space, and fenced code with triple backticks. Tables are always
pipe-aligned. Ordered lists use `1. 2. 3.` numbering recovered from
`QTextList.itemNumber`. When you load+save an existing page, these
canonicalizations may rewrite the source — but the round-trip is
idempotent (a fixed point) after the first save.

## Round-trip strategy

This is the load-bearing property of the project.

1. `md_to_qdoc.markdown_to_qdoc(md, doc)` parses with `markdown-it-py`
   (commonmark + table + strikethrough) and walks tokens, inserting
   styled runs into a `QTextDocument`. Block-level kind and extra data
   (heading level, list kind, ordered-list start, code fence language,
   task state, wikilink target) are stored on Qt formats as
   `QTextFormat.Property.UserProperty + N` slots (constants defined at
   the top of `md_to_qdoc.py`).
2. `qdoc_to_md.qdoc_to_markdown(doc)` walks `QTextBlock`s and fragments,
   reads those custom properties, and emits markdown.

**Property**: `serialize(parse(md))` converges to a fixed point in at
most one pass for every supported construct (see `tests/test_md_roundtrip.py`).

## Index schema

`.qnotebook/index.sqlite`:

```sql
CREATE TABLE pages (path TEXT PRIMARY KEY, mtime REAL NOT NULL);
CREATE TABLE links (src TEXT NOT NULL, dst TEXT NOT NULL);
CREATE INDEX idx_links_dst ON links(dst);
CREATE INDEX idx_links_src ON links(src);
```

Wikilinks are extracted from the markdown **source** (not the rendered
`QTextDocument`) via regex, skipping fenced code blocks and inline code
spans. Rebuilt on notebook open; incrementally updated on save.

## Module map

- `qnotebook/__main__.py`       — entry point, `QApplication` setup
- `qnotebook/window.py`         — `MainWindow` (tree + editor + backlinks dock)
- `qnotebook/editor.py`         — `MarkdownEditor(QTextEdit)` WYSIWYG surface
- `qnotebook/md_to_qdoc.py`     — markdown → `QTextDocument`
- `qnotebook/qdoc_to_md.py`     — `QTextDocument` → markdown
- `qnotebook/notebook.py`       — filesystem layer (`Notebook`, `PageRef`)
- `qnotebook/index.py`          — SQLite index + wikilink extractor
- `qnotebook/page_model.py`     — `QAbstractItemModel` over the notebook
- `qnotebook/history.py`        — back/forward stack
- `qnotebook/search.py`         — `Search(notebook, index)` full-text query

## Features added in v0.4

- **Page operations:** delete (with inbound-link warning), move, copy,
  plus a tree context menu (right-click).
- **Drag-and-drop page moves** via `PageTreeModel.dropMimeData`.
- **Full-text search** (`qnotebook/search.py`), SearchDock widget,
  Ctrl+Shift+F. Uses SQLite FTS5 for prefiltering when available;
  falls back to a full .md scan.
- **Tags**: `#tag` extraction (`index.extract_tags`, `index.tags()`,
  `index.pages_with_tag()`), inline styling in the editor (blue,
  DemiBold), TagsDock widget.
- **Recent pages + Bookmarks** persisted per-notebook in `QSettings`;
  Go menu.
- **Insert menu**: Date (Ctrl+D), Time, Date+Time, Horizontal Rule,
  Symbol (common arrows/currency/math).
- **Auto-save** (`MarkdownEditor.autoSaveRequested`, default on, 30s
  idle). Focus-out also triggers a save. Title shows `*` when dirty.
- **Word count / char count / reading time** in the status bar.
- **Attachments** (non-image files) copied into `_resources/` and
  inserted as `[filename](_resources/filename.ext)`. Toolbar action +
  drag-drop of non-image files.
- **Code block syntax highlighting** via Pygments for fenced blocks
  with a language tag. Colors are applied per fragment, serialization
  still round-trips to the same fence + content.

## Explicitly deferred features (wave 2+)

- **Live incremental re-parse per block.** Currently the document is
  fully re-serialized on save. It's fast enough for reasonable pages,
  but a per-block dirty-range serializer is a future optimization.
- **Export** (HTML/PDF).
- **Spell check.**
- **Plugins.**
- **mdit-py-plugins tasklist extension.** We detect `[ ]` / `[x]`
  ourselves on the first text token of a bullet-list item.
- **Tag autocomplete** while typing `#`.
- **Search result highlighting** in the editor after a jump.

## Build / test commands

```bash
just run /path/to/notebook  # launch (needs X display)
just verify                 # PyQt6 + markdown-it-py sanity check
just test                   # full suite per-file (offscreen)
just test-fast              # full suite in one process
just test-file FILE=...     # single file
just test-match PATTERN     # substring -k
just compile                # syntax check
```

## Dependencies

System (openSUSE / Debian / Fedora auto-detected by `just install-deps`):

- `PyQt6`
- `pytest` + `pytest-qt`
- `markdown-it-py` (v3+ / v4 works)

No GObject, no GTK, no `pyxdg`.

## Test conventions

- Headless: `QT_QPA_PLATFORM=offscreen`
- `tests/conftest.py` provides the `qapp` session fixture and
  `tmp_notebook` (a 4-page markdown notebook).
- After each test: `processEvents + gc.collect` to release PyQt
  C++ objects.
- `MainWindow._maybe_save_dirty` returns `True` by default so tests
  close cleanly without a modal; monkeypatch to test the prompt path.

## Non-obvious gotchas

- **Headings emit bold char runs.** The serializer must suppress `**…**`
  for fragments whose font point size exceeds 11.5 (heuristic used to
  distinguish heading-level bold from explicit `**` bold). Same logic
  for table header cells.
- **Empty paragraphs.** `QTextCursor.insertTable` leaves an empty block
  before the table. The serializer skips any block whose inline
  rendering is empty rather than emitting a stray blank line.
- **`QTextList` identity.** For ordered lists to number correctly
  (1. 2. 3. rather than 1. 1. 1.), every item in the same markdown list
  must be added via `QTextList.add(block)` to the same `QTextList`
  object — not via separate `cursor.createList()` calls. See the
  `qlist_stack` discipline in `md_to_qdoc._apply_list_format`.
- **Ordered list numbering on serialize.** We use
  `textList.itemNumber(block) + 1` as the marker; the original `start`
  attribute is preserved in a block property but not currently
  surfaced (always starts at 1).
- **Image fragments don't carry alt in Qt.** `QTextImageFormat` stores
  the path in `name()` but has no built-in alt attribute. We stash the
  alt on `CHAR_IMAGE_ALT` (a `UserProperty+12` slot) at insertion time
  and read it back on serialize. Images inserted outside our helpers
  (via `setName` alone) serialize with empty alt.
- **Image resource registration.** Loading a markdown page re-registers
  each referenced image under its relative path via
  `doc.addResource(ImageResource, QUrl(rel), QImage(abs))`. Without
  this, Qt renders a broken-image placeholder. `markdown_to_qdoc` needs
  `base_path` (the page file's directory) to resolve these.
- **`FindBar` widget.** Lives at the bottom of the editor column inside
  a `QVBoxLayout`. `_open_find` shows it and focuses the line-edit. The
  wrap-around in `_find` catches the "no match from cursor position"
  case by resetting the cursor to doc start/end and retrying.
- **Task-list detection** is done by regex `^\[[ xX]\]\s+` on the first
  `text` token of a bullet list item's first paragraph, then stripping
  that prefix before rendering. Bold/italic inside a task item after
  the checkbox work normally.
- **Tag detection** only matches `#foo` when the `#` is at start-of-line
  or after whitespace / `(` / `[`. URL fragments like `site.com#frag`
  and `[[Page#section]]` are excluded by the extractor stripping links
  first. Inside code spans / fenced blocks the run is passed through
  verbatim without a `CHAR_TAG` property.
- **Pygments in fenced code.** `markdown_to_qdoc` splits token text on
  `\n` and emits one line per code block. A trailing empty line from
  the lexer is stripped so round-trips stay a fixed point. If the
  language is unknown or Pygments is missing the block falls back to
  plain monospace (same code path as v0.3).
- **FTS5** is initialized opportunistically. `Index.has_fts()` reports
  availability; old SQLite builds keep working via a plain scan. The
  `pages_fts` table is kept in sync in `_update_page_locked`, `remove_page`
  and `rename_page`.
- **Recents / bookmarks** are stored under `QSettings` key
  `notebooks/<abs-path>/{recent,bookmarks}` so switching notebooks
  swaps the state. Tests isolate `QSettings` via
  `QSettings.setPath(IniFormat, UserScope, tmpdir)` in a fixture.
- **Auto-save timer**: `MarkdownEditor._autosave_timer` is a single-shot
  `QTimer` that restarts on every `textChanged` while dirty. Use
  `set_autosave_interval_ms(ms)` in tests for a fast interval.
- **Drag-drop drop target.** `PageTreeModel.dropMimeData` rejects drops
  onto self and onto a descendant of self (would orphan the move). A
  drop with `parent.isValid() == False` is interpreted as "move to
  top level".

## Key design decisions

- **Markdown on disk.** No proprietary format; any markdown editor can
  open a notebook.
- **Single QTextEdit, no preview tab.** What-you-see-is-markdown.
- **Parse on load, serialize on save.** We do not keep the token stream
  around; the `QTextDocument` is the authoritative in-memory state.
- **SQLite for the index**, not an in-memory dict — survives restart,
  scales to large notebooks.
- **Round-trip tests are parametrized** and added to whenever a new
  construct is supported. If you add a new markdown feature, add a
  sample to `tests/test_md_roundtrip.py::SAMPLES`.
