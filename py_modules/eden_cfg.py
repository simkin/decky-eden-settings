"""Read and write Eden settings (global and per game) in Eden's Qt INI files.

Eden stores a setting as a small group of lines inside a section:

    key\\default=false      (true = Eden ignores the value and uses its built-in default)
    key=<value>
    key\\use_global=false   (per game only: true = this game follows the global value)

An override without ``\\default=false`` is silently ignored by Eden, so we always write every line.
Eden rewrites these files when it exits (and when a game starts), so we refuse to write while Eden runs.

This module is pure Python and has no dependency on Decky, so it can be unit-tested on its own.
Human-readable texts live in the frontend (src/locales); the backend only deals with keys and values.
"""
import base64
import glob
import os
import re
import shutil
import stat
import time

# ---------------------------------------------------------------------------------------------------
# Setting schema. Only settings whose values were verified against Eden's own source (settings_enums.h,
# the order of the enum names) and against a real qt-config.ini are listed here.
# `options` are the stored values, in display order. `group` selects the section in the UI.
# ---------------------------------------------------------------------------------------------------
SETTINGS = [
    # --- image quality
    dict(key="resolution_setup", section="Renderer", group="image", default="3",
         options=["1", "2", "3", "5", "6", "7", "8"]),          # 0.5x 0.75x 1x 1.5x 2x 3x 4x
    dict(key="scaling_filter", section="Renderer", group="image", default="1",
         options=["0", "1", "2", "3", "4", "5", "6"]),          # nearest bilinear bicubic gaussian lanczos scaleforce fsr
    dict(key="fsr_sharpening_slider", section="Renderer", group="image", default="25",
         options=["0", "25", "50", "75", "100", "150", "200"]),
    dict(key="anti_aliasing", section="Renderer", group="image", default="0",
         options=["0", "1", "2"]),                              # none fxaa smaa
    dict(key="max_anisotropy", section="Renderer", group="image", default="0",
         options=["0", "2", "3", "4", "5"]),                    # auto 2x 4x 8x 16x
    dict(key="aspect_ratio", section="Renderer", group="image", default="0",
         options=["0", "1", "2", "3", "4"]),                    # 16:9 4:3 21:9 16:10 stretch
    # --- performance
    dict(key="use_docked_mode", section="System", group="performance", default="1",
         options=["1", "0"]),                                   # docked handheld
    dict(key="vram_usage_mode", section="Renderer", group="performance", default="0",
         options=["0", "1"]),                                   # conservative aggressive
    dict(key="use_vsync", section="Renderer", group="performance", default="2",
         options=["2", "3", "1", "0"]),                         # fifo fifo-relaxed mailbox immediate
    dict(key="use_speed_limit", section="Core", group="performance", default="true",
         options=["true", "false"]),
    dict(key="speed_limit", section="Core", group="performance", default="100",
         options=["50", "75", "100", "125", "150", "200", "300"]),
    dict(key="force_max_clock", section="Renderer", group="performance", default="false",
         options=["false", "true"]),
    dict(key="use_asynchronous_shaders", section="Renderer", group="performance", default="false",
         options=["false", "true"]),
    # --- audio
    dict(key="sound_index", section="System", group="audio", default="1",
         options=["1", "2", "0"]),                              # stereo surround mono
    # --- fixes
    dict(key="rescale_hack", section="Renderer", group="fixes", default="false",
         options=["false", "true"]),
    dict(key="nvdec_emulation", section="Renderer", group="fixes", default="2",
         options=["2", "1", "0"]),                              # gpu cpu off
]
BY_KEY = {s["key"]: s for s in SETTINGS}

# Eden is distributed as a Flatpak (recommended on Bazzite/SteamOS) or a native/AppImage build.
FLATPAK_ID = "dev.eden_emu.eden"
SPECIAL_GAMEDIRS = {"SDMC", "UserNAND", "SysNAND"}
GAME_EXTENSIONS = (".nsp", ".xci")
TITLE_ID_RE = re.compile(r"\[([0-9A-Fa-f]{16})\]")
VERSION_RE = re.compile(r"\[v(\d+)\]")
RELEASE_RE = re.compile(r"<release\s[^>]*?version=\"([^\"]+)\"")
BACKUPS_TO_KEEP = 20
ICON_EXTENSIONS = ("jpg", "jpeg", "png")
MAX_ICON_BYTES = 3 * 1024 * 1024
LAUNCHER_NAME = "launch-eden"
SCAN_DEPTH = 3
MAX_GAMES = 500


class EdenCfgError(Exception):
    pass


# ---------------------------------------------------------------------------------------------------
# INI helpers
# ---------------------------------------------------------------------------------------------------
def _bounds(lines, section):
    head = "[" + section + "]"
    start = next((i for i, l in enumerate(lines) if l.strip() == head), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("[")), len(lines))
    return start, end


def _get(lines, section, name):
    b = _bounds(lines, section)
    if not b:
        return None
    prefix = name + "="
    for i in range(b[0] + 1, b[1]):
        if lines[i].startswith(prefix):
            return lines[i][len(prefix):]
    return None


def _set(lines, section, name, value):
    new = f"{name}={value}"
    b = _bounds(lines, section)
    if b is None:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.extend([f"[{section}]", new])
        return
    prefix = name + "="
    for i in range(b[0] + 1, b[1]):
        if lines[i].startswith(prefix):
            lines[i] = new
            return
    idx = b[1]
    while idx > b[0] + 1 and lines[idx - 1].strip() == "":
        idx -= 1
    lines.insert(idx, new)


def _is_eden_running():
    for comm in glob.glob("/proc/[0-9]*/comm"):
        try:
            with open(comm) as f:
                if f.read().strip() == "eden":
                    return True
        except OSError:
            continue
    return False


# ---------------------------------------------------------------------------------------------------
# Installation discovery
# ---------------------------------------------------------------------------------------------------
def find_install(home, environ=None):
    """Return (kind, config_dir). kind is 'flatpak', 'native' or None when no Eden config exists yet."""
    environ = os.environ if environ is None else environ
    xdg = environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    candidates = [
        ("flatpak", os.path.join(home, ".var/app", FLATPAK_ID, "config/eden")),
        ("native", os.path.join(xdg, "eden")),
    ]
    for kind, path in candidates:
        if os.path.isfile(os.path.join(path, "qt-config.ini")):
            return kind, path
    return None, candidates[0][1]


def flatpak_version(home):
    """Version of the installed Eden Flatpak, read from its AppStream metadata (user or system install)."""
    roots = [
        os.path.join(home, ".local/share/flatpak/app", FLATPAK_ID),
        os.path.join("/var/lib/flatpak/app", FLATPAK_ID),
    ]
    for root in roots:
        for meta in glob.glob(os.path.join(root, "current/active/files/share/metainfo/*.metainfo.xml")):
            # Regex instead of an XML parser: Decky's embedded Python ships without xml.etree.
            try:
                with open(meta, encoding="utf-8", errors="replace") as f:
                    m = RELEASE_RE.search(f.read())
            except OSError:
                continue
            if m:
                return m.group(1)
    return None


class EdenCfg:
    def __init__(self, home, backup_dir, running_check=_is_eden_running, environ=None):
        self.home = home
        self.kind, self.cfg_dir = find_install(home, environ)
        self.global_path = os.path.join(self.cfg_dir, "qt-config.ini")
        self.custom_dir = os.path.join(self.cfg_dir, "custom")
        self.backup_dir = backup_dir
        self._running = running_check

    # ------------------------------------------------------------------ reading
    @staticmethod
    def _read(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read().split("\n")
        except FileNotFoundError:
            return []

    def _global_value(self, lines, s):
        flag = _get(lines, s["section"], s["key"] + "\\default")
        val = _get(lines, s["section"], s["key"])
        return s["default"] if flag == "true" or val is None else val

    def _game_override(self, lines, s):
        """None = follows the global value, otherwise the game's own value."""
        ug = _get(lines, s["section"], s["key"] + "\\use_global")
        if ug is None or ug == "true":
            return None
        flag = _get(lines, s["section"], s["key"] + "\\default")
        val = _get(lines, s["section"], s["key"])
        return s["default"] if flag == "true" or val is None else val

    def game_dirs(self):
        """Folders to look for games: Eden's own game list folders plus a few common locations."""
        lines = self._read(self.global_path)
        found = []
        for line in lines:
            m = re.match(r"^Paths\\gamedirs\\\d+\\path=(.+)$", line)
            if m and m.group(1) not in SPECIAL_GAMEDIRS:
                found.append(m.group(1))
        for rel in ("Emulation/switch/games", "Emulation/roms/switch", "ROMs/switch"):
            found.append(os.path.join(self.home, rel))
        seen, out = set(), []
        for d in found:
            d = os.path.normpath(d)
            if d not in seen and os.path.isdir(d):
                seen.add(d)
                out.append(d)
        return out

    def games(self):
        """Games found on disk (title id taken from the `[0100...]` part of the file name) plus any game
        that already has a per-game config file. Sorted by name."""
        games = {}
        for base in self.game_dirs():
            for root, dirs, files in os.walk(base):
                if root[len(base):].count(os.sep) >= SCAN_DEPTH:
                    dirs[:] = []
                for fn in files:
                    if not fn.lower().endswith(GAME_EXTENSIONS):
                        continue
                    m = TITLE_ID_RE.search(fn)
                    if not m:
                        continue
                    tid = m.group(1).upper()
                    name = fn[: m.start()].strip() or tid
                    v = VERSION_RE.search(fn)
                    games.setdefault(tid, dict(id=tid, name=name, version=int(v.group(1)) if v else 0,
                                               path=os.path.join(root, fn)))
                if len(games) >= MAX_GAMES:
                    break
        for p in glob.glob(os.path.join(self.custom_dir, "*.ini")):
            tid = os.path.basename(p)[:-4].upper()
            if re.fullmatch(r"[0-9A-F]{16}", tid):
                games.setdefault(tid, dict(id=tid, name=tid, version=0, path=None))
        return sorted(games.values(), key=lambda g: (g["name"].lower(), g["id"]))

    def eden_command(self):
        """Shell command that starts Eden (without arguments)."""
        if self.kind == "native":
            for pattern in (os.path.join(self.home, "Applications/*[Ee]den*.AppImage"),
                            os.path.join(self.home, ".local/bin/eden*"),
                            os.path.join(self.home, "Applications/eden*")):
                for hit in sorted(glob.glob(pattern)):
                    if os.access(hit, os.X_OK):
                        return '"' + hit + '"'
            return "eden"
        return "flatpak run " + FLATPAK_ID

    def launcher_script(self):
        return f"""#!/bin/bash
# Generated by the Eden Settings Decky plugin; rewritten whenever the plugin loads, so do not edit it.
# Optional: put an executable script at ${{XDG_CONFIG_HOME:-$HOME/.config}}/eden-settings/pre-launch and it runs first,
# with the game path as its argument (for example to assign controllers).
LOG=/tmp/eden-settings-launch.log
{{ echo "=== $(date '+%F %T') start: $*"; }} >> "$LOG"
HOOK="${{XDG_CONFIG_HOME:-$HOME/.config}}/eden-settings/pre-launch"
if [ -x "$HOOK" ]; then "$HOOK" "$@" >> "$LOG" 2>&1; fi
{self.eden_command()} -f -g "$1" >> "$LOG" 2>&1
echo "=== $(date '+%F %T') Eden stopped (exit $?)" >> "$LOG"
"""

    def ensure_launcher(self):
        """Write (or refresh) the launcher that Steam shortcuts point at; returns its path."""
        directory = os.path.dirname(self.backup_dir)
        path = os.path.join(directory, LAUNCHER_NAME)
        text = self.launcher_script()
        try:
            with open(path, encoding="utf-8") as f:
                current = f.read()
        except OSError:
            current = None
        if current != text:
            os.makedirs(directory, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.chmod(tmp, os.stat(tmp).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            os.replace(tmp, path)
        return path

    def icon_dirs(self):
        dirs = []
        for d in self.game_dirs():
            dirs += [os.path.join(d, "artwork"), os.path.join(os.path.dirname(d), "artwork")]
        dirs.append(os.path.join(self.home, "Emulation/switch/artwork"))
        seen, out = set(), []
        for d in dirs:
            if d not in seen and os.path.isdir(d):
                seen.add(d)
                out.append(d)
        return out

    def find_icon(self, title_id):
        """Path of a game icon named `<TITLEID>-icon.jpg|png` or `<TITLEID>.jpg|png` in an `artwork` folder."""
        title_id = title_id.upper()
        if not re.fullmatch(r"[0-9A-F]{16}", title_id):
            return None
        for d in self.icon_dirs():
            for name in (title_id + "-icon", title_id):
                for ext in ICON_EXTENSIONS:
                    for cand in (f"{name}.{ext}", f"{name.lower()}.{ext}"):
                        p = os.path.join(d, cand)
                        if os.path.isfile(p) and os.path.getsize(p) <= MAX_ICON_BYTES:
                            return p
        return None

    def icon_data_url(self, title_id):
        p = self.find_icon(title_id)
        if not p:
            return None
        mime = "image/png" if p.lower().endswith(".png") else "image/jpeg"
        with open(p, "rb") as f:
            return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")

    def save_shortcut_icon(self, title_id, b64png):
        """Store the shortcut's small icon as a file (Steam's SetShortcutIcon wants a path); returns that path."""
        title_id = title_id.upper()
        if not re.fullmatch(r"[0-9A-F]{16}", title_id):
            raise EdenCfgError("invalid title id")
        data = base64.b64decode(b64png, validate=True)
        if len(data) > MAX_ICON_BYTES:
            raise EdenCfgError("icon too large")
        directory = os.path.join(os.path.dirname(self.backup_dir), "icons")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, title_id + ".png")
        with open(path, "wb") as f:
            f.write(data)
        return path

    def backups(self):
        return len(glob.glob(os.path.join(self.backup_dir, "*.bak")))

    def info(self):
        return dict(
            installed=self.kind is not None,
            kind=self.kind,
            version=flatpak_version(self.home) if self.kind == "flatpak" else None,
            config_dir=self.cfg_dir,
            game_dirs=self.game_dirs(),
            backup_dir=self.backup_dir,
            backups=self.backups(),
            launcher=os.path.join(os.path.dirname(self.backup_dir), LAUNCHER_NAME),
        )

    def state(self):
        g_lines = self._read(self.global_path)
        glob_vals = {s["key"]: self._global_value(g_lines, s) for s in SETTINGS}
        games = []
        for g in self.games():
            lines = self._read(os.path.join(self.custom_dir, g["id"] + ".ini"))
            games.append(dict(g, has_icon=self.find_icon(g["id"]) is not None, overrides={s["key"]: self._game_override(lines, s) for s in SETTINGS}))
        return dict(
            eden_running=self._running(),
            info=self.info(),
            schema=[dict(key=s["key"], group=s["group"], default=s["default"], options=list(s["options"]))
                    for s in SETTINGS],
            global_values=glob_vals,
            games=games,
        )

    # ------------------------------------------------------------------ writing
    def _check_write(self, key, value):
        s = BY_KEY.get(key)
        if s is None:
            raise EdenCfgError(f"unknown setting: {key}")
        if str(value) not in s["options"]:
            raise EdenCfgError(f"invalid value for {key}: {value}")
        if self.kind is None:
            raise EdenCfgError("eden_not_found")
        if self._running():
            raise EdenCfgError("eden_running")
        return s

    def _write(self, path, lines):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            os.makedirs(self.backup_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(path, os.path.join(self.backup_dir, f"{os.path.basename(path)}.{stamp}.bak"))
            baks = sorted(glob.glob(os.path.join(self.backup_dir, os.path.basename(path) + ".*.bak")))
            for old in baks[:-BACKUPS_TO_KEEP]:
                os.remove(old)
        tmp = path + ".edenplugin.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        if os.path.exists(path):
            shutil.copymode(path, tmp)
        os.replace(tmp, path)

    def set_global(self, key, value):
        s = self._check_write(key, value)
        lines = self._read(self.global_path)
        _set(lines, s["section"], s["key"] + "\\default", "false")
        _set(lines, s["section"], s["key"], str(value))
        self._write(self.global_path, lines)

    def set_game(self, title_id, key, value):
        """value=None puts the game back on 'follow global'."""
        title_id = title_id.upper()
        if not re.fullmatch(r"[0-9A-F]{16}", title_id):
            raise EdenCfgError("invalid title id")
        if value is None:
            s = BY_KEY.get(key)
            if s is None:
                raise EdenCfgError(f"unknown setting: {key}")
            if self.kind is None:
                raise EdenCfgError("eden_not_found")
            if self._running():
                raise EdenCfgError("eden_running")
        else:
            s = self._check_write(key, value)
        path = os.path.join(self.custom_dir, title_id + ".ini")
        lines = self._read(path)
        if value is None:
            if _get(lines, s["section"], s["key"] + "\\use_global") is None:
                return  # nothing to undo
            _set(lines, s["section"], s["key"] + "\\use_global", "true")
        else:
            _set(lines, s["section"], s["key"] + "\\use_global", "false")
            _set(lines, s["section"], s["key"] + "\\default", "false")
            _set(lines, s["section"], s["key"], str(value))
        self._write(path, lines)

    def reset_game(self, title_id):
        for s in SETTINGS:
            self.set_game(title_id, s["key"], None)
