import { Ionicons } from "@expo/vector-icons";
import { Modal, Pressable, Text, View } from "react-native";
import type { Gate } from "../api/client";
import { colors, fonts, radius, spacing } from "../theme";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppButton } from "../ui";

/**
 * Gate bottom sheet (Phase 35B Part A; 35I Q). Presentation of the SAME
 * selector the scanner already uses — not a second navigation system.
 * The sheet's controls are the GATE ONLY: direction (Entry/Exit) lives in
 * one authoritative place — the scanner top bar (and the Home toggle) —
 * never as a second selector here. Selected gate chip is ink-filled with a
 * check mark beside the short tile name.
 */
export function ScannerSheet({
  visible,
  gates,
  gatesError,
  gateId,
  onSelectGate,
  onClose,
}: {
  visible: boolean;
  gates: Gate[];
  gatesError: string | null;
  gateId: number | null;
  onSelectGate: (gate: Gate) => void;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  // 35M R2 (item 15): this sheet is an RN Modal. On Expo Go (SDK 57) the
  // app does not ship expo-navigation-bar, and app code cannot change the
  // Android system navigation-bar colour while a Modal is open — the system
  // bar renders its default dark treatment over the sheet backdrop. That is
  // OS behaviour, not a missed style; the config intentionally carries no
  // androidNavigationBar control (ui-35j W/Z). A standalone dev-build could
  // re-style the bar via a native dependency — out of this phase's scope.
  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="Close" />
      <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 16) }]}>
        <View style={styles.handle} />
        {/* 35L (G): the sheet names the decision it asks for. The
            title IS the label — the redundant "Gate" eyebrow above the
            chips is removed (35M item 10); the chips carry the names. */}
        <Text style={styles.sheetTitle}>Choose a gate</Text>
        {gatesError ? (
          <Text style={styles.note}>Gates could not be loaded. Close and retry.</Text>
        ) : gates.length === 0 ? (
          <Text style={styles.note}>
            No gates found on the server. Ask the admin to add gates.
          </Text>
        ) : (
          <View style={styles.gateRow}>
            {gates.map((gate, index) => {
              const active = gate.id === gateId;
              const loneTail =
                gates.length % 2 === 1 && index === gates.length - 1;
              return (
                <Pressable
                  key={gate.id}
                  accessibilityRole="button"
                  accessibilityState={{ selected: active }}
                  accessibilityLabel={gate.label}
                  onPress={() => onSelectGate(gate)}
                  style={({ pressed }) => [
                    styles.gateChip,
                    loneTail && styles.gateChipFull,
                    active && styles.gateChipActive,
                    pressed && styles.pressed,
                  ]}
                >
                  <Text
                    style={[styles.gateChipText, active && styles.gateChipTextActive]}
                  >
                    {gate.label.replace(/ Gate$/, "")}
                  </Text>
                  {active ? (
                    <Ionicons name="checkmark" size={18} color={colors.paper} />
                  ) : null}
                </Pressable>
              );
            })}
          </View>
        )}
        <View style={styles.doneRow}>
          <AppButton
            label="Done"
            icon="checkmark"
            disabled={gateId === null}
            onPress={onClose}
          />
        </View>
        <View style={styles.grabZone} />
      </View>
    </Modal>
  );
}

const styles = {
  backdrop: {
    flex: 1,
    backgroundColor: colors.overlay,
  },
  sheet: {
    backgroundColor: colors.paper,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingHorizontal: spacing.screen,
    paddingTop: spacing.md,
    gap: spacing.sm,
  },
  handle: {
    alignSelf: "center" as const,
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.track,
    marginBottom: spacing.xs,
  },
  sheetTitle: {
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: -0.4,
    color: colors.ink,
  },
  gateRow: {
    flexDirection: "row" as const,
    flexWrap: "wrap" as const,
    gap: spacing.sm,
  },
  gateChip: {
    // Two-column equal grid (Phase 35H item 33); row layout so the
    // selected-state check icon sits beside the gate name (item 34).
    // QA fix cycle 2: a lone final chip (odd gate count) spans the full
    // row via gateChipFull — never a half-width orphan.
    flexBasis: "48%",
    flexGrow: 1,
    maxWidth: "48%",
    flexDirection: "row" as const,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    gap: 6,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    minHeight: 48,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.track,
    backgroundColor: colors.paper,
  },
  gateChipFull: {
    flexBasis: "100%" as const,
    maxWidth: "100%" as const,
  },
  gateChipActive: {
    backgroundColor: colors.ink,
    borderColor: colors.ink,
  },
  gateChipText: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  gateChipTextActive: {
    // 35M R2 (item 14): family encodes the weight — display (bold) on
    // the ink-filled chip.
    fontFamily: fonts.display,
    color: colors.paper,
  },
  note: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    lineHeight: 18,
  },
  pressed: {
    opacity: 0.7,
  },
  doneRow: {
    marginTop: spacing.sm,
  },
  grabZone: {
    height: spacing.lg,
  },
};
