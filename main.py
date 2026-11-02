import os
import sys

import decky

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "py_modules"))
import eden_cfg  # noqa: E402


class Plugin:
    async def _main(self):
        self.cfg = eden_cfg.EdenCfg(decky.DECKY_USER_HOME,
                                    os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "backups"))
        decky.logger.info("Eden Settings started as %s (install: %s, config: %s)",
                          decky.USER, self.cfg.kind or "not found", self.cfg.global_path)

    async def _unload(self):
        decky.logger.info("Eden Settings stopped")

    def _run(self, what, fn):
        try:
            fn()
            decky.logger.info("%s", what)
            return {"ok": True}
        except eden_cfg.EdenCfgError as e:
            decky.logger.info("refused (%s): %s", what, e)
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001 - never leave the frontend hanging
            decky.logger.exception("error during %s", what)
            return {"ok": False, "error": f"internal: {e}"}

    async def get_state(self):
        # Re-detect every time: Eden may have been installed or first started since the plugin loaded.
        self.cfg = eden_cfg.EdenCfg(decky.DECKY_USER_HOME, self.cfg.backup_dir)
        if self.cfg.kind:
            try:
                self.cfg.ensure_launcher()
            except OSError as e:
                decky.logger.warning("could not write the launcher: %s", e)
        state = self.cfg.state()
        state["info"]["plugin_version"] = decky.DECKY_PLUGIN_VERSION
        return state

    async def set_global(self, key: str, value: str):
        return self._run(f"global {key}={value}", lambda: self.cfg.set_global(key, value))

    async def set_game(self, title_id: str, key: str, value):
        label = "follow global" if value is None else value
        return self._run(f"game {title_id} {key}={label}", lambda: self.cfg.set_game(title_id, key, value))

    async def reset_game(self, title_id: str):
        return self._run(f"game {title_id} reset", lambda: self.cfg.reset_game(title_id))

    async def get_icon(self, title_id: str):
        """Game icon as a data URL for the shortcut artwork, or None when there is none."""
        try:
            return self.cfg.icon_data_url(title_id)
        except OSError:
            return None

    async def save_icon(self, title_id: str, data: str):
        """Writes the generated small icon for a Steam shortcut and returns its path (None on failure)."""
        try:
            return self.cfg.save_shortcut_icon(title_id, data)
        except (eden_cfg.EdenCfgError, OSError, ValueError) as e:
            decky.logger.warning("could not save the shortcut icon: %s", e)
            return None
