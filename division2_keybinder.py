#!/usr/bin/env python3
"""
Division 2 Keybinder — a GTK keybinding editor for Tom Clancy's The Division 2
running through Steam / Proton on Linux Mint.

The game keeps its key bindings in a Lua-like text file called `user.bindings`
inside the Proton prefix:

  <SteamLibrary>/steamapps/compatdata/2221490/pfx/drive_c/users/steamuser/
      Documents/My Games/Tom Clancy's The Division 2/user.bindings

Each binding is a block like:

  {
    myIndex = 0,
    myKeyCombo = 17,
    myKeyComboAlt = 0,
    myName = "KB_UI_F",
  },

myKeyCombo / myKeyComboAlt are DirectInput scan codes (17 = W, 33 = F ...),
mouse inputs live at 65536 and up. This tool edits only those numbers in place,
so the rest of the file is left exactly as the game wrote it.
"""

import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

APP_NAME = "Division 2 Keybinder"
APP_VERSION = "1.0"
STEAM_APP_ID = "2221490"
BINDINGS_FILENAME = "user.bindings"
CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "division2-keybinder",
)
PROFILE_DIR = os.path.join(CONFIG_DIR, "profiles")
BACKUP_DIR = os.path.join(CONFIG_DIR, "backups")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
LABELS_FILE = os.path.join(CONFIG_DIR, "labels.json")
MAX_BACKUPS = 50


# ---------------------------------------------------------------------------
# Key codes
# ---------------------------------------------------------------------------

# DirectInput scan codes (DIK_*) with US-layout names.
DIK_NAMES = {
    1: "Esc", 2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8",
    10: "9", 11: "0", 12: "-", 13: "=", 14: "Backspace", 15: "Tab",
    16: "Q", 17: "W", 18: "E", 19: "R", 20: "T", 21: "Y", 22: "U", 23: "I",
    24: "O", 25: "P", 26: "[", 27: "]", 28: "Enter", 29: "Left Ctrl",
    30: "A", 31: "S", 32: "D", 33: "F", 34: "G", 35: "H", 36: "J", 37: "K",
    38: "L", 39: ";", 40: "'", 41: "`", 42: "Left Shift", 43: "\\",
    44: "Z", 45: "X", 46: "C", 47: "V", 48: "B", 49: "N", 50: "M", 51: ",",
    52: ".", 53: "/", 54: "Right Shift", 55: "Numpad *", 56: "Left Alt",
    57: "Space", 58: "Caps Lock", 59: "F1", 60: "F2", 61: "F3", 62: "F4",
    63: "F5", 64: "F6", 65: "F7", 66: "F8", 67: "F9", 68: "F10",
    69: "Num Lock", 70: "Scroll Lock", 71: "Numpad 7", 72: "Numpad 8",
    73: "Numpad 9", 74: "Numpad -", 75: "Numpad 4", 76: "Numpad 5",
    77: "Numpad 6", 78: "Numpad +", 79: "Numpad 1", 80: "Numpad 2",
    81: "Numpad 3", 82: "Numpad 0", 83: "Numpad .", 86: "< > (ISO key)",
    87: "F11", 88: "F12",
    156: "Numpad Enter", 157: "Right Ctrl", 181: "Numpad /",
    183: "Print Screen", 184: "Right Alt / AltGr", 197: "Pause",
    199: "Home", 200: "Up", 201: "Page Up", 203: "Left", 205: "Right",
    207: "End", 208: "Down", 209: "Page Down", 210: "Insert", 211: "Delete",
    219: "Left Super", 220: "Right Super", 221: "Menu",
}

# Linux evdev keycodes 1..88 are identical to DIK codes. Extended keys differ.
EVDEV_TO_DIK_EXTENDED = {
    96: 156, 97: 157, 98: 181, 99: 183, 100: 184, 102: 199, 103: 200,
    104: 201, 105: 203, 106: 205, 107: 207, 108: 208, 109: 209, 110: 210,
    111: 211, 119: 197, 125: 219, 126: 220, 127: 221,
}
DIK_TO_EVDEV = {v: k for k, v in EVDEV_TO_DIK_EXTENDED.items()}

MOUSE_BASE = 65536
# 65540 (Mouse 4), wheel up 65547 and wheel down 98315 are confirmed by the
# community; the others follow the same numbering.
MOUSE_NAMES = {
    65536: "Mouse (code 65536)",
    65537: "Left Mouse",
    65538: "Right Mouse",
    65539: "Middle Mouse",
    65540: "Mouse 4 (side)",
    65541: "Mouse 5 (side)",
    65542: "Mouse 6",
    65543: "Mouse 7",
    65544: "Mouse 8",
    65547: "Wheel Up",
    98315: "Wheel Down",
}
# GTK button number -> game code
GTK_BUTTON_TO_CODE = {1: 65537, 3: 65538, 2: 65539, 8: 65540, 9: 65541}

# Physical keyboard grid used by "Move keys" (DIK codes, US/ISO main block).
KEY_GRID = [
    [41, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
    [15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27],
    [58, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 43],
    [42, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54],
]
# Visual column offset of each row so that "up/down" follows the real stagger
# (1 sits above Q, Q above A, A above Z).
KEY_GRID_OFFSET = [0, 0, 0, 0]


def _grid_pos(code):
    for r, row in enumerate(KEY_GRID):
        if code in row:
            return r, row.index(code)
    return None


def shift_code(code, direction):
    """Move a key code one step on the physical keyboard. Returns new code or None."""
    pos = _grid_pos(code)
    if pos is None:
        return None
    r, c = pos
    dr, dc = {"left": (0, -1), "right": (0, 1), "up": (-1, 0), "down": (1, 0)}[direction]
    r2, c2 = r + dr, c + dc
    if not (0 <= r2 < len(KEY_GRID)):
        return None
    row = KEY_GRID[r2]
    if not (0 <= c2 < len(row)):
        return None
    return row[c2]


class KeyNamer:
    """Turns game codes into readable names, using the user's real keyboard layout
    (so a Norwegian keyboard shows Ø/Æ/Å instead of ; ' [) where possible."""

    def __init__(self):
        self.cache = {}
        self.keymap = None
        try:
            display = Gdk.Display.get_default()
            if display is not None:
                self.keymap = Gdk.Keymap.get_for_display(display)
        except Exception:
            self.keymap = None

    def _layout_char(self, dik):
        if self.keymap is None:
            return None
        evdev = DIK_TO_EVDEV.get(dik, dik)
        if not (2 <= evdev <= 53 or evdev == 86):
            return None
        try:
            ok, _keys, keyvals = self.keymap.get_entries_for_keycode(evdev + 8)
        except Exception:
            return None
        if not ok or not keyvals:
            return None
        uni = Gdk.keyval_to_unicode(keyvals[0])
        if uni and chr(uni).isprintable() and not chr(uni).isspace():
            return chr(uni).upper()
        return None

    def name(self, code):
        if code in self.cache:
            return self.cache[code]
        if code == 0:
            result = ""
        elif code in MOUSE_NAMES:
            result = MOUSE_NAMES[code]
        elif code >= MOUSE_BASE:
            result = "Mouse/other (code %d)" % code
        else:
            us = DIK_NAMES.get(code)
            local = self._layout_char(code)
            if local and us and local != us.upper():
                result = local
            elif us:
                result = us
            elif local:
                result = local
            else:
                result = "Key code %d" % code
        self.cache[code] = result
        return result


# ---------------------------------------------------------------------------
# user.bindings parsing / writing
# ---------------------------------------------------------------------------

BLOCK_RE = re.compile(r"\{[^{}]*?\bmyName\s*=\s*\"([^\"]*)\"[^{}]*?\}", re.S)
FIELD_RE = re.compile(r"\b(myIndex|myKeyCombo|myKeyComboAlt)\s*=\s*(-?\d+)")


class Entry:
    def __init__(self, name, index, combo, alt, spans, block_span):
        self.name = name
        self.index = index
        self.combo = combo
        self.alt = alt  # None if the block has no myKeyComboAlt field
        self.spans = spans  # field -> (start, end) of the number in the text
        self.block_span = block_span

    @property
    def id(self):
        return "%s#%d" % (self.name, self.index)


class BindingsDoc:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            raw = f.read()
        self.text = raw.decode("utf-8", errors="surrogateescape")
        self.newline = "\r\n" if "\r\n" in self.text else "\n"
        self.entries = []
        self._parse()

    def _parse(self):
        self.entries = []
        seen = set()
        for m in BLOCK_RE.finditer(self.text):
            name = m.group(1)
            spans = {}
            values = {}
            for fm in FIELD_RE.finditer(m.group(0)):
                field = fm.group(1)
                if field in spans:
                    continue
                spans[field] = (m.start() + fm.start(2), m.start() + fm.end(2))
                values[field] = int(fm.group(2))
            if "myKeyCombo" not in spans:
                continue
            index = values.get("myIndex", 0)
            e = Entry(name, index, values["myKeyCombo"], values.get("myKeyComboAlt"),
                      spans, (m.start(), m.end()))
            if e.id in seen:  # extremely unlikely; keep the first one
                continue
            seen.add(e.id)
            self.entries.append(e)

    def values(self):
        return {e.id: [e.combo, e.alt] for e in self.entries}

    def render(self, values, new_entries=None):
        """Return the file text with new values substituted (and new entries added)."""
        edits = []
        for e in self.entries:
            combo, alt = values.get(e.id, [e.combo, e.alt])
            if combo != e.combo:
                edits.append((e.spans["myKeyCombo"], str(int(combo))))
            if alt is not None and "myKeyComboAlt" in e.spans and alt != e.alt:
                edits.append((e.spans["myKeyComboAlt"], str(int(alt))))
        text = self.text
        for (s, t), rep in sorted(edits, key=lambda x: x[0][0], reverse=True):
            text = text[:s] + rep + text[t:]

        if new_entries:
            if not self.entries:
                raise ValueError("Cannot add entries: no existing binding block to follow.")
            # Offsets after the last block are shifted by edits made before it.
            last = self.entries[-1]
            shift = 0
            for (s, t), rep in edits:
                if s < last.block_span[1]:
                    shift += len(rep) - (t - s)
            end = last.block_span[1] + shift
            line_start = text.rfind("\n", 0, last.block_span[0] + shift) + 1
            indent = re.match(r"[ \t]*", text[line_start:]).group(0)
            inner = indent + "  "
            nl = self.newline
            insert_at = end
            prefix = ","
            m = re.match(r"\s*,", text[end:])
            if m:
                insert_at = end + m.end()
                prefix = ""
            chunks = []
            for name, combo, alt in new_entries:
                chunks.append(
                    "%s{%s%smyIndex = 0,%s%smyKeyCombo = %d,%s%smyKeyComboAlt = %d,%s"
                    "%smyName = \"%s\",%s%s}," % (
                        nl + indent, nl, inner, nl, inner, combo, nl, inner, alt, nl,
                        inner, name, nl, indent))
            block = prefix + "".join(chunks)
            if block.endswith(","):
                block = block[:-1]
                # keep a trailing comma only if the original had one after the last block
                if not prefix:
                    block += ","
            text = text[:insert_at] + block + text[insert_at:]
        return text


def write_atomic(path, text):
    """Write text to path, keeping permissions; temporarily lifts read-only."""
    st = os.stat(path)
    was_readonly = not (st.st_mode & stat.S_IWUSR)
    if was_readonly:
        os.chmod(path, st.st_mode | stat.S_IWUSR)
    tmp = path + ".kbtmp"
    with open(tmp, "wb") as f:
        f.write(text.encode("utf-8", errors="surrogateescape"))
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)
    os.replace(tmp, path)


def set_readonly(path, readonly):
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if readonly:
        mode &= ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    else:
        mode |= stat.S_IWUSR
    os.chmod(path, mode)


def is_readonly(path):
    try:
        return not (os.stat(path).st_mode & stat.S_IWUSR)
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Locating the file
# ---------------------------------------------------------------------------

def steam_roots():
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".steam", "root"),
        os.path.join(home, ".local", "share", "Steam"),
        os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
        os.path.join(home, ".var", "app", "com.valvesoftware.Steam", "data", "Steam"),
        os.path.join(home, "snap", "steam", "common", ".local", "share", "Steam"),
    ]
    return [c for c in candidates if os.path.isdir(c)]


def steam_libraries():
    libs = []
    for root in steam_roots():
        libs.append(root)
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                for p in re.findall(r'"path"\s+"([^"]+)"', f.read()):
                    libs.append(p.replace("\\\\", "\\"))
        except OSError:
            pass
    out, seen = [], set()
    for lib in libs:
        try:
            real = os.path.realpath(lib)
        except OSError:
            continue
        if real not in seen and os.path.isdir(real):
            seen.add(real)
            out.append(real)
    return out


def find_bindings_files():
    found, seen = [], set()
    tail = os.path.join("pfx", "drive_c", "users", "steamuser", "Documents", "My Games")
    for lib in steam_libraries():
        compat = os.path.join(lib, "steamapps", "compatdata")
        # Only the Steam version's own Proton folder (app id 2221490) is searched.
        # Other games' folders are never looked at.
        for prefix in [os.path.join(compat, STEAM_APP_ID)]:
            pattern = os.path.join(prefix, tail, "*Division 2*", BINDINGS_FILENAME)
            for path in glob.glob(pattern):
                real = os.path.realpath(path)
                if real not in seen:
                    seen.add(real)
                    found.append(path)
    return found


def game_is_running():
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            # Only the short process name (max 15 chars) is read - never the
            # command line, which for other programs could contain private data.
            try:
                with open("/proc/%s/comm" % pid, "rb") as f:
                    comm = f.read().strip().lower()
            except OSError:
                continue
            if comm.startswith(b"thedivision2"):
                return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------
# Settings, labels, profiles, backups
# ---------------------------------------------------------------------------

def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def safe_filename(name):
    s = re.sub(r"[^\w\-. ]+", "_", name, flags=re.UNICODE).strip()
    return s or "profile"


def list_profiles():
    out = []
    for p in sorted(glob.glob(os.path.join(PROFILE_DIR, "*.json"))):
        data = _load_json(p, None)
        if isinstance(data, dict) and isinstance(data.get("bindings"), dict):
            out.append((data.get("name") or os.path.basename(p)[:-5], p, data))
    return out


def clean_bindings(bindings):
    """Keep only well-formed entries: 'NAME#n' -> [int, int|None]. Anything else is dropped."""
    out = {}
    if not isinstance(bindings, dict):
        return out
    for eid, val in list(bindings.items())[:2000]:
        if not (isinstance(eid, str) and re.match(r"^[A-Za-z0-9_]{1,80}#\d{1,3}$", eid)):
            continue
        if not (isinstance(val, list) and len(val) == 2):
            continue
        try:
            combo = int(val[0] or 0)
            alt = None if val[1] is None else int(val[1])
        except (TypeError, ValueError):
            continue
        if not (0 <= combo < 2 ** 31) or (alt is not None and not (0 <= alt < 2 ** 31)):
            continue
        out[eid] = [combo, alt]
    return out


def save_profile(name, values, note=""):
    data = {
        "name": name,
        "game": "Tom Clancy's The Division 2",
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "note": note,
        "bindings": clean_bindings(values),
    }
    path = os.path.join(PROFILE_DIR, safe_filename(name) + ".json")
    _save_json(path, data)
    return path


def scrub_old_profiles():
    """Older versions stored the bindings file's full path (which contains your
    user name) inside the automatic "Original layout" profile. Remove it."""
    for p in glob.glob(os.path.join(PROFILE_DIR, "*.json")):
        data = _load_json(p, None)
        if isinstance(data, dict) and "/" in str(data.get("note", "")):
            data["note"] = "Automatic snapshot taken the first time this file was opened."
            try:
                _save_json(p, data)
            except OSError:
                pass


def file_key(path):
    return hashlib.sha1(os.path.realpath(path).encode()).hexdigest()[:10]


def backup_file(path):
    folder = os.path.join(BACKUP_DIR, file_key(path))
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest = os.path.join(folder, "user.bindings.%s" % stamp)
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(folder, "user.bindings.%s-%d" % (stamp, n))
    shutil.copy2(path, dest)
    os.chmod(dest, stat.S_IMODE(os.stat(dest).st_mode) | stat.S_IWUSR)
    backups = sorted(glob.glob(os.path.join(folder, "user.bindings.*")))
    for old in backups[:-MAX_BACKUPS]:
        try:
            os.remove(old)
        except OSError:
            pass
    return dest


def list_backups(path):
    folder = os.path.join(BACKUP_DIR, file_key(path))
    return sorted(glob.glob(os.path.join(folder, "user.bindings.*")), reverse=True)


# ---------------------------------------------------------------------------
# Friendly names
# ---------------------------------------------------------------------------

def category_of(name):
    if name.startswith("KB_UI_") or name.startswith("UI_"):
        return "Menus / UI"
    if name.startswith("KB_"):
        return "Gameplay"
    return "Other"


def pretty_name(name):
    s = name
    for p in ("KB_UI_", "KB_"):
        if s.startswith(p):
            s = s[len(p):]
            break
    words = [w for w in s.split("_") if w]
    if not words:
        return name
    pretty = " ".join(w.capitalize() if not w.isdigit() else w for w in words)
    if name.startswith("KB_UI_") and len(words) == 1 and len(words[0]) <= 3:
        pretty = "UI key \"%s\"" % words[0]
    return pretty


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

COL_ID, COL_LABEL, COL_CATEGORY, COL_PRIMARY, COL_ALT, COL_NAME, COL_WARN, \
    COL_WARN_TIP, COL_CHANGED, COL_WEIGHT = range(10)

CSS = b"""
.kb-hint { opacity: 0.75; }
.kb-capture {
    border: 2px dashed @theme_selected_bg_color;
    border-radius: 10px;
    padding: 24px;
}
.kb-big { font-size: 20px; font-weight: bold; }
"""


class CaptureDialog(Gtk.Dialog):
    """Waits for a key press, mouse click or wheel scroll and returns the game code."""

    RESP_CLEAR = 1
    RESP_MANUAL = 2

    def __init__(self, parent, action_label, slot_label, current_name):
        super().__init__(title="Bind key", transient_for=parent, modal=True)
        self.set_default_size(460, 260)
        self.result_code = None
        self.add_button("Unbind", self.RESP_CLEAR)
        self.add_button("Enter code…", self.RESP_MANUAL)
        close = self.add_button("Close", Gtk.ResponseType.CANCEL)
        close.set_image(Gtk.Image.new_from_icon_name("window-close", Gtk.IconSize.BUTTON))
        close.set_always_show_image(True)
        close.set_tooltip_text("Close this window without changing the key (Esc)")

        box = self.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)

        title = Gtk.Label(xalign=0)
        title.set_markup("<b>%s</b> — %s" % (GLib.markup_escape_text(action_label), slot_label))
        box.pack_start(title, False, False, 0)
        cur = Gtk.Label(label="Currently: %s" % (current_name or "not bound"), xalign=0)
        cur.get_style_context().add_class("kb-hint")
        box.pack_start(cur, False, False, 0)

        self.area = Gtk.EventBox()
        self.area.set_can_focus(True)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK
                             | Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.get_style_context().add_class("kb-capture")
        big = Gtk.Label(label="Press a key, click a mouse button\nor scroll the wheel here")
        big.set_justify(Gtk.Justification.CENTER)
        big.get_style_context().add_class("kb-big")
        small = Gtk.Label(label="Esc or Close leaves without changing anything. To bind Esc itself, use Enter code… and type 1.")
        small.get_style_context().add_class("kb-hint")
        inner.pack_start(big, True, True, 0)
        inner.pack_start(small, False, False, 0)
        self.area.add(inner)
        box.pack_start(self.area, True, True, 0)

        self.area.connect("button-press-event", self._on_button)
        self.area.connect("scroll-event", self._on_scroll)
        self.connect("key-press-event", self._on_key)
        self.show_all()
        self.area.grab_focus()

    def _finish(self, code):
        self.result_code = code
        self.response(Gtk.ResponseType.OK)

    def _on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        evdev = event.hardware_keycode - 8
        code = EVDEV_TO_DIK_EXTENDED.get(evdev, evdev)
        if 1 <= code <= 255:
            self._finish(code)
        return True  # swallow everything else (Enter, Tab ...)

    def _on_button(self, _w, event):
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return True
        code = GTK_BUTTON_TO_CODE.get(event.button)
        if code:
            self._finish(code)
        return True

    def _on_scroll(self, _w, event):
        direction = event.direction
        if direction == Gdk.ScrollDirection.SMOOTH:
            ok, _dx, dy = event.get_scroll_deltas()
            if not ok or dy == 0:
                return True
            direction = Gdk.ScrollDirection.UP if dy < 0 else Gdk.ScrollDirection.DOWN
        if direction == Gdk.ScrollDirection.UP:
            self._finish(65547)
        elif direction == Gdk.ScrollDirection.DOWN:
            self._finish(98315)
        return True


def ask_number(parent, title, text, value=0):
    dlg = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
    dlg.add_button("OK", Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)
    box = dlg.get_content_area()
    box.set_spacing(8)
    box.set_border_width(12)
    lbl = Gtk.Label(label=text, xalign=0)
    lbl.set_line_wrap(True)
    box.pack_start(lbl, False, False, 0)
    spin = Gtk.SpinButton.new_with_range(0, 999999, 1)
    spin.set_value(value)
    spin.set_activates_default(True)
    box.pack_start(spin, False, False, 0)
    dlg.show_all()
    resp = dlg.run()
    val = int(spin.get_value())
    dlg.destroy()
    return val if resp == Gtk.ResponseType.OK else None


def ask_text(parent, title, text, value=""):
    dlg = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
    dlg.add_button("OK", Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)
    box = dlg.get_content_area()
    box.set_spacing(8)
    box.set_border_width(12)
    lbl = Gtk.Label(label=text, xalign=0)
    lbl.set_line_wrap(True)
    box.pack_start(lbl, False, False, 0)
    entry = Gtk.Entry(text=value)
    entry.set_activates_default(True)
    box.pack_start(entry, False, False, 0)
    dlg.show_all()
    resp = dlg.run()
    val = entry.get_text().strip()
    dlg.destroy()
    return val if resp == Gtk.ResponseType.OK and val else None


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(1000, 680)
        self.set_icon_name("input-keyboard")

        self.settings = _load_json(SETTINGS_FILE, {})
        self.labels = _load_json(LABELS_FILE, {})
        self.namer = KeyNamer()
        self.doc = None
        self.values = {}        # id -> [combo, alt]
        self.disk_values = {}   # values currently on disk
        self.new_entries = []   # (name, combo, alt) to be added on save
        self.history = []
        self.entry_by_id = {}

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._build_header()
        self._build_body()
        self.connect("delete-event", self._on_delete)

        GLib.timeout_add_seconds(3, self._poll_game)
        GLib.idle_add(lambda: self._initial_open(startup=True))

    # ----- layout -------------------------------------------------------

    def _build_header(self):
        # A normal toolbar under Mint's own window title bar, so the window always
        # has the usual minimise / maximise / close buttons.
        bar = Gtk.Box(spacing=6)
        bar.set_border_width(8)
        self.topbar = bar

        open_btn = Gtk.Button.new_with_label("Open…")
        open_btn.set_image(Gtk.Image.new_from_icon_name("document-open", Gtk.IconSize.BUTTON))
        open_btn.set_always_show_image(True)
        open_btn.set_tooltip_text("Find or open a user.bindings file (Ctrl+O)")
        open_btn.connect("clicked", lambda *_: self.choose_file())
        bar.pack_start(open_btn, False, False, 0)

        self.undo_btn = Gtk.Button.new_with_label("Undo")
        self.undo_btn.set_image(Gtk.Image.new_from_icon_name("edit-undo", Gtk.IconSize.BUTTON))
        self.undo_btn.set_always_show_image(True)
        self.undo_btn.set_tooltip_text("Undo last change (Ctrl+Z)")
        self.undo_btn.connect("clicked", lambda *_: self.undo())
        bar.pack_start(self.undo_btn, False, False, 0)

        prof_btn = Gtk.Button.new_with_label("Switch profile…")
        prof_btn.set_image(Gtk.Image.new_from_icon_name("view-list", Gtk.IconSize.BUTTON))
        prof_btn.set_always_show_image(True)
        prof_btn.set_tooltip_text("Choose another saved key layout (Ctrl+P)")
        prof_btn.connect("clicked", lambda *_: self.switch_profile_dialog())
        bar.pack_start(prof_btn, False, False, 0)
        self.prof_btn = prof_btn

        quit_btn = Gtk.Button.new_with_label("Close")
        quit_btn.set_image(Gtk.Image.new_from_icon_name("application-exit", Gtk.IconSize.BUTTON))
        quit_btn.set_always_show_image(True)
        quit_btn.set_tooltip_text("Close the keybinder (Ctrl+Q)")
        quit_btn.connect("clicked", lambda *_: self.quit())
        bar.pack_end(quit_btn, False, False, 0)

        menu_btn = Gtk.MenuButton(label="More")
        menu_btn.set_tooltip_text("Profiles, backups and more")
        menu_btn.set_popover(self._build_menu())
        bar.pack_end(menu_btn, False, False, 0)

        self.save_btn = Gtk.Button.new_with_label("Save")
        self.save_btn.set_image(Gtk.Image.new_from_icon_name("document-save", Gtk.IconSize.BUTTON))
        self.save_btn.set_always_show_image(True)
        self.save_btn.get_style_context().add_class("suggested-action")
        self.save_btn.set_tooltip_text("Write changes to user.bindings (Ctrl+S). A backup is made first.")
        self.save_btn.connect("clicked", lambda *_: self.save())
        bar.pack_end(self.save_btn, False, False, 0)

        # Shortcuts are handled on the window itself so they work no matter which
        # widget has focus (search box, list, ...).
        self.connect("key-press-event", self._on_window_key)

    def _on_window_key(self, _w, event):
        if not (event.state & Gdk.ModifierType.CONTROL_MASK):
            return False
        key = Gdk.keyval_to_lower(event.keyval)
        if key == Gdk.KEY_s:
            self.save()
        elif key == Gdk.KEY_z:
            self.undo()
        elif key == Gdk.KEY_o:
            self.choose_file()
        elif key in (Gdk.KEY_q, Gdk.KEY_w):
            self.quit()
        elif key == Gdk.KEY_f:
            self.search.grab_focus()
        elif key == Gdk.KEY_p:
            self.switch_profile_dialog()
        else:
            return False
        return True

    def quit(self):
        if self._confirm_discard():
            self.destroy()

    def _update_title(self):
        title = APP_NAME
        if self.doc:
            title = ("* " if self.is_dirty() else "") + APP_NAME + " — " + \
                os.path.basename(os.path.dirname(self.doc.path))
        self.set_title(title)

    def _build_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_border_width(8)

        def item(label, cb):
            b = Gtk.ModelButton(text=label)
            b.get_child().set_halign(Gtk.Align.START) if b.get_child() else None
            b.connect("clicked", lambda *_: cb())
            box.pack_start(b, False, False, 0)

        def sep():
            box.pack_start(Gtk.Separator(), False, False, 4)

        item("Switch profile…", self.switch_profile_dialog)
        item("Save current layout as profile…", self.save_profile_dialog)
        item("Profiles (load / import / export)…", self.profiles_dialog)
        sep()
        item("Restore a backup…", self.backups_dialog)
        item("Revert unsaved changes", self.revert)
        item("Reset to game defaults…", self.reset_to_defaults)
        sep()
        self.protect_check = Gtk.CheckButton(label="Protect file (read-only) after saving")
        self.protect_check.set_tooltip_text(
            "Stops the game, Ubisoft Connect or cloud sync from overwriting your bindings.\n"
            "While protected, key changes made inside the game will not be kept.")
        self.protect_check.set_active(bool(self.settings.get("protect", False)))
        self.protect_check.connect("toggled", self._on_protect_toggled)
        box.pack_start(self.protect_check, False, False, 4)
        sep()
        item("Open file location", self.open_location)
        item("Launch The Division 2 (Steam)", self.launch_game)
        item("Help", self.show_help)
        sep()
        item("Close keybinder", self.quit)
        box.show_all()
        pop.add(box)
        return pop

    def _build_body(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        outer.pack_start(self.topbar, False, False, 0)
        outer.pack_start(Gtk.Separator(), False, False, 0)

        self.infobar = Gtk.InfoBar()
        self.infobar.set_message_type(Gtk.MessageType.WARNING)
        self.info_label = Gtk.Label(xalign=0)
        self.info_label.set_line_wrap(True)
        self.infobar.get_content_area().add(self.info_label)
        self.infobar.set_no_show_all(True)
        outer.pack_start(self.infobar, False, False, 0)

        self.stack = Gtk.Stack()
        outer.pack_start(self.stack, True, True, 0)

        # --- welcome page
        welcome = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        welcome.set_valign(Gtk.Align.CENTER)
        welcome.set_halign(Gtk.Align.CENTER)
        img = Gtk.Image.new_from_icon_name("input-keyboard", Gtk.IconSize.DIALOG)
        img.set_pixel_size(96)
        welcome.pack_start(img, False, False, 0)
        self.welcome_label = Gtk.Label()
        self.welcome_label.set_justify(Gtk.Justification.CENTER)
        self.welcome_label.set_line_wrap(True)
        self.welcome_label.set_max_width_chars(70)
        welcome.pack_start(self.welcome_label, False, False, 0)
        wb = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        b1 = Gtk.Button(label="Search again")
        b1.connect("clicked", lambda *_: self._initial_open())
        b2 = Gtk.Button(label="Browse for user.bindings…")
        b2.get_style_context().add_class("suggested-action")
        b2.connect("clicked", lambda *_: self.browse_file())
        wb.pack_start(b1, False, False, 0)
        wb.pack_start(b2, False, False, 0)
        welcome.pack_start(wb, False, False, 0)
        self.stack.add_named(welcome, "welcome")

        # --- editor page
        editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        editor.set_border_width(10)

        tools = Gtk.Box(spacing=6)
        self.search = Gtk.SearchEntry(placeholder_text="Search actions or keys…")
        self.search.set_width_chars(26)
        self.search.connect("search-changed", lambda *_: self.filter.refilter())
        tools.pack_start(self.search, False, False, 0)

        self.cat_combo = Gtk.ComboBoxText()
        for c in ("All categories", "Gameplay", "Menus / UI", "Other"):
            self.cat_combo.append_text(c)
        self.cat_combo.set_active(0)
        self.cat_combo.connect("changed", lambda *_: self.filter.refilter())
        tools.pack_start(self.cat_combo, False, False, 0)

        self.conflict_toggle = Gtk.CheckButton(label="Only conflicts")
        self.conflict_toggle.connect("toggled", lambda *_: self.filter.refilter())
        tools.pack_start(self.conflict_toggle, False, False, 0)

        self.changed_toggle = Gtk.CheckButton(label="Only changed")
        self.changed_toggle.connect("toggled", lambda *_: self.filter.refilter())
        tools.pack_start(self.changed_toggle, False, False, 0)

        editor.pack_start(tools, False, False, 0)
        actions = Gtk.Box(spacing=6)

        def tbtn(label, tip, cb):
            b = Gtk.Button(label=label)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda *_: cb())
            actions.pack_end(b, False, False, 0)
            return b

        self.add_btn = tbtn("Add binding…", "Add a binding entry that is missing from the file "
                            "(e.g. KB_UI_R)", self.add_entry_dialog)
        self.move_btn = tbtn("Move keys…", "Shift the keys of the selected actions on the keyboard, "
                             "e.g. move WASD one step right to ESDF", self.move_keys_dialog)
        self.swap_btn = tbtn("Swap", "Swap the keys of the two selected actions", self.swap_selected)
        self.alt_btn = tbtn("Change alternate…", "Rebind the alternate key of the selected action",
                            lambda: self.rebind_selected(1))
        self.pri_btn = tbtn("Change primary…", "Rebind the primary key of the selected action",
                            lambda: self.rebind_selected(0))
        editor.pack_start(actions, False, False, 0)

        # model: id, label, category, primary, alt, internal, warn icon, tooltip, changed, weight
        self.store = Gtk.ListStore(str, str, str, str, str, str, str, str, bool, int)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        self.sorted = Gtk.TreeModelSort(model=self.filter)
        self.sorted.set_sort_column_id(COL_LABEL, Gtk.SortType.ASCENDING)

        tv = Gtk.TreeView(model=self.sorted)
        tv.set_tooltip_column(COL_WARN_TIP)
        tv.set_enable_search(False)
        tv.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        tv.get_selection().connect("changed", lambda *_: self._update_buttons())
        tv.connect("row-activated", self._on_row_activated)
        tv.connect("button-press-event", self._on_tree_button)
        self.tree = tv

        warn_r = Gtk.CellRendererPixbuf()
        col = Gtk.TreeViewColumn("", warn_r, icon_name=COL_WARN)
        col.set_min_width(28)
        tv.append_column(col)

        label_r = Gtk.CellRendererText(editable=True)
        label_r.connect("edited", self._on_label_edited)
        label_r.set_property("ellipsize", Pango.EllipsizeMode.END)
        col = Gtk.TreeViewColumn("Action  (click name to rename)", label_r, text=COL_LABEL, weight=COL_WEIGHT)
        col.set_sort_column_id(COL_LABEL)
        col.set_resizable(True)
        col.set_expand(True)
        col.set_min_width(220)
        tv.append_column(col)

        r = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn("Category", r, text=COL_CATEGORY)
        col.set_sort_column_id(COL_CATEGORY)
        col.set_resizable(True)
        tv.append_column(col)

        for title, idx in (("Primary key", COL_PRIMARY), ("Alternate key", COL_ALT)):
            r = Gtk.CellRendererText()
            r.set_property("weight", 700)
            col = Gtk.TreeViewColumn(title, r, text=idx)
            col.set_sort_column_id(idx)
            col.set_resizable(True)
            col.set_min_width(150)
            tv.append_column(col)
            if idx == COL_PRIMARY:
                self.col_primary = col
            else:
                self.col_alt = col

        r = Gtk.CellRendererText()
        r.set_property("foreground-rgba", Gdk.RGBA(0.5, 0.5, 0.5, 1))
        col = Gtk.TreeViewColumn("Internal name", r, text=COL_NAME)
        col.set_sort_column_id(COL_NAME)
        col.set_resizable(True)
        tv.append_column(col)

        sw = Gtk.ScrolledWindow()
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(tv)
        editor.pack_start(sw, True, True, 0)

        hint = Gtk.Label(xalign=0)
        hint.set_markup("Double-click a <b>Primary</b> or <b>Alternate</b> cell to rebind it. "
                        "Select two rows and press <b>Swap</b>, or select several and use "
                        "<b>Move keys</b>. Changes are only written when you press <b>Save</b>.")
        hint.set_line_wrap(True)
        hint.set_max_width_chars(90)
        hint.get_style_context().add_class("kb-hint")
        editor.pack_start(hint, False, False, 0)

        bottom = Gtk.Box(spacing=8)
        self.status = Gtk.Label(xalign=0)
        self.status.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        bottom.pack_start(self.status, True, True, 0)
        close_btn = Gtk.Button.new_with_label("Close")
        close_btn.set_image(Gtk.Image.new_from_icon_name("window-close", Gtk.IconSize.BUTTON))
        close_btn.set_always_show_image(True)
        close_btn.set_tooltip_text("Close the keybinder (Ctrl+Q)")
        close_btn.connect("clicked", lambda *_: self.quit())
        bottom.pack_end(close_btn, False, False, 0)
        editor.pack_start(bottom, False, False, 0)
        self.stack.add_named(editor, "editor")

        outer.show_all()
        self.infobar.hide()

    # ----- file handling -------------------------------------------------

    def _initial_open(self, startup=False):
        last = self.settings.get("last_file")
        if isinstance(last, str) and os.path.basename(last) == BINDINGS_FILENAME \
                and os.path.isfile(last):
            self.load(last)
        else:
            files = find_bindings_files()
            if len(files) == 1:
                self.load(files[0])
            elif len(files) > 1:
                self.choose_file(files)
            else:
                self._show_welcome()
        if startup and self.doc and self.settings.get("profiles_at_start", True):
            GLib.timeout_add(150, lambda: (self.switch_profile_dialog(startup=True), False)[1])
        return False

    def _show_welcome(self):
        libs = steam_libraries()
        lib_txt = "\n".join("• " + l for l in libs) if libs else "• (no Steam installation found)"
        self.welcome_label.set_markup(
            "<span size='x-large'><b>No Division 2 key bindings file found</b></span>\n\n"
            "The game creates <tt>user.bindings</tt> the first time you change a key in its "
            "own Controls menu.\n\n"
            "<b>Do this once:</b> start The Division 2 from Steam, go to Settings → Keyboard/Mouse, "
            "change any key (you can change it back), and quit the game. Then press "
            "<i>Search again</i>.\n\n"
            "Searched these Steam libraries:\n<small>%s</small>" % GLib.markup_escape_text(lib_txt))
        self.stack.set_visible_child_name("welcome")
        self._update_buttons()

    def choose_file(self, files=None):
        if not self._confirm_discard():
            return
        if files is None:
            files = find_bindings_files()
        if not files:
            self.browse_file()
            return
        if len(files) == 1 and self.doc is None:
            self.load(files[0])
            return
        dlg = Gtk.Dialog(title="Choose bindings file", transient_for=self, modal=True)
        dlg.add_button("Browse…", 1)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Open", Gtk.ResponseType.OK)
        dlg.set_default_size(720, 260)
        box = dlg.get_content_area()
        box.set_border_width(10)
        box.set_spacing(6)
        box.pack_start(Gtk.Label(label="Division 2 bindings files found on this computer:", xalign=0),
                       False, False, 0)
        lb = Gtk.ListBox()
        for f in files:
            row = Gtk.ListBoxRow()
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M")
            l = Gtk.Label(xalign=0)
            l.set_markup("<b>Modified %s</b>\n<small>%s</small>" % (mtime, GLib.markup_escape_text(f)))
            l.set_ellipsize(Pango.EllipsizeMode.START)
            l.set_margin_top(4)
            l.set_margin_bottom(4)
            row.add(l)
            row.path = f
            lb.add(row)
        lb.select_row(lb.get_row_at_index(0))
        lb.connect("row-activated", lambda *_: dlg.response(Gtk.ResponseType.OK))
        sw = Gtk.ScrolledWindow()
        sw.add(lb)
        box.pack_start(sw, True, True, 0)
        dlg.show_all()
        resp = dlg.run()
        row = lb.get_selected_row()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK and row:
            self.load(row.path)
        elif resp == 1:
            self.browse_file(skip_confirm=True)

    def browse_file(self, skip_confirm=False):
        if not skip_confirm and not self._confirm_discard():
            return
        dlg = Gtk.FileChooserDialog(title="Open user.bindings", transient_for=self,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        dlg.set_show_hidden(True)
        libs = steam_libraries()
        start = None
        for lib in libs:
            p = os.path.join(lib, "steamapps", "compatdata")
            if os.path.isdir(p):
                start = p
                break
        if start:
            dlg.set_current_folder(start)
        flt = Gtk.FileFilter()
        flt.set_name("Division 2 bindings (user.bindings)")
        flt.add_pattern("user.bindings*")
        dlg.add_filter(flt)
        allf = Gtk.FileFilter()
        allf.set_name("All files")
        allf.add_pattern("*")
        dlg.add_filter(allf)
        resp = dlg.run()
        path = dlg.get_filename()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK and path:
            self.load(path)

    def load(self, path):
        try:
            doc = BindingsDoc(path)
        except OSError as e:
            self.error("Could not read the file", str(e))
            return
        if not doc.entries:
            self.error("No key bindings found",
                       "The file was read, but it contains no binding entries "
                       "(blocks with myName / myKeyCombo). Is it the right file?\n\n%s" % path)
            return
        self.doc = doc
        self.values = {k: list(v) for k, v in doc.values().items()}
        self.disk_values = {k: list(v) for k, v in self.values.items()}
        self.entry_by_id = {e.id: e for e in doc.entries}
        self.new_entries = []
        self.history = []
        self.settings["last_file"] = path
        _save_json(SETTINGS_FILE, self.settings)
        self._ensure_original_profile()
        self.stack.set_visible_child_name("editor")
        self.refresh()
        self._poll_game()

    def _ensure_original_profile(self):
        """Keep a snapshot of the very first layout we ever saw for this file."""
        marker = os.path.join(CONFIG_DIR, "original-saved-" + file_key(self.doc.path))
        legacy = os.path.join(PROFILE_DIR, safe_filename(
            "Original layout (%s)" % file_key(self.doc.path)) + ".json")
        if not os.path.exists(marker) and not os.path.exists(legacy):
            try:
                name = "Original layout (%s)" % datetime.date.today().isoformat()
                save_profile(name, self.disk_values,
                             note="Automatic snapshot taken the first time this file was opened.")
                with open(marker, "w") as f:
                    f.write("")
                backup_file(self.doc.path)
            except OSError:
                pass

    def save(self):
        if not self.doc:
            return
        if not self.is_dirty():
            self.set_status("Nothing to save.")
            return
        if game_is_running():
            if not self.confirm(
                    "The Division 2 is running",
                    "The game rewrites user.bindings when it closes and would overwrite your "
                    "changes. Quit the game first, then save.\n\nSave anyway?",
                    ok_label="Save anyway"):
                return
        path = self.doc.path
        try:
            on_disk = BindingsDoc(path)
            if on_disk.text != self.doc.text:
                if not self.confirm(
                        "File changed on disk",
                        "user.bindings was changed by something else (probably the game) since "
                        "it was opened. Saving will apply your edits on top of the new file.",
                        ok_label="Apply my edits"):
                    return
                self.doc = on_disk
                self.entry_by_id = {e.id: e for e in on_disk.entries}
            backup = backup_file(path)
            text = self.doc.render(self.values, self.new_entries)
            write_atomic(path, text)
            if self.protect_check.get_active():
                set_readonly(path, True)
        except (OSError, ValueError) as e:
            self.error("Saving failed", str(e))
            return
        added = len(self.new_entries)
        self.load(path)
        self.set_status("Saved. Backup: %s%s" % (
            backup, (" — %d new entr%s added" % (added, "y" if added == 1 else "ies")) if added else ""))

    def is_dirty(self):
        return bool(self.new_entries) or self.values != self.disk_values

    def _confirm_discard(self):
        if self.doc is None or not self.is_dirty():
            return True
        return self.confirm("Discard unsaved changes?",
                            "You have changes that are not saved to user.bindings yet.",
                            ok_label="Discard")

    def _on_delete(self, *_):
        return not self._confirm_discard()

    def revert(self):
        if not self.doc:
            return
        self.push_history()
        self.values = {k: list(v) for k, v in self.disk_values.items()}
        self.new_entries = []
        self.refresh()
        self.set_status("Reverted to what is saved on disk.")

    def reset_to_defaults(self):
        if not self.doc:
            return
        if not self.confirm(
                "Reset to the game's default keys?",
                "This makes a backup of your current file and then removes user.bindings. "
                "The game writes a fresh file with its default bindings next time it starts "
                "(change any key once in-game if it doesn't appear).\n\n"
                "You can always get your layout back from Restore a backup or Profiles.",
                ok_label="Reset"):
            return
        try:
            backup = backup_file(self.doc.path)
            path = self.doc.path
            set_readonly(path, False)
            os.remove(path)
        except OSError as e:
            self.error("Reset failed", str(e))
            return
        self.doc = None
        self.values = {}
        self.disk_values = {}
        self.settings.pop("last_file", None)
        _save_json(SETTINGS_FILE, self.settings)
        self._show_welcome()
        self.info("Bindings reset", "Removed user.bindings. Backup saved to:\n%s\n\n"
                  "Start the game to get the defaults." % backup)

    def _on_protect_toggled(self, btn):
        self.settings["protect"] = btn.get_active()
        _save_json(SETTINGS_FILE, self.settings)
        if self.doc and os.path.exists(self.doc.path):
            try:
                set_readonly(self.doc.path, btn.get_active())
            except OSError as e:
                self.error("Could not change file permissions", str(e))
        self._poll_game()

    # ----- editing -------------------------------------------------------

    def push_history(self):
        self.history.append(({k: list(v) for k, v in self.values.items()}, list(self.new_entries)))
        if len(self.history) > 200:
            self.history.pop(0)

    def undo(self):
        if not self.history:
            return
        self.values, self.new_entries = self.history.pop()
        self.refresh()
        self.set_status("Undone.")

    def label_for(self, eid):
        name = eid.split("#")[0]
        idx = int(eid.split("#")[1]) if "#" in eid else 0
        base = self.labels.get(name) or pretty_name(name)
        return base if idx == 0 else "%s (%d)" % (base, idx)

    def all_rows(self):
        """id -> [combo, alt] including pending new entries."""
        rows = dict(self.values)
        for name, combo, alt in self.new_entries:
            rows["%s#0" % name] = [combo, alt]
        return rows

    def conflicts(self):
        rows = self.all_rows()
        users = {}
        for eid, (combo, alt) in rows.items():
            cat = category_of(eid.split("#")[0])
            for slot, code in ((0, combo), (1, alt)):
                if code:
                    users.setdefault((cat, code), []).append((eid, slot))
        out = {}
        for (_cat, code), lst in users.items():
            if len(lst) > 1:
                for eid, slot in lst:
                    others = [self.label_for(o) for o, _s in lst if o != eid]
                    if others:
                        out.setdefault(eid, []).append((code, others))
        return out

    def refresh(self):
        selected = set(self.selected_ids())
        self.store.clear()
        if not self.doc:
            return
        confl = self.conflicts()
        pending_ids = {"%s#0" % n for n, _c, _a in self.new_entries}
        for eid, (combo, alt) in self.all_rows().items():
            name = eid.split("#")[0]
            disk = self.disk_values.get(eid)
            changed = eid in pending_ids or disk is None or [combo, alt] != disk
            tip_parts = []
            icon = ""
            if eid in confl:
                icon = "dialog-warning"
                for code, others in confl[eid]:
                    tip_parts.append("%s is also used by: %s" % (self.namer.name(code), ", ".join(others)))
            if changed:
                tip_parts.append("Changed — not saved yet" if eid not in pending_ids
                                 else "New entry — will be added on save")
                if not icon:
                    icon = "document-edit-symbolic"
            tip_parts.append("Internal: %s   codes: %s / %s" % (
                name, combo, "—" if alt is None else alt))
            self.store.append([
                eid, self.label_for(eid), category_of(name),
                self.namer.name(combo) or "—",
                ("n/a" if alt is None else (self.namer.name(alt) or "—")),
                eid if not eid.endswith("#0") else name,
                icon, GLib.markup_escape_text("\n".join(tip_parts)), changed,
                700 if changed else 400,
            ])
        # restore selection
        sel = self.tree.get_selection()
        for row in self.sorted:
            if row[COL_ID] in selected:
                sel.select_iter(row.iter)
        n_conf = len(confl)
        n_changed = sum(1 for r in self.store if r[COL_CHANGED])
        self._update_title()
        self.set_status(("Unsaved changes — press Save (Ctrl+S).  •  " if self.is_dirty() else "") +
                        "%d bindings  •  %d changed  •  %d with conflicts  •  %s" % (
            len(self.store), n_changed, n_conf, self.doc.path))
        self._update_buttons()

    def _visible(self, model, it, _data):
        q = self.search.get_text().strip().lower()
        if q:
            hay = " ".join(str(model[it][c]) for c in (COL_LABEL, COL_PRIMARY, COL_ALT, COL_NAME)).lower()
            if q not in hay:
                return False
        cat = self.cat_combo.get_active_text()
        if cat and cat != "All categories" and model[it][COL_CATEGORY] != cat:
            return False
        if self.conflict_toggle.get_active() and model[it][COL_WARN] != "dialog-warning":
            return False
        if self.changed_toggle.get_active() and not model[it][COL_CHANGED]:
            return False
        return True

    def selected_ids(self):
        if not hasattr(self, "tree"):
            return []
        model, paths = self.tree.get_selection().get_selected_rows()
        return [model[p][COL_ID] for p in paths]

    def _update_buttons(self):
        have = self.doc is not None
        n = len(self.selected_ids()) if have else 0
        self.save_btn.set_sensitive(have and self.is_dirty())
        self.undo_btn.set_sensitive(have and bool(self.history))
        self.pri_btn.set_sensitive(n == 1)
        sel = self.selected_ids()
        self.alt_btn.set_sensitive(n == 1 and self.all_rows().get(sel[0], [0, None])[1] is not None)
        self.swap_btn.set_sensitive(n == 2)
        self.move_btn.set_sensitive(have)
        self.add_btn.set_sensitive(have)

    def _on_tree_button(self, tv, event):
        # Keep multi-selection when right-clicking etc.; nothing special for now.
        return False

    def _on_row_activated(self, tv, path, column):
        eid = self.sorted[path][COL_ID]
        slot = 1 if column is self.col_alt else 0
        self.rebind(eid, slot)

    def _on_label_edited(self, _r, path, text):
        eid = self.sorted[path][COL_ID]
        name = eid.split("#")[0]
        text = text.strip()
        if not text or text == pretty_name(name):
            self.labels.pop(name, None)
        else:
            self.labels[name] = text
        _save_json(LABELS_FILE, self.labels)
        self.refresh()

    def rebind_selected(self, slot):
        ids = self.selected_ids()
        if len(ids) == 1:
            self.rebind(ids[0], slot)

    def get_code(self, eid, slot):
        return self.all_rows()[eid][slot]

    def set_code(self, eid, slot, code):
        if eid in self.values:
            self.values[eid][slot] = code
        else:
            for i, (n, c, a) in enumerate(self.new_entries):
                if "%s#0" % n == eid:
                    self.new_entries[i] = (n, code, a) if slot == 0 else (n, c, code)

    def rebind(self, eid, slot):
        if slot == 1 and self.get_code(eid, 1) is None:
            self.info("No alternate slot", "This entry has no alternate key in the file.")
            return
        current = self.get_code(eid, slot)
        dlg = CaptureDialog(self, self.label_for(eid), "primary key" if slot == 0 else "alternate key",
                            self.namer.name(current))
        resp = dlg.run()
        code = dlg.result_code
        dlg.destroy()
        if resp == CaptureDialog.RESP_CLEAR:
            code = 0
        elif resp == CaptureDialog.RESP_MANUAL:
            code = ask_number(self, "Enter key code",
                              "Enter the raw game code (DirectInput scan code, or 65536+ for "
                              "mouse). 0 = unbound.", current or 0)
            if code is None:
                return
        elif resp != Gtk.ResponseType.OK or code is None:
            return
        if code == current:
            return
        self.assign(eid, slot, code)

    def assign(self, eid, slot, code):
        """Assign code to eid/slot, resolving conflicts with the user."""
        old = self.get_code(eid, slot)
        cat = category_of(eid.split("#")[0])
        users = []
        if code:
            for other, (c, a) in self.all_rows().items():
                if category_of(other.split("#")[0]) != cat:
                    continue
                for s, v in ((0, c), (1, a)):
                    if v == code and not (other == eid and s == slot):
                        users.append((other, s))
        action = "keep"
        if users:
            names = "\n".join("• %s (%s)" % (self.label_for(o), "primary" if s == 0 else "alternate")
                              for o, s in users)
            dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                    message_type=Gtk.MessageType.QUESTION,
                                    text="%s is already used" % self.namer.name(code))
            dlg.format_secondary_text(
                "%s is already bound to:\n%s\n\n"
                "Move: take the key away from the other action(s).\n"
                "Swap: give the other action(s) %s instead.\n"
                "Keep both: allow the same key twice."
                % (self.namer.name(code), names, self.namer.name(old) or "nothing (unbound)"))
            dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dlg.add_button("Keep both", 3)
            dlg.add_button("Swap", 2)
            dlg.add_button("Move", 1)
            dlg.set_default_response(1)
            resp = dlg.run()
            dlg.destroy()
            if resp == 1:
                action = "move"
            elif resp == 2:
                action = "swap"
            elif resp == 3:
                action = "keep"
            else:
                return
        self.push_history()
        if action == "move":
            for o, s in users:
                self.set_code(o, s, 0)
        elif action == "swap":
            for o, s in users:
                self.set_code(o, s, old or 0)
        self.set_code(eid, slot, code)
        self.refresh()
        self.set_status("%s → %s" % (self.label_for(eid), self.namer.name(code) or "unbound"))

    def swap_selected(self):
        ids = self.selected_ids()
        if len(ids) != 2:
            return
        a, b = ids
        ra, rb = self.all_rows()[a], self.all_rows()[b]
        self.push_history()
        self.set_code(a, 0, rb[0])
        self.set_code(b, 0, ra[0])
        if ra[1] is not None and rb[1] is not None:
            self.set_code(a, 1, rb[1])
            self.set_code(b, 1, ra[1])
        self.refresh()
        self.set_status("Swapped keys of %s and %s." % (self.label_for(a), self.label_for(b)))

    def move_keys_dialog(self):
        ids = self.selected_ids()
        rows = self.all_rows()
        if not ids:
            self.info("Select actions first",
                      "Select the actions whose keys you want to move (Ctrl/Shift-click for several), "
                      "for example Move Forward / Back / Left / Right, then press Move keys again.")
            return
        dlg = Gtk.Dialog(title="Move keys", transient_for=self, modal=True)
        dlg.set_default_size(560, 420)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        apply_btn = dlg.add_button("Apply", Gtk.ResponseType.OK)
        apply_btn.get_style_context().add_class("suggested-action")
        box = dlg.get_content_area()
        box.set_border_width(12)
        box.set_spacing(8)
        lbl = Gtk.Label(xalign=0)
        lbl.set_line_wrap(True)
        lbl.set_markup("Shift the keys of the <b>%d selected action(s)</b> across the keyboard. "
                       "Press a direction several times to move further. Mouse buttons and keys "
                       "outside the letter/number block stay where they are." % len(ids))
        box.pack_start(lbl, False, False, 0)

        slots_box = Gtk.Box(spacing=12)
        pri_cb = Gtk.CheckButton(label="Primary keys", active=True)
        alt_cb = Gtk.CheckButton(label="Alternate keys", active=False)
        slots_box.pack_start(pri_cb, False, False, 0)
        slots_box.pack_start(alt_cb, False, False, 0)
        box.pack_start(slots_box, False, False, 0)

        grid = Gtk.Grid(column_spacing=4, row_spacing=4, halign=Gtk.Align.CENTER)
        state = {"steps": []}
        preview = Gtk.ListStore(str, str, str)

        def compute():
            result = {}
            problems = []
            for eid in ids:
                for slot, cb in ((0, pri_cb), (1, alt_cb)):
                    if not cb.get_active():
                        continue
                    code = rows[eid][slot]
                    if not code:
                        continue
                    new = code
                    for d in state["steps"]:
                        n2 = shift_code(new, d)
                        if n2 is None:
                            new = None
                            break
                        new = n2
                    if new is None:
                        problems.append(eid)
                        new = code
                    result[(eid, slot)] = (code, new)
            return result, problems

        def update(*_):
            preview.clear()
            result, problems = compute()
            for (eid, slot), (old, new) in sorted(result.items(), key=lambda x: self.label_for(x[0][0])):
                preview.append(["%s%s" % (self.label_for(eid), " (alt)" if slot else ""),
                                self.namer.name(old),
                                self.namer.name(new) + ("   (can't move — edge/not a letter key)"
                                                        if eid in problems and old == new else "")])
            steps_lbl.set_text("Steps: " + (" ".join({"left": "←", "right": "→", "up": "↑", "down": "↓"}[s]
                                                    for s in state["steps"]) or "none"))

        def step(d):
            state["steps"].append(d)
            update()

        def undo_step(*_):
            if state["steps"]:
                state["steps"].pop()
                update()

        for label, d, x, y in (("↑", "up", 1, 0), ("←", "left", 0, 1), ("→", "right", 2, 1), ("↓", "down", 1, 2)):
            b = Gtk.Button(label=label)
            b.set_size_request(48, 36)
            b.connect("clicked", lambda _b, d=d: step(d))
            grid.attach(b, x, y, 1, 1)
        back = Gtk.Button.new_from_icon_name("edit-undo-symbolic", Gtk.IconSize.BUTTON)
        back.set_tooltip_text("Remove last step")
        back.connect("clicked", undo_step)
        grid.attach(back, 1, 1, 1, 1)
        box.pack_start(grid, False, False, 0)
        steps_lbl = Gtk.Label(xalign=0.5)
        box.pack_start(steps_lbl, False, False, 0)

        tv = Gtk.TreeView(model=preview)
        for i, t in enumerate(("Action", "Now", "After move")):
            r = Gtk.CellRendererText()
            c = Gtk.TreeViewColumn(t, r, text=i)
            c.set_resizable(True)
            c.set_expand(i == 0)
            tv.append_column(c)
        sw = Gtk.ScrolledWindow()
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)
        pri_cb.connect("toggled", update)
        alt_cb.connect("toggled", update)
        update()
        dlg.show_all()
        resp = dlg.run()
        result, _problems = compute()
        dlg.destroy()
        if resp != Gtk.ResponseType.OK or not state["steps"]:
            return
        self.push_history()
        for (eid, slot), (_old, new) in result.items():
            self.set_code(eid, slot, new)
        self.refresh()
        n_conf = len(self.conflicts())
        self.set_status("Moved %d key(s). %s" % (
            len(result), ("%d action(s) now have conflicts — tick 'Only conflicts' to review them."
                          % n_conf) if n_conf else "No conflicts."))

    def add_entry_dialog(self):
        name = ask_text(self, "Add binding entry",
                        "Internal name of the binding to add, exactly as the game spells it "
                        "(for example KB_UI_R). Only add entries you know the game uses; "
                        "unknown names are ignored by the game.", "KB_UI_")
        if not name:
            return
        if not re.match(r"^[A-Za-z0-9_]+$", name):
            self.error("Invalid name", "Use letters, digits and underscores only.")
            return
        if "%s#0" % name in self.all_rows():
            self.info("Already present", "%s already exists — edit it in the list." % name)
            return
        self.push_history()
        self.new_entries.append((name, 0, 0))
        self.refresh()
        eid = "%s#0" % name
        for row in self.sorted:
            if row[COL_ID] == eid:
                self.tree.get_selection().unselect_all()
                self.tree.get_selection().select_iter(row.iter)
                self.tree.scroll_to_cell(row.path, None, False, 0, 0)
                break
        self.rebind(eid, 0)

    # ----- profiles & backups -------------------------------------------

    def save_profile_dialog(self):
        if not self.doc:
            return
        name = ask_text(self, "Save profile",
                        "Name for this layout (it is stored in ~/.config/division2-keybinder/profiles):",
                        datetime.date.today().isoformat() + " my layout")
        if not name:
            return
        path = os.path.join(PROFILE_DIR, safe_filename(name) + ".json")
        if os.path.exists(path) and not self.confirm("Overwrite profile?",
                                                     "A profile called “%s” exists." % name,
                                                     ok_label="Overwrite"):
            return
        save_profile(name, self.all_rows())
        self.set_status("Profile “%s” saved." % name)

    def apply_profile(self, data):
        bindings = clean_bindings(data.get("bindings", {}))
        self.push_history()
        applied, missing = 0, []
        for eid, val in bindings.items():
            if eid in self.values:
                combo, alt = val
                self.values[eid][0] = int(combo or 0)
                if alt is not None and self.values[eid][1] is not None:
                    self.values[eid][1] = int(alt)
                applied += 1
            elif eid.endswith("#0"):
                name = eid[:-2]
                combo, alt = val
                self.new_entries = [e for e in self.new_entries if e[0] != name]
                self.new_entries.append((name, int(combo or 0), int(alt or 0)))
                applied += 1
            else:
                missing.append(eid)
        self.settings["active_profile"] = str(data.get("name", ""))[:100]
        _save_json(SETTINGS_FILE, self.settings)
        self.refresh()
        msg = "Loaded profile “%s”: %d bindings applied." % (data.get("name", "?"), applied)
        if missing:
            msg += " %d not in this file (skipped)." % len(missing)
        self.set_status(msg + " Press Save to write it.")

    def profile_matches_file(self, data):
        b = data.get("bindings", {})
        if not b:
            return False
        for eid, val in b.items():
            cur = self.disk_values.get(eid)
            if cur is None or not isinstance(val, list) or len(val) != 2:
                return False
            if int(val[0] or 0) != cur[0]:
                return False
            if val[1] is not None and cur[1] is not None and int(val[1]) != cur[1]:
                return False
        return True

    def switch_profile_dialog(self, startup=False):
        """Pick a saved layout and write it to the game in one step."""
        if not self.doc:
            self.info("No bindings file open",
                      "Open the game's user.bindings first (Open… button), then choose a profile.")
            return
        RESP_USE, RESP_EDIT, RESP_QUIT = 10, 11, 12
        dlg = Gtk.Dialog(title="Choose key binding profile", transient_for=self, modal=True)
        dlg.set_default_size(620, 440)
        if startup:
            dlg.add_button("Quit program", RESP_QUIT)
        dlg.add_button("Edit keys" if startup else "Close", RESP_EDIT)
        use_btn = dlg.add_button("Use this profile", RESP_USE)
        use_btn.get_style_context().add_class("suggested-action")
        use_btn.set_tooltip_text("Write the selected profile to the game's bindings file now "
                                 "(a backup is made first)")
        dlg.set_default_response(RESP_USE)

        box = dlg.get_content_area()
        box.set_border_width(12)
        box.set_spacing(8)
        head = Gtk.Label(xalign=0)
        head.set_markup("<span size='large'><b>Which key layout do you want to play with?</b></span>")
        box.pack_start(head, False, False, 0)
        sub = Gtk.Label(xalign=0)
        sub.set_line_wrap(True)
        sub.set_text("Pick a profile and press “Use this profile” — it is written to the game "
                     "straight away. “Edit keys” keeps the current layout and opens the editor. "
                     "Save new profiles from the editor (More → Save current layout as profile).")
        sub.get_style_context().add_class("kb-hint")
        box.pack_start(sub, False, False, 0)

        lb = Gtk.ListBox()
        lb.set_selection_mode(Gtk.SelectionMode.SINGLE)
        profiles = list_profiles()
        active = self.settings.get("active_profile")
        current_row = None
        for name, path, data in profiles:
            row = Gtk.ListBoxRow()
            row.data = data
            hb = Gtk.Box(spacing=10)
            hb.set_border_width(8)
            lbl = Gtk.Label(xalign=0)
            created = data.get("created", "").replace("T", " ")
            lbl.set_markup("<b>%s</b>\n<small>%d keys  •  saved %s</small>" % (
                GLib.markup_escape_text(name), len(data.get("bindings", {})),
                GLib.markup_escape_text(created)))
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            hb.pack_start(lbl, True, True, 0)
            if self.profile_matches_file(data):
                tag = Gtk.Label()
                tag.set_markup("<b>● in use now</b>")
                hb.pack_end(tag, False, False, 0)
                if current_row is None or name == active:
                    current_row = row
            row.add(hb)
            lb.add(row)
        if not profiles:
            empty = Gtk.Label(label="No profiles saved yet.")
            empty.set_margin_top(20)
            lb.set_placeholder(empty)
        sw = Gtk.ScrolledWindow()
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(lb)
        box.pack_start(sw, True, True, 0)

        row0 = current_row or lb.get_row_at_index(0)
        if row0:
            lb.select_row(row0)
        use_btn.set_sensitive(row0 is not None)
        lb.connect("row-selected", lambda _l, r: use_btn.set_sensitive(r is not None))
        lb.connect("row-activated", lambda *_: dlg.response(RESP_USE))

        manage = Gtk.Button(label="Manage profiles (import / export / delete)…")
        manage.set_halign(Gtk.Align.START)
        box.pack_start(manage, False, False, 0)

        show_cb = Gtk.CheckButton(label="Show this window every time the program starts")
        show_cb.set_active(self.settings.get("profiles_at_start", True))
        box.pack_start(show_cb, False, False, 0)

        def on_manage(*_):
            dlg.response(RESP_EDIT)
            GLib.idle_add(lambda: (self.profiles_dialog(), self.switch_profile_dialog(startup), False)[2])
        manage.connect("clicked", on_manage)

        dlg.show_all()
        resp = dlg.run()
        row = lb.get_selected_row()
        self.settings["profiles_at_start"] = show_cb.get_active()
        _save_json(SETTINGS_FILE, self.settings)
        dlg.destroy()

        if resp == RESP_QUIT:
            self.quit()
            return
        if resp != RESP_USE or row is None:
            return
        if self.is_dirty() and not self.confirm(
                "Replace unsaved changes?",
                "You have edits that are not saved. Loading a profile replaces them.",
                ok_label="Use profile"):
            return
        self.values = {k: list(v) for k, v in self.disk_values.items()}
        self.new_entries = []
        self.apply_profile(row.data)
        name = row.data.get("name", "?")
        if self.is_dirty():
            self.save()
        if not self.is_dirty():
            self.set_status("Profile “%s” is now active and written to the game." % name)

    def profiles_dialog(self):
        dlg = Gtk.Dialog(title="Profiles", transient_for=self, modal=True)
        dlg.set_default_size(620, 380)
        box = dlg.get_content_area()
        box.set_border_width(10)
        box.set_spacing(8)
        lbl = Gtk.Label(xalign=0)
        lbl.set_line_wrap(True)
        lbl.set_text("Profiles are saved layouts. Loading one changes the list; press Save "
                     "afterwards to write it to the game. “Original layout” is the snapshot "
                     "taken the first time this app opened your file.")
        box.pack_start(lbl, False, False, 0)
        store = Gtk.ListStore(str, str, str)
        tv = Gtk.TreeView(model=store)
        for i, t in enumerate(("Name", "Created")):
            c = Gtk.TreeViewColumn(t, Gtk.CellRendererText(), text=i)
            c.set_expand(i == 0)
            tv.append_column(c)

        def reload():
            store.clear()
            for name, path, data in list_profiles():
                store.append([name, data.get("created", ""), path])
        reload()
        sw = Gtk.ScrolledWindow()
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)

        btns = Gtk.Box(spacing=6)
        box.pack_start(btns, False, False, 0)

        def selected():
            m, it = tv.get_selection().get_selected()
            return m[it][2] if it else None

        def do_load(*_):
            p = selected()
            if not p:
                return
            if not self.doc:
                self.info("No file open", "Open a user.bindings file first.")
                return
            self.apply_profile(_load_json(p, {}))
            dlg.response(Gtk.ResponseType.CLOSE)

        def do_delete(*_):
            p = selected()
            if p and self.confirm("Delete profile?", os.path.basename(p), ok_label="Delete", parent=dlg):
                os.remove(p)
                reload()

        def do_export(*_):
            p = selected()
            if not p:
                return
            fc = Gtk.FileChooserDialog(title="Export profile", transient_for=dlg,
                                       action=Gtk.FileChooserAction.SAVE)
            fc.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Export", Gtk.ResponseType.OK)
            fc.set_do_overwrite_confirmation(True)
            fc.set_current_name(os.path.basename(p))
            fc.set_current_folder(os.path.expanduser("~"))
            if fc.run() == Gtk.ResponseType.OK:
                src = _load_json(p, {})
                _save_json(fc.get_filename(), {
                    "name": re.sub(r" \([0-9a-f]{10}\)$", "", str(src.get("name", "")))[:100],
                    "game": "Tom Clancy's The Division 2",
                    "created": str(src.get("created", ""))[:32],
                    "bindings": clean_bindings(src.get("bindings", {})),
                })
            fc.destroy()

        def do_import(*_):
            fc = Gtk.FileChooserDialog(title="Import profile", transient_for=dlg,
                                       action=Gtk.FileChooserAction.OPEN)
            fc.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Import", Gtk.ResponseType.OK)
            f = Gtk.FileFilter()
            f.set_name("Profiles (*.json)")
            f.add_pattern("*.json")
            fc.add_filter(f)
            if fc.run() == Gtk.ResponseType.OK:
                data = _load_json(fc.get_filename(), None)
                if isinstance(data, dict) and clean_bindings(data.get("bindings")):
                    name = data.get("name")
                    if not isinstance(name, str) or not name.strip():
                        name = os.path.basename(fc.get_filename())[:-5]
                    save_profile(name.strip()[:100], data["bindings"])
                    reload()
                else:
                    self.error("Not a profile", "That file is not a Division 2 Keybinder profile.",
                               parent=dlg)
            fc.destroy()

        for label, cb in (("Load", do_load), ("Delete", do_delete), ("Export…", do_export),
                          ("Import…", do_import)):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            if label == "Load":
                b.get_style_context().add_class("suggested-action")
            btns.pack_start(b, False, False, 0)
        tv.connect("row-activated", do_load)
        dlg.add_button("Close", Gtk.ResponseType.CLOSE)
        dlg.show_all()
        dlg.run()
        dlg.destroy()

    def backups_dialog(self):
        path = self.doc.path if self.doc else self.settings.get("last_file")
        if not path:
            self.info("No file", "Open a bindings file first.")
            return
        backups = list_backups(path)
        if not backups:
            self.info("No backups yet", "A backup is made automatically every time you save.")
            return
        dlg = Gtk.Dialog(title="Restore a backup", transient_for=self, modal=True)
        dlg.set_default_size(520, 360)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Restore", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_border_width(10)
        box.pack_start(Gtk.Label(label="Backups of %s (newest first):" % BINDINGS_FILENAME, xalign=0),
                       False, False, 6)
        lb = Gtk.ListBox()
        for b in backups:
            row = Gtk.ListBoxRow()
            stamp = b.rsplit("user.bindings.", 1)[-1].replace("_", "  ")
            row.add(Gtk.Label(label=stamp, xalign=0, margin=6))
            row.path = b
            lb.add(row)
        lb.select_row(lb.get_row_at_index(0))
        sw = Gtk.ScrolledWindow()
        sw.add(lb)
        box.pack_start(sw, True, True, 0)
        dlg.show_all()
        resp = dlg.run()
        row = lb.get_selected_row()
        dlg.destroy()
        if resp != Gtk.ResponseType.OK or not row:
            return
        if game_is_running() and not self.confirm(
                "The Division 2 is running", "Quit the game first or it may overwrite the restore.",
                ok_label="Restore anyway"):
            return
        try:
            if os.path.exists(path):
                backup_file(path)
                set_readonly(path, False)
            shutil.copyfile(row.path, path)
            if self.protect_check.get_active():
                set_readonly(path, True)
        except OSError as e:
            self.error("Restore failed", str(e))
            return
        self.load(path)
        self.set_status("Restored backup %s" % os.path.basename(row.path))

    # ----- misc ----------------------------------------------------------

    def open_location(self):
        if self.doc:
            subprocess.Popen(["xdg-open", os.path.dirname(self.doc.path)])

    def launch_game(self):
        if self.is_dirty() and not self.confirm(
                "Unsaved changes", "Your changes are not saved and the game won't see them.",
                ok_label="Launch anyway"):
            return
        subprocess.Popen(["xdg-open", "steam://rungameid/%s" % STEAM_APP_ID])

    def show_help(self):
        self.info(
            "How it works",
            "• The game keeps keyboard/mouse bindings in user.bindings inside Steam's Proton "
            "prefix (compatdata/%s). This app edits that file.\n\n"
            "• Always QUIT the game before saving. The game rewrites the file when it exits.\n\n"
            "• Double-click a key cell to rebind it. If the key is taken you can Move it "
            "(unbind the other action), Swap, or Keep both.\n\n"
            "• Menu keys (Menus / UI) are separate from gameplay keys — the game uses "
            "them in inventory/map screens. Only conflicts within the same category are flagged.\n\n"
            "• Move keys shifts a group (e.g. WASD → ESDF). Swap exchanges two actions.\n\n"
            "• Every save makes a backup; Profiles let you keep several layouts. "
            "If the game or Ubisoft cloud keeps resetting your keys, turn on "
            "“Protect file (read-only) after saving”.\n\n"
            "• Action names are generated from the game's internal names. Click a name to give "
            "it your own label." % STEAM_APP_ID)

    def _poll_game(self):
        msgs = []
        if game_is_running():
            msgs.append("<b>The Division 2 is running.</b> Quit the game before saving — "
                        "it overwrites user.bindings when it closes.")
        if self.doc and is_readonly(self.doc.path):
            msgs.append("The file is <b>read-only (protected)</b>: key changes made inside the game "
                        "won't be kept until you untick protection in the menu.")
        if msgs:
            self.info_label.set_markup("\n".join(msgs))
            self.infobar.set_message_type(Gtk.MessageType.WARNING if "running" in msgs[0]
                                          else Gtk.MessageType.INFO)
            self.infobar.show()
            self.info_label.show()
        else:
            self.infobar.hide()
        return True

    def set_status(self, text):
        self.status.set_text(text)

    def confirm(self, title, text, ok_label="OK", parent=None):
        dlg = Gtk.MessageDialog(transient_for=parent or self, modal=True,
                                message_type=Gtk.MessageType.QUESTION, text=title)
        dlg.format_secondary_text(text)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button(ok_label, Gtk.ResponseType.OK)
        resp = dlg.run()
        dlg.destroy()
        return resp == Gtk.ResponseType.OK

    def info(self, title, text, parent=None):
        dlg = Gtk.MessageDialog(transient_for=parent or self, modal=True,
                                message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
                                text=title)
        dlg.format_secondary_text(text)
        dlg.run()
        dlg.destroy()

    def error(self, title, text, parent=None):
        dlg = Gtk.MessageDialog(transient_for=parent or self, modal=True,
                                message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
                                text=title)
        dlg.format_secondary_text(text)
        dlg.run()
        dlg.destroy()


class App(Gtk.Application):
    def __init__(self, path=None):
        super().__init__(application_id="io.github.division2keybinder")
        self.path = path
        self.win = None

    def do_activate(self):
        if self.win is None:
            self.win = MainWindow(self)
            if self.path:
                GLib.idle_add(lambda: (self.win.load(self.path), False)[1])
        self.win.present()


def main():
    os.makedirs(PROFILE_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    scrub_old_profiles()
    path = None
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args and os.path.isfile(args[0]):
        path = os.path.abspath(args[0])
    app = App(path)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
