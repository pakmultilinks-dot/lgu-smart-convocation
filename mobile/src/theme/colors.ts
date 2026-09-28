// LGU brand palette. Deep navy is the primary surface colour, gold is used
// sparingly for active indicators and dividers, green signals success.

export const colors = {
  navy: "#0B2447",
  navyDark: "#071A36",
  navySoft: "#14315E",
  gold: "#C9A227",
  goldSoft: "#E9D48A",
  green: "#1B7A3D",
  greenSoft: "#E3F2E8",
  red: "#B3261E",
  redSoft: "#F9E4E2",
  amber: "#9A6B1A",
  amberSoft: "#FBF0D9",
  white: "#FFFFFF",
  background: "#F2F4F8",
  card: "#FFFFFF",
  text: "#16233A",
  muted: "#5C6B84",
  border: "#DFE5EE",
  inputBg: "#FFFFFF",
  overlay: "rgba(7, 26, 54, 0.72)",
} as const;

export type ColorName = keyof typeof colors;
