import {
  CameraView,
  useCameraPermissions,
  type BarcodeScanningResult,
} from "expo-camera";
import * as Haptics from "expo-haptics";
import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Animated,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  ApiError,
  fetchDemoPayload,
  fetchGates,
  postScan,
  postSync,
  type Gate,
  type ScanMode,
  type ScanResult,
} from "../api/client";
import { PrimaryButton } from "../components/PrimaryButton";
import { ResultCard } from "../components/ResultCard";
import { SegmentedControl } from "../components/SegmentedControl";
import { SectionCard } from "../components/SectionCard";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import {
  enqueueScan,
  getQueue,
  queueCount,
  reconcileSync,
} from "../store/offlineQueue";
import { getVolunteerName, setVolunteerName } from "../store/settings";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

function localTimestamp(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
    minute: "2-digit",
    month: "2-digit",
    second: "2-digit",
    timeZone: "Asia/Karachi",
    year: "numeric",
  }).formatToParts(new Date());
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}:${get("second")}`;
}

function ViewfinderCorners() {
  return (
    <View style={styles.frame} pointerEvents="none">
      <View style={[styles.corner, styles.cornerTL]} />
      <View style={[styles.corner, styles.cornerTR]} />
      <View style={[styles.corner, styles.cornerBL]} />
      <View style={[styles.corner, styles.cornerBR]} />
    </View>
  );
}

const RESULT_DISMISS_MS = 4000;

export function ScannerScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const [gates, setGates] = useState<Gate[]>([]);
  const [gatesError, setGatesError] = useState<string | null>(null);
  const [gateId, setGateId] = useState<number | null>(null);
  const [mode, setMode] = useState<ScanMode>("entry");
  const [volunteer, setVolunteer] = useState("");
  const [offline, setOffline] = useState(false);
  const [torch, setTorch] = useState(false);
  const [queued, setQueued] = useState(0);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);

  const scanningRef = useRef(false);
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [scanAnim] = useState(() => new Animated.Value(0));

  // Web has no real camera preview in this build: show a clean animated
  // placeholder instead of the native camera view.
  useEffect(() => {
    if (Platform.OS !== "web") {
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(scanAnim, {
          duration: 1800,
          toValue: 1,
          useNativeDriver: true,
        }),
        Animated.timing(scanAnim, {
          duration: 1800,
          toValue: 0,
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [scanAnim]);

  const loadGates = useCallback(async () => {
    try {
      const list = await fetchGates();
      setGates(list);
      setGateId((prev) => prev ?? list[0]?.id ?? null);
      setGatesError(null);
    } catch (e) {
      setGatesError(
        e instanceof ApiError ? e.message : "Could not load gates.",
      );
    }
  }, []);

  const refreshQueueCount = useCallback(async () => {
    setQueued(await queueCount());
  }, []);

  useEffect(() => {
    void loadGates();
    void refreshQueueCount();
    void getVolunteerName().then(setVolunteer);
  }, [loadGates, refreshQueueCount]);

  useFocusEffect(
    useCallback(() => {
      void refreshQueueCount();
      return () => undefined;
    }, [refreshQueueCount]),
  );

  const showResult = useCallback((r: ScanResult) => {
    if (dismissTimer.current) {
      clearTimeout(dismissTimer.current);
    }
    setResult(r);
    dismissTimer.current = setTimeout(() => setResult(null), RESULT_DISMISS_MS);
  }, []);

  const dismissResult = useCallback(() => {
    if (dismissTimer.current) {
      clearTimeout(dismissTimer.current);
      dismissTimer.current = null;
    }
    setResult(null);
  }, []);

  const handleBarcode = useCallback(
    async (scan: BarcodeScanningResult) => {
      if (scanningRef.current || !scan.data) {
        return;
      }
      scanningRef.current = true;
      try {
        const payload = scan.data;
        const volunteerName = volunteer.trim() || "Volunteer";
        if (gateId === null) {
          showResult({
            detail: "Choose a gate before scanning.",
            level: "red",
            status: "error",
            title: "NO GATE SELECTED",
          });
          return;
        }
        if (offline) {
          const { duplicate } = await enqueueScan({
            gate_id: gateId,
            mode,
            payload,
            scanned_at: localTimestamp(),
            volunteer: volunteerName,
          });
          await refreshQueueCount();
          await Haptics.notificationAsync(
            Haptics.NotificationFeedbackType.Warning,
          );
          showResult({
            detail: duplicate
              ? "This scan is already queued on this device."
              : "Saved on this device. Press Sync now when back online.",
            level: "amber",
            status: "ok",
            title: duplicate ? "ALREADY QUEUED" : "SCAN QUEUED",
          });
          return;
        }
        const response = await postScan({
          gate_id: gateId,
          mode,
          payload,
          volunteer: volunteerName,
        });
        if (response.status === "ok") {
          await Haptics.notificationAsync(
            Haptics.NotificationFeedbackType.Success,
          );
        } else {
          await Haptics.notificationAsync(
            Haptics.NotificationFeedbackType.Error,
          );
        }
        showResult(response);
      } catch (e) {
        await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        showResult({
          detail:
            e instanceof ApiError
              ? e.message
              : "The scan could not be verified. Try again.",
          level: "red",
          status: "error",
          title: "SCAN FAILED",
        });
      } finally {
        setTimeout(() => {
          scanningRef.current = false;
        }, 1200);
      }
    },
    [gateId, mode, offline, refreshQueueCount, showResult, volunteer],
  );

  const handleSync = useCallback(async () => {
    const items = await getQueue();
    if (items.length === 0) {
      return;
    }
    setSyncing(true);
    try {
      const response = await postSync(items);
      const { remaining, accepted, rejected } = await reconcileSync(
        response.results,
      );
      setQueued(remaining.length);
      await Haptics.notificationAsync(
        Haptics.NotificationFeedbackType.Success,
      );
      const lines = [`${accepted} scan(s) counted.`];
      if (rejected.length > 0) {
        lines.push(
          `${rejected.length} did NOT count: ` +
            rejected.map((r) => r.title).join(", ") +
            ".",
        );
      }
      if (remaining.length > 0) {
        lines.push(`${remaining.length} still queued, will retry.`);
      }
      showResult({
        detail: lines.join(" "),
        level: rejected.length > 0 ? "amber" : "green",
        status: "ok",
        title: "SYNC COMPLETE",
      });
    } catch (e) {
      showResult({
        detail:
          e instanceof ApiError
            ? e.message
            : "Sync failed. The queue is kept on this device.",
        level: "red",
        status: "error",
        title: "SYNC FAILED",
      });
    } finally {
      setSyncing(false);
    }
  }, [showResult]);

  const handleDemoScan = useCallback(async () => {
    setDemoLoading(true);
    try {
      const demo = await fetchDemoPayload();
      if (!demo.payload) {
        showResult({
          detail: demo.hint,
          level: "amber",
          status: "error",
          title: "NO DEMO AVAILABLE",
        });
        return;
      }
      await handleBarcode({ data: demo.payload } as BarcodeScanningResult);
    } catch (e) {
      showResult({
        detail: e instanceof ApiError ? e.message : "Demo scan failed.",
        level: "red",
        status: "error",
        title: "DEMO FAILED",
      });
    } finally {
      setDemoLoading(false);
    }
  }, [handleBarcode, showResult]);

  const saveVolunteer = useCallback((name: string) => {
    void setVolunteerName(name);
  }, []);

  if (!permission) {
    return <LoadingState message="Checking camera permission..." />;
  }

  if (!permission.granted) {
    return (
      <View style={styles.permissionWrap}>
        <EmptyState
          icon="camera-outline"
          title="Camera access needed"
          message="The scanner needs the camera to read QR codes at the gate."
        />
        <View style={styles.permissionButton}>
          <PrimaryButton
            title="Grant camera permission"
            onPress={() => void requestPermission()}
          />
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <ScrollView style={styles.scroll} keyboardShouldPersistTaps="handled">
        <SectionCard title="Gate Setup" subtitle="Pick your gate before the crowd arrives">
          {gatesError ? (
            <ErrorState message={gatesError} onRetry={() => void loadGates()} />
          ) : gates.length === 0 ? (
            <Text style={styles.noGatesText}>
              No gates found on the server. Ask the admin to add gates, then
              pull to refresh.
            </Text>
          ) : (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.gateRow}
            >
              {gates.map((gate) => {
                const active = gate.id === gateId;
                return (
                  <Pressable
                    key={gate.id}
                    onPress={() => {
                      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      setGateId(gate.id);
                    }}
                    style={({ pressed }) => [
                      styles.gateChip,
                      active && styles.gateChipActive,
                      pressed && styles.pressed,
                    ]}
                  >
                    <Text
                      style={[
                        styles.gateChipText,
                        active && styles.gateChipTextActive,
                      ]}
                    >
                      {gate.label}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          )}

          <View style={styles.row}>
            <View style={styles.segmentWrap}>
              <SegmentedControl<ScanMode>
                options={[
                  { label: "Entry", value: "entry" },
                  { label: "Exit", value: "exit" },
                ]}
                value={mode}
                onChange={setMode}
              />
            </View>
            <Pressable
              onPress={() => setTorch((t) => !t)}
              style={[styles.iconButton, torch && styles.iconButtonActive]}
            >
              <Ionicons
                name={torch ? "flash" : "flash-outline"}
                size={22}
                color={torch ? colors.white : colors.greenDark}
              />
            </Pressable>
          </View>

          <TextInput
            style={styles.input}
            placeholder="Volunteer name"
            placeholderTextColor={colors.muted}
            value={volunteer}
            onChangeText={setVolunteer}
            onEndEditing={(e) => saveVolunteer(e.nativeEvent.text)}
            autoCapitalize="words"
            returnKeyType="done"
          />

          <View style={styles.offlineRow}>
            <View style={styles.offlineLeft}>
              <Ionicons name="cloud-offline-outline" size={18} color={colors.muted} />
              <Text style={styles.offlineLabel}>Offline mode</Text>
              {queued > 0 && (
                <View style={styles.queueBadge}>
                  <Text style={styles.queueBadgeText}>{queued} queued</Text>
                </View>
              )}
            </View>
            <Switch
              value={offline}
              onValueChange={setOffline}
              trackColor={{ false: colors.border, true: colors.emerald }}
              thumbColor={offline ? colors.white : colors.white}
            />
          </View>

          {queued > 0 && (
            <View style={styles.syncWrap}>
              <PrimaryButton
                title={syncing ? "Syncing..." : `Sync now (${queued})`}
                onPress={() => void handleSync()}
                loading={syncing}
                variant="accent"
              />
            </View>
          )}
        </SectionCard>

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
              <View style={styles.cameraHintPill}>
                <Text style={styles.cameraHint}>
                  Point the camera at a student QR card
                </Text>
              </View>
            </View>
          ) : (
            <View style={styles.cameraWrap}>
              <CameraView
                style={styles.camera}
                facing="back"
                enableTorch={torch}
                barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
                onBarcodeScanned={handleBarcode}
              />
              <ViewfinderCorners />
              <View style={styles.scanLine} />
              <View style={styles.cameraHintPill}>
                <Text style={styles.cameraHint}>
                  Point the camera at a student QR card
                </Text>
              </View>
            </View>
          )}
        </View>

        <View style={styles.footer}>
          <PrimaryButton
            title="Demo scan (no camera)"
            onPress={() => void handleDemoScan()}
            loading={demoLoading}
            variant="outline"
          />
        </View>
        <View style={styles.bottomPad} />
      </ScrollView>

      {result && <ResultCard result={result} onDismiss={dismissResult} />}
    </View>
  );
}

const CORNER = 40;
const FRAME = 250;

const styles = StyleSheet.create({
  bottomPad: {
    height: spacing.md,
  },
  camera: {
    ...StyleSheet.absoluteFill,
  },
  cameraCard: {
    borderRadius: radius.lg,
    elevation: 4,
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
    overflow: "hidden",
    shadowColor: colors.greenDark,
    shadowOffset: { height: 3, width: 0 },
    shadowOpacity: 0.2,
    shadowRadius: 10,
  },
  cameraHint: {
    color: colors.white,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.medium,
  },
  cameraHintPill: {
    alignSelf: "center",
    backgroundColor: "rgba(8, 74, 39, 0.75)",
    borderRadius: radius.full,
    bottom: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    position: "absolute",
  },
  cameraWrap: {
    backgroundColor: colors.greenDark,
    height: 340,
    overflow: "hidden",
    position: "relative",
  },
  corner: {
    borderColor: colors.emerald,
    height: CORNER,
    position: "absolute",
    width: CORNER,
  },
  cornerBL: {
    borderBottomWidth: 4,
    borderLeftWidth: 4,
    bottom: 0,
    left: 0,
  },
  cornerBR: {
    borderBottomWidth: 4,
    borderRightWidth: 4,
    bottom: 0,
    right: 0,
  },
  cornerTL: {
    borderLeftWidth: 4,
    borderTopWidth: 4,
    left: 0,
    top: 0,
  },
  cornerTR: {
    borderRightWidth: 4,
    borderTopWidth: 4,
    right: 0,
    top: 0,
  },
  footer: {
    padding: spacing.md,
  },
  frame: {
    alignSelf: "center",
    height: FRAME,
    marginTop: -FRAME / 2,
    position: "absolute",
    top: "50%",
    width: FRAME,
  },
  gateChip: {
    backgroundColor: colors.tint,
    borderColor: colors.border,
    borderRadius: radius.full,
    borderWidth: 1,
    marginRight: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  gateChipActive: {
    backgroundColor: colors.green,
    borderColor: colors.green,
    elevation: 2,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
  },
  gateChipText: {
    color: colors.text,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
  },
  gateChipTextActive: {
    color: colors.white,
  },
  gateRow: {
    paddingBottom: spacing.sm,
  },
  iconButton: {
    alignItems: "center",
    backgroundColor: colors.tint,
    borderColor: colors.border,
    borderRadius: radius.lg,
    borderWidth: 1,
    height: 52,
    justifyContent: "center",
    width: 52,
  },
  iconButtonActive: {
    backgroundColor: colors.green,
    borderColor: colors.green,
  },
  input: {
    backgroundColor: colors.inputBg,
    borderColor: colors.border,
    borderRadius: radius.md,
    borderWidth: 1,
    color: colors.text,
    fontSize: fontSize.body,
    marginTop: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  noGatesText: {
    color: colors.muted,
    fontSize: fontSize.body,
    paddingVertical: spacing.sm,
  },
  offlineLabel: {
    color: colors.text,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
    marginLeft: spacing.xs,
  },
  offlineLeft: {
    alignItems: "center",
    flexDirection: "row",
  },
  offlineRow: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: spacing.md,
  },
  permissionButton: {
    padding: spacing.md,
    width: "100%",
  },
  permissionWrap: {
    backgroundColor: colors.background,
    flex: 1,
  },
  pressed: {
    opacity: 0.85,
  },
  queueBadge: {
    backgroundColor: colors.gold,
    borderRadius: radius.full,
    marginLeft: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  queueBadgeText: {
    color: colors.greenDark,
    fontSize: fontSize.small,
    fontWeight: fontWeight.bold,
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  row: {
    alignItems: "center",
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  scanLine: {
    alignSelf: "center",
    backgroundColor: "rgba(22, 163, 74, 0.9)",
    borderRadius: 2,
    height: 3,
    marginTop: -1.5,
    position: "absolute",
    top: "50%",
    width: "86%",
  },
  scroll: {
    flex: 1,
  },
  segmentWrap: {
    flex: 1,
  },
  syncWrap: {
    marginTop: spacing.sm,
  },
  webScanLine: {
    alignSelf: "center",
    backgroundColor: colors.emerald,
    borderRadius: 2,
    height: 3,
    position: "absolute",
    top: "50%",
    width: "86%",
  },
  webViewfinder: {
    alignItems: "center",
    backgroundColor: "#22332B",
    height: 340,
    justifyContent: "center",
    overflow: "hidden",
    position: "relative",
  },
});
