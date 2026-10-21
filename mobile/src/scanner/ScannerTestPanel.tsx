import { Ionicons } from "@expo/vector-icons";
import { Pressable, Text, View } from "react-native";
import type { TestRecord } from "../api/client";
import { colors, fonts, radius, spacing } from "../theme";
import { AppButton, SectionCard, SectionEyebrow } from "../ui";

/**
 * Test scan card — deterministic demo records pushed through the REAL
 * backend (/api/scan) via the same handler as the camera, plus the reset
 * action. Same behavior as the Phase 30 scanner test panel.
 */
export function ScannerTestPanel({
  records,
  testLoading,
  testResetLoading,
  onTestScan,
  onTestReset,
}: {
  records: TestRecord[];
  testLoading: boolean;
  testResetLoading: boolean;
  onTestScan: (record: TestRecord) => void;
  onTestReset: () => void;
}) {
  return (
    <SectionCard>
      <SectionEyebrow>Test scan</SectionEyebrow>
      <Text style={styles.testHint}>
        TEST FUNCTIONALITY — runs demo records from the local test dataset
        through the same backend as the camera. Use the Entry/Exit control
        above to switch direction; scan twice without resetting to test
        duplicate detection.
      </Text>
      {records.length === 0 ? (
        <Text style={styles.noGatesText}>
          {"Test data isn't available."}
        </Text>
      ) : (
        <View style={styles.testGrid}>
          {records.map((record) => (
            <Pressable
              key={record.key}
              disabled={testLoading}
              onPress={() => onTestScan(record)}
              style={({ pressed }) => [
                styles.testButton,
                pressed && styles.pressed,
                testLoading && styles.testButtonBusy,
              ]}
            >
              <Ionicons
                name={
                  record.kind === "guest"
                    ? "ticket-outline"
                    : record.key === "female"
                      ? "woman-outline"
                      : "man-outline"
                }
                size={18}
                color={colors.ink}
              />
              <View style={styles.testButtonText}>
                <Text style={styles.testButtonTitle} numberOfLines={1}>
                  Test Scan: {record.label}
                </Text>
                <Text style={styles.testButtonSub}>Runs a real /api/scan</Text>
              </View>
            </Pressable>
          ))}
        </View>
      )}
      <AppButton
        label={testResetLoading ? "Resetting..." : "Reset test scans"}
        icon="refresh"
        variant="ghost"
        loading={testResetLoading}
        onPress={onTestReset}
      />
    </SectionCard>
  );
}

const styles = {
  pressed: { opacity: 0.7 },
  noGatesText: {
    // 35M item 18: helper sentence — sans, not DM Mono.
    marginTop: spacing.sm,
    fontFamily: fonts.displayMedium,
    fontSize: 11,
    color: colors.muted,
    lineHeight: 17,
  },
  testHint: {
    fontFamily: fonts.displayMedium,
    fontSize: 11,
    color: colors.muted,
    lineHeight: 17,
    marginBottom: spacing.sm,
  },
  testGrid: {
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  testButton: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.track,
    borderRadius: radius.sm,
    padding: spacing.md,
    backgroundColor: colors.paper,
  },
  testButtonBusy: {
    opacity: 0.5,
  },
  testButtonText: {
    flex: 1,
  },
  testButtonTitle: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  testButtonSub: {
    // 35M item 18: label sentence — sans, not DM Mono.
    fontFamily: fonts.displayMedium,
    fontSize: 11,
    color: colors.muted,
    marginTop: 1,
  },
};
