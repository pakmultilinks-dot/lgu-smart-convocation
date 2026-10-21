import { Ionicons } from "@expo/vector-icons";
import { Pressable, Text, View } from "react-native";
import type { Occasion, ScanMode } from "../api/client";
import { colors, fonts, radius, spacing } from "../theme";
import { SegmentedControl, StatusPill } from "../ui";

/**
 * Scanner top area (Phase 35B Part A/B): current gate (tappable → gate
 * sheet), Entry/Exit, and the connection pill. Own layout zone above
 * the camera — it cannot overlap the viewfinder.
 *
 * User-directed visual revert (post-release-blocker review): the Entry/
 * Exit presentation returns to the previous compact treatment — the
 * shared SegmentedControl with a neutral selected state (ink active
 * segment on track), and no large semantic ENTRY/EXIT banner or
 * full-width mode colors above the camera. QA fix cycle 2 removed the
 * gate-text gold underline (the sanctioned gold accent is the active
 * tab underline in the tab bar only). Scan-result colors (valid/
 * invalid/amber) stay reserved for scan outcomes in ScannerResult
 * (design law unchanged).
 *
 * Security/integrity wiring is intentionally untouched: onModeChange
 * still routes through requestModeChange in ScannerScreen, which opens
 * the confirmation modal ("Switch mode? Scanning will stop on this
 * device.") before the mode actually changes.
 */
export function ScannerTopBar({
  gateLabel,
  mode,
  occasion,
  online,
  onModeChange,
  onOccasionChange,
  onOpenSheet,
}: {
  gateLabel: string;
  mode: ScanMode;
  occasion: Occasion;
  online: boolean | null;
  onModeChange: (mode: ScanMode) => void;
  onOccasionChange: (occasion: Occasion) => void;
  onOpenSheet: () => void;
}) {
  return (
    <View style={styles.wrap}>
      <View style={styles.row}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Current gate ${gateLabel}. Change gate`}
          onPress={onOpenSheet}
          style={({ pressed }) => [styles.gateButton, pressed && styles.pressed]}
        >
          <Ionicons name="location-outline" size={18} color={colors.ink} />
          <View style={styles.gateText}>
            <Text style={styles.gateCaption}>Gate</Text>
            <Text style={styles.gateLabel}>{gateLabel}</Text>
          </View>
          <Ionicons name="chevron-down" size={16} color={colors.muted} />
        </Pressable>
        <StatusPill
          state={online === false ? "offline" : online ? "live" : "connecting"}
          label={online === false ? "Offline" : online ? "Online" : "—"}
          size="sm"
        />
      </View>

      {/* QA fix cycle 4 (Finding 2): the selected direction carries a
          distinct semantic accent — Entry = green (success), Exit = amber
          (a clear contrast to entry) — so the volunteer always knows at a
          glance which way scans are being recorded. onModeChange still
          routes through requestModeChange → the confirmation modal in
          ScannerScreen ("Switch to Exit? Scans will be recorded as
          exits."). */}
      <SegmentedControl<ScanMode>
        options={[
          { label: "Entry", value: "entry" },
          { label: "Exit", value: "exit" },
        ]}
        value={mode}
        onChange={onModeChange}
        activeColor={mode === "exit" ? colors.amber : colors.valid}
      />

      {/* Phase 29: which occasion of the annual cycle these scans record.
          Same confirmation discipline as Entry/Exit — onOccasionChange
          routes through requestOccasionChange → the confirmation modal in
          ScannerScreen ("Switch to Rehearsal? Scans will be recorded as
          rehearsal check-ins."), so the volunteer never flips occasion by
          accident. Default is the main convocation. */}
      <SegmentedControl<Occasion>
        options={[
          { label: "Main convocation", value: "ceremony" },
          { label: "Rehearsal", value: "rehearsal" },
        ]}
        value={occasion}
        onChange={onOccasionChange}
        activeColor={occasion === "rehearsal" ? colors.amber : colors.valid}
      />
    </View>
  );
}

const styles = {
  wrap: {
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  row: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
  },
  gateButton: {
    flex: 1,
    minWidth: 0,
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
    minHeight: 48,
    paddingHorizontal: spacing.md,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.ink,
    backgroundColor: colors.paper,
  },
  pressed: {
    opacity: 0.7,
  },
  gateText: {
    flex: 1,
    minWidth: 0,
  },
  gateCaption: {
    // 35M item 18: "Gate" is a normal label, not a status chip or a
    // G1–G7 identifier — sans, not DM Mono.
    fontFamily: fonts.displayMedium,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase" as const,
    letterSpacing: 0.4,
  },
  gateLabel: {
    fontFamily: fonts.display,
    fontSize: 15,
    color: colors.ink,
  },
};
