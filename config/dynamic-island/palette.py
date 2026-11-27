"""Shared Island palette, loaded from the selected local bar profile."""
import json
from pathlib import Path
import sys
from theme_tokens import normalize_palette,on_accent,track_color

ROOT = Path(__file__).resolve().parent.parent
NAMES = ('CRUST', 'MANTLE', 'BASE', 'SURFACE', 'SURFACE2', 'OVERLAY', 'MUTED',
         'TEXT', 'LAVENDER', 'MAUVE', 'PINK', 'ROSEWATER')
DEFAULT = dict(zip(NAMES, ('#11111b', '#181825', '#1e1e2e', '#313244', '#45475a', '#6c7086',
                           '#a6adc8', '#cdd6f4', '#b4befe', '#cba6f7', '#f5c2e7', '#f5e0dc')))
THEME = 'catppuccin'


def load_theme(name):
    global THEME
    try:
        # Only manifest IDs reach a path; unknown and legacy values are rejected.
        from theme_catalog import load_catalog
        data = json.loads((load_catalog(ROOT).profile_dir(name) / 'palette.json').read_text(encoding='utf-8'))
        if not all(isinstance(data.get(key), str) and len(data[key]) == 7
                   and data[key][0] == '#' and int(data[key][1:], 16) >= 0 for key in NAMES):
            return False
    except (OSError, ValueError, TypeError):
        return False
    try:
        overrides = json.loads((ROOT / 'bar-settings.json').read_text(encoding='utf-8')).get('palette', {})
        data.update({key: value for key, value in overrides.items() if key in NAMES
                     and isinstance(value, str) and len(value) == 7 and value.startswith('#')})
    except (OSError, ValueError, TypeError):
        pass
    data = normalize_palette(data)
    for key in NAMES:
        globals()[key] = data[key]
    THEME = name
    # Update the names imported by the live painter modules. No worker restarts.
    for module_name in ('audio_mixer', 'dashboard', 'live_activity', 'player', 'tab_views', 'island', '__main__'):
        module = sys.modules.get(module_name)
        if module is not None:
            for key in NAMES:
                if key in vars(module):
                    setattr(module, key, data[key])
    dashboard = sys.modules.get('dashboard')
    if dashboard is not None and hasattr(dashboard, 'RESOURCES'):
        dashboard.RESOURCES = (('CPU', 'cpu', data['MAUVE']), ('RAM', 'ram', data['LAVENDER']), ('Ổ đĩa', 'disk', data['PINK']))
    player = sys.modules.get('player')
    if player is not None:
        player.INK = data['TEXT']
    return True


globals().update(DEFAULT)
try:
    selected = json.loads((ROOT / 'theme.json').read_text(encoding='utf-8'))['name']
    load_theme(selected)
except (OSError, ValueError, KeyError, TypeError):
    pass
