from functools import lru_cache

from PySide6.QtCore import QRectF
from PySide6.QtSvg import QSvgRenderer


GLYPHS = {
    'close': '<path d="m6 15 6-6 6 6"/>',
    'left': '<path d="m14 6-6 6 6 6"/>',
    'right': '<path d="m10 6 6 6-6 6"/>',
    'play': '<path fill="currentColor" stroke="none" d="M8 5.7a1 1 0 0 1 1.5-.9l10 6.3a1 1 0 0 1 0 1.8l-10 6.3a1 1 0 0 1-1.5-.9z"/>',
    'pause': '<path stroke-width="3.4" d="M9 6v12m6-12v12"/>',
    'previous': '<path fill="currentColor" stroke="none" d="M6 5h2v14H6zm13 1.5a.9.9 0 0 0-1.4-.75l-8 5.5a.9.9 0 0 0 0 1.5l8 5.5a.9.9 0 0 0 1.4-.75z"/>',
    'next': '<path fill="currentColor" stroke="none" d="M16 5h2v14h-2zm-11 1.5a.9.9 0 0 1 1.4-.75l8 5.5a.9.9 0 0 1 0 1.5l-8 5.5a.9.9 0 0 1-1.4-.75z"/>',
    'shuffle': '<path d="M3 6h2c5.5 0 7.5 12 13 12h3m-4-4 4 4-4 4M3 18h2c5.5 0 7.5-12 13-12h3m-4-4 4 4-4 4"/>',
    'repeat': '<path d="m16 3 4 4-4 4M4 11V9a2 2 0 0 1 2-2h14m-12 6-4 4 4 4m12-8v2a2 2 0 0 1-2 2H4"/>',
    'repeat_one': '<path d="m16 3 4 4-4 4M4 11V9a2 2 0 0 1 2-2h14m-12 6-4 4 4 4m12-8v2a2 2 0 0 1-2 2H4m7-6 1-1v4"/>',
    'volume': '<path d="M3 9h4l5-4v14l-5-4H3zM16 9a4 4 0 0 1 0 6m3-9a8 8 0 0 1 0 12"/>',
    'mute': '<path d="M3 9h4l5-4v14l-5-4H3zm13 0 5 6m0-6-5 6"/>',
    'music': '<path d="M9 17V6l10-2v11M9 9l10-2"/><ellipse cx="6" cy="17" rx="3" ry="2"/><ellipse cx="16" cy="15" rx="3" ry="2"/>',
    'grid': '<path fill="currentColor" stroke="none" d="M4 4h7v7H4zm9 0h7v7h-7zM4 13h7v7H4zm9 0h7v7h-7z"/>',
    'gauge': '<path d="M4 17a8.7 8.7 0 1 1 16 0zM12 14l4-5M6.5 12l1 .5M12 7v1m5.5 4-.9.5"/>',
    'cloud': '<path d="M6.5 17.5a3.7 3.7 0 1 1 .1-7.4 5.8 5.8 0 0 1 11.2-.9 4.2 4.2 0 1 1 .5 8.3z"/>',
    'partly': '<path d="M8.3 7a3.5 3.5 0 1 1 6.6-1.9M7 2l.7 1.4M3 5l1.5.4M2.5 10l1.4-.6M18.4 3l-1.2 1M6.5 19a3.4 3.4 0 1 1 .2-6.8 5.1 5.1 0 0 1 9.9-1 4 4 0 1 1 1 7.8z"/>',
    'sun': '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
    'rain': '<path d="M6 15a3.4 3.4 0 1 1 .5-6.7 5.2 5.2 0 0 1 10 0A3.6 3.6 0 1 1 18 15zM8 18l-1 3m6-3-1 3m6-3-1 3"/>',
    'storm': '<path d="M6 15a3.4 3.4 0 1 1 .5-6.7 5.2 5.2 0 0 1 10 0A3.6 3.6 0 1 1 18 15h-1M11 14l-2 4h4l-2 4"/>',
    'snow': '<path d="M6 14a3 3 0 1 1 .5-5.9 5 5 0 0 1 9.6-.2 3.3 3.3 0 1 1 1 6.1zM7 18h.1m9.9 0h.1m-5.1 3h.1"/>',
    'fog': '<path d="M6 13a3.2 3.2 0 1 1 .5-6.4 5.4 5.4 0 0 1 10-.2 3.4 3.4 0 1 1 1 6.6zM4 17h16m-13 4h10"/>',
    'user': '<circle cx="12" cy="8" r="3.5"/><path d="M4.5 20v-2c0-2.8 3.4-4.6 7.5-4.6s7.5 1.8 7.5 4.6v2z"/>',
    'windows': '<path fill="currentColor" stroke="none" d="M3 3h8v8H3zm10 0h8v8h-8zM3 13h8v8H3zm10 0h8v8h-8z"/>',
    'desktop': '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
    'clock': '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
    'terminal': '<rect x="3" y="4" width="18" height="16" rx="4"/><path d="m7 9 3 3-3 3m6 0h4"/>',
    'bell': '<path d="M18 9a6 6 0 0 0-12 0c0 7-2.5 7-2.5 8.5h17C20.5 16 18 16 18 9ZM10 21h4"/>',
    'check': '<path d="m5 12 4 4L19 6"/>',
    'stop': '<rect x="7" y="7" width="10" height="10" rx="2"/>',
    'activity': '<path d="M3 12h4l2.5-6 4 12 2.5-6H21"/>',
    'hourglass': '<path d="M6 3h12M6 21h12M7 3v3a5 5 0 0 0 2 4l3 2 3-2a5 5 0 0 0 2-4V3M7 21v-3a5 5 0 0 1 2-4l3-2 3 2a5 5 0 0 1 2 4v3"/>',
    'stopwatch': '<circle cx="12" cy="14" r="7"/><path d="M10 2h4m-2 5V2m5 6 2-2m-7 4v4l2 1"/>',
    'headphones': '<path d="M4 13v-1a8 8 0 0 1 16 0v1"/><rect x="4" y="12" width="4" height="7" rx="2"/><rect x="16" y="12" width="4" height="7" rx="2"/>',
    'flag': '<path d="M6 21V4m0 1c4-4 8 4 12 0v9c-4 4-8-4-12 0"/>',
    'plus': '<path d="M5 12h14M12 5v14"/>',
    'minus': '<path d="M5 12h14"/>',
    'external': '<path d="M13 5h6v6m0-6-8 8m7 0v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    'x': '<path d="m7 7 10 10M17 7 7 17"/>',
    'cpu': '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M10 10h4v4h-4zM9 3v3m6-3v3M9 18v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3"/>',
    'ram': '<rect x="3" y="6" width="18" height="11" rx="2"/><path d="M8 9v5m4-5v5m4-5v5M6 17v3m4-3v3m4-3v3m4-3v3"/>',
    'disk': '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 16h8m-7-4h.1m5.9 0h.1M9 7h6"/>',
    'refresh': '<path d="M20 8a8 8 0 1 0 0 8m0-12v4h-4"/>',
    'drop': '<path d="M12 3c-3.1 4.2-6 7.1-6 11a6 6 0 0 0 12 0c0-3.9-2.9-6.8-6-11z"/>',
    'wind': '<path d="M3 9h12a3 3 0 1 0-3-3m-9 7h15a2.5 2.5 0 1 1-2.5 2.5M3 17h7a2 2 0 1 1-2 2"/>',
    'sunrise': '<path d="M3 17h18M3 21h18M7 17a5 5 0 0 1 10 0M12 4v3m-7 1 2 2m12-2-2 2M3 13l2 1m16-1-2 1"/>',
    'moon': '<path d="M20 15.1a8.3 8.3 0 1 1-11-11A7.9 7.9 0 0 0 20 15.1z"/>',
    'network': '<path d="M7 4v16m-4-12 4-4 4 4m6 12V4m-4 12 4 4 4-4"/>',
    'temperature': '<path d="M10 14V5a2 2 0 0 1 4 0v9a4.5 4.5 0 1 1-4 0zM12 9v7m0 1h.01"/>',
}


@lru_cache(maxsize=100)
def _icon(name, color):
    markup = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
              f'fill="none" color="{color}" stroke="{color}" stroke-width="1.8" '
              f'stroke-linecap="round" stroke-linejoin="round">{GLYPHS[name]}</svg>')
    return QSvgRenderer(markup.encode('utf-8'))


def icon(painter, name, x, y, size, color):
    _icon(name, color).render(painter, QRectF(x - size / 2, y - size / 2, size, size))
