import { colors } from "./colors";

/**
 * Restrained ink shadows — Phase 35C. Shadows are rare (at most one raised
 * element per screen); ink-tinted, low opacity, no colored glows.
 */
export const elevation = {
  soft: {
    shadowColor: colors.ink,
    shadowOpacity: 0.06,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  raised: {
    shadowColor: colors.ink,
    shadowOpacity: 0.12,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
} as const;
