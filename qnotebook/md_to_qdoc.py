"""Render markdown source into a QTextDocument with semantic formats.

Each block stores a `UserProperty` with its block kind so the serializer
can reconstruct markdown without guessing. Inline character formats use
standard Qt attributes (bold, italic, etc.) plus anchor href for links.
Wikilinks use href `qnotebook:<Target>`; regular links use their URL as-is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFrameFormat,
    QTextImageFormat,
    QTextListFormat,
    QTextTableFormat,
)
from markdown_it import MarkdownIt

try:
    from mdit_py_plugins.tasklists import tasklists_plugin  # type: ignore
    HAS_MDIT_TASKLISTS = True
except Exception:
    tasklists_plugin = None  # type: ignore
    HAS_MDIT_TASKLISTS = False


# Qt User properties on blocks — all values are strings/ints for portability.
BLOCK_KIND = QTextCharFormat.Property.UserProperty + 1  # "p" | "h" | "code" | "bq" | "hr" | "li" | "task" | "th" | "td"
BLOCK_LEVEL = QTextCharFormat.Property.UserProperty + 2  # heading level, list depth
BLOCK_LIST_KIND = QTextCharFormat.Property.UserProperty + 3  # "ul" | "ol"
BLOCK_TASK_STATE = QTextCharFormat.Property.UserProperty + 4  # 0 | 1
BLOCK_CODE_LANG = QTextCharFormat.Property.UserProperty + 5
BLOCK_ORDERED_START = QTextCharFormat.Property.UserProperty + 6

# Char properties
CHAR_WIKILINK = QTextCharFormat.Property.UserProperty + 10  # str target
CHAR_CODE = QTextCharFormat.Property.UserProperty + 11  # bool
CHAR_IMAGE_ALT = QTextCharFormat.Property.UserProperty + 12  # str alt text for images
CHAR_TAG = QTextCharFormat.Property.UserProperty + 13  # str tag name (e.g. "todo" for `#todo`)
BLOCK_TOC_MARKER = QTextCharFormat.Property.UserProperty + 14  # bool: this paragraph is a [[!TOC]] marker
BLOCK_TRANSCLUSION = QTextCharFormat.Property.UserProperty + 22  # str: transclusion source target e.g. "Foo" or "Foo#Heading"
BLOCK_TRANSCLUDED_CHILD = QTextCharFormat.Property.UserProperty + 23  # bool: rendered included content, skipped on serialize
BLOCK_FOOTNOTE_DEF = QTextCharFormat.Property.UserProperty + 24  # str: footnote label for a `[^label]: ...` block
CHAR_FOOTNOTE_REF = QTextCharFormat.Property.UserProperty + 25  # str: footnote label for a `[^label]` reference

IMAGE_MAX_WIDTH = 600


def register_image_resource(doc: QTextDocument, rel_path: str, abs_path: str | None) -> None:
    """Register an image pixel source under `rel_path` so the document
    renders the image inline. Tolerates missing files (renders as a placeholder)."""
    if not abs_path:
        return
    img = QImage(abs_path)
    if img.isNull():
        return
    doc.addResource(
        QTextDocument.ResourceType.ImageResource.value,
        QUrl(rel_path),
        img,
    )


WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
TAG_INLINE_RE = re.compile(r"(?:(?<=^)|(?<=[\s(\[]))(#[A-Za-z][\w-]*)")


def _heading_format(level: int) -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    fmt.setHeadingLevel(level)
    fmt.setTopMargin(12)
    fmt.setBottomMargin(6)
    fmt.setProperty(BLOCK_KIND, "h")
    fmt.setProperty(BLOCK_LEVEL, level)
    return fmt


def _heading_char_format(level: int) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setFontWeight(QFont.Weight.Bold)
    sizes = {1: 20, 2: 17, 3: 15, 4: 13, 5: 12, 6: 11}
    f.setFontPointSize(sizes.get(level, 11))
    return f


def _paragraph_format() -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    fmt.setProperty(BLOCK_KIND, "p")
    fmt.setTopMargin(4)
    fmt.setBottomMargin(4)
    return fmt


def _code_format() -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    fmt.setProperty(BLOCK_KIND, "code")
    fmt.setBackground(QColor("#f4f4f4"))
    fmt.setLeftMargin(12)
    fmt.setRightMargin(12)
    fmt.setTopMargin(2)
    fmt.setBottomMargin(2)
    return fmt


def _code_char_format() -> QTextCharFormat:
    f = QTextCharFormat()
    f.setFontFamilies(["monospace"])
    return f


def _quote_format() -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    fmt.setProperty(BLOCK_KIND, "bq")
    fmt.setLeftMargin(16)
    fmt.setTopMargin(2)
    fmt.setBottomMargin(2)
    return fmt


def _hr_format() -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    fmt.setProperty(BLOCK_KIND, "hr")
    fmt.setTopMargin(8)
    fmt.setBottomMargin(8)
    return fmt


@dataclass
class _InlineStyle:
    bold: bool = False
    italic: bool = False
    strike: bool = False
    code: bool = False
    link: str | None = None  # href (regular URL)
    wikilink: str | None = None  # qnotebook target
    tag: str | None = None  # when set, this run is a `#tag` token
    image_src: str | None = None  # if set, this run is an image insertion
    image_alt: str = ""
    equation: str | None = None  # if set, this run is a LaTeX equation
    equation_display: bool = False  # True for `$$..$$`

    def char_format(self) -> QTextCharFormat:
        f = QTextCharFormat()
        if self.bold:
            f.setFontWeight(QFont.Weight.Bold)
        if self.italic:
            f.setFontItalic(True)
        if self.strike:
            f.setFontStrikeOut(True)
        if self.code:
            f.setFontFamilies(["monospace"])
            f.setBackground(QColor("#f4f4f4"))
            f.setProperty(CHAR_CODE, True)
        if self.wikilink is not None:
            f.setAnchor(True)
            f.setAnchorHref(f"qnotebook:{self.wikilink}")
            f.setForeground(QColor("#1a5fb4"))
            f.setFontUnderline(True)
            f.setProperty(CHAR_WIKILINK, self.wikilink)
        elif self.link is not None:
            f.setAnchor(True)
            f.setAnchorHref(self.link)
            f.setForeground(QColor("#1a5fb4"))
            f.setFontUnderline(True)
        if self.tag is not None:
            f.setForeground(QColor("#1c71d8"))
            f.setFontWeight(QFont.Weight.DemiBold)
            f.setProperty(CHAR_TAG, self.tag)
        if self.equation is not None:
            from .equations import EQ_LATEX, EQ_DISPLAY
            f.setFontFamilies(["monospace"])
            f.setBackground(QColor("#fff8dc"))
            f.setProperty(EQ_LATEX, self.equation)
            f.setProperty(EQ_DISPLAY, bool(self.equation_display))
        return f


class _Renderer:
    def __init__(self, doc: QTextDocument, base_path: Path | None = None) -> None:
        self.doc = doc
        self.cursor = QTextCursor(doc)
        self._first_block = True
        self.base_path = base_path

    def new_block(self, block_fmt: QTextBlockFormat, char_fmt: QTextCharFormat | None = None) -> None:
        if self._first_block:
            self.cursor.setBlockFormat(block_fmt)
            if char_fmt is not None:
                self.cursor.setBlockCharFormat(char_fmt)
            self._first_block = False
        else:
            self.cursor.insertBlock(block_fmt, char_fmt or QTextCharFormat())

    def insert_text(self, text: str, fmt: QTextCharFormat | None = None) -> None:
        if fmt is None:
            fmt = QTextCharFormat()
        self.cursor.insertText(text, fmt)

    def insert_run(self, text: str, style: "_InlineStyle", base_fmt: QTextCharFormat | None = None) -> None:
        """Insert a run; image runs become image fragments, others become text."""
        if style.image_src is not None:
            self._insert_image_run(style.image_src, style.image_alt)
            return
        f = style.char_format()
        if base_fmt is not None:
            merged = QTextCharFormat(base_fmt)
            merged.merge(f)
            f = merged
        self.cursor.insertText(text, f)

    def _insert_image_run(self, src: str, alt: str) -> None:
        img_fmt = QTextImageFormat()
        img_fmt.setName(src)
        img_fmt.setProperty(CHAR_IMAGE_ALT, alt)
        # Resolve absolute path and register resource if the file exists.
        abs_path: str | None = None
        if self.base_path is not None:
            try:
                abs_path = str((self.base_path / src).resolve())
            except (OSError, ValueError):
                abs_path = None
        if abs_path:
            img = QImage(abs_path)
            if not img.isNull():
                self.doc.addResource(
                    QTextDocument.ResourceType.ImageResource.value,
                    QUrl(src),
                    img,
                )
                w = img.width()
                h = img.height()
                if w > IMAGE_MAX_WIDTH:
                    ratio = IMAGE_MAX_WIDTH / float(w)
                    img_fmt.setWidth(IMAGE_MAX_WIDTH)
                    img_fmt.setHeight(h * ratio)
                else:
                    img_fmt.setWidth(w)
                    img_fmt.setHeight(h)
        self.cursor.insertImage(img_fmt)


def _parse_inline_children(children: list, style: _InlineStyle) -> list[tuple[str, _InlineStyle]]:
    """Flatten inline tokens into (text, style) runs, handling wikilinks."""
    out: list[tuple[str, _InlineStyle]] = []
    stack: list[_InlineStyle] = [style]

    def top() -> _InlineStyle:
        return stack[-1]

    def push(modify) -> None:
        new = _InlineStyle(**top().__dict__)
        modify(new)
        stack.append(new)

    i = 0
    while i < len(children):
        t = children[i]
        typ = t.type
        if typ == "text":
            _emit_with_wikilinks(out, t.content, top())
        elif typ == "strong_open":
            push(lambda s: setattr(s, "bold", True))
        elif typ == "strong_close":
            stack.pop()
        elif typ == "em_open":
            push(lambda s: setattr(s, "italic", True))
        elif typ == "em_close":
            stack.pop()
        elif typ == "s_open":
            push(lambda s: setattr(s, "strike", True))
        elif typ == "s_close":
            stack.pop()
        elif typ == "code_inline":
            s = _InlineStyle(**top().__dict__)
            s.code = True
            out.append((t.content, s))
        elif typ == "image":
            src = t.attrGet("src") or ""
            # alt is the concatenated text of the image's inline children
            alt_parts: list[str] = []
            for c in (t.children or []):
                if c.type == "text":
                    alt_parts.append(c.content)
            alt_text = "".join(alt_parts) or (t.content or "")
            s = _InlineStyle(**top().__dict__)
            s.image_src = src
            s.image_alt = alt_text
            out.append(("", s))
        elif typ == "link_open":
            href = t.attrGet("href") or ""
            push(lambda s, h=href: setattr(s, "link", h))
        elif typ == "link_close":
            stack.pop()
        elif typ == "softbreak":
            out.append(("\n", top()))
        elif typ == "hardbreak":
            out.append(("\n", top()))
        elif typ == "html_inline":
            out.append((t.content, top()))
        i += 1
    return out


def _emit_with_wikilinks(out: list[tuple[str, _InlineStyle]], text: str, style: _InlineStyle) -> None:
    """Emit a text run, splitting out [[wikilinks]] and `#tags`."""
    pos = 0
    for m in WIKILINK_RE.finditer(text):
        if m.start() > pos:
            _emit_with_tags(out, text[pos : m.start()], style)
        target = m.group(1).strip()
        alias = m.group(2)
        display = alias.strip() if alias else target
        s = _InlineStyle(**style.__dict__)
        s.wikilink = target
        out.append((display, s))
        pos = m.end()
    if pos < len(text):
        _emit_with_tags(out, text[pos:], style)


def _emit_with_tags(out: list[tuple[str, _InlineStyle]], text: str, style: _InlineStyle) -> None:
    """Emit text, splitting `#tag` tokens into styled runs. Skips runs
    already inside code/link context (those shouldn't be tagged)."""
    if style.code or style.link is not None or style.wikilink is not None:
        out.append((text, style))
        return
    pos = 0
    for m in TAG_INLINE_RE.finditer(text):
        if m.start() > pos:
            _emit_with_equations(out, text[pos : m.start()], style)
        tag_token = m.group(1)  # includes the leading `#`
        s = _InlineStyle(**style.__dict__)
        s.tag = tag_token[1:]
        out.append((tag_token, s))
        pos = m.end()
    if pos < len(text):
        _emit_with_equations(out, text[pos:], style)


def _emit_with_equations(out: list[tuple[str, _InlineStyle]], text: str, style: _InlineStyle) -> None:
    """Emit text, splitting LaTeX `$..$` and `$$..$$` runs."""
    from .equations import find_equations_in_text
    eqs = find_equations_in_text(text)
    if not eqs:
        out.append((text, style))
        return
    pos = 0
    for s, e, latex, display in eqs:
        if s > pos:
            out.append((text[pos:s], style))
        st = _InlineStyle(**style.__dict__)
        st.equation = latex
        st.equation_display = display
        out.append((text[s:e], st))
        pos = e
    if pos < len(text):
        out.append((text[pos:], style))


_TOC_SENTINEL = "QNOTEBOOKTOCMARKERLINE"
_TRANSCLUDE_SENTINEL_PREFIX = "QNOTEBOOKTRANSCLUDELINE"  # + N


def _preprocess_transclusions(md_text: str) -> tuple[str, list[str]]:
    """Replace `{{Target}}` lines with sentinel markers. Return (text, targets)."""
    out_lines: list[str] = []
    targets: list[str] = []
    in_fence = False
    import re as _re
    pat = _re.compile(r"^\{\{([^{}\n]+)\}\}$")
    for line in (md_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        m = pat.match(stripped) if not in_fence else None
        if m:
            idx = len(targets)
            targets.append(m.group(1).strip())
            out_lines.append(f"{_TRANSCLUDE_SENTINEL_PREFIX}{idx}")
        else:
            out_lines.append(line)
    out = "\n".join(out_lines)
    if md_text.endswith("\n"):
        out += "\n"
    return out, targets


def _preprocess_toc_markers(md_text: str) -> str:
    """Replace standalone `[[!TOC]]` lines with a plain-text sentinel that
    survives markdown-it (so we can post-tag the block)."""
    out_lines: list[str] = []
    in_fence = False
    for line in (md_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if not in_fence and stripped == "[[!TOC]]":
            out_lines.append(_TOC_SENTINEL)
        else:
            out_lines.append(line)
    out = "\n".join(out_lines)
    if md_text.endswith("\n"):
        out += "\n"
    return out


def markdown_to_qdoc(
    md_text: str,
    doc: QTextDocument,
    base_path: Path | None = None,
    transclusion_resolver=None,
) -> None:
    """Parse markdown and populate `doc` with styled blocks.

    `base_path` is the directory the markdown source lives in. Used to
    resolve relative image paths (e.g. `_resources/foo.png`). If omitted,
    image pixels aren't loaded but their src/alt are preserved."""
    doc.clear()
    doc.setDefaultStyleSheet("")
    # Remove default root-frame margins for cleaner layout.
    root_fmt = QTextFrameFormat()
    root_fmt.setMargin(0)
    doc.rootFrame().setFrameFormat(root_fmt)

    md = MarkdownIt("commonmark", {"html": False, "breaks": False, "linkify": False}).enable(
        ["table", "strikethrough"]
    )
    # If the official mdit-py-plugins tasklist plugin is installed, use it
    # to mark list-item tokens as tasks. Our fallback regex detection below
    # still runs, but the plugin ensures first-class detection even with
    # edge-case markers.
    if HAS_MDIT_TASKLISTS and tasklists_plugin is not None:
        try:
            md = md.use(tasklists_plugin, enabled=True)
        except Exception:
            pass
    # Split frontmatter so it doesn't render in the editor, but preserve it
    # on the doc so the serializer can emit it back verbatim (key-order + all).
    try:
        from . import frontmatter as _fm_mod
        _fm_data, md_text = _fm_mod.split(md_text or "")
    except Exception:
        _fm_data = {}
    try:
        doc._zimqt_frontmatter = _fm_data  # type: ignore[attr-defined]
    except Exception:
        pass
    md_text = _preprocess_toc_markers(md_text or "")
    md_text, _transclusion_targets = _preprocess_transclusions(md_text)
    tokens = md.parse(md_text or "")
    r = _Renderer(doc, base_path=base_path)

    # Walk tokens with a small state machine
    list_stack: list[tuple[str, int]] = []  # ("ul"|"ol", start_value_for_ol)
    qlist_stack: list = []  # parallel stack of active QTextList (or None) for appending siblings
    in_table = False
    table_rows: list[list[str]] = []  # each row is list of cell markdown strings
    current_row: list[str] = []
    current_cell_tokens: list = []
    in_cell = False
    in_header = False
    table_align: list[str] = []  # unused for now

    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        typ = t.type
        if typ == "heading_open":
            level = int(t.tag[1])
            r.new_block(_heading_format(level), _heading_char_format(level))
            inline = tokens[i + 1]
            runs = _parse_inline_children(inline.children or [], _InlineStyle())
            base = _heading_char_format(level)
            for text, style in runs:
                r.insert_run(text, style, base_fmt=base)
            i += 3  # heading_open, inline, heading_close
            continue
        if typ == "paragraph_open":
            # Detect task list item: inline starts with "[ ] " or "[x] "
            inline = tokens[i + 1]
            is_task = False
            task_state = 0
            # Check parent: a list_item's first paragraph
            if list_stack and list_stack[-1][0] == "ul":
                children = inline.children or []
                if children and children[0].type == "text":
                    m = re.match(r"^\[([ xX])\]\s+", children[0].content)
                    if m:
                        is_task = True
                        task_state = 1 if m.group(1).lower() == "x" else 0
                        children[0].content = children[0].content[m.end():]
            # Create block
            if list_stack:
                fmt = _list_item_block_format(len(list_stack), is_task, task_state)
            else:
                fmt = _paragraph_format()
            r.new_block(fmt)
            if list_stack:
                current_list = qlist_stack[-1] if qlist_stack else None
                new_list = _apply_list_format(r.cursor, list_stack, current_list)
                qlist_stack[-1] = new_list
            runs = _parse_inline_children(inline.children or [], _InlineStyle())
            for text, style in runs:
                r.insert_run(text, style)
            i += 3
            continue
        if typ == "bullet_list_open":
            list_stack.append(("ul", 1))
            qlist_stack.append(None)
            i += 1
            continue
        if typ == "ordered_list_open":
            start = int(t.attrGet("start") or 1)
            list_stack.append(("ol", start))
            qlist_stack.append(None)
            i += 1
            continue
        if typ in ("bullet_list_close", "ordered_list_close"):
            list_stack.pop()
            qlist_stack.pop()
            i += 1
            continue
        if typ in ("list_item_open", "list_item_close"):
            i += 1
            continue
        if typ == "fence":
            lang = t.info.strip()
            content = t.content
            if content.endswith("\n"):
                content = content[:-1]
            # Try Pygments token-based highlighting per line if a lang is set.
            highlighted = _pygments_highlight(content, lang) if lang else None
            if highlighted is not None:
                for idx, line_tokens in enumerate(highlighted):
                    fmt = _code_format()
                    fmt.setProperty(BLOCK_CODE_LANG, lang)
                    if idx == 0 and len(highlighted) > 1:
                        fmt.setProperty(BLOCK_LEVEL, 1)
                    r.new_block(fmt, _code_char_format())
                    for tok_text, tok_color in line_tokens:
                        f = _code_char_format()
                        if tok_color:
                            f.setForeground(QColor(tok_color))
                        r.insert_text(tok_text, f)
            else:
                lines = content.split("\n") if content else [""]
                for idx, line in enumerate(lines):
                    fmt = _code_format()
                    fmt.setProperty(BLOCK_CODE_LANG, lang)
                    if idx == 0 and len(lines) > 1:
                        fmt.setProperty(BLOCK_LEVEL, 1)
                    r.new_block(fmt, _code_char_format())
                    r.insert_text(line, _code_char_format())
            i += 1
            continue
        if typ == "code_block":
            # Indented code (CommonMark). Treat like fence without lang.
            content = t.content.rstrip("\n")
            lines = content.split("\n") if content else [""]
            for line in lines:
                fmt = _code_format()
                fmt.setProperty(BLOCK_CODE_LANG, "")
                r.new_block(fmt, _code_char_format())
                r.insert_text(line, _code_char_format())
            i += 1
            continue
        if typ == "blockquote_open":
            # Emit contained paragraphs as blockquote blocks.
            depth = 1
            j = i + 1
            inner = []
            while j < n and depth > 0:
                if tokens[j].type == "blockquote_open":
                    depth += 1
                elif tokens[j].type == "blockquote_close":
                    depth -= 1
                    if depth == 0:
                        break
                inner.append(tokens[j])
                j += 1
            # Render inner: just paragraphs for now
            k = 0
            while k < len(inner):
                tt = inner[k]
                if tt.type == "paragraph_open":
                    inline_tok = inner[k + 1]
                    r.new_block(_quote_format())
                    runs = _parse_inline_children(inline_tok.children or [], _InlineStyle())
                    for text, style in runs:
                        r.insert_run(text, style)
                    k += 3
                    continue
                k += 1
            i = j + 1
            continue
        if typ == "hr":
            fmt = _hr_format()
            r.new_block(fmt)
            r.insert_text("—" * 20)
            i += 1
            continue
        if typ == "table_open":
            # Collect the whole table
            rows: list[list[list]] = []  # list of rows; each row = list of cells; each cell = list of inline child tokens
            header_row: list[list] = []
            align: list[str] = []
            j = i + 1
            depth = 1
            current_is_header = False
            row_cells: list[list] = []
            while j < n and depth > 0:
                tt = tokens[j]
                if tt.type == "table_open":
                    depth += 1
                elif tt.type == "table_close":
                    depth -= 1
                    if depth == 0:
                        break
                elif tt.type == "thead_open":
                    current_is_header = True
                elif tt.type == "thead_close":
                    current_is_header = False
                elif tt.type == "tr_open":
                    row_cells = []
                elif tt.type == "tr_close":
                    if current_is_header:
                        header_row = row_cells
                    else:
                        rows.append(row_cells)
                elif tt.type in ("th_open", "td_open"):
                    cell_align = tt.attrGet("style") or ""
                    if current_is_header:
                        if "text-align:left" in cell_align:
                            align.append("left")
                        elif "text-align:right" in cell_align:
                            align.append("right")
                        elif "text-align:center" in cell_align:
                            align.append("center")
                        else:
                            align.append("")
                    # next token is inline
                    inline_tok = tokens[j + 1]
                    row_cells.append(inline_tok.children or [])
                j += 1
            _render_table(r, header_row, rows, align)
            i = j + 1
            continue
        # Unknown / close tokens
        i += 1

    _post_process_toc_markers(doc)
    _post_process_transclusions(doc, _transclusion_targets, transclusion_resolver)
    _post_process_footnotes(doc)


def _post_process_toc_markers(doc: QTextDocument) -> None:
    """Find TOC-sentinel blocks; tag them, replace the sentinel with a styled
    `[[!TOC]]` label, and append a clickable list of the document's headings
    as read-only child blocks (marked `BLOCK_TRANSCLUDED_CHILD` so they're
    dropped on save)."""
    # First pass: collect headings so we can render them as a list.
    headings: list[tuple[int, str]] = []
    block = doc.firstBlock()
    while block.isValid():
        bf = block.blockFormat()
        if (bf.property(BLOCK_KIND) or "") == "h":
            level = int(bf.property(BLOCK_LEVEL) or 1)
            headings.append((level, block.text().strip()))
        block = block.next()

    # Second pass: find + rewrite sentinel blocks.
    hits: list[int] = []
    block = doc.firstBlock()
    while block.isValid():
        if block.text().strip() == _TOC_SENTINEL:
            hits.append(block.position())
        block = block.next()
    for pos in reversed(hits):
        cur = QTextCursor(doc)
        cur.setPosition(pos)
        blk = cur.block()
        cur.setPosition(blk.position())
        cur.setPosition(blk.position() + blk.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()
        bf = blk.blockFormat()
        bf.setProperty(BLOCK_TOC_MARKER, True)
        cur.setBlockFormat(bf)
        cf = QTextCharFormat()
        cf.setForeground(QColor("#1a5fb4"))
        cf.setFontItalic(True)
        cur.insertText("[[!TOC]]", cf)
        # Append a clickable anchor list, one heading per child block.
        for level, htext in headings:
            if not htext:
                continue
            cbf = QTextBlockFormat()
            cbf.setProperty(BLOCK_KIND, "p")
            cbf.setProperty(BLOCK_TRANSCLUDED_CHILD, True)
            cbf.setLeftMargin(12 * level)
            cur.insertBlock(cbf)
            acf = QTextCharFormat()
            acf.setForeground(QColor("#1a5fb4"))
            acf.setAnchor(True)
            acf.setAnchorHref(f"qnotebook:#{htext}")
            acf.setProperty(CHAR_WIKILINK, f"#{htext}")
            acf.setFontUnderline(True)
            cur.insertText(htext, acf)


def _post_process_transclusions(doc: QTextDocument, targets: list[str], resolver) -> None:
    """Find transclusion sentinel blocks; tag them, replace text with styled
    `{{target}}` placeholder, and optionally append the included content
    as read-only child paragraphs (marked so the serializer skips them)."""
    import re as _re
    pat = _re.compile(rf"^{_TRANSCLUDE_SENTINEL_PREFIX}(\d+)$")
    # Collect first, then mutate (iterating while inserting is fragile).
    hits: list[tuple[int, int]] = []  # (block_position, target_idx)
    block = doc.firstBlock()
    while block.isValid():
        m = pat.match(block.text().strip())
        if m:
            hits.append((block.position(), int(m.group(1))))
        block = block.next()
    # Iterate in reverse so earlier positions stay valid.
    for pos, tidx in reversed(hits):
        if tidx >= len(targets):
            continue
        target = targets[tidx]
        cur = QTextCursor(doc)
        cur.setPosition(pos)
        blk = cur.block()
        # Select the block's text (not the surrounding block separators).
        cur.setPosition(blk.position())
        cur.setPosition(blk.position() + blk.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()
        bf = blk.blockFormat()
        bf.setProperty(BLOCK_TRANSCLUSION, target)
        cur.setBlockFormat(bf)
        cf = QTextCharFormat()
        cf.setForeground(QColor("#7f7f7f"))
        cf.setFontItalic(True)
        cur.insertText(f"{{{{{target}}}}}", cf)
        # Optionally render the included content as a read-only child block.
        if resolver is not None:
            try:
                included = resolver(target)
            except Exception:
                included = None
            if included:
                cbf = QTextBlockFormat()
                cbf.setProperty(BLOCK_KIND, "p")
                cbf.setProperty(BLOCK_TRANSCLUDED_CHILD, True)
                cbf.setLeftMargin(12)
                cur.insertBlock(cbf)
                ccf = QTextCharFormat()
                ccf.setForeground(QColor("#4a4a4a"))
                cur.insertText(included.strip(), ccf)


_FN_REF_RE = re.compile(r"\[\^([A-Za-z0-9_-]+)\]")
_FN_DEF_RE = re.compile(r"^\[\^([A-Za-z0-9_-]+)\]:\s")


def _post_process_footnotes(doc: QTextDocument) -> None:
    """Mark footnote reference spans and footnote definition blocks."""
    block = doc.firstBlock()
    while block.isValid():
        text = block.text()
        # Definition: `[^label]: body`
        m_def = _FN_DEF_RE.match(text)
        if m_def:
            bf = block.blockFormat()
            bf.setProperty(BLOCK_FOOTNOTE_DEF, m_def.group(1))
            cur = QTextCursor(block)
            cur.setBlockFormat(bf)
        # References: `[^label]` inside the block
        for m in _FN_REF_RE.finditer(text):
            # Skip if this match is the definition prefix (starts at col 0 and
            # is followed by `:` — same as `_FN_DEF_RE`).
            if m.start() == 0 and m_def and m.group(1) == m_def.group(1):
                continue
            cur = QTextCursor(doc)
            cur.setPosition(block.position() + m.start())
            cur.setPosition(block.position() + m.end(), QTextCursor.MoveMode.KeepAnchor)
            cf = QTextCharFormat()
            cf.setForeground(QColor("#1a5fb4"))
            cf.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)
            cf.setProperty(CHAR_FOOTNOTE_REF, m.group(1))
            cur.mergeCharFormat(cf)
        block = block.next()


def _list_item_block_format(depth: int, is_task: bool, task_state: int) -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    fmt.setProperty(BLOCK_KIND, "task" if is_task else "li")
    fmt.setProperty(BLOCK_LEVEL, depth)
    if is_task:
        fmt.setProperty(BLOCK_TASK_STATE, task_state)
    fmt.setTopMargin(2)
    fmt.setBottomMargin(2)
    return fmt


def _apply_list_format(cursor: QTextCursor, list_stack: list[tuple[str, int]], existing):
    kind, start = list_stack[-1]
    block_fmt = cursor.blockFormat()
    block_fmt.setProperty(BLOCK_LIST_KIND, kind)
    if kind == "ol":
        block_fmt.setProperty(BLOCK_ORDERED_START, start)
    cursor.setBlockFormat(block_fmt)
    if existing is not None:
        existing.add(cursor.block())
        return existing
    lf = QTextListFormat()
    depth = len(list_stack)
    lf.setIndent(depth)
    if kind == "ul":
        styles = [
            QTextListFormat.Style.ListDisc,
            QTextListFormat.Style.ListCircle,
            QTextListFormat.Style.ListSquare,
        ]
        lf.setStyle(styles[(depth - 1) % 3])
    else:
        lf.setStyle(QTextListFormat.Style.ListDecimal)
        lf.setStart(start)
    return cursor.createList(lf)


def _pygments_highlight(source: str, lang: str) -> list[list[tuple[str, str | None]]] | None:
    """Return a list-per-line of (text, css_color) tokens using Pygments.
    Returns None if Pygments is unavailable or the lexer is unknown."""
    try:
        from pygments import lex
        from pygments.lexers import get_lexer_by_name
        from pygments.token import Token
        from pygments.util import ClassNotFound
    except ImportError:
        return None
    try:
        lexer = get_lexer_by_name(lang, stripall=False)
    except ClassNotFound:
        return None

    # Minimal Token → color map for a light theme.
    palette = {
        Token.Keyword: "#8f3f71",
        Token.Keyword.Namespace: "#8f3f71",
        Token.Keyword.Constant: "#8f3f71",
        Token.Name.Function: "#1d4e89",
        Token.Name.Class: "#1d4e89",
        Token.Name.Builtin: "#1d4e89",
        Token.Name.Decorator: "#b16286",
        Token.String: "#af5f00",
        Token.String.Doc: "#7f7f7f",
        Token.Number: "#d65d0e",
        Token.Comment: "#7f7f7f",
        Token.Operator: "#5f5f5f",
        Token.Punctuation: "#5f5f5f",
    }

    def color_for(tok_type) -> str | None:
        t = tok_type
        while t is not None:
            if t in palette:
                return palette[t]
            t = t.parent
        return None

    lines: list[list[tuple[str, str | None]]] = [[]]
    for tok_type, tok_text in lex(source, lexer):
        color = color_for(tok_type)
        # Split on newlines to preserve per-line structure
        parts = tok_text.split("\n")
        for k, part in enumerate(parts):
            if part:
                lines[-1].append((part, color))
            if k < len(parts) - 1:
                lines.append([])
    # Drop a trailing empty line the lexer may have appended after the final newline.
    if len(lines) > 1 and not lines[-1]:
        lines.pop()
    if not lines:
        lines = [[]]
    return lines


def _render_table(r: _Renderer, header: list, rows: list[list[list]], align: list[str]) -> None:
    n_cols = max(len(header), max((len(row) for row in rows), default=0)) if (header or rows) else 0
    if n_cols == 0:
        return
    n_rows = 1 + len(rows) if header else len(rows)
    if n_rows == 0:
        return
    # Insert a paragraph to anchor the table after, to avoid orphan cursor issues
    # Actually Qt insertTable works inline — insert at current position.
    tfmt = QTextTableFormat()
    tfmt.setBorder(1)
    tfmt.setCellPadding(4)
    tfmt.setCellSpacing(0)
    # Ensure we're on a new block first
    r.new_block(_paragraph_format())
    # Mark this paragraph as pre-table marker (empty)
    table = r.cursor.insertTable(n_rows, n_cols, tfmt)
    # Fill cells
    def fill_cell(row: int, col: int, children: list, is_header: bool) -> None:
        cell = table.cellAt(row, col)
        cur = cell.firstCursorPosition()
        bfmt = QTextBlockFormat()
        bfmt.setProperty(BLOCK_KIND, "th" if is_header else "td")
        cur.setBlockFormat(bfmt)
        runs = _parse_inline_children(children, _InlineStyle())
        for text, style in runs:
            f = style.char_format()
            if is_header:
                f.setFontWeight(QFont.Weight.Bold)
            cur.insertText(text, f)

    row_offset = 0
    if header:
        for c in range(n_cols):
            fill_cell(0, c, header[c] if c < len(header) else [], True)
        row_offset = 1
    for ri, row in enumerate(rows):
        for c in range(n_cols):
            fill_cell(row_offset + ri, c, row[c] if c < len(row) else [], False)
    # Move cursor past the table
    r.cursor.movePosition(QTextCursor.MoveOperation.End)
