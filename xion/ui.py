"""Terminal presentation layer for Xion.

Everything the CLI shows the person — banners, menus, tables, status
messages, and the exit screen — lives here so the rest of the app can stay
focused on logic. Two things this module guarantees:

  * A single, consistent visual language (a bold neon-on-black palette,
    italic secondary text, centered/aligned composition, and soft-rounded
    panels) so nothing looks like an afterthought.
  * A single, consistent way to leave: whether someone picks "Exit", hits
    Ctrl+C, or closes the input stream (Ctrl+D), it always ends on the same
    calm, deliberate goodbye screen instead of a stack trace.
"""

from __future__ import annotations

from typing import Callable, Iterable, Mapping, Sequence

import pandas as pd
from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

APP_NAME = "XION"
APP_VERSION = "1.0"
APP_TAGLINE = "Analyze your own call logs & mobile network signals."


THEME = Theme({
    "brand":        "bold #00e5ff",          # electric cyan
    "brand.dim":    "italic #2fb8cf",        # quiet cyan, for bylines/labels
    "accent":       "bold #ff2ec4",          # hot magenta
    "accent2":      "bold #9d4eff",          # electric violet
    "accent3":      "bold #ffd60a",          # struck gold — ornaments only
    "muted":        "italic #9aa5b8",        # secondary body copy
    "subtle":       "italic dim #7c8697",    # tertiary hints / footnotes
    "caption":      "italic dim #6f7891",    # small print under tables
    "success":      "bold #00e676",          # vivid green
    "warning":      "bold #ffb300",          # vivid amber
    "error":        "bold #ff3860",          # vivid rose-red
    "info":         "bold #00e5ff",
    "prompt":       "bold #f5f5f7",
    "index":        "bold #ff2ec4",
    "header":       "bold italic #00e5ff",
    "value":        "#f5f5f7",
    "badge.brand":   "bold black on #00e5ff",
    "badge.accent":  "bold white on #ff2ec4",
    "badge.gold":    "bold black on #ffd60a",
    "badge.success": "bold black on #00e676",
    "badge.warning": "bold black on #ffb300",
    "badge.error":   "bold white on #ff3860",
})

console = Console(theme=THEME, highlight=False)

_RULE_CHAR = "─"
_BOX = box.ROUNDED          # soft corners everywhere data lives
_BOX_STRONG = box.DOUBLE    # reserved for the goodbye screen only


class QuitRequested(Exception):
    """Raised to unwind cleanly to the goodbye screen.

    Every exit path funnels through this: choosing "Exit" from the menu,
    typing q/quit, pressing Ctrl+C, or hitting Ctrl+D at any prompt. The
    ``reason`` just changes which farewell line is shown.
    """

    def __init__(self, reason: str = "exit"):
        self.reason = reason
        super().__init__(reason)


_QUIT_WORDS = {"q", "quit", "exit", ":q"}


# ── Wordmark ─────────────────────────────────────────────────────────────
_LOGO_FONT = {
    "X": ["█   █", " █ █ ", "  █  ", " █ █ ", "█   █"],
    "I": ["█████", "  █  ", "  █  ", "  █  ", "█████"],
    "O": [" ███ ", "█   █", "█   █", "█   █", " ███ "],
    "N": ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
}

_LOGO_GRADIENT = ["#00e5ff", "#9d4eff", "#ff2ec4", "#ffd60a"]


def _logo() -> Text:
    colors = _LOGO_GRADIENT[: len(APP_NAME)]
    logo = Text()
    for row in range(5):
        for i, ch in enumerate(APP_NAME):
            logo.append(_LOGO_FONT[ch][row], style=f"bold {colors[i % len(colors)]}")
            if i < len(APP_NAME) - 1:
                logo.append("  ")
        if row < 4:
            logo.append("\n")
    return logo


def _gradient_bar(width: int, colors: list[str] = _LOGO_GRADIENT, ornament: str = "◆") -> Text:
    """A solid bar split into bold color bands with a centered ornament —
    a deliberate flourish under the banner instead of a plain rule."""
    bar = Text()
    n = len(colors)
    half = max(1, (width - 1) // 2)
    seg = max(1, half // n)

    def _side(reverse: bool) -> Text:
        t = Text()
        cs = list(reversed(colors)) if reverse else colors
        for i, color in enumerate(cs):
            length = seg if i < n - 1 else max(1, half - seg * (n - 1))
            t.append(_RULE_CHAR * length, style=f"bold {color}")
        return t

    bar.append(_side(reverse=True))
    bar.append(f" {ornament} ", style="bold #ffd60a")
    bar.append(_side(reverse=False))
    return bar


def _ornamented(text: str, *, style: str = "muted", glyph: str = "◆", glyph_style: str = "accent3") -> Text:
    """`◆  text  ◆` — the small framing device used under the wordmark and
    above section content so short lines don't float unanchored."""
    t = Text()
    t.append(glyph, style=glyph_style)
    t.append(f"  {text}  ", style=style)
    t.append(glyph, style=glyph_style)
    return t


def banner() -> None:
    console.print()
    console.print(Align.center(_logo()))
    console.print()
    console.print(Align.center(_gradient_bar(48)))
    console.print()
    console.print(Align.center(_ornamented(APP_TAGLINE)))
    console.print(Align.center(Text(f"⟨ v{APP_VERSION} ⟩", style="brand.dim")))
    console.print()


def notice() -> None:
    lines = [
        ("Xion only works with data ", "you", " exported."),
        ("It never collects data from a device on its own.", None, None),
        ("Built for personal insight and research.", None, None),
        ("Author : Xdzy-TD // Github : https://github.com/Xdzy-TD", None, None),
    ]
    body = Text()
    for i, (pre, strong, post) in enumerate(lines):
        body.append("◆ ", style="accent3")
        body.append(pre, style="muted")
        if strong:
            body.append(strong, style="italic bold value")
            body.append(post, style="muted")
        if i < len(lines) - 1:
            body.append("\n")
    console.print(Panel(
        body,
        title="[badge.warning]  ✦ BEFORE YOU START  [/badge.warning]",
        title_align="center",
        border_style="warning",
        box=_BOX,
        padding=(1, 3),
    ))
    console.print()


def section_header(profile_name: str) -> None:
    console.print()
    console.rule(
        f"[brand]{APP_NAME}[/brand] [subtle]▸[/subtle] "
        f"[badge.accent]  {profile_name}  [/badge.accent]",
        style="brand.dim",
        characters=_RULE_CHAR,
    )


def panel(
    content: RenderableType,
    *,
    title: str | None = None,
    badge_style: str = "badge.brand",
    border_style: str = "brand",
    centered_title: bool = True,
) -> Panel:
    """Shared panel chrome (rounded box, badge title, even padding) so any
    caller — including the CLI layer — gets the same frame as everything
    else instead of hand-rolling `rich.panel.Panel(...)` per call site."""
    return Panel(
        content,
        title=f"[{badge_style}]  {title.upper()}  [/{badge_style}]" if title else None,
        title_align="center" if centered_title else "left",
        border_style=border_style,
        box=_BOX,
        padding=(1, 2),
    )


# ── Input ────────────────────────────────────────────────────────────────
def ask(prompt: str, *, default: str | None = None, password: bool = False) -> str:
    """A themed stand-in for input()/Prompt.ask() that never crashes on exit.

    Ctrl+C and Ctrl+D are treated as an intentional (if abrupt) request to
    leave, not an error — they're converted into QuitRequested so the caller
    doesn't need its own try/except at every input site.

    Always returns a str (never None): pressing Enter with nothing typed
    and no explicit default returns "", matching plain input()'s behavior,
    rather than rich's own default-less prompt (which loops forever asking
    again) or a bare None (which would crash the first .strip() downstream).
    """
    try:
        return Prompt.ask(
            f"[accent3]❯[/accent3] [prompt]{prompt}[/prompt]",
            default="" if default is None else default,
            show_default=default is not None,
            password=password,
            console=console,
        )
    except (EOFError, KeyboardInterrupt):
        console.print()
        raise QuitRequested("interrupt") from None


def confirm(prompt: str, *, default: bool = True) -> bool:
    suffix = "[italic #5fe89a][Y/n][/]" if default else "[italic #ff7a92][y/N][/]"
    raw = ask(f"{prompt} {suffix}", default="y" if default else "n").strip().lower()
    return raw in ("y", "yes", "1", "true")


def menu(options: list[str], *, title: str | None = None) -> str:
    if title:
        console.print(Text(title, style="header"))
    width = len(str(len(options)))
    table = Table(show_header=False, box=None, padding=(0, 1, 0, 0))
    table.add_column(justify="right", width=max(3, width + 1))
    table.add_column()
    for i, opt in enumerate(options, 1):
        # The way out gets its own color so it always reads as distinct
        # from the rest of the list, at a glance.
        is_exit = opt.strip().lower() == "exit"
        num_style = "error" if is_exit else "index"
        text_style = "italic error" if is_exit else "prompt"
        marker = "✕" if is_exit else "·"
        table.add_row(
            f"[{num_style}]{i:>{width}}[/{num_style}][subtle]{marker}[/subtle]",
            f"[{text_style}]{opt}[/{text_style}]",
        )
    console.print(table)
    console.print(Align.left(Text(
        "Enter a number, 'h' for help, or 'q' to quit anytime.", style="subtle",
    )))
    choice = ask("Select an option")
    if choice.strip().lower() in _QUIT_WORDS:
        raise QuitRequested("exit")
    return choice


# ── Data display ─────────────────────────────────────────────────────────
def show_dataframe(
    df: pd.DataFrame,
    title: str = "",
    *,
    columns: Sequence[str] | None = None,
    headers: Mapping[str, str] | None = None,
    formatters: Mapping[str, Callable[[object], str]] | None = None,
    max_rows: int = 50,
) -> None:
    if df.empty:
        console.print(Align.left(Text("No records to display.", style="muted")))
        return

    cols = [c for c in (columns or list(df.columns)) if c in df.columns]
    headers = headers or {}
    formatters = formatters or {}

    table = Table(
        title=f"[badge.brand]  {title.upper()}  [/badge.brand]" if title else None,
        title_style="none",
        box=_BOX,
        border_style="brand",
        header_style="header",
        show_lines=False,
        expand=False,
        padding=(0, 1),
    )
    for c in cols:
        label = headers.get(c, c.replace("_", " ").title())
        table.add_column(label)

    for _, row in df.head(max_rows).iterrows():
        cells = []
        for c in cols:
            val = row.get(c)
            fmt = formatters.get(c)
            if fmt:
                cells.append(fmt(val))
            elif val is None or (isinstance(val, float) and pd.isna(val)) or val == "None":
                cells.append("[subtle]—[/subtle]")
            else:
                cells.append(str(val))
        table.add_row(*cells)

    console.print(table)
    if len(df) > max_rows:
        console.print(Align.left(Text(
            f"… and {len(df) - max_rows} more row(s) — export a report to see all.",
            style="caption",
        )))
    console.print()


def key_value_table(rows: Iterable[tuple[str, str]], title: str | None = None) -> Table:
    table = Table(
        title=f"[badge.brand]  {title.upper()}  [/badge.brand]" if title else None,
        title_style="none",
        box=_BOX,
        border_style="brand",
        show_header=False,
        padding=(0, 1),
    )
    table.add_column(style="muted", justify="right")
    table.add_column(style="value")
    for k, v in rows:
        table.add_row(k, v)
    return table


def indexed_table(
    rows: Iterable[tuple[str, str, str]],
    *,
    title: str | None = None,
    headers: tuple[str, str, str] = ("#", "Setting", "Value"),
) -> Table:
    """A numbered variant of key_value_table, for lists the person picks from
    by number (e.g. Settings) — so "type the number you see" stays true
    everywhere in the app, not just at the main menu."""
    table = Table(
        title=f"[badge.brand]  {title.upper()}  [/badge.brand]" if title else None,
        title_style="none",
        box=_BOX,
        border_style="brand",
        header_style="header",
        padding=(0, 1),
    )
    table.add_column(headers[0], justify="right", style="index", width=3)
    table.add_column(headers[1], style="muted")
    table.add_column(headers[2], style="value")
    for idx, label, value in rows:
        table.add_row(idx, label, value)
    return table


# ── Feedback ─────────────────────────────────────────────────────────────
# Every status line gets a solid-color badge chip up front, so the outcome
# (done / heads up / failed / fyi) reads instantly, even skimming fast.
def success(msg: str) -> None:
    console.print(f"[badge.success] ✓ [/badge.success] [success]{msg}[/success]")


def warn(msg: str) -> None:
    console.print(f"[badge.warning] ! [/badge.warning] [warning]{msg}[/warning]")


def error(msg: str) -> None:
    console.print(f"[badge.error] ✗ [/badge.error] [error]{msg}[/error]")


def info(msg: str) -> None:
    console.print(f"[badge.brand] i [/badge.brand] [info]{msg}[/info]")


def status(msg: str):
    """Context manager showing a themed spinner for slow operations."""
    return console.status(f"[italic brand]{msg}…[/italic brand]", spinner="dots", spinner_style="accent3")


# ── Exit ─────────────────────────────────────────────────────────────────
_GOODBYE = {
    "exit": "Thanks for stopping by — your data stays right where you left it.",
    "interrupt": "Cut that short — no problem, nothing was lost.",
}


def goodbye(reason: str = "exit") -> None:
    message = _GOODBYE.get(reason, _GOODBYE["exit"])
    title = Text.from_markup(
        f"[accent3]◆[/accent3]  [badge.accent]  {APP_NAME} — SESSION CLOSED  [/badge.accent]  [accent3]◆[/accent3]"
    )
    sub = Text(message, style="muted")
    console.print()
    console.print(Panel(
        Group(Align.center(title), Text(""), Align.center(sub)),
        border_style="accent",
        box=_BOX_STRONG,
        padding=(1, 4),
    ))
    console.print(Align.center(Text("Goodbye! 👋", style="italic bold accent2")))
    console.print()
