/** Draws Steam library artwork for a game on a canvas (no image library needed), in the style
 *  "blurred icon background + icon + title + EDEN badge". Returns base64 PNGs (without the data-URL prefix). */

export interface Artwork {
  grid_p: string; // portrait capsule 600x900
  grid_l: string; // wide capsule 920x430
  hero: string; // 1920x620
  logo: string; // 800x300, transparent
  icon: string; // 256x256
}

const FONT = '"Motiva Sans", "Noto Sans", sans-serif';
const BADGE = "#7b4dff";
const BADGE_TEXT = "EDEN";

function canvas(w: number, h: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return [c, c.getContext("2d") as CanvasRenderingContext2D];
}

const b64 = (c: HTMLCanvasElement) => c.toDataURL("image/png").split(",")[1];

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("icon could not be loaded"));
    img.src = src;
  });
}

/** Splits a title over at most two lines at the word boundary that balances them best. */
export function splitTitle(title: string): string[] {
  const words = title.trim().split(/\s+/);
  if (words.length < 2 || title.length <= 14) return [title.trim()];
  let best = 1;
  let bestDiff = Infinity;
  for (let i = 1; i < words.length; i++) {
    const diff = Math.abs(words.slice(0, i).join(" ").length - words.slice(i).join(" ").length);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = i;
    }
  }
  return [words.slice(0, best).join(" "), words.slice(best).join(" ")];
}

function background(w: number, h: number, icon: HTMLImageElement | null, dark: number) {
  const [c, ctx] = canvas(w, h);
  if (icon) {
    const side = Math.max(w, h) * 1.3;
    ctx.filter = "blur(28px)";
    ctx.drawImage(icon, (w - side) / 2, (h - side) / 2, side, side);
    ctx.filter = "none";
  } else {
    const g = ctx.createLinearGradient(0, 0, w, h);
    g.addColorStop(0, "#3a2d7a");
    g.addColorStop(1, "#15111f");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
  }
  ctx.fillStyle = `rgba(0,0,0,${1 - dark})`;
  ctx.fillRect(0, 0, w, h);
  return { c, ctx };
}

function badge(ctx: CanvasRenderingContext2D, x: number, y: number, size: number) {
  ctx.font = `bold ${size}px ${FONT}`;
  const pad = size * 0.55;
  const w = ctx.measureText(BADGE_TEXT).width + pad * 2;
  const h = size * 1.9;
  ctx.fillStyle = BADGE;
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, size * 0.5);
  ctx.fill();
  ctx.fillStyle = "#fff";
  ctx.textBaseline = "middle";
  ctx.fillText(BADGE_TEXT, x + pad, y + h / 2 + size * 0.04);
  ctx.textBaseline = "alphabetic";
}

function text(ctx: CanvasRenderingContext2D, lines: string[], x: number, y: number, size: number, step: number) {
  ctx.fillStyle = "#fff";
  ctx.font = `bold ${size}px ${FONT}`;
  lines.forEach((l, i) => ctx.fillText(l, x, y + step * i));
}

export async function makeArtwork(title: string, iconUrl: string | null): Promise<Artwork> {
  let icon: HTMLImageElement | null = null;
  if (iconUrl) {
    try {
      icon = await loadImage(iconUrl);
    } catch (e) {
      console.warn("Eden Settings: icon not usable, drawing text artwork", e);
    }
  }
  const lines = splitTitle(title);

  // portrait capsule
  const p = background(600, 900, icon, 0.45);
  if (icon) p.ctx.drawImage(icon, 40, 90, 520, 520);
  text(p.ctx, lines, 40, icon ? 700 : 420, 44, 55);
  badge(p.ctx, 40, 790, 46);

  // wide capsule
  const l = background(920, 430, icon, 0.45);
  if (icon) l.ctx.drawImage(icon, 40, 50, 330, 330);
  text(l.ctx, lines, icon ? 400 : 60, icon ? 175 : 175, 52, 65);
  badge(l.ctx, icon ? 400 : 60, 290, 40);

  // hero
  const h = background(1920, 620, icon, 0.6);

  // logo (transparent)
  const [logoC, logoCtx] = canvas(800, 300);
  text(logoCtx, lines, 0, 110, 52, 62);

  // icon
  const [iconC, iconCtx] = canvas(256, 256);
  if (icon) iconCtx.drawImage(icon, 0, 0, 256, 256);
  else {
    iconCtx.fillStyle = "#3a2d7a";
    iconCtx.fillRect(0, 0, 256, 256);
  }
  badge(iconCtx, 8, 200, 24);

  return { grid_p: b64(p.c), grid_l: b64(l.c), hero: b64(h.c), logo: b64(logoC), icon: b64(iconC) };
}
