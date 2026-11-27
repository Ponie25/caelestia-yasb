"""Read-only, validated theme catalog shared by the YASB process and Island.

One manifest (theme-catalog/manifest.json) is the only list of selectable preset
IDs. Every consumer validates an ID here before it builds a profile path.
`wallpaper` is a legacy state value and is never a catalog member.
"""
import json
import re
from pathlib import Path

LEGACY_WALLPAPER = 'wallpaper'
LOCAL_IDS = ('light', 'dark', 'catppuccin', 'everforest', 'red-white', 'red-black')
DEFAULT_IDS = {'light': 'caelestia-caelestia-default-light', 'dark': 'caelestia-caelestia-default-dark'}
ROLES = ('CRUST', 'MANTLE', 'BASE', 'SURFACE', 'SURFACE2', 'OVERLAY', 'MUTED', 'TEXT',
         'LAVENDER', 'MAUVE', 'PINK', 'ROSEWATER')
EXPECTED = {'total': 35, 'caelestia': 29, 'yasb': 6, 'caelestia_light': 7, 'caelestia_dark': 22}
_ID = re.compile(r'[a-z][a-z0-9-]{1,63}')
_COLOR = re.compile(r'#[0-9a-f]{6}')
_CACHE = {}


class CatalogError(ValueError):
    pass


class Catalog:
    legacy = LEGACY_WALLPAPER  # retired value: accepted only as migration input, never a member

    def __init__(self, root, entries):
        self.root = Path(root)
        self.entries = tuple(entries)
        self._by_id = {entry['id']: entry for entry in self.entries}

    def __contains__(self, name):
        return isinstance(name, str) and name in self._by_id

    def __iter__(self):
        return iter(self.entries)

    def __len__(self):
        return len(self.entries)

    @property
    def ids(self):
        return tuple(self._by_id)

    def get(self, name):
        return self._by_id.get(name) if isinstance(name, str) else None

    def originals(self, tone=None):
        return [e for e in self.entries if e['origin'] == 'caelestia' and (tone is None or e['tone'] == tone)]

    def label(self, name):
        entry = self.get(name)
        return entry['name'] if entry else ''

    def tone(self, name):
        entry = self.get(name)
        return entry['tone'] if entry else None

    def default_for_tone(self, tone):
        return DEFAULT_IDS['light' if tone == 'light' else 'dark']

    def profile_dir(self, name):
        """Path of a validated profile; raises for any ID outside the manifest."""
        if name not in self:
            raise CatalogError('Unknown theme preset.')
        return self.root / 'theme-profiles' / name

    def palette(self, name):
        data = json.loads((self.profile_dir(name) / 'palette.json').read_text(encoding='utf-8'))
        _check_palette(data)
        return data

    def styles(self, name):
        return (self.profile_dir(name) / 'styles.css').read_text(encoding='utf-8')


def _check_palette(data):
    if not isinstance(data, dict) or any(not isinstance(data.get(r), str) or not _COLOR.fullmatch(data[r].lower()) for r in ROLES):
        raise CatalogError('Invalid theme palette.')


def _check_entry(entry, root, seen):
    if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not _ID.fullmatch(entry['id']):
        raise CatalogError('Invalid preset id.')
    name = entry['id']
    if name in seen or name == LEGACY_WALLPAPER:
        raise CatalogError('Duplicate or reserved preset id.')
    if entry.get('origin') not in ('yasb', 'caelestia') or entry.get('tone') not in ('light', 'dark'):
        raise CatalogError('Invalid preset metadata.')
    for key in ('name', 'family', 'family_name'):
        if not isinstance(entry.get(key), str) or not entry[key] or len(entry[key]) > 80:
            raise CatalogError('Invalid preset metadata.')
    swatch = entry.get('swatch')
    if not isinstance(swatch, dict) or any(not _COLOR.fullmatch(str(swatch.get(k, '')).lower()) for k in ('surface', 'accent')):
        raise CatalogError('Invalid preset swatch.')
    if (entry['origin'] == 'caelestia') != isinstance(entry.get('source'), dict):
        raise CatalogError('Invalid preset provenance.')
    folder = (root / 'theme-profiles' / name).resolve()
    if not folder.is_relative_to((root / 'theme-profiles').resolve()) or not all((folder / f).is_file() for f in ('palette.json', 'styles.css')):
        raise CatalogError('Missing preset files.')


def load_catalog(root):
    """Load and validate the manifest for a config root; cached until the file changes."""
    root = Path(root)
    path = root / 'theme-catalog' / 'manifest.json'
    stat = path.stat()
    key = (str(root.resolve()), stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(key[0])
    if cached and cached[0] == key:
        return cached[1]
    if stat.st_size > 400_000:
        raise CatalogError('Theme manifest is too large.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('presets'), list):
        raise CatalogError('Invalid theme manifest.')
    seen, entries = set(), []
    for entry in data['presets']:
        _check_entry(entry, root, seen)
        seen.add(entry['id'])
        entries.append(entry)
    originals = [e for e in entries if e['origin'] == 'caelestia']
    counts = {'total': len(entries), 'caelestia': len(originals), 'yasb': len(entries) - len(originals),
              'caelestia_light': sum(e['tone'] == 'light' for e in originals),
              'caelestia_dark': sum(e['tone'] == 'dark' for e in originals)}
    if counts != EXPECTED or [e['id'] for e in entries if e['origin'] == 'yasb'] != list(LOCAL_IDS):
        raise CatalogError('Theme catalog inventory does not match the supported release.')
    if any(name not in seen for name in DEFAULT_IDS.values()):
        raise CatalogError('Missing Caelestia Default presets.')
    catalog = Catalog(root, entries)
    _CACHE[key[0]] = (key, catalog)
    return catalog


def is_known(root, name):
    try:
        return name in load_catalog(root)
    except (OSError, ValueError):
        return False
