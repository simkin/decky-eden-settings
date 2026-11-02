import de from "./locales/de.json";
import en from "./locales/en.json";
import es from "./locales/es.json";
import fr from "./locales/fr.json";
import nl from "./locales/nl.json";

type Dict = Record<string, string>;
export type Vars = Record<string, string | number>;
export type Translate = (key: string, vars?: Vars) => string;

/** English is the source of truth and the fallback for every missing key and every unsupported language. */
const LOCALES: Record<string, Dict> = { en, nl, de, fr, es };

/** Steam's language names (SteamClient.Settings.GetCurrentLanguage) -> our locale codes. */
const STEAM_LANGUAGES: Record<string, string> = {
  english: "en",
  dutch: "nl",
  german: "de",
  french: "fr",
  spanish: "es",
  latam: "es",
};

export function normalizeLanguage(raw: string | undefined | null): string {
  if (!raw) return "en";
  const s = raw.toLowerCase();
  const code = STEAM_LANGUAGES[s] ?? s.split(/[-_]/)[0];
  return code in LOCALES ? code : "en";
}

/** Manual override, handy for testing or for a language Steam is not set to:
 *  run `localStorage.setItem("eden-settings-language", "de")` in the Steam dev console (remove it to go back to auto). */
const OVERRIDE_KEY = "eden-settings-language";

/** Reads Steam's UI language; falls back to the browser language and finally to English. */
export async function detectLanguage(): Promise<string> {
  try {
    const forced = window.localStorage?.getItem(OVERRIDE_KEY);
    if (forced) return normalizeLanguage(forced);
  } catch {
    /* localStorage can be unavailable; ignore */
  }
  try {
    const steam = (window as any).SteamClient?.Settings?.GetCurrentLanguage;
    if (typeof steam === "function") {
      const lang = await steam.call((window as any).SteamClient.Settings);
      if (lang) return normalizeLanguage(lang);
    }
  } catch (e) {
    console.warn("Eden Settings: could not read Steam language", e);
  }
  return normalizeLanguage((window as any).LocalizationManager?.m_rgLocalesToUse?.[0] ?? navigator.language);
}

export function makeTranslator(language: string): Translate {
  const dict = LOCALES[language] ?? en;
  return (key, vars) => {
    const text = dict[key] ?? (en as Dict)[key] ?? key;
    return vars ? text.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m)) : text;
  };
}

/** True when English (the source locale) defines this key. */
export function hasKey(key: string): boolean {
  return key in en;
}
