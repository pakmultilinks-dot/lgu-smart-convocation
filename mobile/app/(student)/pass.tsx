// Digital convocation invitation pass (Phase 11) + entry QR (Phase 12). The
// invitation state shown here is computed by the backend from the claimed
// registration, its status, open support requests and the published event —
// this screen never grants eligibility. GET /pass stays a read-only
// invitation with no QR payload; while the state is `eligible` the screen
// asks the backend to mint a scannable convocation QR (POST /pass/issue) and
// renders it. The QR value is an opaque bearer token the gate verifies
// server-side against the registration record — it carries no personal data,
// and a visible QR image is never treated as proof of validity on its own.

import { router } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import QRCode from "react-native-qrcode-svg";
import { ApiError } from "../../src/api/client";
import * as passApi from "../../src/api/passApi";
import { getToken } from "../../src/store/studentSession";
import { useFreshServerData } from "../../src/hooks/useFreshServerData";
import { colors, fonts, spacing } from "../../src/theme";
import {
  AppButton,
  AppHeader,
  ErrorState,
  ListRow,
  LoadingState,
  Screen,
  SectionCard,
  SectionEyebrow,
  StatusPill,
} from "../../src/ui";

type Step =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; pass: passApi.Pass; stale: boolean };

const STATE_PILL: Record<passApi.PassState, "accept" | "queued" | "invalid" | "info"> = {
  eligible: "accept",
  pending_review: "queued",
  event_unpublished: "queued",
  registration_missing: "invalid",
  registration_cancelled: "invalid",
  registration_revoked: "invalid",
  no_convocation: "info",
};

export default function PassScreen() {
  const [step, setStep] = useState<Step>({ kind: "loading" });
  const [qr, setQr] = useState<passApi.IssuedPass | null>(null);
  const [qrError, setQrError] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);

  const issue = useCallback(async () => {
    const token = await getToken();
    if (!token) return router.replace("/(student)/welcome");
    setIssuing(true);
    setQrError(null);
    try {
      const res = await passApi.issuePass(token);
      setQr(res.pass);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/(student)/welcome");
        return;
      }
      setQrError(
        e instanceof ApiError
          ? e.message
          : "Your entry QR could not be issued. Check the connection.",
      );
    } finally {
      setIssuing(false);
    }
  }, []);

  const load = useCallback(async (silent = false) => {
    const token = await getToken();
    if (!token) return router.replace("/(student)/welcome");
    if (!silent) setStep({ kind: "loading" });
    try {
      const res = await passApi.getPass(token);
      setStep({ kind: "ready", pass: res.pass, stale: false });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/(student)/welcome");
        return;
      }
      // Network/server failure keeps the last pass on screen (stale) — it
      // is never rendered as "your pass was revoked".
      setStep((prev) =>
        prev.kind === "ready"
          ? { ...prev, stale: true }
          : {
              kind: "error",
              message:
                e instanceof ApiError
                  ? e.message
                  : "Your invitation could not be loaded. Check the connection.",
            },
      );
    }
  }, []);

  // Auto-issue once while eligible; a freshness refresh re-reads the
  // invitation only and never reissues (reissue is an explicit user action).
  useEffect(() => {
    if (step.kind !== "ready") return;
    if (step.pass.state !== "eligible") {
      // Eligibility lost — a previously shown QR must not linger on screen.
      setQr(null);
      setQrError(null);
      return;
    }
    if (!qr && !issuing && !qrError) void issue();
  }, [step, qr, issuing, qrError, issue]);

  const refresh = useFreshServerData(() => load(true));

  if (step.kind === "loading") {
    return (
      <Screen scroll={false}>
        <LoadingState label="Loading your invitation..." />
      </Screen>
    );
  }
  if (step.kind === "error") {
    return (
      <Screen scroll={false}>
        <ErrorState
          title="Invitation unavailable"
          body={step.message}
          onRetry={() => void load()}
        />
      </Screen>
    );
  }

  const { pass, stale } = step;
  const event = pass.event;

  return (
    <Screen>
      <AppHeader
        title="Convocation invitation"
        subtitle={pass.convocation ? pass.convocation.name : "Digital pass"}
        eyebrow="Your pass"
        onBack={() => router.back()}
      />
      {stale ? (
        <Text style={styles.stale}>
          Offline — showing your last loaded invitation. Retrying automatically.
        </Text>
      ) : null}

      <View style={styles.status}>
        <StatusPill state={STATE_PILL[pass.state]} label={pass.state_label} />
      </View>

      <SectionCard>
        <Text style={styles.title}>{pass.title}</Text>
        <Text style={styles.detail}>{pass.detail}</Text>
      </SectionCard>

      {pass.registration ? (
        <>
          <SectionEyebrow>Registration</SectionEyebrow>
          <SectionCard pad={false}>
            <ListRow title="Student" subtitle={pass.registration.student_name} />
            <ListRow
              title="Registration number"
              subtitle={pass.registration.registration_number}
            />
            <ListRow title="Roll number" subtitle={pass.registration.roll_number} />
            <ListRow title="Department" subtitle={pass.registration.department} />
          </SectionCard>
        </>
      ) : null}

      {event ? (
        <>
          <SectionEyebrow>Official event details</SectionEyebrow>
          <SectionCard pad={false}>
            {/* Phase 33 Part F: the row names the ceremony date, so
                "Confirmed <date>" can't be misread as a registration
                confirmation — the label carries the meaning. */}
            <ListRow
              title="Ceremony date"
              subtitle={
                event.confirmed_date
                  ? `Confirmed ${event.confirmed_date}`
                  : event.expected_date
                    ? `Expected ${event.expected_date} (provisional)`
                    : "Not announced yet"
              }
              trailing={
                <StatusPill
                  state={event.date_state === "confirmed" ? "accept" : "queued"}
                  label={event.date_state_label}
                  size="sm"
                />
              }
            />
            {event.rehearsal ? (
              <ListRow
                title="Rehearsal"
                subtitle={`${event.rehearsal.date}${event.rehearsal.time ? ` · ${event.rehearsal.time}` : ""}`}
              />
            ) : null}
            <ListRow title="Venue" subtitle={event.venue || "Not published"} />
            {event.instructions ? (
              <ListRow title="Instructions" subtitle={event.instructions} />
            ) : null}
          </SectionCard>
        </>
      ) : null}

      <SectionEyebrow>Gate entry</SectionEyebrow>
      <SectionCard>
        {pass.state === "eligible" && qr ? (
          <>
            <View style={styles.qrWrap}>
              <QRCode
                value={qr.payload}
                size={200}
                backgroundColor="#FFFFFF"
                color={colors.ink}
              />
            </View>
            <Text style={styles.note}>
              Applies to{" "}
              {event?.occasions?.some(
                (o) => o.key === "rehearsal" && o.state !== "not_announced",
              )
                ? "both the rehearsal and the main convocation"
                : "the main convocation"}
              . Show this QR at the entry gate. It carries no personal data — the
              gate verifies it against your registration record. Issued{" "}
              {qr.issued_at}
              {qr.expires_at ? `, valid until ${qr.expires_at}` : ""}.
            </Text>
            <AppButton
              label="Refresh QR"
              variant="ghost"
              icon="refresh"
              onPress={() => void issue()}
              style={styles.refresh}
            />
          </>
        ) : pass.state === "eligible" && qrError ? (
          <>
            <View style={styles.qrRow}>
              <StatusPill state="invalid" label="QR unavailable" />
            </View>
            <Text style={styles.detail}>{qrError}</Text>
            <AppButton
              label="Try again"
              variant="ghost"
              icon="refresh"
              onPress={() => {
                setQrError(null);
                void issue();
              }}
              style={styles.refresh}
            />
          </>
        ) : pass.state === "eligible" ? (
          <Text style={styles.detail}>Preparing your entry QR...</Text>
        ) : (
          <>
            <View style={styles.qrRow}>
              <StatusPill state="info" label="Entry QR not available" />
            </View>
            <Text style={styles.detail}>{pass.qr_blocker}</Text>
            <Text style={styles.note}>
              This invitation is informational — it is not a scannable entry code. An
              entry QR appears here only while your registration is eligible.
            </Text>
          </>
        )}
      </SectionCard>

      <AppButton
        label="Refresh"
        variant="ghost"
        icon="refresh"
        onPress={() => void refresh()}
        style={styles.refresh}
      />
      <AppButton
        label="Back to home"
        variant="secondary"
        onPress={() => router.replace("/(student)/home")}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  stale: {
    color: colors.amber,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginBottom: spacing.md,
  },
  status: {
    flexDirection: "row",
    marginBottom: spacing.lg,
  },
  title: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 20,
    marginBottom: spacing.sm,
  },
  detail: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
    lineHeight: 21,
  },
  note: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 12,
    marginTop: spacing.sm,
  },
  qrRow: {
    marginBottom: spacing.sm,
  },
  qrWrap: {
    alignItems: "center",
    marginBottom: spacing.md,
  },
  refresh: {
    marginTop: spacing.lg,
  },
});