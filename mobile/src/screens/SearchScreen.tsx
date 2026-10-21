import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Platform, Pressable, Text, View } from "react-native";
import { searchAttendees, ApiError, type SearchResult } from "../api/client";
import { addRecentSearch, getRecentSearches } from "../store/settings";
import { colors, fonts, spacing } from "../theme";
import {
  AppHeader,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Screen,
  SectionCard,
  SectionEyebrow,
  StatusPill,
  formatServerClock,
} from "../ui";

type StatusTone = "info" | "nodata" | "accept" | "duplicate";

function stateForHit(hit: SearchResult): { state: StatusTone; label: string } {
  if (hit.type === "guest") {
    // Phase 34 (Part C): a revoked pass is refused at the gate, so it is
    // neither Ready nor Used — it gets its own truthful state.
    if (hit.status === "revoked") return { state: "nodata", label: "Revoked" };
    // QA fix cycle 2: sentence-case pills, same as the guest list.
    return hit.used
      ? { state: "duplicate", label: "Used" }
      : { state: "accept", label: "Ready" };
  }
  return hit.inside
    ? { state: "info", label: "Inside" }
    : { state: "nodata", label: "Not arrived" };
}

/**
 * Search — Screen 3 of the institutional system (Phase 35C, 35H live
 * search): Find attendee / one-line hint / results — results appear while
 * you type (no Search button). Results are aligned rows (name, roll,
 * status — restrained pills) with dashed dividers, never cards. Counting
 * semantics unchanged. 35I (AA): recent searches — device-local only,
 * shown while no query is active; tapping one sets the query.
 */
export function SearchScreen() {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hits, setHits] = useState<SearchResult[] | null>(null);
  const [recent, setRecent] = useState<string[]>([]);
  // Phase 34 (Part D): /api/search is scanner-gated, so a 401 is a distinct
  // "sign in first" state, not a generic failure.
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const requestSeq = useRef(0);
  // 35J (T): remount key so the field re-focuses every time Search is
  // entered (expo-router keeps tab screens mounted — autoFocus alone
  // would only fire on first mount).
  const [focusTick, setFocusTick] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query.trim()), 400);
    return () => clearTimeout(timer);
  }, [query]);

  const hasQuery = debouncedQuery.length >= 2;

  // 35J (T): native-only focus-on-entry — the keyboard can open
  // immediately; web never forces it.
  useFocusEffect(
    useCallback(() => {
      if (Platform.OS !== "web") setFocusTick((t) => t + 1);
    }, []),
  );

  useFocusEffect(
    useCallback(() => {
      if (!hasQuery) {
        setHits(null);
        setError(null);
        setLoading(false);
        // 35I (AA): recents load when no query is active.
        void getRecentSearches().then(setRecent);
        return;
      }
      const seq = ++requestSeq.current;
      setLoading(true);
      setError(null);
      setNeedsSignIn(false);
      void (async () => {
        try {
          const data = await searchAttendees(debouncedQuery);
          if (seq !== requestSeq.current) return;
          setHits(data);
          setLoading(false);
          // Queries that returned results join the device-local recents.
          if (data.length > 0) void addRecentSearch(debouncedQuery);
        } catch (e) {
          if (seq !== requestSeq.current) return;
          setHits(null);
          setLoading(false);
          setNeedsSignIn(e instanceof ApiError && e.code === "scanner_auth_required");
          setError(
            e instanceof Error ? e.message : "The search request failed.",
          );
        }
      })();
    }, [debouncedQuery, hasQuery]),
  );

  return (
    <Screen>
      <AppHeader
        title="Find attendee"
        subtitle="Search by name, roll number, phone or host roll"
      />

      {/* Live search field (Phase 35H items 10–11): the redundant Search
          button is gone — results appear while you type. 35J (T): the
          duplicate label above the field is gone too; the placeholder +
          the "Find attendee" header name it. Native autofocus opens the
          keyboard on entry — web never forces it. */}
      <Field
        key={focusTick}
        placeholder="Name, roll number or phone"
        value={query}
        onChangeText={setQuery}
        autoCapitalize="words"
        returnKeyType="search"
        autoFocus={Platform.OS !== "web"}
      />
      {/* 35L (H): helper tells the operator exactly what to do before
          results can exist. */}
      <Text style={styles.hint}>
        {debouncedQuery.trim().length < 2
          ? "Type at least 2 characters to search"
          : "Results appear while you type"}
      </Text>

      {/* 35I (AA): compact recent searches — device-local, only while no
          query is active; tapping sets the query. */}
      {!hasQuery && recent.length > 0 ? (
        <SectionCard>
          <SectionEyebrow>Recent searches</SectionEyebrow>
          {recent.map((q) => (
            <Pressable
              key={q}
              accessibilityRole="button"
              accessibilityLabel={`Search for ${q}`}
              onPress={() => setQuery(q)}
              style={styles.recentRow}
            >
              <Text style={styles.recentText} numberOfLines={1}>
                {q}
              </Text>
              <Ionicons name="time-outline" size={16} color={colors.muted} />
            </Pressable>
          ))}
        </SectionCard>
      ) : null}

      {loading ? <LoadingState label="Searching the roster..." /> : null}

      {error ? (
        <ErrorState
          title={needsSignIn ? "Sign in to search" : "Search unavailable"}
          body={
            needsSignIn
              ? "Attendee lookup is restricted to signed-in scanner staff. Sign in on the Scanner tab, then retry."
              : error
          }
          onRetry={() => setDebouncedQuery(query.trim())}
        />
      ) : null}

      {hasQuery && !loading && !error && hits && hits.length === 0 ? (
        <EmptyState
          icon="search-outline"
          title="No match found"
          body={`Nothing matched "${debouncedQuery}". Check the spelling or try the roll number instead.`}
        />
      ) : null}

      {/* Results — aligned rows, dashed dividers, no cards, no gold. */}
      {hits && hits.length > 0 ? (
        <SectionCard pad={false}>
          {hits.map((hit, index) => {
            const s = stateForHit(hit);
            // Phase 34 (Part D): the qr_id credential is no longer returned
            // (nor needed) — key on the stable server id / roll number.
            const hitKey =
              hit.type === "guest"
                ? `guest-${hit.gid ?? hit.name}`
                : `student-${hit.roll_no ?? hit.name}`;
            return (
              <Pressable
                key={hitKey}
                accessibilityRole="button"
                accessibilityLabel={`${hit.name}, ${hit.roll_no ?? "guest"}, ${s.label}`}
                onPress={() => {
                  if (hit.type === "guest" && hit.gid) {
                    router.push(`/guest-pass?gid=${hit.gid}`);
                  } else {
                    router.push("/(volunteer)/scanner");
                  }
                }}
                style={({ pressed }) => [
                  styles.hitRow,
                  index > 0 && styles.hitDivider,
                  pressed && styles.pressed,
                ]}
              >
                <View style={styles.flex1}>
                  <Text style={styles.hitName}>{hit.name}</Text>
                  {hit.roll_no ? (
                    <Text style={styles.hitRoll}>{hit.roll_no}</Text>
                  ) : null}
                  {hit.program ? (
                    <Text style={styles.hitMeta}>{hit.program}</Text>
                  ) : null}
                  {hit.host_roll_no ? (
                    // 33-QA (I23): host name + roll, not roll alone.
                    <Text style={styles.hitMeta}>
                      Host{" "}
                      {hit.host_name
                        ? `${hit.host_name} (${hit.host_roll_no})`
                        : hit.host_roll_no}
                    </Text>
                  ) : null}
                  {hit.phone ? (
                    <Text style={styles.hitMeta}>{hit.phone}</Text>
                  ) : null}
                  {hit.last_scan ? (
                    <Text style={styles.hitMeta}>
                      Last scan {formatServerClock(hit.last_scan.time)}
                    </Text>
                  ) : null}
                </View>
                <View style={styles.hitStatus}>
                  <StatusPill state={s.state} label={s.label} size="sm" />
                  {hit.type === "guest" && hit.gid ? (
                    <View style={styles.passLink}>
                      <Ionicons
                        name="ticket-outline"
                        size={14}
                        color={colors.ink}
                      />
                      <Text style={styles.passLinkText}>Guest pass</Text>
                    </View>
                  ) : (
                    <Ionicons
                      name="scan-outline"
                      size={16}
                      color={colors.muted}
                    />
                  )}
                </View>
              </Pressable>
            );
          })}
          <Text style={styles.footerNote}>
            Search reads the live roster · tap a guest to open the pass
          </Text>
        </SectionCard>
      ) : null}
    </Screen>
  );
}

const styles = {
  flex1: { flex: 1 },
  pressed: { opacity: 0.7 },

  hint: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },

  recentRow: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
    paddingVertical: spacing.sm,
  },
  recentText: {
    flex: 1,
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },

  hitRow: {
    flexDirection: "row" as const,
    alignItems: "flex-start" as const,
    gap: spacing.md,
    paddingVertical: spacing.md,
  },
  hitDivider: {
    borderTopWidth: 1,
    borderTopColor: colors.track,
    borderStyle: "dashed" as const,
  },
  hitName: {
    fontFamily: fonts.display,
    fontSize: 15,
    color: colors.ink,
  },
  hitRoll: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
    marginTop: 2,
  },
  hitMeta: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    marginTop: 2,
  },
  hitStatus: {
    alignItems: "flex-end" as const,
    gap: spacing.sm,
  },
  passLink: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: 4,
  },
  passLinkText: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
  },
  footerNote: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    paddingTop: spacing.sm,
  },
};
