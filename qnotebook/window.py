"""MainWindow: tree + WYSIWYG editor + backlinks dock."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QSettings, QModelIndex
from PyQt6.QtGui import QAction, QKeySequence, QTextCursor, QTextDocument
from PyQt6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QTreeView,
    QWidget,
)

from .editor import MarkdownEditor
from .search import Search, Hit


def _unique_path(desired: Path) -> Path:
    """Return `desired`, or `desired` with a `-1`, `-2`, ... suffix on collision."""
    if not desired.exists():
        return desired
    stem = desired.stem
    suffix = desired.suffix
    parent = desired.parent
    n = 1
    while True:
        candidate = parent / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


class FindBar(QWidget):
    """Inline find-in-page bar. Hidden by default; Ctrl+F toggles."""

    def __init__(self, editor: "MarkdownEditor", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Find")
        self.input.textChanged.connect(self._on_text_changed)
        self.input.returnPressed.connect(self.find_next)

        self.btn_prev = QPushButton("Prev", self)
        self.btn_prev.clicked.connect(self.find_prev)
        self.btn_next = QPushButton("Next", self)
        self.btn_next.clicked.connect(self.find_next)

        self.case_checkbox = QCheckBox("Aa", self)
        self.case_checkbox.setToolTip("Case sensitive")
        self.case_checkbox.stateChanged.connect(lambda _: self._recount())

        self.count_label = QLabel("", self)

        self.btn_close = QPushButton("x", self)
        self.btn_close.setFixedWidth(24)
        self.btn_close.clicked.connect(self.close_bar)

        layout.addWidget(self.input, 1)
        layout.addWidget(self.btn_prev)
        layout.addWidget(self.btn_next)
        layout.addWidget(self.case_checkbox)
        layout.addWidget(self.count_label)
        layout.addWidget(self.btn_close)

        self.hide()

    # ---- public API ----

    def open_bar(self) -> None:
        self.show()
        cur = self.editor.textCursor()
        if cur.hasSelection():
            self.input.setText(cur.selectedText())
        self.input.setFocus()
        self.input.selectAll()
        self._recount()

    def close_bar(self) -> None:
        self.hide()
        self.editor.setFocus()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close_bar()
            return
        super().keyPressEvent(e)

    # ---- search ----

    def _flags(self, backward: bool = False) -> QTextDocument.FindFlag:
        f = QTextDocument.FindFlag(0)
        if backward:
            f |= QTextDocument.FindFlag.FindBackward
        if self.case_checkbox.isChecked():
            f |= QTextDocument.FindFlag.FindCaseSensitively
        return f

    def find_next(self) -> bool:
        return self._find(backward=False)

    def find_prev(self) -> bool:
        return self._find(backward=True)

    def _find(self, backward: bool) -> bool:
        needle = self.input.text()
        if not needle:
            return False
        found = self.editor.find(needle, self._flags(backward))
        if not found:
            # Wrap around
            cur = self.editor.textCursor()
            wrap = QTextCursor(self.editor.document())
            if backward:
                wrap.movePosition(QTextCursor.MoveOperation.End)
            # Start: default cursor position is 0
            self.editor.setTextCursor(wrap)
            found = self.editor.find(needle, self._flags(backward))
            if not found:
                self.editor.setTextCursor(cur)
        self._update_count_label()
        return found

    def _on_text_changed(self, _text: str) -> None:
        self._recount()
        # Auto-advance to next match on typing
        needle = self.input.text()
        if not needle:
            return
        cur = self.editor.textCursor()
        cur.setPosition(cur.selectionStart())
        self.editor.setTextCursor(cur)
        self.find_next()

    def _recount(self) -> None:
        self._update_count_label()

    def _match_count(self) -> int:
        needle = self.input.text()
        if not needle:
            return 0
        doc = self.editor.document()
        flags = self._flags(False)
        count = 0
        cur = QTextCursor(doc)
        while True:
            cur = doc.find(needle, cur, flags)
            if cur.isNull():
                break
            count += 1
        return count

    def _update_count_label(self) -> None:
        needle = self.input.text()
        if not needle:
            self.count_label.setText("")
            return
        n = self._match_count()
        self.count_label.setText(f"{n} match" + ("" if n == 1 else "es"))
class SearchDock(QWidget):
    """Full-text search across the notebook. Results grouped by page."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout
        self._TreeWidget = QTreeWidget
        self._TreeWidgetItem = QTreeWidgetItem
        self._search: Search | None = None
        self._on_activate_page = lambda path, line: None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Search")
        self.input.returnPressed.connect(self._run)
        self.case_cb = QCheckBox("Aa", self)
        self.case_cb.setToolTip("Case sensitive")
        self.word_cb = QCheckBox("Wo", self)
        self.word_cb.setToolTip("Whole word")
        self.regex_cb = QCheckBox(".*", self)
        self.regex_cb.setToolTip("Regex")
        self.btn = QPushButton("Search", self)
        self.btn.clicked.connect(self._run)
        top.addWidget(self.input, 1)
        top.addWidget(self.case_cb)
        top.addWidget(self.word_cb)
        top.addWidget(self.regex_cb)
        top.addWidget(self.btn)
        v.addLayout(top)
        self.results = QTreeWidget(self)
        self.results.setHeaderHidden(True)
        self.results.itemActivated.connect(self._on_item_activated)
        v.addWidget(self.results, 1)
        self.status = QLabel("", self)
        v.addWidget(self.status)

    def set_search(self, search: Search | None) -> None:
        self._search = search

    def set_on_activate(self, cb) -> None:
        self._on_activate_page = cb

    def focus_query(self) -> None:
        self.input.setFocus()
        self.input.selectAll()

    def set_query(self, text: str) -> None:
        self.input.setText(text)
        self._run()

    def _run(self) -> None:
        self.results.clear()
        if self._search is None:
            self.status.setText("No notebook open")
            return
        text = self.input.text()
        if not text:
            self.status.setText("")
            return
        hits = self._search.query(
            text,
            case=self.case_cb.isChecked(),
            whole_word=self.word_cb.isChecked(),
            regex=self.regex_cb.isChecked(),
        )
        by_page: dict[str, list[Hit]] = {}
        for h in hits:
            by_page.setdefault(h.page_path, []).append(h)
        for page, page_hits in by_page.items():
            top = self._TreeWidgetItem([f"{page}  ({len(page_hits)})"])
            top.setData(0, Qt.ItemDataRole.UserRole, (page, -1))
            for h in page_hits:
                snippet = h.line_text.strip()
                if len(snippet) > 120:
                    snippet = snippet[:117] + "..."
                child = self._TreeWidgetItem([f"{h.line_no}: {snippet}"])
                child.setData(0, Qt.ItemDataRole.UserRole, (page, h.line_no))
                top.addChild(child)
            self.results.addTopLevelItem(top)
            top.setExpanded(True)
        self.status.setText(
            f"{len(hits)} hit" + ("" if len(hits) == 1 else "s")
            + f" in {len(by_page)} page" + ("" if len(by_page) == 1 else "s")
        )

    def _on_item_activated(self, item, _col) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        page, line = data
        self._on_activate_page(page, line)


class TagsDock(QWidget):
    """Tag cloud: flat list of tags sorted by count. Click → search."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout
        self._ListWidgetItem = QListWidgetItem
        self._on_tag_clicked = lambda name: None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)
        self.list = QListWidget(self)
        self.list.itemActivated.connect(self._on_activated)
        self.list.itemClicked.connect(self._on_activated)
        v.addWidget(self.list, 1)

    def set_on_clicked(self, cb) -> None:
        self._on_tag_clicked = cb

    def refresh(self, tag_counts: list[tuple[str, int]]) -> None:
        self.list.clear()
        for tag, count in tag_counts:
            item = self._ListWidgetItem(f"#{tag}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, tag)
            self.list.addItem(item)

    def _on_activated(self, item) -> None:
        tag = item.data(Qt.ItemDataRole.UserRole)
        if tag:
            self._on_tag_clicked(tag)


from .history import NavigationHistory
from .index import Index
from .notebook import Notebook
from .page_model import PageTreeModel


class MainWindow(QMainWindow):
    def __init__(self, notebook_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("qnotebook")
        self.resize(1100, 720)

        self._settings = QSettings("qnotebook", "qnotebook")
        self._recent: list[str] = []
        self._bookmarks: list[str] = []
        self.notebook: Notebook | None = None
        self.index: Index | None = None
        self.model: PageTreeModel | None = None
        self.search: Search | None = None
        self.history = NavigationHistory()
        self._current_page: str | None = None

        self._build_ui()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()

        path = notebook_path or self._settings.value("last_notebook", type=str)
        if path:
            self.open_notebook(path)

    # ---- UI ----

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.tree = QTreeView(self)
        self.tree.setHeaderHidden(True)
        self.tree.clicked.connect(self._on_tree_clicked)
        self.tree.activated.connect(self._on_tree_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        from PyQt6.QtWidgets import QAbstractItemView
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)

        self.editor = MarkdownEditor(self)
        self.editor.linkActivated.connect(self._on_link_activated)
        self.editor.dirtyChanged.connect(self._on_dirty_changed)
        self.editor.imageDropped.connect(self._on_image_dropped)
        self.editor.imagePasted.connect(self._on_image_pasted)
        self.editor.fileDropped.connect(self._on_file_dropped)
        self.editor.autoSaveRequested.connect(self._auto_save)
        self.editor.escapePressed.connect(self._clear_search_highlights)
        self.editor.textChanged.connect(self._update_status)
        # Debounce toc refresh
        from PyQt6.QtCore import QTimer
        self._toc_refresh_timer = QTimer(self)
        self._toc_refresh_timer.setSingleShot(True)
        self._toc_refresh_timer.setInterval(200)
        self._toc_refresh_timer.timeout.connect(self._refresh_toc)
        self.editor.textChanged.connect(self._toc_refresh_timer.start)
        # Load autosave prefs
        autosave_ms = int(self._settings.value("autosave_ms", 30000, type=int))
        autosave_on = self._settings.value("autosave_enabled", True, type=bool)
        self.editor.set_autosave_interval_ms(autosave_ms)
        self.editor.set_autosave_enabled(bool(autosave_on))

        self.find_bar = FindBar(self.editor, self)

        editor_container = QWidget(self)
        ec_layout = QHBoxLayout(editor_container)
        ec_layout.setContentsMargins(0, 0, 0, 0)
        ec_layout.setSpacing(0)
        from PyQt6.QtWidgets import QVBoxLayout
        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.editor, 1)
        v.addWidget(self.find_bar)
        ec_layout.addLayout(v, 1)

        splitter.addWidget(self.tree)
        splitter.addWidget(editor_container)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 860])
        self.setCentralWidget(splitter)

        self.backlinks_list = QListWidget(self)
        self.backlinks_list.itemActivated.connect(self._on_backlink_activated)
        dock = QDockWidget("Backlinks", self)
        dock.setWidget(self.backlinks_list)
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.backlinks_dock = dock

        self.tags_dock_widget = TagsDock(self)
        self.tags_dock_widget.set_on_clicked(self._on_tag_clicked)
        tags_dock = QDockWidget("Tags", self)
        tags_dock.setWidget(self.tags_dock_widget)
        tags_dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, tags_dock)
        tags_dock.hide()
        self.tags_dock = tags_dock

        from .linkmap import LinkMapDock
        self.linkmap_widget = LinkMapDock(self)
        self.linkmap_widget.set_on_navigate(self.load_page)
        linkmap_dock = QDockWidget("Link Map", self)
        linkmap_dock.setWidget(self.linkmap_widget)
        linkmap_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, linkmap_dock)
        linkmap_dock.hide()
        self.linkmap_dock = linkmap_dock

        from .toc import TocDock
        self.toc_widget = TocDock(self)
        self.toc_widget.set_on_activated(self._jump_to_line_from_toc)
        toc_dock = QDockWidget("Table of Contents", self)
        toc_dock.setWidget(self.toc_widget)
        toc_dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, toc_dock)
        toc_dock.hide()
        self.toc_dock = toc_dock

        from .journal import CalendarDock
        self.calendar_widget = CalendarDock(self)
        self.calendar_widget.set_on_date_activated(self._on_calendar_date_activated)
        self.calendar_widget.set_page_exists(
            lambda p: self.notebook is not None and self.notebook.exists(p)
        )
        calendar_dock = QDockWidget("Calendar", self)
        calendar_dock.setWidget(self.calendar_widget)
        calendar_dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, calendar_dock)
        calendar_dock.hide()
        self.calendar_dock = calendar_dock

        self.search_dock_widget = SearchDock(self)
        self.search_dock_widget.set_on_activate(self._on_search_hit_activated)
        search_dock = QDockWidget("Search", self)
        search_dock.setWidget(self.search_dock_widget)
        search_dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, search_dock)
        search_dock.hide()
        self.search_dock = search_dock

        self.setStatusBar(QStatusBar(self))
        self._status_label = QLabel("")
        self.statusBar().addPermanentWidget(self._status_label)

    def _build_actions(self) -> None:
        self.act_open = QAction("&Open Notebook...", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self._choose_notebook)

        self.act_new_page = QAction("&New Page...", self)
        self.act_new_page.setShortcut(QKeySequence("Ctrl+N"))
        self.act_new_page.triggered.connect(self._new_page)

        self.act_save = QAction("&Save", self)
        self.act_save.setShortcut(QKeySequence.StandardKey.Save)
        self.act_save.triggered.connect(self._save_current)

        self.act_back = QAction("Back", self)
        self.act_back.setShortcut(QKeySequence("Alt+Left"))
        self.act_back.triggered.connect(self._go_back)

        self.act_forward = QAction("Forward", self)
        self.act_forward.setShortcut(QKeySequence("Alt+Right"))
        self.act_forward.triggered.connect(self._go_forward)

        self.act_bold = QAction("Bold", self)
        self.act_bold.setShortcut(QKeySequence("Ctrl+B"))
        self.act_bold.triggered.connect(lambda: self.editor.toggle_bold())

        self.act_italic = QAction("Italic", self)
        self.act_italic.setShortcut(QKeySequence("Ctrl+I"))
        self.act_italic.triggered.connect(lambda: self.editor.toggle_italic())

        self.act_strike = QAction("Strike", self)
        self.act_strike.triggered.connect(lambda: self.editor.toggle_strike())

        self.act_code = QAction("Code", self)
        self.act_code.triggered.connect(lambda: self.editor.toggle_code())

        self.act_h1 = QAction("H1", self)
        self.act_h1.triggered.connect(lambda: self.editor.set_heading(1))
        self.act_h2 = QAction("H2", self)
        self.act_h2.triggered.connect(lambda: self.editor.set_heading(2))
        self.act_h3 = QAction("H3", self)
        self.act_h3.triggered.connect(lambda: self.editor.set_heading(3))
        self.act_para = QAction("Paragraph", self)
        self.act_para.triggered.connect(lambda: self.editor.set_heading(0))

        self.act_find = QAction("&Find...", self)
        self.act_find.setShortcut(QKeySequence.StandardKey.Find)
        self.act_find.triggered.connect(self._open_find)

        self.act_find_next = QAction("Find Next", self)
        self.act_find_next.setShortcuts([QKeySequence("Ctrl+G"), QKeySequence("F3")])
        self.act_find_next.triggered.connect(self._find_next)

        self.act_find_prev = QAction("Find Previous", self)
        self.act_find_prev.setShortcut(QKeySequence("Shift+F3"))
        self.act_find_prev.triggered.connect(self._find_prev)

        self.act_search = QAction("&Search Notebook...", self)
        self.act_search.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.act_search.triggered.connect(self._open_search)

        self.act_insert_image = QAction("Insert &Image...", self)
        self.act_insert_image.triggered.connect(self._insert_image_dialog)

        self.act_insert_date = QAction("Insert &Date", self)
        self.act_insert_date.setShortcut(QKeySequence("Ctrl+D"))
        self.act_insert_date.triggered.connect(self._insert_date)

        self.act_insert_time = QAction("Insert &Time", self)
        self.act_insert_time.triggered.connect(self._insert_time)

        self.act_insert_datetime = QAction("Insert Date+Time", self)
        self.act_insert_datetime.triggered.connect(self._insert_datetime)

        self.act_insert_hr = QAction("Insert &Horizontal Rule", self)
        self.act_insert_hr.triggered.connect(self._insert_hr)

        self.act_insert_symbol = QAction("Insert &Symbol...", self)
        self.act_insert_symbol.triggered.connect(self._insert_symbol_dialog)

        self.act_insert_attachment = QAction("Insert &Attachment...", self)
        self.act_insert_attachment.triggered.connect(self._insert_attachment_dialog)

        self.act_bookmark = QAction("&Bookmark This Page", self)
        self.act_bookmark.triggered.connect(self._toggle_bookmark_current)

        self.act_manage_bookmarks = QAction("Manage Bookmarks...", self)
        self.act_manage_bookmarks.triggered.connect(self._manage_bookmarks)

        self.act_export_page_html = QAction("Current page as &HTML...", self)
        self.act_export_page_html.triggered.connect(self._export_page_html)

        self.act_export_notebook_html = QAction("Whole &notebook as HTML...", self)
        self.act_export_notebook_html.triggered.connect(self._export_notebook_html)

        self.act_export_page_pdf = QAction("Current page as &PDF...", self)
        self.act_export_page_pdf.triggered.connect(self._export_page_pdf)

        self.act_toggle_versioning = QAction("Enable &Version History", self, checkable=True)
        self.act_toggle_versioning.triggered.connect(self._toggle_versioning)

        self.act_print = QAction("&Print...", self)
        self.act_print.setShortcut(QKeySequence("Ctrl+P"))
        self.act_print.triggered.connect(self._print_current_page)

        self.act_quit = QAction("&Quit", self)
        self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_quit.triggered.connect(self.close)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu("&File")
        m_file.addAction(self.act_open)
        self.m_recent_notebooks = m_file.addMenu("Recent &Notebooks")
        self.m_recent_notebooks.aboutToShow.connect(self._populate_recent_notebooks_menu)
        m_file.addAction(self.act_new_page)
        self.m_new_from_template = m_file.addMenu("New from &Template")
        self.m_new_from_template.aboutToShow.connect(self._populate_templates_menu)
        m_file.addAction(self.act_save)
        m_file.addSeparator()
        self.m_export = m_file.addMenu("&Export")
        self.m_export.addAction(self.act_export_page_html)
        self.m_export.addAction(self.act_export_notebook_html)
        self.m_export.addAction(self.act_export_page_pdf)
        m_file.addSeparator()
        m_file.addAction(self.act_print)
        m_file.addSeparator()
        m_file.addAction(self.act_toggle_versioning)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)
        m_edit = mb.addMenu("&Edit")
        m_edit.addAction(self.act_find)
        m_edit.addAction(self.act_find_next)
        m_edit.addAction(self.act_find_prev)
        m_edit.addAction(self.act_search)
        m_edit.addSeparator()
        m_insert = mb.addMenu("&Insert")
        m_insert.addAction(self.act_insert_image)
        m_insert.addAction(self.act_insert_date)
        m_insert.addAction(self.act_insert_time)
        m_insert.addAction(self.act_insert_datetime)
        m_insert.addAction(self.act_insert_hr)
        m_insert.addAction(self.act_insert_symbol)
        m_insert.addAction(self.act_insert_attachment)
        self.m_insert = m_insert
        m_nav = mb.addMenu("&Navigate")
        m_nav.addAction(self.act_back)
        m_nav.addAction(self.act_forward)
        self.m_go = mb.addMenu("&Go")
        self.m_go.aboutToShow.connect(self._populate_go_menu)
        m_view = mb.addMenu("&View")
        self.act_toggle_calendar = QAction("&Calendar", self, checkable=True)
        self.act_toggle_calendar.triggered.connect(self._toggle_calendar_dock)
        m_view.addAction(self.act_toggle_calendar)
        self.act_toggle_toc = QAction("&Table of Contents", self, checkable=True)
        self.act_toggle_toc.triggered.connect(self._toggle_toc_dock)
        m_view.addAction(self.act_toggle_toc)
        from .spell import HAS_ENCHANT
        self.act_toggle_linkmap = QAction("&Link Map", self, checkable=True)
        self.act_toggle_linkmap.triggered.connect(self._toggle_linkmap_dock)
        m_view.addAction(self.act_toggle_linkmap)
        self.act_toggle_spell = QAction("&Spell Check", self, checkable=True)
        self.act_toggle_spell.setEnabled(HAS_ENCHANT)
        self.act_toggle_spell.triggered.connect(self._toggle_spell_check)
        m_view.addAction(self.act_toggle_spell)
        # Persist preference
        spell_pref = self._settings.value("spell_enabled", False, type=bool)
        if HAS_ENCHANT and bool(spell_pref):
            self.act_toggle_spell.setChecked(True)
            self._toggle_spell_check(True)
        self.m_view = m_view
        m_fmt = mb.addMenu("F&ormat")
        m_fmt.addAction(self.act_bold)
        m_fmt.addAction(self.act_italic)
        m_fmt.addAction(self.act_strike)
        m_fmt.addAction(self.act_code)
        m_fmt.addSeparator()
        m_fmt.addAction(self.act_h1)
        m_fmt.addAction(self.act_h2)
        m_fmt.addAction(self.act_h3)
        m_fmt.addAction(self.act_para)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main", self)
        tb.addAction(self.act_back)
        tb.addAction(self.act_forward)
        tb.addSeparator()
        tb.addAction(self.act_save)
        tb.addAction(self.act_new_page)
        tb.addSeparator()
        tb.addAction(self.act_bold)
        tb.addAction(self.act_italic)
        tb.addAction(self.act_strike)
        tb.addAction(self.act_code)
        tb.addSeparator()
        tb.addAction(self.act_h1)
        tb.addAction(self.act_h2)
        tb.addAction(self.act_h3)
        tb.addAction(self.act_para)
        tb.addSeparator()
        tb.addAction(self.act_insert_image)
        tb.addAction(self.act_insert_attachment)
        tb.addAction(self.act_find)
        tb.addAction(self.act_search)
        self.addToolBar(tb)
        self.toolbar = tb

    # ---- notebook ops ----

    def _choose_notebook(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open Notebook")
        if path:
            self.open_notebook(path)

    def open_notebook(self, path: str) -> None:
        from .templates import ensure_builtin_templates
        root = Path(path)
        self.notebook = Notebook(root)
        ensure_builtin_templates(self.notebook)
        self.index = Index(self.notebook)
        self.index.rebuild()
        self.search = Search(self.notebook, self.index)
        self.search_dock_widget.set_search(self.search)
        self._load_recent_and_bookmarks()
        self._refresh_tags()
        self.model = PageTreeModel(self.notebook, self)
        self.model.set_index(self.index)
        self.model.pageMoved.connect(self._on_page_moved)
        self.tree.setModel(self.model)
        self._settings.setValue("last_notebook", str(self.notebook.root))
        self._push_recent_notebook(str(self.notebook.root))
        self.act_toggle_versioning.setChecked(
            bool(self._settings.value("versioning_enabled", False, type=bool))
        )
        self._update_title()
        first = next(iter(self.notebook.pages()), None)
        if first:
            self.load_page(first.path)

    def load_page(self, page_path: str) -> None:
        if self.notebook is None:
            return
        if not self.notebook.exists(page_path):
            self.notebook.create_page(page_path)
            if self.index:
                self.index.update_page(page_path, "")
            if self.model:
                self.model.refresh()
                self.tree.setModel(self.model)
        text = self.notebook.get_page(page_path)
        self.editor.load_markdown(
            text, page_path=page_path,
            base_path=self.notebook.file_for(page_path).parent,
        )
        self._current_page = page_path
        self._push_recent(page_path)
        self.history.push(page_path)
        self._refresh_backlinks()
        self._refresh_linkmap()
        self._update_status()
        self._update_title()
        if self.model:
            idx = self.model.index_for_page(page_path)
            if idx.isValid():
                self.tree.setCurrentIndex(idx)

    def _save_current(self) -> None:
        if self.notebook is None or self._current_page is None:
            return
        md = self.editor.markdown()
        self.notebook.save_page(self._current_page, md)
        if self.index:
            self.index.update_page(self._current_page, md)
        self.editor.clear_dirty()
        self._maybe_versioning_commit(self._current_page)
        self._refresh_backlinks()
        self._refresh_tags()
        self._refresh_toc()
        self._update_status()

    def _maybe_versioning_commit(self, page: str) -> None:
        if self.notebook is None:
            return
        if not bool(self._settings.value("versioning_enabled", False, type=bool)):
            return
        from . import versioning
        versioning.commit_page(self.notebook.root, page)

    def _toggle_versioning(self, checked: bool) -> None:
        self._settings.setValue("versioning_enabled", bool(checked))
        if checked and self.notebook is not None:
            from . import versioning
            versioning.init_repo(self.notebook.root)

    def _new_page(self, template_name: str | None = None) -> None:
        if self.notebook is None:
            return
        from .templates import list_templates, load_template, render_template
        from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("New Page")
        form = QFormLayout(dlg)
        name_edit = QLineEdit(dlg)
        name_edit.setPlaceholderText("Foo or Foo:Bar")
        form.addRow("Page path:", name_edit)
        combo = QComboBox(dlg)
        available = list_templates(self.notebook)
        combo.addItems(available)
        if template_name and template_name in available:
            combo.setCurrentText(template_name)
        form.addRow("Template:", combo)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dlg,
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        path = name_edit.text().strip()
        if not path:
            return
        chosen_template = combo.currentText()
        if self.notebook.exists(path):
            QMessageBox.warning(self, "Exists", f"Page {path} already exists")
            return
        if chosen_template == "Blank":
            initial = f"# {path.rsplit(':', 1)[-1]}\n"
        else:
            tpl = load_template(self.notebook, chosen_template)
            initial = render_template(tpl, path)
        self.notebook.create_page(path, initial)
        if self.index:
            self.index.update_page(path)
        if self.model:
            self.model.refresh()
            self.tree.setModel(self.model)
        self.load_page(path)

    def create_page_from_template(self, page_path: str, template_name: str) -> None:
        """Programmatic helper: create a page using a named template.

        Used by New-from-template menu entries, calendar/journal, etc."""
        if self.notebook is None:
            return
        from .templates import load_template, render_template
        if self.notebook.exists(page_path):
            self.load_page(page_path)
            return
        tpl = load_template(self.notebook, template_name)
        initial = render_template(tpl, page_path) if tpl else f"# {page_path.rsplit(':', 1)[-1]}\n"
        self.notebook.create_page(page_path, initial)
        if self.index:
            self.index.update_page(page_path)
        if self.model:
            self.model.refresh()
            self.tree.setModel(self.model)
        self.load_page(page_path)

    # ---- navigation ----

    def _on_tree_clicked(self, index: QModelIndex) -> None:
        if self.model is None:
            return
        ref = self.model.page_for_index(index)
        if ref is None:
            return
        self.load_page(ref.path)

    def _on_link_activated(self, target: str) -> None:
        if self.notebook is None:
            return
        if target.startswith(("http://", "https://", "mailto:")):
            return
        page = target.replace("/", ":").strip(":")
        self.load_page(page)

    def _go_back(self) -> None:
        p = self.history.go_back()
        if p:
            self._load_without_history(p)

    def _go_forward(self) -> None:
        p = self.history.go_forward()
        if p:
            self._load_without_history(p)

    def _load_without_history(self, page: str) -> None:
        if self.notebook is None or not self.notebook.exists(page):
            return
        text = self.notebook.get_page(page)
        self.editor.load_markdown(
            text, page_path=page,
            base_path=self.notebook.file_for(page).parent,
        )
        self._current_page = page
        self._refresh_backlinks()
        self._update_status()

    # ---- rename ----

    def rename_page(self, old: str, new: str) -> list[str]:
        """Rename a page, rewrite inbound wikilinks, reload editor if open."""
        if self.notebook is None or self.index is None:
            return []
        modified = self.index.rename_page_and_rewrite(old, new)
        if self.model:
            self.model.refresh()
            self.tree.setModel(self.model)
        if self._current_page == old:
            # Editor text is stale (it points to the old path).
            self._current_page = new
            text = self.notebook.get_page(new)
            self.editor.load_markdown(
                text, page_path=new,
                base_path=self.notebook.file_for(new).parent,
            )
            self._refresh_backlinks()
            self._update_status()
        elif self._current_page in modified:
            # Source of the currently-open page was rewritten on disk.
            text = self.notebook.get_page(self._current_page)
            self.editor.load_markdown(
                text, page_path=self._current_page,
                base_path=self.notebook.file_for(self._current_page).parent,
            )
            self._refresh_backlinks()
            self._update_status()
        return modified

    def _on_page_moved(self, old: str, new: str) -> None:
        if self._current_page == old:
            self._current_page = new
            if self.notebook and self.notebook.exists(new):
                text = self.notebook.get_page(new)
                self.editor.load_markdown(
                    text, page_path=new,
                    base_path=self.notebook.file_for(new).parent,
                )
        if self.model:
            idx = self.model.index_for_page(new)
            if idx.isValid():
                self.tree.setCurrentIndex(idx)
        self._refresh_backlinks()
        self._update_status()

    # ---- tree context menu & page ops ----

    def _on_tree_context_menu(self, pos) -> None:
        if self.notebook is None or self.model is None:
            return
        idx = self.tree.indexAt(pos)
        ref = self.model.page_for_index(idx) if idx.isValid() else None
        menu = QMenu(self.tree)
        act_new = menu.addAction("New child page...")
        act_rename = menu.addAction("Rename...")
        act_move = menu.addAction("Move to...")
        act_copy = menu.addAction("Copy to...")
        menu.addSeparator()
        act_delete = menu.addAction("Delete...")
        if ref is None:
            act_rename.setEnabled(False)
            act_move.setEnabled(False)
            act_copy.setEnabled(False)
            act_delete.setEnabled(False)
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_new:
            self._new_child_page(ref)
        elif chosen is act_rename and ref:
            self._rename_page_dialog(ref.path)
        elif chosen is act_move and ref:
            self._move_page_dialog(ref.path)
        elif chosen is act_copy and ref:
            self._copy_page_dialog(ref.path)
        elif chosen is act_delete and ref:
            self._delete_page_dialog(ref.path)

    def _new_child_page(self, parent: "PageRef | None") -> None:
        if self.notebook is None:
            return
        prefix = (parent.path + ":") if parent else ""
        name, ok = QInputDialog.getText(
            self, "New Page", f"New page under {prefix or '(root)'}:"
        )
        if not ok or not name.strip():
            return
        leaf = name.strip()
        if ":" in leaf or "/" in leaf:
            QMessageBox.warning(self, "Invalid name", "Name cannot contain : or /")
            return
        full = prefix + leaf
        if self.notebook.exists(full):
            QMessageBox.warning(self, "Exists", f"Page {full} already exists")
            return
        self.notebook.create_page(full, f"# {leaf}\n")
        if self.index:
            self.index.update_page(full)
        if self.model:
            self.model.refresh()
            self.tree.setModel(self.model)
        self.load_page(full)

    def _rename_page_dialog(self, old: str) -> None:
        leaf = old.rsplit(":", 1)[-1]
        parent = old.rsplit(":", 1)[0] if ":" in old else ""
        new_leaf, ok = QInputDialog.getText(
            self, "Rename Page", f"New name for {old}:", text=leaf,
        )
        if not ok or not new_leaf.strip():
            return
        new_leaf = new_leaf.strip()
        if ":" in new_leaf or "/" in new_leaf:
            QMessageBox.warning(self, "Invalid name", "Name cannot contain : or /")
            return
        new = (parent + ":" + new_leaf) if parent else new_leaf
        if new == old:
            return
        if self.notebook and self.notebook.exists(new):
            QMessageBox.warning(self, "Exists", f"Page {new} already exists")
            return
        self.rename_page(old, new)

    def _move_page_dialog(self, old: str) -> None:
        leaf = old.rsplit(":", 1)[-1]
        new_parent, ok = QInputDialog.getText(
            self, "Move Page",
            f"Move {old} under (colon-path, blank for root):",
        )
        if not ok:
            return
        new_parent = new_parent.strip().strip(":")
        new = (new_parent + ":" + leaf) if new_parent else leaf
        if new == old:
            return
        if self.notebook and self.notebook.exists(new):
            QMessageBox.warning(self, "Exists", f"Page {new} already exists")
            return
        self.move_page(old, new)

    def _copy_page_dialog(self, src: str) -> None:
        dst, ok = QInputDialog.getText(
            self, "Copy Page", f"Copy {src} to (colon-path):",
            text=src + "-copy",
        )
        if not ok or not dst.strip():
            return
        dst = dst.strip().strip(":")
        if self.notebook and self.notebook.exists(dst):
            QMessageBox.warning(self, "Exists", f"Page {dst} already exists")
            return
        self.copy_page(src, dst)

    def _delete_page_dialog(self, page: str) -> None:
        if self.index is None or self.notebook is None:
            return
        inbound = len(self.index.backlinks(page))
        msg = f"Delete page {page}?"
        if inbound:
            msg += f"\n\n{inbound} other page(s) link here; those links will break."
        reply = QMessageBox.question(
            self, "Delete Page", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.delete_page(page)

    def move_page(self, old: str, new: str) -> list[str]:
        """Move a page (like rename but to different parent)."""
        return self.rename_page(old, new)

    def copy_page(self, src: str, dst: str) -> None:
        if self.notebook is None or self.index is None:
            return
        self.index.copy_page(src, dst)
        if self.model:
            self.model.refresh()
            self.tree.setModel(self.model)
        self.load_page(dst)

    def delete_page(self, page: str) -> None:
        if self.notebook is None or self.index is None:
            return
        was_current = (self._current_page == page)
        self.index.delete_page_and_cleanup(page)
        if self.model:
            self.model.refresh()
            self.tree.setModel(self.model)
        if was_current:
            self._current_page = None
            self.editor.load_markdown("", page_path=None, base_path=None)
            first = next(iter(self.notebook.pages()), None)
            if first:
                self.load_page(first.path)
            else:
                self._refresh_backlinks()
                self._update_status()

    # ---- recent + bookmarks ----

    def _settings_key(self, suffix: str) -> str:
        nb_key = str(self.notebook.root) if self.notebook else ""
        return f"notebooks/{nb_key}/{suffix}"

    def _load_recent_and_bookmarks(self) -> None:
        if self.notebook is None:
            self._recent = []
            self._bookmarks = []
            return
        r = self._settings.value(self._settings_key("recent"), [], type=list) or []
        b = self._settings.value(self._settings_key("bookmarks"), [], type=list) or []
        self._recent = [str(x) for x in r]
        self._bookmarks = [str(x) for x in b]

    def _save_recent(self) -> None:
        if self.notebook is None:
            return
        self._settings.setValue(self._settings_key("recent"), self._recent)

    def _save_bookmarks(self) -> None:
        if self.notebook is None:
            return
        self._settings.setValue(self._settings_key("bookmarks"), self._bookmarks)

    def _push_recent(self, page: str) -> None:
        if not page:
            return
        if page in self._recent:
            self._recent.remove(page)
        self._recent.insert(0, page)
        del self._recent[20:]
        self._save_recent()

    def _toggle_bookmark_current(self) -> None:
        if self._current_page is None:
            return
        if self._current_page in self._bookmarks:
            self._bookmarks.remove(self._current_page)
        else:
            self._bookmarks.append(self._current_page)
        self._save_bookmarks()

    def _manage_bookmarks(self) -> None:
        from PyQt6.QtWidgets import QDialog, QListWidget, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("Manage Bookmarks")
        v = QVBoxLayout(dlg)
        lst = QListWidget(dlg)
        for b in self._bookmarks:
            lst.addItem(b)
        v.addWidget(lst)
        row = QHBoxLayout()
        btn_remove = QPushButton("Remove", dlg)
        btn_close = QPushButton("Close", dlg)
        row.addWidget(btn_remove)
        row.addStretch(1)
        row.addWidget(btn_close)
        v.addLayout(row)

        def do_remove():
            it = lst.currentItem()
            if it is None:
                return
            name = it.text()
            if name in self._bookmarks:
                self._bookmarks.remove(name)
            lst.takeItem(lst.currentRow())
            self._save_bookmarks()

        btn_remove.clicked.connect(do_remove)
        btn_close.clicked.connect(dlg.accept)
        dlg.exec()

    def _populate_go_menu(self) -> None:
        self.m_go.clear()
        self.m_go.addAction(self.act_bookmark)
        self.m_go.addAction(self.act_manage_bookmarks)
        self.m_go.addSeparator()
        if self._bookmarks:
            self.m_go.addSection("Bookmarks")
            for b in self._bookmarks:
                act = self.m_go.addAction(b)
                act.triggered.connect(
                    lambda _checked=False, p=b: self.load_page(p)
                )
        if self._recent:
            self.m_go.addSection("Recent")
            for r in self._recent[:10]:
                act = self.m_go.addAction(r)
                act.triggered.connect(
                    lambda _checked=False, p=r: self.load_page(p)
                )

    # ---- search ----

    def _open_search(self) -> None:
        self.search_dock.show()
        self.search_dock.raise_()
        self.search_dock_widget.focus_query()

    def _on_tag_clicked(self, tag: str) -> None:
        self.search_dock.show()
        self.search_dock.raise_()
        self.search_dock_widget.set_query(f"#{tag}")

    def _refresh_tags(self) -> None:
        if self.index is None:
            return
        self.tags_dock_widget.refresh(self.index.tags())
        self._refresh_completion_sources()

    def _refresh_completion_sources(self) -> None:
        if self.index is None:
            return
        pages = self.index.all_pages()
        tags = [t for t, _ in self.index.tags()]
        self.editor.set_completion_sources(pages, tags)

    def _on_search_hit_activated(self, page: str, line: int) -> None:
        if self.notebook is None or not self.notebook.exists(page):
            return
        self.load_page(page)
        if line > 0:
            self._jump_to_line(line)
        needle = self.search_dock_widget.input.text().strip()
        if needle:
            self._highlight_all_occurrences(needle)

    def _highlight_all_occurrences(self, needle: str) -> None:
        from PyQt6.QtGui import QColor, QTextCharFormat
        from PyQt6.QtWidgets import QTextEdit
        doc = self.editor.document()
        selections: list[QTextEdit.ExtraSelection] = []
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#fff48a"))
        cursor = QTextCursor(doc)
        while True:
            cursor = doc.find(needle, cursor)
            if cursor.isNull():
                break
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            selections.append(sel)
        self.editor.setExtraSelections(selections)

    def _clear_search_highlights(self) -> None:
        self.editor.setExtraSelections([])

    def _jump_to_line(self, line_no: int) -> None:
        doc = self.editor.document()
        block = doc.findBlockByNumber(max(0, line_no - 1))
        if not block.isValid():
            return
        cur = self.editor.textCursor()
        cur.setPosition(block.position())
        self.editor.setTextCursor(cur)
        self.editor.ensureCursorVisible()

    # ---- find ----

    def _open_find(self) -> None:
        self.find_bar.open_bar()

    def _find_next(self) -> None:
        if not self.find_bar.isVisible():
            self.find_bar.open_bar()
        else:
            self.find_bar.find_next()

    def _find_prev(self) -> None:
        if not self.find_bar.isVisible():
            self.find_bar.open_bar()
        else:
            self.find_bar.find_prev()

    # ---- insert helpers ----

    def _insert_date(self) -> None:
        from datetime import date
        self.editor.insert_text_at_cursor(date.today().isoformat())

    def _insert_time(self) -> None:
        from datetime import datetime
        self.editor.insert_text_at_cursor(datetime.now().strftime("%H:%M"))

    def _insert_datetime(self) -> None:
        from datetime import datetime
        self.editor.insert_text_at_cursor(datetime.now().strftime("%Y-%m-%d %H:%M"))

    def _insert_hr(self) -> None:
        self.editor.insert_horizontal_rule()

    def _insert_symbol_dialog(self) -> None:
        from PyQt6.QtWidgets import QDialog, QGridLayout, QPushButton, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("Insert Symbol")
        v = QVBoxLayout(dlg)
        grid = QGridLayout()
        symbols = [
            "→", "←", "↑", "↓", "↔", "⇒", "⇐", "⇔",
            "€", "£", "¥", "¢", "$", "₹", "₽", "¤",
            "×", "÷", "±", "≈", "≠", "≤", "≥", "∞",
            "°", "•", "…", "§", "¶", "†", "‡", "©",
        ]
        for i, sym in enumerate(symbols):
            btn = QPushButton(sym, dlg)
            btn.clicked.connect(
                lambda _checked=False, s=sym: (
                    self.editor.insert_text_at_cursor(s),
                    dlg.accept(),
                )
            )
            grid.addWidget(btn, i // 8, i % 8)
        v.addLayout(grid)
        dlg.exec()

    # ---- image insertion ----

    def _insert_image_dialog(self) -> None:
        if self.notebook is None or self._current_page is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Insert Image",
            "",
            "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)",
        )
        if not path:
            return
        self._insert_image_from_path(Path(path))

    def _on_image_dropped(self, src_path: str) -> None:
        self._insert_image_from_path(Path(src_path))

    def _on_image_pasted(self, image) -> None:
        from PyQt6.QtGui import QImage
        from datetime import datetime
        if self.notebook is None or self._current_page is None:
            return
        if not isinstance(image, QImage) or image.isNull():
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        rel = self._copy_image_bytes(image, f"pasted-{stamp}.png")
        if rel:
            self._insert_image_markdown(rel)

    def _insert_image_from_path(self, src: Path) -> None:
        if self.notebook is None or self._current_page is None:
            return
        if not src.is_file():
            return
        rel = self._copy_image_file(src)
        if rel:
            self._insert_image_markdown(rel)

    def _resources_dir_for_current(self) -> Path:
        """Directory that holds images for the currently-open page."""
        assert self.notebook is not None and self._current_page is not None
        page_file = self.notebook.file_for(self._current_page)
        return page_file.parent / "_resources"

    def _copy_image_file(self, src: Path) -> str | None:
        resdir = self._resources_dir_for_current()
        resdir.mkdir(parents=True, exist_ok=True)
        dst = _unique_path(resdir / src.name)
        dst.write_bytes(src.read_bytes())
        return f"_resources/{dst.name}"

    def _copy_image_bytes(self, image, default_name: str) -> str | None:
        resdir = self._resources_dir_for_current()
        resdir.mkdir(parents=True, exist_ok=True)
        dst = _unique_path(resdir / default_name)
        image.save(str(dst), "PNG")
        return f"_resources/{dst.name}"

    def _insert_attachment_dialog(self) -> None:
        if self.notebook is None or self._current_page is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Insert Attachment", "", "All Files (*)")
        if not path:
            return
        self._insert_attachment_from_path(Path(path))

    def _on_file_dropped(self, src_path: str) -> None:
        self._insert_attachment_from_path(Path(src_path))

    def _insert_attachment_from_path(self, src: Path) -> None:
        if self.notebook is None or self._current_page is None:
            return
        if not src.is_file():
            return
        resdir = self._resources_dir_for_current()
        resdir.mkdir(parents=True, exist_ok=True)
        dst = _unique_path(resdir / src.name)
        dst.write_bytes(src.read_bytes())
        rel = f"_resources/{dst.name}"
        link_md = f"[{dst.name}]({rel})"
        self.editor.insert_text_at_cursor(link_md)

    def _insert_image_markdown(self, rel_path: str) -> None:
        from pathlib import PurePosixPath
        alt = PurePosixPath(rel_path).stem
        assert self.notebook is not None and self._current_page is not None
        page_dir = self.notebook.file_for(self._current_page).parent
        abs_path = (page_dir / rel_path).resolve()
        self.editor.insert_image(rel_path, alt, str(abs_path))

    def _populate_templates_menu(self) -> None:
        self.m_new_from_template.clear()
        if self.notebook is None:
            act = self.m_new_from_template.addAction("(no notebook open)")
            act.setEnabled(False)
            return
        from .templates import list_templates
        for name in list_templates(self.notebook):
            act = self.m_new_from_template.addAction(name)
            act.triggered.connect(
                lambda _checked=False, n=name: self._new_page(template_name=n)
            )

    # ---- link map ----

    def _toggle_linkmap_dock(self, checked: bool) -> None:
        if checked:
            self.linkmap_dock.show()
            self.linkmap_dock.raise_()
            self._refresh_linkmap()
        else:
            self.linkmap_dock.hide()

    def _refresh_linkmap(self) -> None:
        if self.index is None or self._current_page is None:
            self.linkmap_widget.build(None, [], [])
            return
        fwd = self.index.forward_links(self._current_page)
        back = self.index.backlinks(self._current_page)
        self.linkmap_widget.build(self._current_page, fwd, back)

    # ---- spell check ----

    def _toggle_spell_check(self, checked: bool) -> None:
        from .spell import HAS_ENCHANT, SpellHighlighter
        if not HAS_ENCHANT:
            self.act_toggle_spell.setChecked(False)
            return
        if checked:
            if not hasattr(self, "_spell_highlighter") or self._spell_highlighter is None:
                self._spell_highlighter = SpellHighlighter(self.editor.document())
        else:
            if getattr(self, "_spell_highlighter", None) is not None:
                self._spell_highlighter.setDocument(None)
                self._spell_highlighter = None
        self._settings.setValue("spell_enabled", bool(checked))

    # ---- toc ----

    def _toggle_toc_dock(self, checked: bool) -> None:
        if checked:
            self.toc_dock.show()
            self.toc_dock.raise_()
            self._refresh_toc()
        else:
            self.toc_dock.hide()

    def _refresh_toc(self) -> None:
        self.toc_widget.refresh(self.editor.markdown())

    def _jump_to_line_from_toc(self, line: int) -> None:
        self._jump_to_line(line + 1)
        self.editor.setFocus()

    # ---- calendar / journal ----

    def _toggle_calendar_dock(self, checked: bool) -> None:
        if checked:
            self.calendar_dock.show()
            self.calendar_dock.raise_()
            self.calendar_widget.refresh_highlights()
        else:
            self.calendar_dock.hide()

    def _on_calendar_date_activated(self, d) -> None:
        if self.notebook is None:
            return
        from .journal import journal_page_for_date
        page = journal_page_for_date(d)
        if not self.notebook.exists(page):
            self.create_page_from_template(page, "Daily Journal")
        else:
            self.load_page(page)
        self.calendar_widget.refresh_highlights()

    # ---- recent notebooks ----

    def _recent_notebooks(self) -> list[str]:
        raw = self._settings.value("recent_notebooks", [], type=list) or []
        return [str(x) for x in raw]

    def _push_recent_notebook(self, path: str) -> None:
        existing = self._recent_notebooks()
        if path in existing:
            existing.remove(path)
        existing.insert(0, path)
        del existing[5:]
        self._settings.setValue("recent_notebooks", existing)

    def _populate_recent_notebooks_menu(self) -> None:
        self.m_recent_notebooks.clear()
        entries = self._recent_notebooks()
        if not entries:
            act = self.m_recent_notebooks.addAction("(none)")
            act.setEnabled(False)
            return
        for p in entries:
            act = self.m_recent_notebooks.addAction(p)
            act.triggered.connect(
                lambda _checked=False, path=p: self.open_notebook(path)
            )

    # ---- export ----

    def _export_page_html(self) -> None:
        if self.notebook is None or self._current_page is None:
            return
        from .export import export_page_html
        default_name = self._current_page.replace(":", "_") + ".html"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Page as HTML", default_name, "HTML Files (*.html)"
        )
        if not path:
            return
        export_page_html(self.notebook, self._current_page, Path(path))

    def _export_notebook_html(self) -> None:
        if self.notebook is None:
            return
        from .export import export_notebook_html
        out = QFileDialog.getExistingDirectory(self, "Export Notebook to Directory")
        if not out:
            return
        export_notebook_html(self.notebook, Path(out))

    def _export_page_pdf(self) -> None:
        if self.notebook is None or self._current_page is None:
            return
        from .export import export_page_pdf
        default_name = self._current_page.replace(":", "_") + ".pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Page as PDF", default_name, "PDF Files (*.pdf)"
        )
        if not path:
            return
        export_page_pdf(self.notebook, self._current_page, Path(path))

    def _print_current_page(self) -> None:
        from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
        if self.notebook is None or self._current_page is None:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self.editor.document().print(printer)

    # ---- misc ----

    def _refresh_backlinks(self) -> None:
        self.backlinks_list.clear()
        if self.index is None or self._current_page is None:
            return
        for src in self.index.backlinks(self._current_page):
            self.backlinks_list.addItem(src)

    def _on_backlink_activated(self, item) -> None:
        self.load_page(item.text())

    def _on_dirty_changed(self, dirty: bool) -> None:
        self._update_status()
        self._update_title()

    def _auto_save(self) -> None:
        if self._current_page and self.editor.is_dirty():
            self._save_current()

    def _update_title(self) -> None:
        name = self.notebook.root.name if self.notebook else ""
        prefix = "*" if self.editor.is_dirty() else ""
        parts: list[str] = []
        if self._current_page:
            parts.append(self._current_page)
        if name:
            parts.append(name)
        parts.append("qnotebook")
        self.setWindowTitle(prefix + " — ".join(parts))

    def _update_status(self) -> None:
        parts = []
        text = self.editor.toPlainText() if hasattr(self.editor, "toPlainText") else ""
        words = len(text.split())
        chars = len(text)
        mins = max(1, round(words / 200)) if words else 0
        if self.notebook is not None:
            parts.append(self.notebook.root.name)
        if self.index is not None:
            total = len(self.index.all_pages())
            parts.append(f"{total} page" + ("" if total == 1 else "s"))
        if words:
            parts.append(f"{words} words")
        if chars:
            parts.append(f"{chars} chars")
        if mins:
            parts.append(f"~{mins} min")
        if self._current_page:
            parts.append(self._current_page)
        if self.editor.is_dirty():
            parts.append("[modified]")
        self._status_label.setText("  |  ".join(parts))

    def _maybe_save_dirty(self) -> bool:
        """Hook for tests to bypass unsaved-changes prompt."""
        return True

    def closeEvent(self, event) -> None:
        if self.editor.is_dirty():
            if not self._maybe_save_dirty():
                event.ignore()
                return
        if self.index:
            self.index.close()
        super().closeEvent(event)
