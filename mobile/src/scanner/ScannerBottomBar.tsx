import { Ionicons } from "@expo/vector-icons";
import { Pressable, Switch, Text, View } from "react-native";
import { colors, fonts, radius, spacing } from "../theme";
import { AppButton } from "../ui";

/**
 * Scanner controls under the camera (Phase 35B Parts A/F/G + QA fix
 * cycle 2): labeled Flash (≥48dp), Find manually → existing Search flow,
 * then one compact status line (offline switch + queue + Sync) and the
 * gates error/no-gates notice. Purely presentational; the hierarchy
 * stays camera-first and fits without scrolling.
 */
export function ScannerBottomBar({
  torch,
  torchSupported,
  onTorchToggle,
  onFindManual,
  online,
  offline,
  onOfflineChange,
  queued,
  syncing,
  onSync,
  gatesError,
  onRetryGates,
}: {
  torch: boolean;
  /** 35L (C1): false where the platform exposes no torch (e.g. web). */
  torchSupported: boolean;
  onTorchToggle: () => void;
  onFindManual: () => void;
  /** Actual network reachability (null until the first probe). This is
      the connection truth — never derived from the offline preference. */
  online: boolean | null;
  offline: boolean;
  onOfflineChange: (value: boolean) => void;
  queued: number;
  syncing: boolean;
  onSync: () => void;
  gatesError: string | null;
  onRetryGates: () => void;
}) {
  return (
    <View style={styles.wrap}>
      <View style={styles.actionRow}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Toggle flash"
          accessibilityState={{ selected: torch, disabled: !torchSupported }}
          disabled={!torchSupported}
          onPress={onTorchToggle}
          style={({ pressed }) => [
            styles.flashButton,
            torch && styles.flashButtonActive,
            !torchSupported && styles.flashButtonDisabled,
            pressed && styles.pressed,
          ]}
        >
          <Ionicons
            name={torch ? "flash" : "flash-outline"}
            size={20}
            color={torch ? colors.paper : colors.ink}
          />
          <Text style={[styles.flashLabel, torch && styles.flashLabelActive]}>
            {torchSupported ? "Flash" : "Flash unavailable"}
          </Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Find manually"
          onPress={onFindManual}
          style={({ pressed }) => [styles.findButton, pressed && styles.pressed]}
        >
          <Ionicons name="search" size={20} color={colors.ink} />
          <Text style={styles.findLabel}>Find manually</Text>
        </Pressable>
      </View>

      {/* QA fix cycle 2 (scanner layout): one compact status line —
          offline state + queue + sync sit BELOW the actions, never a
          second bulky block between the camera and the controls. */}
      <View style={styles.statusRow}>
        {/* 33-QA (P8-28): the toggle carries its own accessible name —
            screen readers announce the switch itself, not an anonymous
            control sitting beside the visible "Offline mode" text. */}
        <Switch
          value={offline}
          onValueChange={onOfflineChange}
          trackColor={{ false: colors.track, true: colors.ink }}
          thumbColor={colors.paper}
          accessibilityLabel="Offline mode"
          accessibilityHint="Queue scans on this device and sync later"
        />
        {/* QA fix cycle 3 (Issue 1): the NETWORK status (line 1) is kept
            separate from the offline PREFERENCE (line 2). The label shows
            the real connection — it never reads "Online" just because the
            queueing switch is off; when the server is unreachable it says
            "Offline". The preference is stated plainly on/off with its
            full explanation so the volunteer knows exactly what the
            switch does. */}
        <View style={styles.statusText}>
          <Text style={styles.offlineLabel}>
            {syncing
              ? "Syncing"
              : online === false
                ? "Offline"
                : online
                  ? "Online"
                  : "Connecting"}
          </Text>
          <Text style={styles.offlineHint}>
            {offline
              ? "On. Scans are saved on this phone and sent later."
              : "Off. Scans send right away."}
          </Text>
        </View>
        {queued > 0 ? (
          <Text style={styles.offlineHint}>{`${queued} waiting`}</Text>
        ) : null}
        {queued > 0 ? (
          <AppButton
            label={syncing ? "Syncing..." : "Sync now"}
            icon="cloud-upload-outline"
            variant="secondary"
            loading={syncing}
            onPress={onSync}
          />
        ) : null}
      </View>

      {gatesError ? (
        <View style={styles.gateNotice}>
          <Text style={styles.gateNoticeText}>
            Gates could not be loaded. Check the connection, then retry.
          </Text>
          <AppButton label="Retry gates" icon="refresh" variant="secondary" onPress={onRetryGates} />
        </View>
      ) : null}
    </View>
  );
}

const styles = {
  wrap: {
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  pressed: { opacity: 0.7 },
  actionRow: {
    flexDirection: "row" as const,
    gap: spacing.sm,
  },
  flashButton: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    gap: spacing.sm,
    minHeight: 48,
    paddingHorizontal: spacing.md,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.ink,
    backgroundColor: colors.paper,
  },
  flashButtonActive: {
    backgroundColor: colors.ink,
    borderColor: colors.ink,
  },
  flashButtonDisabled: {
    borderColor: colors.track,
    backgroundColor: colors.track,
  },
  flashLabel: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  flashLabelActive: {
    color: colors.paper,
  },
  findButton: {
    flex: 1,
    flexDirection: "row" as const,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    gap: spacing.sm,
    minHeight: 48,
    paddingHorizontal: spacing.md,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.ink,
    backgroundColor: colors.paper,
  },
  findLabel: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  statusRow: {
    // QA fix cycle 2: single compact status line under the actions.
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
    flexWrap: "wrap" as const,
  },
  statusText: {
    // 33-QA (Issue 1): the two-line status block flexes and wraps so the
    // Sync action is never pushed off a narrow viewfinder.
    flex: 1,
    minWidth: 160,
    gap: 2,
  },
  offlineLabel: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  offlineHint: {
    // 35M item 18: helper sentence — sans, not DM Mono.
    fontFamily: fonts.displayMedium,
    fontSize: 11,
    color: colors.muted,
  },
  gateNotice: {
    gap: spacing.sm,
  },
  gateNoticeText: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.muted,
    lineHeight: 21,
  },
};
