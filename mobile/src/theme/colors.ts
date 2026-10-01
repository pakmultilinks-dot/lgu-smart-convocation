// LGU brand palette, institutional green edition.
// Deep ink greens lead, white stays dominant, gold is reserved for the
// convocation hero premium touch only. Accents are muted on purpose: this
// is an official university tool, not a game.

export const colors = {
  greenDark: "#16382B",
  greenDeep: "#1E4D38",
  green: "#2A6B47",
  emerald: "#35794C",
  emeraldSoft: "#E3EDE5",
  tint: "#EDF2EE",
  white: "#FFFFFF",
  background: "#F4F6F5",
  card: "#FFFFFF",
  text: "#182420",
  muted: "#64766B",
  border: "#DCE5DE",
  inputBg: "#FFFFFF",
  overlay: "rgba(22, 56, 43, 0.55)",
  gold: "#B8912A",
  goldSoft: "#F6EED6",
  red: "#B3261E",
  redSoft: "#F9E4E2",
  amber: "#9A6B1A",
  amberSoft: "#FBF0D9",
} as const;

export type ColorName = keyof typeof colors;
