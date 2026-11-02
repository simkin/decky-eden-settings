# Changelog

## 1.0.1

- New: *Eden info* has its own tab next to *Settings*; status and version stay visible on top. Every info line is
  focusable, so the gamepad can reach it, and the text is larger and easier to read.
- Fixed: choosing another game (or changing a setting) made the gamepad focus jump to the top of the panel. Rows
  are no longer rebuilt when the game changes, and controls are no longer disabled while a change is being saved.

## 1.0.0

First public release.

- English by default, with Dutch, German, French and Spanish. Follows Steam's language; missing texts fall back to English.
- Every option has a plain-language explanation, and every value says what it does.
- 15 settings, grouped into *Image quality*, *Performance* and *Compatibility*: resolution, upscaling filter, FSR
  sharpness, anti-aliasing, anisotropic filtering, aspect ratio, console mode, video memory use, VSync mode, speed
  limit, forced GPU clock, asynchronous shaders, rescale hack and video decoding.
- Global settings and per-game overrides ("Global" = follow the global value).
- **Steam shortcuts** per game: add or remove a Game Mode tile with generated artwork and icon, through Steam's own
  API. Existing tiles are recognised. A launcher script with an optional `pre-launch` hook starts Eden.
- *Eden info*: status, version, installation type, settings file, game folders, backups and plugin version.
- Finds Eden as a Flatpak (user or system install) or a native/AppImage build, and finds games in Eden's own
  game-list folders.
- Safe by design: refuses to write while Eden runs, backs up the file before every change (last 20 kept), writes
  atomically and only touches the lines it owns.
- Unit tests for the config logic and for locale completeness.
