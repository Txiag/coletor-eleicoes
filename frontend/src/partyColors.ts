const defaultPartyColors: Record<string, string> = {
  PT: "#ef3340",
  PL: "#506cf0",
  AVANTE: "#FFA500",
  MISSÃO: "#FFFF00",
  MISSAO: "#FFFF00",
  UP: "#000000",
  UNIÃO: "#008000",
  UNIAO: "#008000",
};
const palette = [
  "#205fb3",
  "#c83a54",
  "#138477",
  "#9656b5",
  "#cc7c1d",
  "#4c7285",
  "#8b6744",
  "#665db3",
];

export function partyColor(number: string, name: string, preferences: Record<string, string>) {
  return preferences[number] || defaultPartyColors[name.trim().toUpperCase()] || palette[Number(number) % palette.length] || palette[0];
}
