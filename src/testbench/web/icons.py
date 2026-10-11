"""Testbench's icon set: outline icons on a 24px grid, one stroke weight, drawn for this app.

Icons are inline SVG, so they follow the text colour and need no extra request. An icon is
decorative unless it gets a label, and then screen readers announce the label.
"""

from __future__ import annotations

from markupsafe import Markup, escape

_RING = '<circle cx="12" cy="12" r="8.5"/>'

ICONS: dict[str, str] = {
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "play": (
        '<path d="M8 5.8v12.4a.8.8 0 0 0 1.2.7l9.9-6.2a.8.8 0 0 0 0-1.4'
        'L9.2 5.1a.8.8 0 0 0-1.2.7z"/>'
    ),
    "chevron-right": '<path d="m9.5 6 6 6-6 6"/>',
    "chevron-down": '<path d="m6 9.5 6 6 6-6"/>',
    "more": (
        '<circle cx="5.5" cy="12" r=".9"/><circle cx="12" cy="12" r=".9"/>'
        '<circle cx="18.5" cy="12" r=".9"/>'
    ),
    "pencil": '<path d="M4.5 19.5h4l10-10a2.83 2.83 0 0 0-4-4l-10 10z"/><path d="m13 7 4 4"/>',
    "trash": (
        '<path d="M4.5 7h15M10 11v5.5M14 11v5.5"/>'
        '<path d="m6.5 7 .8 11.6a2 2 0 0 0 2 1.9h5.4a2 2 0 0 0 2-1.9L17.5 7M9.5 7V4.5h5V7"/>'
    ),
    "logout": (
        '<path d="M14.5 4.5h3a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-3"/>'
        '<path d="M10 16.5 14.5 12 10 7.5M14.5 12h-10"/>'
    ),
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "passed": _RING + '<path d="m8.5 12.3 2.4 2.4 4.6-4.9"/>',
    "failed": _RING + '<path d="m9.3 9.3 5.4 5.4M14.7 9.3l-5.4 5.4"/>',
    "error": (
        '<path d="M10.4 4.6 3.2 17.3a1.8 1.8 0 0 0 1.6 2.7h14.4a1.8 1.8 0 0 0 1.6-2.7'
        'L13.6 4.6a1.8 1.8 0 0 0-3.2 0z"/>'
        '<path d="M12 9.5v4M12 16.8v.01"/>'
    ),
    "skipped": _RING + '<path d="M8.5 12h7"/>',
    "not-run": '<circle cx="12" cy="12" r="8.5" stroke-dasharray="2.6 2.95"/>',
    "info": _RING + '<path d="M12 11v5M12 8v.01"/>',
    "database": (
        '<ellipse cx="12" cy="6.5" rx="6.5" ry="2.5"/>'
        '<path d="M5.5 6.5v11c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5v-11"/>'
        '<path d="M5.5 12c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5"/>'
    ),
    "cloud": (
        '<path d="M7.5 18.5h9.8a3.7 3.7 0 0 0 .5-7.4 5.8 5.8 0 0 0-11.2-.9'
        'A4.2 4.2 0 0 0 7.5 18.5z"/>'
    ),
    "settings": (
        '<path d="M4.5 7.5h8M16.5 7.5h3M4.5 16.5h3M11.5 16.5h8"/>'
        '<circle cx="14.5" cy="7.5" r="2"/><circle cx="9.5" cy="16.5" r="2"/>'
    ),
    "lineage": (
        '<rect x="3.5" y="4" width="6" height="4.5" rx="1.2"/>'
        '<rect x="14.5" y="4" width="6" height="4.5" rx="1.2"/>'
        '<rect x="9" y="15.5" width="6" height="4.5" rx="1.2"/>'
        '<path d="M6.5 8.5v1.8a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2V8.5M12 12.3v3.2"/>'
    ),
    "pulse": '<path d="M3.5 12h3.5l2.2-5.5 5.1 11 2.2-5.5h4"/>',
    "lock": (
        '<rect x="5.5" y="10.5" width="13" height="9.5" rx="2"/>'
        '<path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>'
    ),
    "baseline": (
        '<path d="M4.5 8.8c0-.8.7-1.5 1.5-1.5h1.8L9.3 5h5.4l1.5 2.3H18c.8 0 1.5.7 1.5 1.5v8.7'
        'c0 .8-.7 1.5-1.5 1.5H6c-.8 0-1.5-.7-1.5-1.5z"/><circle cx="12" cy="12.8" r="3.2"/>'
    ),
    "clock": _RING + '<path d="M12 7.5V12l3 2"/>',
    "external": (
        '<path d="M13.5 4.5h6v6M19.5 4.5l-8 8"/>'
        '<path d="M17.5 14v3.5a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2H10"/>'
    ),
    "workspace": (
        '<rect x="4" y="4" width="7" height="7" rx="1.6"/>'
        '<rect x="13" y="4" width="7" height="7" rx="1.6"/>'
        '<rect x="4" y="13" width="7" height="7" rx="1.6"/>'
        '<rect x="13" y="13" width="7" height="7" rx="1.6"/>'
    ),
    "scenario": (
        '<path d="M13.5 3.5H7.5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8.5z"/>'
        '<path d="M13.5 3.5v5h5M9 13h6M9 16.5h4"/>'
    ),
    "code": '<path d="m9 7.5-4.5 4.5L9 16.5M15 7.5l4.5 4.5-4.5 4.5"/>',
    "plug": '<path d="M9 3.5v4M15 3.5v4M7 7.5h10v3.5a5 5 0 0 1-10 0zM12 16v4.5"/>',
}


def icon(name: str, label: str | None = None, cls: str = "") -> Markup:
    """An inline SVG icon; ``label`` makes it meaningful to screen readers."""
    a11y = f'role="img" aria-label="{escape(label)}"' if label else 'aria-hidden="true"'
    classes = f"icon {cls}".strip()
    return Markup(
        f'<svg class="{escape(classes)}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" focusable="false" '
        f"{a11y}>{ICONS[name]}</svg>"
    )


def logo(cls: str = "logo") -> Markup:
    """The Testbench mark: a health strip of four scenario results, the last one still open."""
    bars = "".join(
        f'<rect class="logo-bar{" off" if i == 3 else ""}" x="{3.8 + i * 4.4:g}" y="6.5" '
        f'width="3.2" height="11" rx="1"/>'
        for i in range(4)
    )
    return Markup(
        f'<svg class="{escape(cls)}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        f'<rect class="logo-ground" width="24" height="24" rx="6"/>{bars}</svg>'
    )
