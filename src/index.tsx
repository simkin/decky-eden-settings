import {
  ButtonItem,
  DropdownItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { CSSProperties, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { FaGamepad } from "react-icons/fa";
import { makeArtwork } from "./artwork";
import { detectLanguage, hasKey, makeTranslator, Translate } from "./i18n";
import { addSteamShortcut, findShortcut, removeSteamShortcut } from "./shortcuts";

interface Setting {
  key: string;
  group: string;
  default: string;
  options: string[];
}
interface Game {
  id: string;
  name: string;
  version: number;
  path: string | null;
  has_icon: boolean;
  overrides: Record<string, string | null>;
}
interface Info {
  installed: boolean;
  kind: "flatpak" | "native" | null;
  version: string | null;
  config_dir: string;
  game_dirs: string[];
  backup_dir: string;
  backups: number;
  launcher: string;
  plugin_version?: string;
}
interface State {
  eden_running: boolean;
  info: Info;
  schema: Setting[];
  global_values: Record<string, string>;
  games: Game[];
}
interface Result {
  ok: boolean;
  error?: string;
}

const getState = callable<[], State>("get_state");
const setGlobal = callable<[key: string, value: string], Result>("set_global");
const setGame = callable<[titleId: string, key: string, value: string | null], Result>("set_game");
const resetGame = callable<[titleId: string], Result>("reset_game");
const saveIcon = callable<[titleId: string, data: string], string | null>("save_icon");
const getIcon = callable<[titleId: string], string | null>("get_icon");

const FOLLOW_GLOBAL = "__global__";
const GROUPS = ["image", "performance", "fixes"];

const small: CSSProperties = { fontSize: "12px", lineHeight: 1.35, opacity: 0.8 };
const heading: CSSProperties = {
  fontSize: "12px",
  fontWeight: 700,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  opacity: 0.8,
  paddingTop: "10px",
};

/** Label for a stored value. Values that were set by hand in Eden and that we have no label for show as-is. */
function optionLabel(t: Translate, s: Setting, value: string): string {
  const key = `option.${s.key}.${value}`;
  return hasKey(key) ? t(key) : value;
}

/** Keeps a value that falls outside our presets (set manually in Eden) visible instead of hiding it. */
function optionValues(s: Setting, current: string | null | undefined): string[] {
  return current != null && !s.options.includes(current) ? [...s.options, current] : s.options;
}

/** "FIFO (default)" -> "FIFO": keeps the "Global (...)" entry short enough to fit the dropdown button. */
function shortLabel(label: string): string {
  return label.replace(/\s*\(.*\)\s*$/, "") || label;
}

function errorText(t: Translate, error?: string): string {
  if (error === "eden_running" || error === "eden_not_found") return t(`toast.${error}`);
  return error ?? t("toast.unknown");
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <PanelSectionRow>
      <div style={{ width: "100%", paddingBottom: "6px" }}>
        <div style={{ ...small, opacity: 0.7 }}>{label}</div>
        <div style={{ fontSize: "13px", lineHeight: 1.35, overflowWrap: "anywhere" }}>{children}</div>
      </div>
    </PanelSectionRow>
  );
}

function StatusBlock({ t, state }: { t: Translate; state: State }) {
  const { info } = state;
  if (!info.installed) {
    return (
      <PanelSection title={t("status.notFound.title")}>
        <PanelSectionRow>
          <div style={small}>{t("status.notFound.body")}</div>
        </PanelSectionRow>
      </PanelSection>
    );
  }
  return (
    <PanelSection title={t("status.title")}>
      <PanelSectionRow>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "14px", fontWeight: 600 }}>
          <span
            style={{
              width: "10px",
              height: "10px",
              borderRadius: "50%",
              flexShrink: 0,
              background: state.eden_running ? "#e0a030" : "#4cb860",
            }}
          />
          <span>{state.eden_running ? t("status.running") : t("status.idle")}</span>
          {info.version && <span style={{ ...small, marginLeft: "auto" }}>v{info.version}</span>}
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={small}>{state.eden_running ? t("status.hint.running") : t("status.hint.idle")}</div>
      </PanelSectionRow>
    </PanelSection>
  );
}

function InfoBlock({ t, info }: { t: Translate; info: Info }) {
  return (
    <PanelSection title={t("info.title")}>
      <Row label={t("info.version")}>{info.version ?? t("info.unknown")}</Row>
      <Row label={t("info.install")}>
        {info.kind ? t(`info.install.${info.kind}`) : t("info.unknown")}
      </Row>
      <Row label={t("info.config")}>{info.config_dir}/qt-config.ini</Row>
      <Row label={t("info.launcher")}>{info.launcher}</Row>
      <Row label={t("info.games")}>
        {info.game_dirs.length ? info.game_dirs.map((d) => <div key={d}>{d}</div>) : t("info.gamesNone")}
      </Row>
      <Row label={t("info.backups")}>
        <div>{t("info.backups.value", { n: info.backups })}</div>
        <div style={small}>{t("info.backups.where", { path: info.backup_dir })}</div>
      </Row>
      <Row label={t("info.plugin")}>{info.plugin_version ?? t("info.unknown")}</Row>
    </PanelSection>
  );
}

function Content({ t }: { t: Translate }) {
  const [state, setState] = useState<State | null>(null);
  const [gameId, setGameId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [shortcutTick, setShortcutTick] = useState(0); // bumped after a Steam shortcut changes, to re-read Steam's list

  const refresh = useCallback(async () => {
    try {
      const s = await getState();
      setState(s);
      setGameId((prev) => (prev && s.games.some((g) => g.id === prev) ? prev : (s.games[0]?.id ?? "")));
    } catch (e) {
      console.error("Eden Settings: loading failed", e);
      toaster.toast({ title: t("toast.title"), body: t("toast.loadFailed") });
    }
  }, [t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const act = async (fn: () => Promise<Result>) => {
    setBusy(true);
    try {
      const r = await fn();
      if (!r.ok) toaster.toast({ title: t("toast.title"), body: errorText(t, r.error) });
    } catch (e) {
      console.error("Eden Settings: action failed", e);
      toaster.toast({ title: t("toast.title"), body: t("toast.actionFailed") });
    } finally {
      await refresh();
      setBusy(false);
    }
  };

  const shortcutAction = async (game: Game, info: Info, existing: ReturnType<typeof findShortcut>) => {
    setBusy(true);
    const name = `${game.name} (Eden)`;
    try {
      if (existing) {
        await removeSteamShortcut(existing.appid);
        toaster.toast({ title: t("toast.title"), body: t("toast.shortcutRemoved", { name: existing.name }) });
      } else {
        const art = await makeArtwork(game.name, game.has_icon ? await getIcon(game.id) : null);
        await addSteamShortcut(name, info.launcher, game.path as string, art, (png) => saveIcon(game.id, png));
        toaster.toast({ title: t("toast.title"), body: t("toast.shortcutAdded", { name }) });
      }
    } catch (e) {
      console.error("Eden Settings: Steam shortcut failed", e);
      toaster.toast({ title: t("toast.title"), body: t("toast.shortcutFailed") });
    } finally {
      // Steam updates its app list asynchronously; give it a moment before re-reading.
      setTimeout(() => setShortcutTick((n) => n + 1), 800);
      setBusy(false);
    }
  };

  if (!state) {
    return (
      <PanelSection title={t("app.title")} spinner>
        <PanelSectionRow>{t("loading")}</PanelSectionRow>
      </PanelSection>
    );
  }

  const locked = busy || state.eden_running || !state.info.installed;
  const game = state.games.find((g) => g.id === gameId);
  const customCount = game ? state.schema.filter((s) => game.overrides[s.key] != null).length : 0;

  const groups = GROUPS.map((g) => ({ id: g, settings: state.schema.filter((s) => s.group === g) })).filter(
    (g) => g.settings.length > 0,
  );

  return (
    <>
      <StatusBlock t={t} state={state} />

      <PanelSection title={t("section.global")}>
        <PanelSectionRow>
          <div style={small}>{t("section.global.hint")}</div>
        </PanelSectionRow>
        {groups.map((g) => (
          <div key={g.id}>
            <PanelSectionRow>
              <div style={heading}>{t(`group.${g.id}`)}</div>
            </PanelSectionRow>
            {g.settings.map((s) => {
              const cur = state.global_values[s.key] ?? s.default;
              return (
                <PanelSectionRow key={s.key}>
                  <DropdownItem
                    layout="below"
                    label={t(`setting.${s.key}.label`)}
                    description={t(`setting.${s.key}.desc`)}
                    disabled={locked}
                    rgOptions={optionValues(s, cur).map((v) => ({ data: v, label: optionLabel(t, s, v) }))}
                    selectedOption={cur}
                    onChange={(o) => act(() => setGlobal(s.key, o.data as string))}
                  />
                </PanelSectionRow>
              );
            })}
          </div>
        ))}
      </PanelSection>

      <PanelSection title={t("section.game")}>
        {state.games.length === 0 ? (
          <PanelSectionRow>
            <div style={small}>{t("game.none")}</div>
          </PanelSectionRow>
        ) : (
          <>
            <PanelSectionRow>
              <DropdownItem
                    layout="below"
                label={t("game.pick")}
                description={
                  <>
                    {t("game.pick.desc")}
                    {game && (
                      <>
                        <br />
                        <b>{customCount > 0 ? t(customCount === 1 ? "game.custom.one" : "game.custom.other", { n: customCount }) : t("game.customNone")}</b>
                        <br />
                        {game.id}
                      </>
                    )}
                  </>
                }
                disabled={busy}
                rgOptions={state.games.map((g) => ({ data: g.id, label: g.name }))}
                selectedOption={gameId}
                onChange={(o) => setGameId(o.data as string)}
              />
            </PanelSectionRow>
            {game && (
              <PanelSectionRow key={`shortcut-${game.id}-${shortcutTick}`}>
                {(() => {
                  const existing = findShortcut(game);
                  if (!game.path && !existing) return <div style={small}>{t("shortcut.noPath")}</div>;
                  return (
                    <ButtonItem
                      layout="below"
                      disabled={busy}
                      description={
                        existing
                          ? t("shortcut.remove.desc", { name: existing.name })
                          : t("shortcut.add.desc") + (game.has_icon ? "" : " " + t("shortcut.noIcon", { id: game.id }))
                      }
                      onClick={() => shortcutAction(game, state.info, existing)}
                    >
                      {existing ? t("shortcut.remove") : t("shortcut.add")}
                    </ButtonItem>
                  );
                })()}
              </PanelSectionRow>
            )}
            {game &&
              groups.map((g) => (
                <div key={game.id + g.id}>
                  <PanelSectionRow>
                    <div style={heading}>{t(`group.${g.id}`)}</div>
                  </PanelSectionRow>
                  {g.settings.map((s) => {
                    const override = game.overrides[s.key] ?? null;
                    const globalCur = state.global_values[s.key] ?? s.default;
                    const rg = [
                      {
                        data: FOLLOW_GLOBAL,
                        label: t("game.followGlobal", { value: shortLabel(optionLabel(t, s, globalCur)) }),
                      },
                      ...optionValues(s, override).map((v) => ({ data: v, label: optionLabel(t, s, v) })),
                    ];
                    return (
                      <PanelSectionRow key={game.id + s.key}>
                        <DropdownItem
                    layout="below"
                          label={t(`setting.${s.key}.label`)}
                          description={t(`setting.${s.key}.desc`)}
                          disabled={locked}
                          rgOptions={rg}
                          selectedOption={override ?? FOLLOW_GLOBAL}
                          onChange={(o) =>
                            act(() => setGame(game.id, s.key, o.data === FOLLOW_GLOBAL ? null : (o.data as string)))
                          }
                        />
                      </PanelSectionRow>
                    );
                  })}
                </div>
              ))}
            {game && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  description={t("game.reset.desc")}
                  disabled={locked || customCount === 0}
                  onClick={() => act(() => resetGame(game.id))}
                >
                  {t("game.reset")}
                </ButtonItem>
              </PanelSectionRow>
            )}
          </>
        )}
      </PanelSection>

      <InfoBlock t={t} info={state.info} />
    </>
  );
}

function Root() {
  const [language, setLanguage] = useState<string | null>(null);
  useEffect(() => {
    detectLanguage().then(setLanguage);
  }, []);
  const t = useMemo(() => makeTranslator(language ?? "en"), [language]);
  if (language === null) {
    return (
      <PanelSection spinner>
        <PanelSectionRow>…</PanelSectionRow>
      </PanelSection>
    );
  }
  return <Content t={t} />;
}

export default definePlugin(() => {
  return {
    name: "Eden Settings",
    titleView: <div className={staticClasses.Title}>Eden Settings</div>,
    content: <Root />,
    icon: <FaGamepad />,
    onDismount() {},
  };
});
