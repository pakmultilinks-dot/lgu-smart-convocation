import type { ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";
import { colors, fonts, radius, spacing } from "../theme";
import { DIM_COLOR, FRAME } from "./scannerConstants";
import { ViewfinderCorners } from "./ViewfinderCorners";

/** Bottom hint pill shared by the live overlay and the web fallback.
    Phase 35I (O): readable sans 13 — not technical mono 11. */
export function CameraHintPill({ text }: { text: string }) {
  return (
    <View style={styles.cameraHintPill}>
      <Text style={styles.cameraHint}>{text}</Text>
    </View>
  );
}

/**
 * Live camera overlay — dimmed frame with the scan window. Phase 35I (M):
 * the in-frame status strip is GONE — it duplicated the scanner top bar
 * (gate + Entry/Exit + connection) above the camera. Children (the result
 * moment) render below the scan window; the hint pill stays at the bottom.
 */
export function ScannerOverlay({
  children,
}: {
  children?: ReactNode;
}) {
  return (
    <>
      <View pointerEvents="none" style={styles.overlay}>
        <View style={styles.dimTop} />
        <View style={styles.dimRow}>
          <View style={styles.dimSide} />
          <View style={styles.scanWindow}>
            <ViewfinderCorners />
          </View>
          <View style={styles.dimSide} />
        </View>
        <View style={styles.dimBottom} />
      </View>

      {children}
    </>
  );
}

const styles = {
  overlay: {
    ...StyleSheet.absoluteFill,
  },
  dimTop: {
    flex: 1,
    backgroundColor: DIM_COLOR,
  },
  dimBottom: {
    flex: 1,
    backgroundColor: DIM_COLOR,
  },
  dimRow: {
    flexDirection: "row" as const,
    height: FRAME,
  },
  dimSide: {
    flex: 1,
    backgroundColor: DIM_COLOR,
  },
  scanWindow: {
    width: FRAME,
    height: FRAME,
    alignItems: "center" as const,
    justifyContent: "center" as const,
  },
  cameraHintPill: {
    position: "absolute" as const,
    bottom: 14,
    alignSelf: "center" as const,
    backgroundColor: "rgba(27, 26, 22, 0.78)",
    borderRadius: radius.full,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
  },
  cameraHint: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.paper,
  },
};
