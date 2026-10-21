import { router } from "expo-router";
import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { ApiError } from "../../src/api/client";
import * as eventApi from "../../src/api/eventApi";
import * as readinessApi from "../../src/api/readinessApi";
import * as studentApi from "../../src/api/studentApi";
import { useCountdown } from "../../src/components/EventCountdown";
import { useFreshServerData } from "../../src/hooks/useFreshServerData";
import { clearToken, getToken } from "../../src/store/studentSession";
import { colors, fonts, radius, spacing } from "../../src/theme";
import {
  AppButton,
  AppHeader,
  EmptyState,
  ErrorState,
  ListRow,
  LoadingState,
  ProgressTrack,
  Screen,
  SectionCard,
  SectionEyebrow,
  StatusPill,
} from "../../src/ui";

type Step =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      me: studentApi.SessionBody;
      event: eventApi.EventPayload | null;
      ready: readinessApi.ReadinessResponse | null;
      att: studentApi.StudentAttendance | null;
      stale: boolean;
    };

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

const OCCASION_PILL: Record<
  eventApi.OccasionInfo["state"],
  "nodata" | "stale" | "info" | "accept"
> = {
  not_announced: "nodata",
  announced: "info",
  expected: "stale",
  confirmed: "accept",
};

const OCCASION_STATE: Record<eventApi.OccasionInfo["state"], string> = {
  not_announced: "Not announced",
  announced: "Announced",
  expected: "Expected",
  confirmed: "Confirmed",
};

/** One occasion of the annual cycle as its own compact card (Phase 31
    Part B §4): rehearsal and the main convocation never share a card or a
    countdown. Every field is server-published; absent fields say so, and
    the countdown follows countdownText's honest rules (never a fake
    clock, never a negative count). */
function OccasionCard({
  o,
  name,
  tz,
}: {
  o?: eventApi.OccasionInfo;
  name: string;
  tz?: string | null;
}) {
  const text = useCountdown(o ?? null);
  return (
    <View style={styles.card}>
      <View style={styles.cardHead}>
        <Text style={styles.cardTitle}>{o?.label ?? name}</Text>
        {o ? (
          <StatusPill state={OCCASION_PILL[o.state]} label={OCCASION_STATE[o.state]} />
        ) : null}
      </View>
      {o ? (
        <>
          <Text style={styles.cardMeta}>
            {[o.date, o.time].filter(Boolean).join(" · ") || "Date and time not published"}
            {o.time && tz ? ` (${tz})` : ""}
          </Text>
          <Text style={styles.cardMeta}>{o.venue ?? "Venue not published"}</Text>
          {text ? <Text style={styles.countdown}>{text}</Text> : null}
        </>
      ) : (
        <Text style={styles.cardMeta}>Not yet scheduled</Text>
      )}
    </View>
  );
}

/** Student home (Phase 31 Part B): status first, entry pass one tap away,
 *  two separate event cards, profile and readiness as distinct counts.
 *  Phase 8 freshness rules still apply — focus, resume, manual refresh and
 *  a controlled ≤30s foreground cadence refetch silently, keeping the last
 *  data on screen (stale badge) instead of treating a failure as a
 *  rejection; only a real 401 ends the session. */
export default function StudentHome() {
  const [step, setStep] = useState<Step>({ kind: "loading" });

  const load = useCallback(async (silent = false) => {
    const token = await getToken();
    if (!token) {
      setStep({ kind: "loading" });
      router.replace("/(student)/welcome");
      return;
    }
    if (!silent) setStep({ kind: "loading" });
    try {
      const [me, event, ready, att] = await Promise.all([
        studentApi.me(token),
        // Phase 29: the public event snapshot is supplementary — if it
        // cannot load, home still renders and reports the schedule failure
        // honestly instead of treating it as a rejection.
        eventApi.fetchEvent().catch(() => null),
        // Readiness is supplementary too: a failed checklist shows an
        // honest "unavailable" line, never a fabricated 0-of-N.
        readinessApi.get(token).catch(() => null),
        // Phase 38: attendance counts follow the same supplementary rule —
        // a failed fetch degrades to an honest unavailable line.
        studentApi.fetchAttendance(token).catch(() => null),
      ]);
      if (!me.registration) {
        router.replace("/(student)/verify");
        return;
      }
      if (!me.completion.complete) {
        router.replace("/(student)/profile");
        return;
      }
      setStep({ kind: "ready", me, event, ready, att, stale: false });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await clearToken();
        router.replace("/(student)/welcome");
        return;
      }
      // Network failure (status 0) or server hiccup: keep the last data
      // visible and mark it stale — never a rejection, never a blank screen.
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

  // Focus / resume / manual / ≤30s cadence — one shared rule.
  const refresh = useFreshServerData(() => load(true));

  const signOut = async () => {
    const token = await getToken();
    if (token) await studentApi.logout(token);
    router.replace("/(student)/welcome");
  };

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
  const { me, event: eventInfo, ready, att, stale } = step;
  const reg = me.registration!;
  // 24B: the raw status word alone is not a status — pair every state with
  // what it means and what the student can do about it.
  const status = REG_STATUS[reg.status] ?? {
    label: `Registration ${reg.status}`,
    state: "nodata" as const,
    meaning: "Ask the Examination Department what this status means.",
  };
  // Official-list inclusion is its own concept — never inferred from the
  // account claim or a successful login (Phase 31 Part B §2).
  const listText =
    reg.status === "active"
      ? "Included — this record comes from the official Examination Department list."
      : reg.status === "cancelled" || reg.status === "revoked"
        ? "Not usable for entry — see the registration status above."
        : "Unknown — ask the Examination Department to confirm.";
  const occasions = eventInfo?.event?.occasions ?? [];
  const rehearsal = occasions.find((o) => o.key === "rehearsal");
  const ceremony = occasions.find((o) => o.key === "ceremony");
  const tz = eventInfo?.event?.portal_tz ?? null;
  const summary = ready?.readiness.summary;

  return (
    <Screen>
      <AppHeader
        title={reg.student_name}
        subtitle={reg.registration_number}
        eyebrow="Student Portal"
      />

      {/* Status: registration, official list, reference and claim are four
          distinct concepts — the claim date is the account claim only. */}
      <View style={styles.statusRow}>
        <StatusPill state={status.state} label={status.label} />
        {stale ? (
          <Text style={styles.stale}>Offline — showing your last loaded details.</Text>
        ) : null}
      </View>
      <Text style={styles.meaning}>{status.meaning}</Text>
      <SectionCard pad={false}>
        <ListRow title="Official convocation list" subtitle={listText} />
        <ListRow title="Registration reference" subtitle={reg.registration_number} />
        <ListRow
          title="Account claimed"
          subtitle={
            me.claimed_at ? `Claimed ${me.claimed_at.slice(0, 10)}` : "Not claimed yet"
          }
        />
      </SectionCard>
      <Text style={styles.hint}>
        The student API reports no separate last-status-check time — status is read live at
        each refresh.
      </Text>

      {/* Primary actions, right next to the status. */}
      <AppButton
        label="View Entry Pass"
        icon="qr-code-outline"
        onPress={() => router.push("/(student)/pass")}
        style={styles.action}
      />
      <AppButton
        label="View Registration Details"
        variant="secondary"
        onPress={() => router.push("/(student)/registration")}
        style={styles.action}
      />
      {reg.status !== "active" ? (
        <AppButton
          label="Request a correction"
          variant="secondary"
          onPress={() => router.push("/(student)/support")}
          style={styles.action}
        />
      ) : null}

      {/* Two separate occasion cards — rehearsal and the main convocation
          never share a countdown or a status (Phase 31 Part B §4). */}
      <SectionEyebrow>Convocation schedule</SectionEyebrow>
      {eventInfo === null ? (
        <ErrorState
          title="Event schedule unavailable"
          body="The published schedule could not be loaded. Check the connection and retry."
          onRetry={() => void load(true)}
        />
      ) : occasions.length ? (
        <>
          <OccasionCard o={rehearsal} name="Rehearsal" tz={tz} />
          <OccasionCard o={ceremony} name="Main convocation" tz={tz} />
        </>
      ) : (
        <EmptyState
          icon="calendar-outline"
          title="No schedule published"
          body="Rehearsal and main convocation details will appear here once the university publishes them."
          actionLabel="Event details"
          onAction={() => router.push("/(student)/event")}
        />
      )}

      {/* Phase 38 shared analytics: live attendance as counts only — the
          student view never exposes operational detail (gates, feed,
          refusals, other people's names). */}
      <SectionEyebrow>Live attendance</SectionEyebrow>
      {att ? (
        <>
          <SectionCard pad={false}>
            <ListRow
              title="Verified inside"
              subtitle={`${att.verified} of ${att.registered} registered students`}
            />
            <ListRow
              title={att.attendance_set ? "Still expected" : "Attendance target"}
              subtitle={
                att.attendance_set
                  ? `${att.remaining} yet to arrive · ${att.percentage}% arrived`
                  : "Not set by the administration"
              }
            />
          </SectionCard>
          <ProgressTrack value={att.verified} max={Math.max(1, att.registered)} />
        </>
      ) : (
        <Text style={styles.hint}>
          Live attendance could not be loaded — it refreshes with the page.
        </Text>
      )}

      {/* Profile completion and event readiness are separate counts with
          one clear next action each (Phase 31 Part B §5). */}
      <SectionEyebrow>{`Profile: ${me.completion.done} of ${me.completion.total} complete`}</SectionEyebrow>
      <ProgressTrack value={me.completion.done} max={me.completion.total} />
      <AppButton
        label="Manage profile"
        variant="secondary"
        onPress={() => router.push("/(student)/profile")}
        style={styles.action}
      />

      <SectionEyebrow>
        {summary
          ? `Event readiness: ${summary.required_done} of ${summary.required_total} complete`
          : "Event readiness unavailable"}
      </SectionEyebrow>
      {summary ? (
        <ProgressTrack value={summary.required_done} max={summary.required_total} />
      ) : (
        <Text style={styles.hint}>
          The readiness checklist could not be loaded — open it to retry.
        </Text>
      )}
      <AppButton
        label="Open readiness checklist"
        variant="secondary"
        onPress={() => router.push("/(student)/readiness")}
        style={styles.action}
      />

      {/* Less-frequent destinations live under More / My Registration —
          Home keeps only the highest-value links (Part B §6). */}
      <SectionEyebrow>More</SectionEyebrow>
      <SectionCard pad={false}>
        <ListRow
          title="Event details"
          subtitle="Full schedule, venue and instructions"
          onPress={() => router.push("/(student)/event")}
        />
        <ListRow
          title="Updates"
          subtitle="Official announcements"
          onPress={() => router.push("/(student)/announcements")}
        />
      </SectionCard>

      <AppButton
        label="Refresh"
        variant="ghost"
        icon="refresh"
        onPress={() => void refresh()}
        style={styles.action}
      />
      <AppButton label="Sign out" variant="danger" onPress={() => void signOut()} />
      <AppButton
        label="Change device mode"
        variant="ghost"
        onPress={() => router.replace("/mode-picker")}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  statusRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  meaning: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginBottom: spacing.md,
  },
  hint: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 12,
    marginTop: spacing.sm,
    marginBottom: spacing.md,
  },
  stale: {
    color: colors.amber,
    fontFamily: fonts.displayMedium,
    fontSize: 12,
    flexShrink: 1,
    textAlign: "right",
  },
  action: { marginTop: spacing.sm },
  card: {
    borderWidth: 1,
    borderColor: colors.ink,
    borderRadius: radius.sm,
    backgroundColor: colors.paper,
    padding: spacing.md,
    marginBottom: spacing.sm,
    gap: 4,
  },
  cardHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  cardTitle: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 15,
    flexShrink: 1,
  },
  cardMeta: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
  },
  countdown: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 18,
    marginTop: 2,
  },
});
