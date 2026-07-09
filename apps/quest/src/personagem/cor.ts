/** Utilitários de cor para o sombreamento 3D (gradientes de volume). */
function hexRgb(h: string): [number, number, number] {
  let s = h.replace("#", "");
  if (s.length === 3) s = s.split("").map((c) => c + c).join("");
  const n = parseInt(s, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgbHex([r, g, b]: number[]): string {
  return "#" + [r, g, b]
    .map((x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, "0"))
    .join("");
}
export function clarear(h: string, amt: number): string {
  const [r, g, b] = hexRgb(h);
  return rgbHex([r + (255 - r) * amt, g + (255 - g) * amt, b + (255 - b) * amt]);
}
export function escurecer(h: string, amt: number): string {
  const [r, g, b] = hexRgb(h);
  return rgbHex([r * (1 - amt), g * (1 - amt), b * (1 - amt)]);
}
