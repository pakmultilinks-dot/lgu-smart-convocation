// One support request and its student-visible history (Phase 9, §3). Fed
// by /api/student/support/<id> — the owning student only (the server
// answers 404 for any other account, so ids can never be probed). The
// trail shows the create event and every staff-visible reply, information
// request and decision; internal staff notes are never sent to the app.

import { router, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { getToken } from "../../src/store/studentSession";
import { ApiError } from "../../src/api/client";
import * as supportApi from "../../src/api/supportApi";
import { useFreshServerData } from "../../src/hooks/useFreshServerData";
import { colors, fonts, spacing } from "../../src/theme";
import {
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
  | { kind: "ready"; data: supportApi.SupportDetail; stale: boolean };

/** Human label for one audit action — the server action word, softened. */
const ACTION_LABEL: Record<string, string> = {
  create: "Request opened",
  status: "Status updated",
  reply: "Reply from the Examination Department",
  info_request: "Information requested",
  resolve: "Decision recorded",
};

export default function SupportDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const requestId = Number(id);
  const [step, setStep] = useState<Step>({ kind: "loading" });

  const load = useCallback(
    async (silent = false) => {
      const token = await getToken();
      if (!token) return router.replace("/(student)/welcome");
      if (!silent) setStep({ kind: "loading" });
      try {
        const data = await supportApi.detail(token, requestId);
        setStep({ kind: "ready", data, stale: false });
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          return router.replace("/(student)/welcome");
        }
        setStep((prev) =>
          prev.kind === "ready"
            ? { ...prev, stale: true }
            : {
                kind: "error",
                message:
                  e instanceof ApiError
                    ? e.message
                    : "This request could not be loaded. Check the connection.",
              },
        );
      }
    },
    [requestId],
  );

  // Focus / resume / manual / ≤30s cadence — silent, keeps last data.
  useFreshServerData(() => load(true));

  if (step.kind === "loading") {
    return (
      <Screen scroll={false}>
        <LoadingState label="Loading this request..." />
      </Screen>
    );
  }
  if (step.kind === "error") {
    return (
      <Screen scroll={false}>
        <ErrorState
          title="Request unavailable"
          body={step.message}
          onRetry={() => void load()}
        />
      </Screen>
    );
  }

  const { request: r } = step.data;
  const history = r.history;

  return (
    <Screen>
      <AppHeader
        eyebrow="Support request"
        title={r.reference}
        subtitle={r.category_label}
        onBack={() => router.back()}
      />
      <View style={styles.statusRow}>
        <StatusPill state={supportApi.pillState(r.status)} label={r.status_label} />
        <Text style={styles.date}>
          {r.resolved_at
            ? `Decided ${r.resolved_at.slice(0, 10)}`
            : `Acknowledged ${r.created_at.slice(0, 10)}`}
        </Text>
      </View>
      <Text style={styles.stateNote}>
        {r.resolved_at
          ? "This request has been decided — see the history below for the outcome."
          : "This request is open with the Examination Department; a decision has not been recorded yet."}
      </Text>
      {step.stale ? (
        <Text style={styles.stale}>
          Offline — showing the last loaded details. Retrying automatically.
        </Text>
      ) : null}

      <SectionEyebrow>What you reported</SectionEyebrow>
      <SectionCard>
        <Text style={styles.subject}>{r.subject}</Text>
        <Text style={styles.body}>{r.message}</Text>
      </SectionCard>

      {r.latest_response ? (
        <>
          <SectionEyebrow>Latest reply</SectionEyebrow>
          <SectionCard>
            <Text style={styles.body}>{r.latest_response.body}</Text>
            <Text style={styles.date}>{r.latest_response.at.slice(0, 10)}</Text>
          </SectionCard>
        </>
      ) : null}

      <SectionEyebrow>Update history</SectionEyebrow>
      <SectionCard pad={false}>
        {history.map((e, i) => (
          <ListRow
            key={`${e.at}-${i}`}
            title={ACTION_LABEL[e.action] ?? "Update"}
            subtitle={
              e.body ||
              (e.after_status
                ? `Status is now ${e.after_status.replace("_", " ")}`
                : undefined)
            }
          />
        ))}
      </SectionCard>

      <Text style={styles.note}>
        A request never changes your registration on its own. Where a correction
        is needed, the Examination Department applies it to the official record.
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  statusRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.lg,
  },
  date: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 12,
    marginTop: spacing.sm,
  },
  stateNote: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 12,
    lineHeight: 18,
    marginTop: -spacing.sm,
    marginBottom: spacing.lg,
  },
  stale: {
    color: colors.amber,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: -spacing.sm,
    marginBottom: spacing.md,
  },
  subject: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    marginBottom: spacing.sm,
  },
  body: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
    lineHeight: 21,
  },
  note: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 12,
    lineHeight: 18,
    marginTop: spacing.lg,
  },
});
