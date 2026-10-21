import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";
import type { ScanMode, ScanResult } from "../api/client";
import { colors, fonts, radius, spacing } from "../theme";
import { formatServerClock } from "../ui";
import { classifyScanResult, sanitizeInvalidDetail } from "./scanResultLogic";

/**
 * Scan-result moment over the camera (Phase 35B Part D; 35J H/I/J).
 * Three canonical scan outcomes fill the camera surface with their tone:
 *   VALID          — solid green #1E8A4C: checkmark, name/roll, Entry/Exit,
 *                    gate, 12h time — the pass was admitted.
 *   ALREADY USED   — solid red #C93A2E: name + previous gate + 12h time.
 *   INVALID        — solid red #C93A2E: main message "Invalid code",
 *                    instruction "Do not admit. Use Find attendee.", the
 *                    actual gate · 12h time, and a sanitized detail (raw
 *                    signature/API/HTTP text is never shown — 35J H).
 * Every state carries a large "Scan next" button — the operator always
 * has the next action in reach. Setup/queue/sync notices (kind "other")
 * keep the compact paper card: they are operational notices, not scan
 * outcomes. Tapping dismisses; text always carries the meaning.
 */
export function ScannerResult({
  result,
  mode,
  onDismiss,
}: {
  result: ScanResult;
  mode?: ScanMode;
  onDismiss: () => void;
}) {
  const c = classifyScanResult(result);
  const action = mode === "exit" ? "Exit" : "Entry";
  const a11yLabel = `${c.stateTitle}. ${result.detail ?? ""}`;

  /* Setup/queue/sync notices — compact paper card, product text kept. */
  if (c.kind === "other") {
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={a11yLabel}
        onPress={onDismiss}
        style={styles.noticeCard}
      >
        <View style={styles.noticeHeader}>
          <Ionicons
            name={result.level === "amber" ? "information-circle" : "alert-circle"}
            size={26}
            color={result.level === "amber" ? colors.amber : colors.invalid}
          />
          <Text
            style={[
              styles.noticeTitle,
              { color: result.level === "amber" ? colors.amber : colors.invalid },
            ]}
          >
            {c.stateTitle}
          </Text>
        </View>
        {result.name ? (
          <Text style={styles.noticeName}>{result.name}</Text>
        ) : null}
        {result.sub ? <Text style={styles.noticeSub}>{result.sub}</Text> : null}
        {result.detail ? (
          <Text style={styles.noticeDetail}>{result.detail}</Text>
        ) : null}
        <View style={styles.noticeFooter}>
          {result.gate ? (
            <Text style={styles.noticeMeta}>{result.gate}</Text>
          ) : null}
          {result.time ? (
            <Text style={styles.noticeMeta}>{formatServerClock(result.time)}</Text>
          ) : null}
        </View>
      </Pressable>
    );
  }

  /* Canonical scan outcomes — full-surface dominant state (35J H/I/J). */
  const valid = c.kind === "valid";
  const tone = valid ? colors.valid : colors.invalid;
  const icon = valid
    ? "checkmark-circle"
    : c.kind === "already-used"
      ? "repeat"
      : "shield-half";
  // Technical backend wording never reaches the operator (35J H).
  const detail = sanitizeInvalidDetail(result.detail);

  return (
    <View
      accessibilityRole="text"
      accessibilityLabel={a11yLabel}
      style={[styles.fullSurface, { backgroundColor: tone }]}
    >
      <Ionicons name={icon} size={72} color={colors.paper} />
      <Text style={styles.fullTitle}>{c.stateTitle}</Text>

      {/* VALID — attendee identity + confirmation. */}
      {valid ? (
        <>
          <Text style={styles.fullAction}>
            {result.title || `${action.toUpperCase()} RECORDED`}
          </Text>
          {result.name ? (
            <Text style={styles.fullName}>{result.name}</Text>
          ) : null}
          {result.sub ? <Text style={styles.fullSub}>{result.sub}</Text> : null}
          <View style={styles.fullMetaRow}>
            {/* 35I (P): Entry/Exit pills share one look — Exit is never
                a paler variant of Entry. */}
            <View style={styles.actionPill}>
              <Text style={styles.actionPillText}>{action.toUpperCase()}</Text>
            </View>
            {result.gate ? <Text style={styles.fullMeta}>{result.gate}</Text> : null}
            {result.time ? (
              <Text style={styles.fullMeta}>{formatServerClock(result.time)}</Text>
            ) : null}
          </View>
        </>
      ) : null}

      {/* INVALID — mandated main message + operator instruction.
          ScannerScreen stamps gate/time from the device context (35I C);
          without them the instruction still stands — never fabricated data. */}
      {!valid && c.kind === "invalid" ? (
        <>
          <Text style={styles.fullInstruction}>
            Do not admit. Use Find attendee.
          </Text>
          {result.gate || result.time ? (
            <Text style={styles.fullSub}>
              {result.gate ?? "Gate unknown"}
              {result.time ? ` · ${formatServerClock(result.time)}` : ""}
            </Text>
          ) : null}
          {detail ? <Text style={styles.fullDetail}>{detail}</Text> : null}
        </>
      ) : null}

      {/* ALREADY USED — name + where/when it was used before (12h).
          35L (D): the state explains itself — the record already exists. */}
      {c.kind === "already-used" ? (
        <>
          <Text style={styles.fullInstruction}>
            This pass has already been processed.
          </Text>
          {result.name ? (
            <Text style={styles.fullName}>{result.name}</Text>
          ) : null}
          {result.gate || result.time ? (
            <Text style={styles.fullSub}>
              {result.gate ?? "Gate unknown"}
              {result.time ? ` · ${formatServerClock(result.time)}` : ""}
            </Text>
          ) : null}
          {detail ? <Text style={styles.fullDetail}>{detail}</Text> : null}
        </>
      ) : null}

      {/* Large next-action button — always present on scan outcomes. */}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Scan next"
        onPress={onDismiss}
        style={styles.scanNextButton}
      >
        <Text style={styles.scanNextText}>Scan next</Text>
      </Pressable>
    </View>
  );
}

const styles = {
  /* Full-surface scan outcomes — cover the camera viewfinder edge to
     edge so the operator cannot miss the verdict (35J H/I/J). */
  fullSurface: {
    ...StyleSheet.absoluteFill,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  fullTitle: {
    fontFamily: fonts.display,
    fontSize: 46,
    letterSpacing: -1.2,
    color: colors.paper,
    textAlign: "center" as const,
  },
  fullAction: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.paper,
    letterSpacing: 0.4,
  },
  fullName: {
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: -0.4,
    color: colors.paper,
    textAlign: "center" as const,
  },
  fullSub: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.paper,
    textAlign: "center" as const,
  },
  fullInstruction: {
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: -0.4,
    color: colors.paper,
    textAlign: "center" as const,
  },
  fullDetail: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.paper,
    textAlign: "center" as const,
    lineHeight: 21,
  },
  fullMetaRow: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    flexWrap: "wrap" as const,
    justifyContent: "center" as const,
    gap: spacing.sm,
    marginTop: 4,
  },
  fullMeta: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.paper,
  },
  actionPill: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: radius.full,
    borderWidth: 1,
    borderColor: colors.paper,
  },
  actionPillText: {
    fontFamily: fonts.monoMedium,
    fontSize: 11,
    color: colors.paper,
    letterSpacing: 0.4,
  },
  scanNextButton: {
    marginTop: spacing.md,
    minHeight: 56,
    paddingHorizontal: spacing.xl,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    borderRadius: radius.sm,
    backgroundColor: colors.paper,
  },
  scanNextText: {
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: -0.4,
    color: colors.ink,
  },
  /* Setup/queue/sync notices — compact paper card (unchanged role). */
  noticeCard: {
    position: "absolute" as const,
    left: 12,
    right: 12,
    top: 56,
    backgroundColor: colors.paper,
    borderRadius: radius.md,
    borderWidth: 1.5,
    padding: spacing.md,
    gap: 4,
  },
  noticeHeader: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
  },
  noticeTitle: {
    flex: 1,
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: -0.4,
  },
  noticeName: {
    fontFamily: fonts.display,
    fontSize: 15,
    color: colors.ink,
  },
  noticeSub: {
    fontFamily: fonts.mono,
    fontSize: 11,
    color: colors.muted,
  },
  noticeDetail: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
    marginTop: 2,
    lineHeight: 21,
  },
  noticeFooter: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    flexWrap: "wrap" as const,
    gap: spacing.sm,
    marginTop: 4,
  },
  noticeMeta: {
    fontFamily: fonts.mono,
    fontSize: 11,
    color: colors.muted,
  },
};
