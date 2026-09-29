// LGU brand palette, green and white edition, softened.
// Muted forest and sage greens lead, white stays dominant, and gold is
// reserved for the convocation hero premium touch only.

export const colors = {
  greenDark: "#1E4D33",
  greenDeep: "#2A5F40",
  green: "#2F7D4E",
  emerald: "#3E8E5A",
  emeraldSoft: "#E2EFE7",
  tint: "#EFF5F1",
  white: "#FFFFFF",
  background: "#F6F9F7",
  card: "#FFFFFF",
  text: "#1C2B23",
  muted: "#6B7F73",
  border: "#DEE8E1",
  inputBg: "#FFFFFF",
  overlay: "rgba(30, 77, 51, 0.55)",
  gold: "#C9A227",
  goldSoft: "#F8F1DA",
  red: "#B3261E",
  redSoft: "#F9E4E2",
  amber: "#9A6B1A",
  amberSoft: "#FBF0D9",
} as const;

export type ColorName = keyof typeof colors;
