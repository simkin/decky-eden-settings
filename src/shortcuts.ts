/** Steam library shortcuts ("non-Steam games") through Steam's own client API, so Steam keeps shortcuts.vdf and the
 *  artwork itself and no restart is needed. */
import { Artwork } from "./artwork";

/** Asset type numbers of SteamClient.Apps.SetCustomArtworkForApp. Type 4 ("icon") writes the same file as the wide
 *  capsule, so the small icon is set with SetShortcutIcon instead. */
const ASSET = { grid_p: 0, hero: 1, logo: 2, grid_l: 3 } as const;
/** `app_type` of a non-Steam shortcut in Steam's app overviews. */
const APP_TYPE_SHORTCUT = 1073741824;

export interface Shortcut {
  appid: number;
  name: string;
}

interface GameRef {
  id: string;
  name: string;
  path: string | null;
}

const steam = () => (window as any).SteamClient;
const unquote = (s: string | undefined) => (s ?? "").replace(/^"|"$/g, "");

/** Finds an existing shortcut for this game: its launch option holds the game path (or at least the title ID). */
export function findShortcut(game: GameRef): Shortcut | null {
  try {
    const w = window as any;
    const wantedName = `${game.name} (Eden)`;
    const id = `[${game.id}]`.toLowerCase();
    for (const app of w.appStore.allApps as Iterable<any>) {
      if (app.app_type !== APP_TYPE_SHORTCUT) continue;
      const details = w.appDetailsStore.GetAppDetails(app.appid);
      const launch = unquote(details?.strShortcutLaunchOptions ?? details?.strLaunchOptions);
      const match =
        (game.path && launch === game.path) || launch.toLowerCase().includes(id) || app.display_name === wantedName;
      if (match) return { appid: app.appid, name: app.display_name };
    }
  } catch (e) {
    console.warn("Eden Settings: could not read Steam's shortcut list", e);
  }
  return null;
}

export async function addSteamShortcut(
  name: string,
  launcher: string,
  gamePath: string,
  art: Artwork,
  saveIcon: (png: string) => Promise<string | null>,
): Promise<number> {
  const startDir = launcher.replace(/[^/]+$/, "");
  // Steam wraps the executable in quotes itself; launch options are set separately (AddShortcut leaves them empty).
  const appid: number = await steam().Apps.AddShortcut(name, launcher, startDir, "");
  if (!appid) throw new Error("Steam did not create the shortcut");
  // AddShortcut ignores its name argument (Steam names the tile after the executable), so set it explicitly.
  await steam().Apps.SetShortcutName(appid, name);
  await steam().Apps.SetShortcutLaunchOptions(appid, `"${gamePath}"`);
  for (const kind of Object.keys(ASSET) as (keyof typeof ASSET)[]) {
    await steam().Apps.SetCustomArtworkForApp(appid, art[kind], "png", ASSET[kind]);
  }
  const iconPath = await saveIcon(art.icon);
  if (iconPath) await steam().Apps.SetShortcutIcon(appid, iconPath);
  return appid;
}

export async function removeSteamShortcut(appid: number): Promise<void> {
  await steam().Apps.RemoveShortcut(appid);
}
