import { router } from "expo-router";
import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { ApiError } from "../../src/api/client";
import * as eventApi from "../../src/api/eventApi";
import * as readinessApi from "../../src/api/readinessApi";
import * as studentApi from "../../src/api/studentApi";
import { DashboardGrid, DashboardStat, DashboardTile } from "../../src/components/DashboardWidgets";
import { useFreshServerData } from "../../src/hooks/useFreshServerData";
import { clearToken, getToken } from "../../src/store/studentSession";
import { colors, fonts } from "../../src/theme";
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
    meaning: "Your registration is active. Open your entry pass to check whether it is ready for admission.",
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
  const occasions = eventInfo?.event?.occasions ?? [];
  const rehearsal = occasions.find((o) => o.key === "rehearsal");
  const ceremony = occasions.find((o) => o.key === "ceremony");

  const summary = ready?.readiness.summary;

  const passItem = ready?.readiness.items.find((item) => item.key === "entry_pass");
  const entryReady = reg.status === "active" && passItem?.status === "done";
  return <Screen>
    <AppHeader title="My dashboard" subtitle={eventInfo?.convocation?.name ?? "LGU Convocation"} titleSize={24} />
    <View style={styles.identity}><Text style={styles.name}>{reg.student_name}</Text><Text style={styles.meta}>{reg.registration_number}</Text><StatusPill state={status.state} label={status.label} size="sm" /></View>
    {stale ? <Text style={styles.notice}>Offline - showing your last loaded details.</Text> : null}
    <SectionCard>
      <SectionEyebrow>Gate entry</SectionEyebrow>
      <Text style={styles.name}>{entryReady ? "Your entry pass is ready" : "Check your entry pass"}</Text>
      <Text style={styles.meta}>{passItem?.detail ?? status.meaning}</Text>
      <AppButton label="View Entry Pass" icon="qr-code-outline" onPress={() => router.push("/(student)/pass")} />
    </SectionCard>
    <DashboardGrid>
      <DashboardStat label="Profile" value={`${me.completion.done}/${me.completion.total}`} detail={me.completion.complete ? "Complete" : "Action needed"} />
      <DashboardStat label="Event readiness" value={summary ? `${summary.required_done}/${summary.required_total}` : "Unavailable"} detail={summary ? `${summary.outstanding} outstanding` : "Open checklist to retry"} />
      <DashboardStat label="Students inside" value={att ? String(att.verified) : "Unavailable"} detail={att ? (att.attendance_set ? `${att.remaining} still expected` : "Not set by the administration") : "Live count unavailable"} />
      <DashboardStat label="New reminders" value={summary ? String(summary.reminders_new) : "Unavailable"} detail="Your personal checklist" />
    </DashboardGrid>
    <SectionEyebrow>Quick actions</SectionEyebrow>
    <DashboardGrid>
      <DashboardTile title="Registration" detail="Official record" icon="document-text-outline" onPress={() => router.push("/(student)/registration")} />
      <DashboardTile title="Updates" detail="University notices" icon="megaphone-outline" onPress={() => router.push("/(student)/announcements")} />
      <DashboardTile title="Manage profile" detail="Photo and contact" icon="person-circle-outline" onPress={() => router.push("/(student)/profile")} />
      <DashboardTile title="Readiness checklist" detail="Review your next steps" icon="checkmark-circle-outline" onPress={() => router.push("/(student)/readiness")} />
    </DashboardGrid>
    <SectionCard><SectionEyebrow>Convocation schedule</SectionEyebrow>
      {eventInfo === null ? <Text style={styles.notice}>Event schedule unavailable. Refresh to retry.</Text> : <>
        <ListRow title="Main convocation" subtitle={ceremony?.date ? `${ceremony.date}${ceremony.time ? ` · ${ceremony.time}` : ""}${ceremony.state === "expected" ? " · Provisional" : ""}` : "Not announced"} onPress={() => router.push("/(student)/event")} />
        <ListRow title="Rehearsal" subtitle={rehearsal?.date ?? "Not announced"} onPress={() => router.push("/(student)/event")} />
        <Text style={styles.meta}>{ceremony?.venue ?? "Venue not published"}</Text>
      </>}
    </SectionCard>
    <AppButton label="Help & corrections" variant="secondary" onPress={() => router.push("/(student)/support")} />
    <AppButton label="Refresh dashboard" variant="ghost" icon="refresh" onPress={() => void refresh()} />
  </Screen>;
}
const styles = StyleSheet.create({
  identity: { gap: 6 },
  name: { fontFamily: fonts.display, fontSize: 15, color: colors.ink },
  meta: { fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 19, color: colors.muted },
  notice: { fontFamily: fonts.displayMedium, fontSize: 13, color: colors.amber },
});
