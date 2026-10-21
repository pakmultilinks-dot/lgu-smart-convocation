// Student convocation history (Phase 11; Phase 33 Part C). A read-only
// ledger of the convocations this student's verified official records
// touch — built by the backend from the registration_claims the account
// owns, paired with the published event snapshot and published honours.
// Every date line says what it means: the ceremony date (confirmed or
// provisional) is never bare "Confirmed <date>", and the account-claim
// date is a separate line. Active and past convocations are grouped.
// Nothing here is stored or edited locally, and only this account's own
// registrations can ever appear.

import { router } from "expo-router";
import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { ApiError } from "../../src/api/client";
import * as passApi from "../../src/api/passApi";
import { getToken } from "../../src/store/studentSession";
import { useFreshServerData } from "../../src/hooks/useFreshServerData";
import { colors, fonts, spacing } from "../../src/theme";
import { convocationLine } from "../../src/utils/convocation";
import {
  AppButton,
  AppHeader,
  EmptyState,
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
  | { kind: "ready"; history: passApi.HistoryEntry[]; stale: boolean };

const REG_PILL: Record<string, "accept" | "invalid"> = {
  active: "accept",
  cancelled: "invalid",
  revoked: "invalid",
};

// Phase 33 Part C: every date line is labelled by meaning. The ceremony
// date (confirmed or provisional) is never a bare "Confirmed <date>" — a
// bare label cannot be distinguished from a registration confirmation,
// and this API carries no registration-confirmation timestamp.
const ceremonyLine = (event: passApi.PassEvent | null): string => {
  if (!event) return "Ceremony date · Event details not published";
  if (event.confirmed_date)
    return `Ceremony date · Confirmed ${event.confirmed_date.slice(0, 10)}`;
  if (event.expected_date)
    return `Ceremony date · Expected ${event.expected_date.slice(0, 10)} (provisional)`;
  return "Ceremony date · Not announced";
};

export default function HistoryScreen() {
  const [step, setStep] = useState<Step>({ kind: "loading" });

  const load = useCallback(async (silent = false) => {
    const token = await getToken();
    if (!token) return router.replace("/(student)/welcome");
    if (!silent) setStep({ kind: "loading" });
    try {
      const res = await passApi.getHistory(token);
      setStep({ kind: "ready", history: res.history, stale: false });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/(student)/welcome");
        return;
      }
      // Network/server failure keeps the last ledger on screen (stale) — it
      // is never rendered as "you have no history".
      setStep((prev) =>
        prev.kind === "ready"
          ? { ...prev, stale: true }
          : {
              kind: "error",
              message:
                e instanceof ApiError
                  ? e.message
                  : "Your history could not be loaded. Check the connection.",
            },
      );
    }
  }, []);

  const refresh = useFreshServerData(() => load(true));

  if (step.kind === "loading") {
    return (
      <Screen scroll={false}>
        <LoadingState label="Loading your history..." />
      </Screen>
    );
  }
  if (step.kind === "error") {
    return (
      <Screen scroll={false}>
        <ErrorState
          title="History unavailable"
          body={step.message}
          onRetry={() => void load()}
        />
      </Screen>
    );
  }

  const { history, stale } = step;
  const active = history.filter((e) => e.convocation.bucket === "active");
  const past = history.filter((e) => e.convocation.bucket === "past");

  const renderEntry = (entry: passApi.HistoryEntry) => (
    <View key={entry.convocation.id} style={styles.entry}>
      <ListRow
        title={convocationLine(entry.convocation) ?? ""}
        subtitle={`Registration ${entry.registration.status} · ${entry.registration.student_name}`}
        trailing={
          <StatusPill
            state={REG_PILL[entry.registration.status] ?? "info"}
            label={entry.registration.status}
            size="sm"
          />
        }
      />
      <View style={styles.meta}>
        <Text style={styles.line}>{ceremonyLine(entry.event)}</Text>
        {entry.event ? (
          <Text style={styles.line}>{entry.event.venue || "Venue not published"}</Text>
        ) : null}
        <Text style={styles.line}>
          {`Account claim · Claimed ${entry.registration.claimed_at.slice(0, 10)}`}
        </Text>
        <Text style={styles.line}>
          {`Registration number · ${entry.registration.registration_number || "Not available"}`}
        </Text>
        {entry.honours.length > 0 ? (
          <Text style={styles.honours}>
            Honours ·{" "}
            {entry.honours
              .map((h) => `${h.award_category} (${h.department})`)
              .join(", ")}
          </Text>
        ) : null}
      </View>
      {/* Phase 33 Part C: link the current convocation's own screens from
          the active entry — the pass route only serves the active
          convocation, so links appear on the active record only. */}
      {entry.convocation.is_active ? (
        <View style={styles.links}>
          <AppButton
            label="View entry pass"
            variant="ghost"
            icon="qr-code-outline"
            onPress={() => router.push("/(student)/pass")}
          />
          <AppButton
            label="My registration"
            variant="ghost"
            onPress={() => router.push("/(student)/registration")}
          />
        </View>
      ) : null}
    </View>
  );

  return (
    <Screen>
      <AppHeader
        title="Convocation history"
        subtitle={`${history.length} convocation${history.length === 1 ? "" : "s"} on your records`}
        eyebrow="Your record"
        onBack={() => router.back()}
      />
      {stale ? (
        <Text style={styles.stale}>
          Offline — showing your last loaded history. Retrying automatically.
        </Text>
      ) : null}

      {history.length === 0 ? (
        <EmptyState
          icon="time-outline"
          title="No convocations yet"
          body="Once your account claims an active registration for a convocation, it will appear here."
        />
      ) : null}

      {active.length > 0 ? (
        <>
          <SectionEyebrow>Current · {active.length}</SectionEyebrow>
          <SectionCard pad={false}>{active.map(renderEntry)}</SectionCard>
        </>
      ) : null}

      {past.length > 0 ? (
        <>
          <SectionEyebrow>Past · {past.length}</SectionEyebrow>
          <SectionCard pad={false}>{past.map(renderEntry)}</SectionCard>
        </>
      ) : null}

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
  entry: {
    borderBottomColor: colors.track,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  meta: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
    marginTop: -spacing.xs,
  },
  links: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
  },
  line: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
  },
  honours: {
    color: colors.brand,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.xs,
  },
  refresh: {
    marginTop: spacing.lg,
  },
});