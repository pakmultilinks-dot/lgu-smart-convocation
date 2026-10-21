import { Ionicons } from "@expo/vector-icons";
import {
  CameraView,
  type BarcodeScanningResult,
  type CameraViewProps,
} from "expo-camera";
import { useEffect, useCallback, useRef, useState } from "react";
import {
  ActivityIndicator,
  Animated,
  Platform,
  StyleSheet,
  Text,
  View,
  type LayoutChangeEvent,
} from "react-native";
import type { ScanMode, ScanResult } from "../api/client";
import { colors, fonts, radius, spacing } from "../theme";
import { AppButton, SectionCard } from "../ui";
import { FRAME } from "./scannerConstants";
import { CameraHintPill, ScannerOverlay } from "./ScannerOverlay";
import { ScannerResult } from "./ScannerResult";
import { ViewfinderCorners } from "./ViewfinderCorners";

type MountErrorHandler = NonNullable<CameraViewProps["onMountError"]>;

/**
 * Camera surface — native CameraView with the dim overlay, or the web
 * placeholder loop. Issue 6 (Release blocker): the camera area renders
 * distinct states, each with a recovery action — never one murky
 * "something's wrong":
 *   STARTING — permission granted, waiting for the first frame: spinner
 *              + "Starting camera…" + "Find manually". Cleared by the
 *              native onCameraReady callback.
 *   READY    — live viewfinder with the dim overlay + hint pill.
 *   ERROR    — mount failed: "Camera unavailable" + Try Again / Back /
 *              Find manually (no native error text is shown to operators).
 *   REQUIRED / DENIED live in ScannerScreen — permission is a screen-level
 *   state decided before the camera area ever mounts.
 */
export function CameraScannerView({
  cameraKey,
  zoom,
  torch,
  paused,
  torchSupported,
  onBarcodeScanned,
  onCameraLayout,
  onMountError,
  failed,
  onTryAgain,
  onBack,
  onFindManual,
  ready,
  onCameraReady,
  mode,
  result,
  onDismissResult,
}: {
  cameraKey: number;
  zoom: number;
  torch: boolean;
  /** 35L (G2): scanning pauses while the gate sheet is open. */
  paused: boolean;
  /** 35L (C1): false on web / devices without a torch — never faked. */
  torchSupported: boolean;
  onBarcodeScanned: (scan: BarcodeScanningResult) => void;
  onCameraLayout: (e: LayoutChangeEvent) => void;
  onMountError: MountErrorHandler;
  failed: boolean;
  onTryAgain: () => void;
  onBack: () => void;
  /** Scanner Fix Round 1: "Find manually" recovery from the failed-camera state. */
  onFindManual: () => void;
  /** Issue 6: false between mount and the first frame — the STARTING state. */
  ready: boolean;
  /** Issue 6: fired by the native CameraView when the preview is live. */
  onCameraReady: () => void;
  mode: ScanMode;
  result: ScanResult | null;
  onDismissResult: () => void;
}) {
  // Web placeholder loop animation (camera unavailable on web).
  const [scanAnim] = useState(() => new Animated.Value(0));
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(scanAnim, {
          toValue: 1,
          duration: 1600,
          useNativeDriver: true,
        }),
        Animated.timing(scanAnim, {
          toValue: 0,
          duration: 1600,
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [scanAnim]);

  // Issue 6: web never mounts a native preview — the placeholder IS the
  // ready state, so report ready on mount (the starting overlay never
  // shows over the placeholder).
  useEffect(() => {
    if (Platform.OS === "web") onCameraReady();
  }, [onCameraReady]);

  // Scanner Fix Round 1 (item 3): the native barcode listener stays
  // attached for the whole scanner session — the gate sheet pauses via
  // a ref instead of swapping the callback prop to undefined, so
  // scanning resumes the instant the sheet closes (no native listener
  // teardown / re-registration).
  const pausedRef = useRef(paused);
  const onScanRef = useRef(onBarcodeScanned);
  useEffect(() => {
    pausedRef.current = paused;
    onScanRef.current = onBarcodeScanned;
  });
  const handleBarcodeScanned = useCallback((scan: BarcodeScanningResult) => {
    if (pausedRef.current) return;
    onScanRef.current(scan);
  }, []);

  if (failed) {
    return (
      <SectionCard>
        <View style={styles.cameraError}>
          <Ionicons name="camera-outline" size={28} color={colors.amber} />
          <Text style={styles.cameraErrorTitle}>Camera unavailable</Text>
          <Text style={styles.cameraErrorBody}>
            Please check camera permission or restart the scanner.
          </Text>
          <View style={styles.cameraErrorRow}>
            <AppButton
              label="Try Again"
              icon="refresh"
              onPress={onTryAgain}
            />
            <AppButton
              label="Back"
              icon="arrow-back"
              variant="secondary"
              onPress={onBack}
            />
          </View>
          {/* Scanner Fix Round 1: manual lookup stays reachable from every
              recovery state — never a dead end without the camera. */}
          <AppButton
            label="Find manually"
            icon="search"
            variant="secondary"
            onPress={onFindManual}
          />
        </View>
      </SectionCard>
    );
  }

  /* Camera viewfinder with dim overlay (status lives in the top bar). */
  return (
    <View style={styles.cameraCard}>
      {Platform.OS === "web" ? (
        <View style={styles.webViewfinder}>
          <ViewfinderCorners />
          <Animated.View
            style={[
              styles.webScanLine,
              {
                transform: [
                  {
                    translateY: scanAnim.interpolate({
                      inputRange: [0, 1],
                      outputRange: [-(FRAME / 2) + 16, FRAME / 2 - 16],
                    }),
                  },
                ],
              },
            ]}
          />
          <CameraHintPill text="Camera preview is unavailable in the browser — use a phone" />
        </View>
      ) : (
        <View style={styles.cameraWrap} onLayout={onCameraLayout}>
          {/* 35L (G2): undefined stops the scanner — no reads under the
              sheet. 35L (C1): torch only when the platform has one. */}
          <CameraView
            key={cameraKey}
            style={styles.camera}
            facing="back"
            enableTorch={torch && torchSupported}
            zoom={zoom}
            autofocus="off"
            barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
            onBarcodeScanned={handleBarcodeScanned}
            onMountError={onMountError}
            onCameraReady={onCameraReady}
          />
          <ScannerOverlay>
            {result ? (
              <ScannerResult
                result={result}
                mode={mode}
                onDismiss={onDismissResult}
              />
            ) : null}
          </ScannerOverlay>
          {/* Issue 6: STARTING state — permission granted but the first
              frame hasn't arrived. CameraView stays mounted beneath so
              onCameraReady can still fire; the overlay clears itself. */}
          {!ready ? (
            <View style={styles.startingOverlay}>
              <ActivityIndicator size="large" color={colors.paper} />
              <Text style={styles.startingText}>Starting camera…</Text>
              <AppButton
                label="Find manually"
                icon="search"
                variant="secondary"
                onPress={onFindManual}
              />
            </View>
          ) : null}
          <CameraHintPill text="Point the camera at a student QR card" />
        </View>
      )}
    </View>
  );
}

const styles = {
  cameraCard: {
    flex: 1,
    borderRadius: radius.md,
    overflow: "hidden" as const,
    backgroundColor: "#0B1210",
  },
  cameraWrap: {
    flex: 1,
  },
  startingOverlay: {
    ...StyleSheet.absoluteFill,
    backgroundColor: "rgba(11, 18, 16, 0.88)",
    alignItems: "center" as const,
    justifyContent: "center" as const,
    gap: spacing.sm,
    padding: spacing.md,
  },
  startingText: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.paper,
  },
  camera: {
    ...StyleSheet.absoluteFill,
  },
  webViewfinder: {
    flex: 1,
    alignItems: "center" as const,
    justifyContent: "center" as const,
  },
  webScanLine: {
    position: "absolute" as const,
    width: FRAME - 32,
    height: 2,
    backgroundColor: colors.paper,
  },
  cameraError: {
    alignItems: "center" as const,
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  cameraErrorTitle: {
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: -0.4,
    color: colors.ink,
  },
  cameraErrorBody: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.muted,
    textAlign: "center" as const,
    lineHeight: 21,
  },
  cameraErrorRow: {
    flexDirection: "row" as const,
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
};
