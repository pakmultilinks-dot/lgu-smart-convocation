// Official announcements feed (Phase 7, §4; Phase 33 Part D). Public
// read-only screen fed by /api/student/announcements — published
// student-audience rows only; drafts, staff-only and archived
// announcements never reach this screen. Phase 33: each state reads
// distinctly — loading, no active convocation, nothing published yet,
// populated (with audience + publication/edit dates), offline-over-data
// (stale badge naming the last successful load), and failed (an error
// state, never an empty success). A failed background refresh keeps the
// last feed on screen; it never swaps valid data for an empty page.
// Phase 8 freshness unchanged: focus, resume, manual refresh and a
// controlled ≤30s foreground cadence refetch silently over the last data.

import { router } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { ApiError } from "../../src/api/client";
import * as eventApi from "../../src/api/eventApi";
import { useFreshServerData } from "../../src/hooks/useFreshServerData";
import { colors, fonts, spacing } from "../../src/theme";
import { convocationLine } from "../../src/utils/convocation";
import {
  AppButton,
  AppHeader,
  EmptyState,
  ErrorState,
  LoadingState,
  Screen,
  SectionCard,
  StatusPill,
} from "../../src/ui";

type State = { error: string } | { payload: eventApi.FeedPayload } | null;

const day = (iso: string) => iso.slice(0, 10);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const stamp = () => {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
};

export default function AnnouncementsScreen() {
  const [state, setState] = useState<State>(null);
  const [stale, setStale] = useState(false);
  // Clock of the last SUCCESSFUL load — shown in the offline badge so a
  // cached feed is never mistaken for a freshly verified one.
  const [lastOk, setLastOk] = useState("");
  const hasDataRef = useRef(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setState(null);
    try {
      const payload = await eventApi.fetchAnnouncements();
      hasDataRef.current = true;
      setState({ payload });
      setStale(false);
      setLastOk(stamp());
    } catch (e) {
      // A failed background refresh keeps the last feed on screen (stale
      // badge) — a network failure is never a rejection, and cached
      // announcements are never swapped for an empty page.
      if (silent && hasDataRef.current) {
        setStale(true);
        return;
      }
      setState({
        error:
          e instanceof ApiError
            ? e.message
            : "Announcements could not be loaded. Check the connection.",
      });
    }
  }, []);

  // Focus / resume / manual / ≤30s cadence — one shared rule.
  const refresh = useFreshServerData(() => load(true));

  if (!state) {
    return (
      <Screen scroll={false}>
        <LoadingState label="Loading announcements..." />
      </Screen>
    );
  }
  if ("error" in state) {
    return (
      <Screen scroll={false}>
        <ErrorState
          title="Announcements unavailable"
          body={state.error}
          onRetry={() => void load()}
        />
      </Screen>
    );
  }

  const { convocation, announcements } = state.payload;

  return (
    <Screen>
      <AppHeader
        eyebrow="Official Updates"
        title="Announcements"
        subtitle={convocationLine(convocation)}
        onBack={() => router.back()}
      />
      {/* The offline badge renders in EVERY ready state — including the
          empty ones — so stale is visible wherever data is. */}
      {stale ? (
        <Text style={styles.stale}>
          {`Offline — showing announcements loaded at ${lastOk || "an earlier time"}. Retrying automatically.`}
        </Text>
      ) : null}
      {convocation === null ? (
        <EmptyState
          icon="calendar-outline"
          title="No active convocation"
          body="Announcements are published per convocation — none is currently active."
          actionLabel="Refresh"
          onAction={() => void refresh()}
        />
      ) : announcements.length === 0 ? (
        <>
          <EmptyState
            icon="megaphone-outline"
            title="No announcements yet"
            body="No announcements have been published for students yet. Official updates will appear here once published."
            actionLabel="Refresh"
            onAction={() => void refresh()}
          />
          {/* Event info stays reachable even with an empty feed. */}
          <AppButton
            label="View event schedule"
            variant="secondary"
            onPress={() => router.push("/(student)/event")}
          />
        </>
      ) : (
        <>
          <Text style={styles.count}>
            {`${announcements.length} published announcement${announcements.length === 1 ? "" : "s"} · latest ${day(announcements[0].published_at)}`}
          </Text>
          {announcements.map((a) => (
            <SectionCard key={a.id}>
              <View style={styles.titleRow}>
                <Text style={styles.title}>{a.title}</Text>
                {a.is_important ? (
                  <StatusPill state="info" label="Important" size="sm" />
                ) : null}
              </View>
              <Text style={styles.body}>{a.body}</Text>
              <Text style={styles.date}>
                {`${cap(a.audience)} · Published ${day(a.published_at)}${
                  day(a.updated_at) !== day(a.published_at)
                    ? ` · Updated ${day(a.updated_at)}`
                    : ""
                }`}
              </Text>
            </SectionCard>
          ))}
          <AppButton
            label="Refresh"
            variant="ghost"
            icon="refresh"
            onPress={() => void refresh()}
            style={styles.refresh}
          />
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  count: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginBottom: spacing.sm,
  },
  titleRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  title: {
    flex: 1,
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 16,
  },
  body: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
    lineHeight: 22,
    marginBottom: spacing.sm,
  },
  date: {
    color: colors.muted,
    fontFamily: fonts.mono,
    fontSize: 12,
  },
  stale: {
    color: colors.amber,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginBottom: spacing.sm,
  },
  refresh: { marginTop: spacing.lg },
});
