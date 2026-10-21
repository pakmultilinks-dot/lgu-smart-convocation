// Official convocation event information (Phase 7, §4; Phase 33 Part B).
// Public read-only screen fed by /api/student/event — published snapshot
// only, so drafts and unpublished changes never appear. The two occasions
// of the annual cycle render as SEPARATE cards (rehearsal ≠ main
// convocation), each with its own pill, date/time and venue, so a venue
// or time can never be read as belonging to the other occasion. The
// expected vs confirmed ceremony date rows stay explicitly distinct, and
// the header is sticky (Screen stickyHeader) so page context stays
// reachable while the schedule scrolls. Phase 8 freshness rules unchanged:
// focus, resume, manual refresh and a controlled ≤30s foreground cadence
// refetch silently over the last data (no push, no uncontrolled polling).

import { router } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { ApiError } from "../../src/api/client";
import * as eventApi from "../../src/api/eventApi";
import { EventCountdown } from "../../src/components/EventCountdown";
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

type State = { error: string } | { payload: eventApi.EventPayload } | null;

const PILL: Record<eventApi.DateState, "nodata" | "stale" | "accept"> = {
  not_announced: "nodata",
  expected: "stale",
  confirmed: "accept",
};

const day = (iso: string | null) => (iso ? iso.slice(0, 10) : null);

export default function EventScreen() {
  const [state, setState] = useState<State>(null);
  const [stale, setStale] = useState(false);
  const hasDataRef = useRef(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setState(null);
    try {
      const payload = await eventApi.fetchEvent();
      hasDataRef.current = true;
      setState({ payload });
      setStale(false);
    } catch (e) {
      // A failed background refresh keeps the last published snapshot on
      // screen (stale badge) — a network failure is never a rejection.
      if (silent && hasDataRef.current) {
        setStale(true);
        return;
      }
      setState({
        error:
          e instanceof ApiError
            ? e.message
            : "The event information could not be loaded. Check the connection.",
      });
    }
  }, []);

  // Focus / resume / manual / ≤30s cadence — one shared rule.
  const refresh = useFreshServerData(() => load(true));

  if (!state) {
    return (
      <Screen scroll={false}>
        <LoadingState label="Loading event information..." />
      </Screen>
    );
  }
  if ("error" in state) {
    return (
      <Screen scroll={false}>
        <ErrorState
          title="Event information unavailable"
          body={state.error}
          onRetry={() => void load()}
        />
      </Screen>
    );
  }

  const { convocation, event } = state.payload;

  return (
    <Screen stickyHeader>
      <AppHeader
        eyebrow="Official Information"
        title="Convocation Event"
        subtitle={convocationLine(convocation)}
        onBack={() => router.back()}
      />
      {/* Offline keeps whatever was last loaded — including the unpublished
          state — visible with an honest badge (never a silent empty swap). */}
      {stale ? (
        <Text style={styles.stale}>
          Offline — showing the last loaded event information. Retrying automatically.
        </Text>
      ) : null}
      {event === null ? (
        <EmptyState
          icon="calendar-outline"
          title="No event information published"
          body="The official convocation date, venue and instructions will appear here once they are published."
          actionLabel="Refresh"
          onAction={() => void refresh()}
        />
      ) : (
        <>
          <View style={styles.state}>
            <StatusPill state={PILL[event.date_state]} label={event.date_state_label} />
            <Text style={styles.updated}>
              {`Published ${event.published_at.slice(0, 10)}`}
            </Text>
          </View>
          {/* Phase 29: server-computed countdown for the next announced
              occasion of the annual cycle (never a provisional date, never a
              fabricated start time). */}
          <EventCountdown
            occasions={event.occasions}
            portalTz={event.portal_tz}
          />
          {/* Phase 33 Part B: the annual cycle renders as SEPARATE cards —
              one per occasion, each with its own state pill, date/time and
              venue (the venue always belongs to the occasion shown; an
              unpublished field says so, never a blank row). */}
          {event.occasions && event.occasions.length > 0 ? (
            <>
              <SectionEyebrow>Annual cycle</SectionEyebrow>
              {event.occasions.map((o) => (
                <SectionCard key={o.key}>
                  <View style={styles.cardHead}>
                    <Text style={styles.cardTitle}>{o.label}</Text>
                    <StatusPill
                      state={
                        o.state === "expected"
                          ? "stale"
                          : o.state === "not_announced"
                            ? "nodata"
                            : "accept"
                      }
                      label={
                        o.phase === "completed"
                          ? "Completed"
                          : o.state === "not_announced"
                            ? "Not announced"
                            : o.state === "expected"
                              ? "Provisional"
                              : o.state === "confirmed"
                                ? "Confirmed"
                                : "Announced"
                      }
                      size="sm"
                    />
                  </View>
                  <Text style={styles.cardLine}>
                    {o.state === "not_announced"
                      ? "Date and time not published"
                      : `${day(o.date) ?? "Date not published"}${
                          o.time
                            ? ` · ${o.time}${
                                event.portal_tz ? ` (${event.portal_tz})` : ""
                              }`
                            : ""
                        }`}
                  </Text>
                  <Text style={styles.cardLine}>
                    {o.venue || "Venue not published"}
                  </Text>
                </SectionCard>
              ))}
            </>
          ) : null}
          {/* Publication status: the expected (provisional) and confirmed
              ceremony dates are separate rows — a provisional date never
              borrows the confirmed label, and a missing confirmation says
              so explicitly. */}
          <SectionEyebrow>Date</SectionEyebrow>
          <SectionCard pad={false}>
            <ListRow
              title="Expected date"
              subtitle={
                day(event.expected_date)
                  ? `${day(event.expected_date)} (provisional)`
                  : "Not announced"
              }
            />
            <ListRow
              title="Confirmed date"
              subtitle={
                day(event.confirmed_date) ?? "Not officially confirmed yet"
              }
            />
            <ListRow
              title="Start time"
              subtitle={event.ceremony_time || "Not announced"}
            />
          </SectionCard>
          {/* Fallback for a server that predates the occasions payload: the
              ceremony venue still renders with its honest "Not announced"
              fallback (Phase 28 contract, kept). */}
          {!event.occasions || event.occasions.length === 0 ? (
            <>
              <SectionEyebrow>Venue</SectionEyebrow>
              <SectionCard pad={false}>
                <ListRow
                  title="Convocation venue"
                  subtitle={event.venue || "Not announced"}
                />
              </SectionCard>
            </>
          ) : null}
          {event.instructions ? (
            <>
              <SectionEyebrow>Approved instructions</SectionEyebrow>
              <SectionCard>
                <Text style={styles.instructions}>{event.instructions}</Text>
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
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  state: {
    // Phase 33: wraps instead of running off screen on narrow devices —
    // the pill and the publication stamp share one flexible row.
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  updated: {
    flexShrink: 1,
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
  },
  cardHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  cardTitle: {
    flex: 1,
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 16,
  },
  cardLine: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    lineHeight: 20,
  },
  instructions: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
    lineHeight: 22,
  },
  stale: {
    color: colors.amber,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginBottom: spacing.md,
  },
  refresh: { marginTop: spacing.lg },
});
