import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { Text, View } from "react-native";
import { ApiError, postManualAttendance, type Occasion, type ScanMode, type ScanResult } from "../api/client";
import { getScanMode, getScanOccasion, getSelectedGate } from "../store/ops";
import type { SelectedGate } from "../store/ops";
import { colors, fonts, spacing } from "../theme";
import {
  AppButton,
  AppHeader,
  ErrorState,
  LoadingState,
  Screen,
  SectionCard,
  SectionEyebrow,
  StatusPill,
} from "../ui";

type ScannerContext = {
  gate: SelectedGate | null;
  mode: ScanMode;
  occasion: Occasion;
};

function errorText(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "Attendance could not be recorded. Check the connection and try again.";
}

export function AttendeeDetailScreen() {
  const params = useLocalSearchParams<{
    type?: string;
    name?: string;
    roll_no?: string;
    gid?: string;
    program?: string;
    host_roll_no?: string;
    host_name?: string;
  }>();
  const isGuest = params.type === "guest";
  const gid = Number(params.gid);
  const valid = isGuest
    ? Number.isInteger(gid) && gid > 0
    : params.type === "student" && Boolean(params.roll_no?.trim());
  const [context, setContext] = useState<ScannerContext | null>(null);
  const [contextError, setContextError] = useState<string | null>(null);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setContext(null);
      setContextError(null);
      void Promise.all([getSelectedGate(), getScanMode(), getScanOccasion()])
        .then(([gate, mode, occasion]) => {
          if (active) setContext({ gate, mode, occasion });
        })
        .catch(() => {
          if (active) setContextError("Scanner context could not be loaded. Return to Scan and try again.");
        });
      return () => { active = false; };
    }, []),
  );

  const recordAttendance = async () => {
    if (busy || !context?.gate) return;
    setBusy(true);
    setActionError(null);
    setResult(null);
    try {
      const attendance = await postManualAttendance({
        type: isGuest ? "guest" : "student",
        ...(isGuest ? { gid } : { roll_no: params.roll_no }),
        gate_id: context.gate.id,
        mode: context.mode,
        occasion: context.occasion,
      });
      setResult(attendance);
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const displayName = typeof params.name === "string" ? params.name : "Attendee";

  return (
    <Screen>
      <AppHeader
        title="Attendee details"
        subtitle={isGuest ? "Guest pass and attendance" : "Student roster record"}
        onBack={() => router.replace("/(volunteer)/search")}
      />
      {!valid ? (
        <ErrorState
          title="Attendee unavailable"
          body="This result link is incomplete. Return to Search and open the attendee again."
          onRetry={() => router.replace("/(volunteer)/search")}
        />
      ) : (
        <>
          <SectionCard>
            <Text style={{ color: colors.ink, fontFamily: fonts.display, fontSize: 20 }}>
              {displayName}
            </Text>
            {isGuest ? (
              <>
                <Text style={styles.detail}>Guest of {params.host_name || params.host_roll_no || "Unknown host"}</Text>
                {params.host_name && params.host_roll_no
                  ? <Text style={styles.detail}>Host roll number: {params.host_roll_no}</Text>
                  : null}
                <AppButton
                  label="Open guest pass"
                  variant="ghost"
                  onPress={() => router.push(`/guest-pass?gid=${gid}&from=/(volunteer)/attendee`)}
                />
              </>
            ) : (
              <>
                <Text style={styles.detail}>Roll number: {params.roll_no}</Text>
                {params.program ? <Text style={styles.detail}>{params.program}</Text> : null}
              </>
            )}
          </SectionCard>

          <SectionEyebrow>Attendance context</SectionEyebrow>
          {contextError ? <Text accessibilityRole="alert" style={styles.error}>{contextError}</Text> : null}
          {!context && !contextError ? <LoadingState label="Loading gate and event selection..." /> : null}
          {context ? (
            <SectionCard>
              <Text style={styles.detail}>Gate: {context.gate?.label ?? "Not selected"}</Text>
              <Text style={styles.detail}>Action: {context.mode === "entry" ? "Entry" : "Exit"}</Text>
              <Text style={styles.detail}>
                Event: {context.occasion === "rehearsal" ? "Rehearsal" : "Main convocation"}
              </Text>
              {context.gate ? (
                <AppButton
                  label={busy ? "Recording..." : `Record ${context.mode}`}
                  loading={busy}
                  onPress={() => void recordAttendance()}
                />
              ) : (
                <AppButton
                  label="Choose gate in Scan"
                  variant="secondary"
                  onPress={() => router.push("/(volunteer)/scanner")}
                />
              )}
            </SectionCard>
          ) : null}

          {result ? (
            <SectionCard>
              <View style={styles.resultHeading}>
                <StatusPill
                  state={result.level === "green" ? "accept" : result.level === "amber" ? "queued" : "invalid"}
                  label={result.title}
                />
              </View>
              {result.detail ? <Text style={styles.detail}>{result.detail}</Text> : null}
              {result.gate ? <Text style={styles.detail}>Gate: {result.gate}</Text> : null}
              {result.time ? <Text style={styles.detail}>Time: {result.time}</Text> : null}
            </SectionCard>
          ) : null}
          {actionError ? <Text accessibilityRole="alert" style={styles.error}>{actionError}</Text> : null}
          <AppButton
            label="Back to Search"
            variant="ghost"
            onPress={() => router.replace("/(volunteer)/search")}
            style={styles.back}
          />
        </>
      )}
    </Screen>
  );
}

const styles = {
  detail: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
    lineHeight: 20,
  },
  error: {
    color: colors.invalid,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
  },
  resultHeading: { marginBottom: spacing.sm },
  back: { marginTop: spacing.sm },
};
