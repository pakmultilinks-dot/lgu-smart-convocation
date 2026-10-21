// Convocation Readiness Centre (Phase 10). One screen: a personalized
// readiness overview, the outstanding and completed checklist, and the
// student's reminders. Everything shown is computed by the backend from
// authoritative records — this screen never edits or stores registration
// status, event dates or support status itself, so a staff change shows up
// on the next refresh. Completion reflects backend state, not a tap.

import { router } from "expo-router";
import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { ApiError } from "../../src/api/client";
import * as readinessApi from "../../src/api/readinessApi";
import { getToken } from "../../src/store/studentSession";
import { useFreshServerData } from "../../src/hooks/useFreshServerData";
import { colors, fonts, spacing } from "../../src/theme";
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
  | { kind: "ready"; data: readinessApi.Readiness; stale: boolean };

const STATUS_PILL: Record<readinessApi.ItemStatus, "accept" | "queued" | "invalid"> = {
  done: "accept",
  todo: "queued",
  attention: "invalid",
};
const ITEM_LABEL: Record<readinessApi.ItemStatus, string> = {
  done: "Done",
  todo: "To do",
  attention: "Attention",
};

export default function ReadinessScreen() {
  const [step, setStep] = useState<Step>({ kind: "loading" });
  // Phase 18: a failed mark/read is now surfaced instead of silently
  // dropped. The reminder stays visible (nothing is optimistically removed)
  // and the student can retry in place. `acting` keys the single in-flight
  // reminder so the two buttons on that row cannot double-submit.
  const [acting, setActing] = useState<string | null>(null);
  const [actError, setActError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    const token = await getToken();
    if (!token) {
      router.replace("/(student)/welcome");
      return;
    }
    if (!silent) setStep({ kind: "loading" });
    try {
      const res = await readinessApi.get(token);
      setStep({ kind: "ready", data: res.readiness, stale: false });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/(student)/welcome");
        return;
      }
      // Network/server failure keeps the last data on screen (stale) — it is
      // never rendered as "you have no registration".
      setStep((prev) =>
        prev.kind === "ready"
          ? { ...prev, stale: true }
          : {
              kind: "error",
              message:
                e instanceof ApiError
                  ? e.message
                  : "Your readiness could not be loaded. Check the connection.",
            },
      );
    }
  }, []);

  const refresh = useFreshServerData(() => load(true));

  const go = (action: readinessApi.NavAction | null) => {
    const route = readinessApi.routeOf(action);
    if (route) router.push(route as never);
  };

  const act = async (key: string, action: "read" | "dismiss") => {
    if (acting) return; // one reminder at a time — no duplicate submits
    const token = await getToken();
    if (!token) return router.replace("/(student)/welcome");
    setActing(key);
    setActError(null);
    try {
      await readinessApi.mark(token, key, action);
      // Server-confirmed: re-read the authoritative list so the row reflects
      // backend state, never a local assumption.
      await load(true);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/(student)/welcome");
        return;
      }
      // Truthful failure: the reminder is still on the list and the server
      // did not record the change.
      setActError(
        e instanceof ApiError
          ? e.message
          : "That reminder could not be updated. Check the connection and try again.",
      );
    } finally {
      setActing(null);
    }
  };

  if (step.kind === "loading") {
    return (
      <Screen scroll={false}>
        <LoadingState label="Loading your readiness..." />
      </Screen>
    );
  }
  if (step.kind === "error") {
    return (
      <Screen scroll={false}>
        <ErrorState
          title="Readiness unavailable"
          body={step.message}
          onRetry={() => void load()}
        />
      </Screen>
    );
  }

  const { data, stale } = step;
  const required = data.items.filter((i) => i.kind === "required");
  const outstanding = required.filter((i) => i.status !== "done");
  // Two checklists from the flat server list: profile items (registration,
  // profile_photo) and event readiness (everything else). The entry pass
  // gets its own callout while it is not done, so its reason and action
  // are stated once — never repeated as a warning.
  const PROFILE_KEYS = new Set(["registration", "profile_photo"]);
  const entryPass = data.items.find((i) => i.key === "entry_pass");
  const passCallout = entryPass && entryPass.status !== "done" ? entryPass : null;
  const profileItems = data.items.filter((i) => PROFILE_KEYS.has(i.key));
  const eventRequired = required.filter(
    (i) => !PROFILE_KEYS.has(i.key) && !(passCallout && i.key === "entry_pass"),
  );
  const info = data.items.filter((i) => i.kind === "info");
  const reminders = data.reminders;

  return (
    <Screen>
      <AppHeader
        title="Convocation readiness"
        subtitle={data.convocation ? data.convocation.name : "No convocation open"}
        eyebrow="Prepare"
        onBack={() => router.back()}
      />

      {stale ? (
        <Text style={styles.stale}>
          Offline — showing your last loaded readiness. Retrying automatically.
        </Text>
      ) : null}

      <SectionEyebrow>
        {data.summary.required_done} of {data.summary.required_total} required done
      </SectionEyebrow>
      <ProgressTrack value={data.summary.required_done} max={data.summary.required_total} />

      {outstanding.length === 0 ? (
        <EmptyState
          icon="checkmark-circle-outline"
          title="You are ready"
          body="Every required preparation step is complete. Keep an eye on reminders below."
        />
      ) : null}

      {passCallout ? (
        <>
          <SectionEyebrow>Entry pass</SectionEyebrow>
          <SectionCard>
            <StatusPill
              state={STATUS_PILL[passCallout.status]}
              label={passCallout.status === "attention" ? "Blocked" : "To do"}
            />
            <Text style={styles.calloutTitle}>{passCallout.title}</Text>
            {/* The actual server-side reason — never a generic warning. */}
            <Text style={styles.calloutDetail}>{passCallout.detail}</Text>
            <AppButton
              label={passCallout.status === "todo" ? "Get Entry Pass" : "Open invitation"}
              variant={passCallout.status === "todo" ? "primary" : "secondary"}
              onPress={() => go(passCallout.action)}
              style={styles.calloutBtn}
            />
          </SectionCard>
        </>
      ) : null}

      <SectionEyebrow>Profile setup</SectionEyebrow>
      <SectionCard pad={false}>
        {profileItems.map((item) => (
          <ListRow
            key={item.key}
            title={item.title}
            subtitle={item.detail}
            trailing={<StatusPill state={STATUS_PILL[item.status]} label={ITEM_LABEL[item.status]} size="sm" />}
            onPress={() => go(item.action)}
          />
        ))}
      </SectionCard>

      <SectionEyebrow>Event readiness</SectionEyebrow>
      <SectionCard pad={false}>
        {eventRequired.map((item) => (
          <ListRow
            key={item.key}
            title={item.title}
            subtitle={item.detail}
            trailing={<StatusPill state={STATUS_PILL[item.status]} label={ITEM_LABEL[item.status]} size="sm" />}
            onPress={() => go(item.action)}
          />
        ))}
      </SectionCard>

      {reminders.length > 0 ? (
        <>
          <SectionEyebrow>Reminders · {reminders.length}</SectionEyebrow>
          {actError ? <Text style={styles.actError}>{actError}</Text> : null}
          <SectionCard pad={false}>
            {reminders.map((r) => (
              <View key={r.key} style={styles.reminder}>
                <ListRow
                  title={r.title}
                  subtitle={r.reason}
                  trailing={
                    <StatusPill
                      state={r.priority === "high" ? "invalid" : "info"}
                      label={r.priority === "high" ? "Action" : "Note"}
                      size="sm"
                    />
                  }
                  onPress={() => go(r.action)}
                />
                {r.dismissible ? (
                  <View style={styles.reminderActions}>
                    <AppButton
                      label="Mark read"
                      variant="ghost"
                      size="md"
                      loading={acting === r.key}
                      disabled={acting !== null}
                      onPress={() => void act(r.key, "read")}
                      style={styles.miniBtn}
                    />
                    <AppButton
                      label="Dismiss"
                      variant="ghost"
                      size="md"
                      disabled={acting !== null}
                      onPress={() => void act(r.key, "dismiss")}
                      style={styles.miniBtn}
                    />
                  </View>
                ) : null}
              </View>
            ))}
          </SectionCard>
        </>
      ) : (
        <EmptyState
          icon="notifications-outline"
          title="No reminders"
          body="There is nothing waiting for your attention right now."
        />
      )}

      {info.length > 0 ? (
        <>
          <SectionEyebrow>Information</SectionEyebrow>
          <SectionCard pad={false}>
            {info.map((item) => (
              <ListRow
                key={item.key}
                title={item.title}
                subtitle={item.detail}
                onPress={() => go(item.action)}
              />
            ))}
          </SectionCard>
        </>
      ) : null}

      <AppButton
        label="Refresh"
        variant="ghost"
        icon="refresh"
        onPress={() => void refresh()}
        style={styles.refresh}
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
  calloutTitle: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 17,
    marginTop: spacing.sm,
  },
  calloutDetail: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    lineHeight: 19,
    marginTop: spacing.xs,
  },
  calloutBtn: {
    marginTop: spacing.md,
  },
  reminder: {
    borderBottomColor: colors.track,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  reminderActions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    marginTop: -spacing.xs,
    paddingBottom: spacing.sm,
  },
  miniBtn: {
    marginTop: 0,
    paddingHorizontal: spacing.sm,
  },
  actError: {
    color: colors.invalid,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginBottom: spacing.sm,
  },
  refresh: { marginTop: spacing.lg },
});
