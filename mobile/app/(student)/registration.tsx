import { router } from "expo-router";
import { useCallback, useState } from "react";
import { StyleSheet, Text } from "react-native";
import { ApiError } from "../../src/api/client";
import * as studentApi from "../../src/api/studentApi";
import { useFreshServerData } from "../../src/hooks/useFreshServerData";
import { clearToken, getToken } from "../../src/store/studentSession";
import { colors, fonts, spacing } from "../../src/theme";
import {
  AppButton,
  AppHeader,
  ErrorState,
  ListRow,
  LoadingState,
  ProgressTrack,
  Screen,
  SectionCard,
  SectionEyebrow,
  StatusPill,
} from "../../src/ui";

/** 24B: every registration status, spelled out — label, pill tone, meaning. */
const REG_STATUS: Record<
  string,
  { label: string; state: "accept" | "invalid" | "nodata"; meaning: string }
> = {
  active: {
    label: "Registration active",
    state: "accept",
    meaning: "Your registration is active and usable for entry.",
  },
  cancelled: {
    label: "Registration cancelled",
    state: "invalid",
    meaning:
      "This registration was cancelled and cannot be used for entry. "
      + "Request a correction if this is wrong.",
  },
  revoked: {
    label: "Registration revoked",
    state: "invalid",
    meaning:
      "This registration was revoked and cannot be used for entry. "
      + "Request a correction if this is wrong.",
  },
};

type Step =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; me: studentApi.SessionBody; stale: boolean };

/**
 * My Registration (Phase 31): the read-only official record — status,
 * official-list inclusion, claim date and profile completion kept as
 * DISTINCT concepts. Registration rows exist only via the official
 * Examination Department import, so an existing registration means the
 * name is on the official list; the API supplies no last-checked
 * timestamp, and none is fabricated here.
 */
export default function MyRegistration() {
  const [step, setStep] = useState<Step>({ kind: "loading" });

  const load = useCallback(async (silent = false) => {
    const token = await getToken();
    if (!token) {
      router.replace("/(student)/welcome");
      return;
    }
    if (!silent) setStep({ kind: "loading" });
    try {
      const me = await studentApi.me(token);
      if (!me.registration) {
        router.replace("/(student)/verify");
        return;
      }
      setStep({ kind: "ready", me, stale: false });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await clearToken();
        router.replace("/(student)/welcome");
        return;
      }
      setStep((prev) =>
        prev.kind === "ready"
          ? { ...prev, stale: true }
          : {
              kind: "error",
              message:
                e instanceof ApiError
                  ? e.message
                  : "Your registration could not be loaded. Check the connection.",
            },
      );
    }
  }, []);

  useFreshServerData(() => load(true));

  if (step.kind === "loading") {
    return (
      <Screen scroll={false}>
        <LoadingState label="Loading your registration..." />
      </Screen>
    );
  }
  if (step.kind === "error") {
    return (
      <Screen scroll={false}>
        <ErrorState
          title="Registration unavailable"
          body={step.message}
          onRetry={() => void load()}
        />
      </Screen>
    );
  }
  const { me, stale } = step;
  const reg = me.registration!;
  const status = REG_STATUS[reg.status] ?? {
    label: `Registration ${reg.status}`,
    state: "nodata" as const,
    meaning: "Ask the Examination Department what this status means.",
  };
  // A field the official list never supplied is stated as such — never
  // rendered as an empty row that reads like a broken record.
  const official = (v: string) => v.trim() || "Not provided on the official list";

  return (
    <Screen>
      <AppHeader title="My Registration" subtitle={reg.student_name} eyebrow="Student Portal" />
      <SectionEyebrow>Status</SectionEyebrow>
      <SectionCard>
        <StatusPill state={status.state} label={status.label} />
        <Text style={styles.meaning}>{status.meaning}</Text>
        <ListRow
          title="Official convocation list"
          subtitle={
            reg.status === "active"
              ? "Included — this record comes from the official Examination Department list."
              : "Not usable for entry while this registration is not active."
          }
        />
        <ListRow
          title="Claim date"
          subtitle={me.claimed_at ? me.claimed_at.slice(0, 10) : "Not claimed yet"}
        />
        <Text style={styles.hint}>
          Status shown as last returned by the server; the API does not report a
          separate last-checked time.
        </Text>
        {stale ? (
          <Text style={styles.stale}>
            Offline — showing your last loaded details. Retrying automatically.
          </Text>
        ) : null}
      </SectionCard>

      <SectionEyebrow>
        Official details · {reg.registration_number}
      </SectionEyebrow>
      <SectionCard pad={false}>
        <ListRow title="Registration number" subtitle={official(reg.registration_number)} />
        <ListRow title="Student name" subtitle={official(reg.student_name)} />
        <ListRow title="Roll number" subtitle={official(reg.roll_number)} />
        <ListRow title="Department" subtitle={official(reg.department)} />
        <ListRow title="Registration status" subtitle={status.label} />
      </SectionCard>
      <Text style={styles.hint}>
        These rows are read-only. Corrections are applied to the official record
        by the Examination Department — a request never changes your
        registration on its own.
      </Text>

      <SectionEyebrow>
        Profile setup · {me.completion.done} of {me.completion.total} complete
      </SectionEyebrow>
      <ProgressTrack value={me.completion.done} max={me.completion.total} />
      <AppButton
        label="Manage profile"
        variant="secondary"
        onPress={() => router.push("/(student)/profile")}
        style={styles.action}
      />
      {/* Always offered: a student who believes any field or the status is
          wrong must be able to ask, not only one whose status already broke. */}
      <AppButton
        label="Request a correction"
        variant="secondary"
        onPress={() => router.push("/(student)/support")}
        style={styles.action}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  meaning: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.sm,
  },
  hint: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 12,
    marginTop: spacing.sm,
  },
  stale: {
    color: colors.amber,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.sm,
  },
  action: { marginTop: spacing.sm },
});