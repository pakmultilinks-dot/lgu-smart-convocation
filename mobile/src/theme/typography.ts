// Type scale for the app. Headings are bold, body text is regular, captions
// are small and muted.

export const fontSize = {
  display: 32,
  title: 24,
  heading: 20,
  subheading: 17,
  body: 15,
  caption: 13,
  small: 11,
} as const;

export const fontWeight = {
  regular: "400" as const,
  medium: "500" as const,
  semibold: "600" as const,
  bold: "700" as const,
};
