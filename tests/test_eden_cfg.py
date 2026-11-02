import difflib
import glob
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py_modules"))
import eden_cfg as E  # noqa: E402

PINBALL = "0100DB7003828000"
MK8D = "0100152000022000"
FLATPAK_CFG = ".var/app/dev.eden_emu.eden/config/eden"


def ini(sections):
    """Build an INI text in Eden's layout: every setting is `key\\default=` + `key=` inside its section."""
    out = []
    for section, pairs in sections.items():
        out.append(f"[{section}]")
        for key, (default, value) in pairs.items():
            out.append(f"{key}\\default={default}")
            out.append(f"{key}={value}")
        out.append("")
    return "\n".join(out)


GLOBAL_INI = ini({
    "Renderer": {
        "resolution_setup": ("true", "3"),
        "scaling_filter": ("false", "6"),
        "anti_aliasing": ("true", "0"),
        "max_anisotropy": ("false", "5"),
        "vram_usage_mode": ("false", "1"),
    },
    "Core": {"speed_limit": ("true", "100")},
}) + "\n[UI]\nPaths\\gamedirs\\size=3\nPaths\\gamedirs\\1\\path=SDMC\nPaths\\gamedirs\\2\\path=UserNAND\n"

# A per-game file as Eden writes it: everything starts as use_global=true.
GAME_INI = "\n".join(
    ["[Renderer]"] + [f"{s['key']}\\use_global=true" for s in E.SETTINGS if s["section"] == "Renderer"]
    + ["", "[Core]"] + [f"{s['key']}\\use_global=true" for s in E.SETTINGS if s["section"] == "Core"]
    + ["", "[System]", "use_docked_mode\\use_global=true", ""])


def diff_lines(a, b):
    return [l for l in difflib.unified_diff(a.split("\n"), b.split("\n"), lineterm="", n=0)
            if l[:1] in "+-" and l[:3] not in ("+++", "---")]


class Base(unittest.TestCase):
    running = False

    @staticmethod
    def read(p):
        with open(p) as f:
            return f.read()

    @staticmethod
    def write(p, text=""):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = os.path.join(self.tmp, FLATPAK_CFG)
        self.write(os.path.join(cfg, "qt-config.ini"), GLOBAL_INI)
        self.write(os.path.join(cfg, "custom", MK8D + ".ini"),
                   GAME_INI.replace("resolution_setup\\use_global=true",
                                    "resolution_setup\\use_global=false\nresolution_setup\\default=false\nresolution_setup=6"))
        self.write(os.path.join(cfg, "custom", PINBALL + ".ini"), GAME_INI)
        games = os.path.join(self.tmp, "Emulation/switch/games")
        for n in (f"Pinball FX3 [{PINBALL}][v0].nsp", f"Mario Kart 8 Deluxe [{MK8D.lower()}][v0].xci", "readme.txt"):
            self.write(os.path.join(games, n))
        self.cfg = E.EdenCfg(self.tmp, os.path.join(self.tmp, "bk"), running_check=lambda: self.running, environ={})
        self.gpath = self.cfg.global_path

    def tearDown(self):
        shutil.rmtree(self.tmp)


class TestDiscovery(Base):
    def test_flatpak_install_detected(self):
        self.assertEqual(self.cfg.kind, "flatpak")

    def test_native_install_detected_via_xdg(self):
        home = tempfile.mkdtemp()
        try:
            self.write(os.path.join(home, "xdg/eden/qt-config.ini"), GLOBAL_INI)
            c = E.EdenCfg(home, os.path.join(home, "bk"), environ={"XDG_CONFIG_HOME": os.path.join(home, "xdg")})
            self.assertEqual(c.kind, "native")
            self.assertEqual(c.cfg_dir, os.path.join(home, "xdg/eden"))
        finally:
            shutil.rmtree(home)

    def test_not_installed(self):
        home = tempfile.mkdtemp()
        try:
            c = E.EdenCfg(home, os.path.join(home, "bk"), environ={})
            self.assertIsNone(c.kind)
            self.assertFalse(c.info()["installed"])
            with self.assertRaises(E.EdenCfgError) as cm:
                c.set_global("anti_aliasing", "2")
            self.assertEqual(str(cm.exception), "eden_not_found")
            self.assertEqual(c.games(), [])
        finally:
            shutil.rmtree(home)

    def test_flatpak_version_read_from_metainfo(self):
        meta = os.path.join(self.tmp, ".local/share/flatpak/app/dev.eden_emu.eden/current/active/files/share/metainfo")
        self.write(os.path.join(meta, "dev.eden_emu.eden.metainfo.xml"),
                   '<component><releases>\n\t\t<release version="0.2.1" date="2026-06-01">\n</releases></component>')
        self.assertEqual(E.flatpak_version(self.tmp), "0.2.1")
        self.assertEqual(self.cfg.info()["version"], "0.2.1")

    def test_flatpak_version_missing_is_none(self):
        self.assertIsNone(E.flatpak_version(self.tmp))


class TestGames(Base):
    def test_games_parsed_sorted_and_id_uppercased(self):
        g = self.cfg.games()
        self.assertEqual([x["name"] for x in g], ["Mario Kart 8 Deluxe", "Pinball FX3"])
        self.assertEqual(g[0]["id"], MK8D)

    def test_game_dirs_come_from_eden_config_and_special_dirs_are_skipped(self):
        extra = os.path.join(self.tmp, "roms")
        self.write(os.path.join(extra, f"Zelda [01007EF00011E000][v0].nsp"))
        lines = self.read(self.gpath).replace("Paths\\gamedirs\\size=3",
                                              "Paths\\gamedirs\\size=4\nPaths\\gamedirs\\4\\path=" + extra)
        self.write(self.gpath, lines)
        self.assertIn(extra, self.cfg.game_dirs())
        self.assertNotIn("SDMC", self.cfg.game_dirs())
        self.assertIn("Zelda", [g["name"] for g in self.cfg.games()])

    def test_game_with_only_a_config_file_is_listed_by_id(self):
        self.write(os.path.join(self.cfg.custom_dir, "0100AAAA0000BBBB.ini"), GAME_INI)
        names = {g["id"]: g["name"] for g in self.cfg.games()}
        self.assertEqual(names["0100AAAA0000BBBB"], "0100AAAA0000BBBB")

    def test_scan_depth_is_limited(self):
        deep = os.path.join(self.tmp, "Emulation/switch/games/a/b/c/d")
        self.write(os.path.join(deep, "Deep [0100DEEP0000DEEP][v0].nsp"))  # not hex -> ignored anyway
        self.write(os.path.join(deep, "Deep [0100DDDD0000DDDD][v0].nsp"))
        self.assertNotIn("0100DDDD0000DDDD", [g["id"] for g in self.cfg.games()])


class TestState(Base):
    def test_global_values_use_defaults_when_eden_says_default(self):
        v = self.cfg.state()["global_values"]
        self.assertEqual(v["scaling_filter"], "6")       # explicit FSR
        self.assertEqual(v["max_anisotropy"], "5")
        self.assertEqual(v["vram_usage_mode"], "1")
        self.assertEqual(v["resolution_setup"], "3")     # \default=true -> built-in default
        self.assertEqual(v["use_vsync"], "2")            # key absent entirely -> built-in default

    def test_game_overrides(self):
        games = {g["id"]: g for g in self.cfg.state()["games"]}
        self.assertEqual(games[MK8D]["overrides"]["resolution_setup"], "6")
        self.assertIsNone(games[PINBALL]["overrides"]["resolution_setup"])

    def test_schema_has_no_texts_only_keys_and_values(self):
        for s in self.cfg.state()["schema"]:
            self.assertEqual(set(s), {"key", "group", "default", "options"})
            self.assertIn(s["default"], s["options"], s["key"])


class TestGlobalWrite(Base):
    def test_only_the_intended_lines_change(self):
        before = self.read(self.gpath)
        self.cfg.set_global("anti_aliasing", "2")
        d = diff_lines(before, self.read(self.gpath))
        self.assertEqual(sorted(d), sorted(["-anti_aliasing\\default=true", "+anti_aliasing\\default=false",
                                            "-anti_aliasing=0", "+anti_aliasing=2"]))
        self.assertEqual(self.cfg.state()["global_values"]["anti_aliasing"], "2")

    def test_new_key_is_appended_to_its_section_not_the_end_of_file(self):
        self.cfg.set_global("rescale_hack", "true")
        lines = self.read(self.gpath).split("\n")
        i = lines.index("rescale_hack=true")
        self.assertEqual(lines[i - 1], "rescale_hack\\default=false")
        section = [l for l in lines[:i] if l.startswith("[")][-1]
        self.assertEqual(section, "[Renderer]")

    def test_missing_section_is_created(self):
        self.cfg.set_global("use_docked_mode", "0")
        self.assertIn("[System]", self.read(self.gpath))
        self.assertEqual(self.cfg.state()["global_values"]["use_docked_mode"], "0")

    def test_backup_made_before_every_write_and_pruned(self):
        for i in range(25):
            self.cfg.set_global("anti_aliasing", str(i % 3))
        self.assertLessEqual(len(glob.glob(os.path.join(self.tmp, "bk", "qt-config.ini.*.bak"))), E.BACKUPS_TO_KEEP)
        self.assertGreater(self.cfg.backups(), 0)

    def test_refuses_while_eden_runs(self):
        self.running = True
        before = self.read(self.gpath)
        with self.assertRaises(E.EdenCfgError) as cm:
            self.cfg.set_global("anti_aliasing", "2")
        self.assertEqual(str(cm.exception), "eden_running")
        self.assertEqual(before, self.read(self.gpath))

    def test_rejects_unknown_key_and_invalid_value(self):
        with self.assertRaises(E.EdenCfgError):
            self.cfg.set_global("not_a_setting", "1")
        with self.assertRaises(E.EdenCfgError):
            self.cfg.set_global("anti_aliasing", "99")

    def test_no_temp_file_left_behind(self):
        self.cfg.set_global("anti_aliasing", "1")
        self.assertEqual(glob.glob(os.path.join(self.cfg.cfg_dir, "*.tmp")), [])


class TestGameWrite(Base):
    def path(self, tid):
        return os.path.join(self.cfg.custom_dir, tid + ".ini")

    def test_override_writes_the_three_lines_eden_needs(self):
        self.cfg.set_game(PINBALL, "anti_aliasing", "2")
        lines = self.read(self.path(PINBALL)).split("\n")
        self.assertIn("anti_aliasing\\use_global=false", lines)
        self.assertIn("anti_aliasing\\default=false", lines)
        self.assertIn("anti_aliasing=2", lines)
        games = {g["id"]: g for g in self.cfg.state()["games"]}
        self.assertEqual(games[PINBALL]["overrides"]["anti_aliasing"], "2")

    def test_follow_global_only_flips_use_global(self):
        self.cfg.set_game(MK8D, "resolution_setup", None)
        games = {g["id"]: g for g in self.cfg.state()["games"]}
        self.assertIsNone(games[MK8D]["overrides"]["resolution_setup"])

    def test_follow_global_on_untouched_setting_changes_nothing(self):
        before = self.read(self.path(PINBALL))
        self.cfg.set_game(PINBALL, "anti_aliasing", None)
        self.assertEqual(before, self.read(self.path(PINBALL)))

    def test_reset_game_clears_every_override(self):
        self.cfg.set_game(MK8D, "anti_aliasing", "1")
        self.cfg.reset_game(MK8D)
        games = {g["id"]: g for g in self.cfg.state()["games"]}
        self.assertTrue(all(v is None for v in games[MK8D]["overrides"].values()))

    def test_other_games_untouched(self):
        before = self.read(self.path(PINBALL))
        self.cfg.set_game(MK8D, "anti_aliasing", "1")
        self.assertEqual(before, self.read(self.path(PINBALL)))

    def test_creates_config_for_game_without_one(self):
        self.cfg.set_game("0100AAAA0000BBBB", "rescale_hack", "true")
        self.assertTrue(os.path.exists(self.path("0100AAAA0000BBBB")))

    def test_bad_title_id_rejected(self):
        for bad in ("../../etc/passwd", "123", "ZZZZZZZZZZZZZZZZ", ""):
            with self.assertRaises(E.EdenCfgError):
                self.cfg.set_game(bad, "anti_aliasing", "1")

    def test_refuses_while_eden_runs(self):
        self.running = True
        with self.assertRaises(E.EdenCfgError):
            self.cfg.set_game(MK8D, "anti_aliasing", "1")
        with self.assertRaises(E.EdenCfgError):
            self.cfg.set_game(MK8D, "anti_aliasing", None)


class TestSteamShortcutSupport(Base):
    PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20

    def test_games_carry_their_file_path(self):
        by_id = {g["id"]: g for g in self.cfg.games()}
        self.assertTrue(by_id[PINBALL]["path"].endswith(f"Pinball FX3 [{PINBALL}][v0].nsp"))
        self.assertTrue(os.path.isfile(by_id[PINBALL]["path"]))

    def test_config_only_game_has_no_path(self):
        self.write(os.path.join(self.cfg.custom_dir, "0100AAAA0000BBBB.ini"), GAME_INI)
        g = {x["id"]: x for x in self.cfg.games()}["0100AAAA0000BBBB"]
        self.assertIsNone(g["path"])

    def test_flatpak_launcher_runs_hook_then_eden_with_game_as_one_argument(self):
        text = self.cfg.launcher_script()
        self.assertTrue(text.startswith("#!/bin/bash"))
        self.assertIn("flatpak run dev.eden_emu.eden -f -g \"$1\"", text)
        self.assertLess(text.index("pre-launch"), text.index("flatpak run"))

    def test_native_launcher_finds_an_appimage(self):
        home = tempfile.mkdtemp()
        try:
            self.write(os.path.join(home, ".config/eden/qt-config.ini"), GLOBAL_INI)
            app = os.path.join(home, "Applications/Eden-1.0.AppImage")
            self.write(app, "#!/bin/sh\n")
            os.chmod(app, 0o755)
            c = E.EdenCfg(home, os.path.join(home, "data/bk"), environ={})
            self.assertEqual(c.kind, "native")
            self.assertEqual(c.eden_command(), '"' + app + '"')
        finally:
            shutil.rmtree(home)

    def test_ensure_launcher_creates_an_executable_file_and_is_idempotent(self):
        path = self.cfg.ensure_launcher()
        self.assertEqual(path, os.path.join(self.tmp, "launch-eden"))
        self.assertTrue(os.access(path, os.X_OK))
        first = os.stat(path).st_mtime_ns
        self.assertEqual(self.cfg.ensure_launcher(), path)
        self.assertEqual(os.stat(path).st_mtime_ns, first)  # unchanged content -> not rewritten
        self.assertEqual(self.cfg.info()["launcher"], path)

    def test_ensure_launcher_repairs_an_outdated_file(self):
        path = self.cfg.ensure_launcher()
        self.write(path, "old")
        self.cfg.ensure_launcher()
        self.assertIn("flatpak run", self.read(path))

    def test_find_icon_in_artwork_folder_next_to_games_folder(self):
        art = os.path.join(self.tmp, "Emulation/switch/artwork")
        self.assertIsNone(self.cfg.find_icon(PINBALL))
        self.write(os.path.join(art, PINBALL + "-icon.jpg"), "jpegdata")
        self.assertEqual(self.cfg.find_icon(PINBALL.lower()), os.path.join(art, PINBALL + "-icon.jpg"))
        self.assertTrue(self.cfg.icon_data_url(PINBALL).startswith("data:image/jpeg;base64,"))
        self.assertTrue({g["id"]: g for g in self.cfg.state()["games"]}[PINBALL]["has_icon"])
        self.assertFalse({g["id"]: g for g in self.cfg.state()["games"]}[MK8D]["has_icon"])

    def test_find_icon_rejects_bad_ids(self):
        self.assertIsNone(self.cfg.find_icon("../../etc/passwd"))

    def test_save_shortcut_icon_writes_a_png_and_validates_input(self):
        import base64
        path = self.cfg.save_shortcut_icon(PINBALL, base64.b64encode(self.PNG).decode())
        self.assertEqual(path, os.path.join(self.tmp, "icons", PINBALL + ".png"))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), self.PNG)
        with self.assertRaises(E.EdenCfgError):
            self.cfg.save_shortcut_icon("../evil", base64.b64encode(self.PNG).decode())
        with self.assertRaises(ValueError):
            self.cfg.save_shortcut_icon(PINBALL, "not base64 !!!")


if __name__ == "__main__":
    unittest.main()
