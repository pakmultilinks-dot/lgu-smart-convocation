import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import {
  ApiError,
  fetchGuests,
  type Guest,
} from "../api/client";
import { colors, fonts, radius, spacing } from "../theme";
import { maskPhone } from "../utils/phone";
import {
  AppButton,
  AppHeader,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Screen,
  SectionCard,
  SectionEyebrow,
  SegmentedControl,
  StatusPill,
  formatLocalClock,
} from "../ui";

/** Read-only guest directory for authenticated gate staff. Paid issuance
 * and revocation live exclusively in the protected administrator workflow. */

const MONTHS_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** 35I (T.4): 12h local time, with a "d MMM, " prefix when the entry
    date is not today (viewer-local date — gate devices share the server's
    timezone, so this matches the physical event day). */
function usedStamp(usedAt: string | null | undefined): string | null {
  if (!usedAt) return null;
  const time = formatLocalClock(usedAt);
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T]/.exec(usedAt);
  if (!m) return time;
  const entryDay = `${m[1]}-${m[2]}-${m[3]}`;
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  if (entryDay === today) return time;
  return `${Number(m[3])} ${MONTHS_SHORT[Number(m[2]) - 1]}, ${time}`;
}
export function GuestsScreen() {
  const [guests, setGuests] = useState<Guest[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  // Phase 26C: the roster is scanner-gated; a 401 means sign in first.
  const [needsSignIn, setNeedsSignIn] = useState(false);

  // Phase 35H list tools: client-side search + Ready/Used filter +
  // per-guest phone reveal (masked by default on shared gate devices).
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "ready" | "used">("all");
  const [revealedPhones, setRevealedPhones] = useState<Record<number, boolean>>({});

  const loadGuests = useCallback(async () => {
    setListError(null);
    setNeedsSignIn(false);
    try {
      const list = await fetchGuests();
      setGuests(list);
    } catch (e) {
      setGuests(null);
      setNeedsSignIn(e instanceof ApiError && e.code === "scanner_auth_required");
      setListError(
        e instanceof Error ? e.message : "The guest list could not be loaded.",
      );
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void loadGuests();
    }, [loadGuests]),
  );

  const showPass = useCallback((gid: number) => {
    router.push({ pathname: "/guest-pass", params: { gid: String(gid) } });
  }, []);

  const isReady = (g: Guest) => !g.used && g.status !== "revoked";

  const filtered =
    guests === null
      ? []
      : guests.filter((guest) => {
          // Revoked is neither Ready nor Used — the filters stay honest.
          if (statusFilter === "ready" && !isReady(guest)) return false;
          if (statusFilter === "used" && !guest.used) return false;
          const q = query.trim().toLowerCase();
          if (!q) return true;
          return (
            guest.name.toLowerCase().includes(q) ||
            guest.host_roll_no.toLowerCase().includes(q) ||
            (guest.host_name ?? "").toLowerCase().includes(q) ||
            guest.phone.includes(q)
          );
        });

  return (
    <Screen>
      <AppHeader
        title="Guest directory"
        subtitle="Existing passes and gate status"
      />

      <Text style={styles.guestMeta}>Paid guest passes are issued by the administrator after payment verification. This directory is for lookup and gate checks only.</Text>

      {/* 1 — Guest list FIRST. */}
      <SectionCard>
        <SectionEyebrow>
          {guests
            ? `Guest list · ${guests.length} registered · ${guests.filter(isReady).length} ready · ${guests.filter((g) => g.used).length} used${guests.some((g) => g.status === "revoked") ? ` · ${guests.filter((g) => g.status === "revoked").length} revoked` : ""}`
            : "Guest list"}
        </SectionEyebrow>
        {listError ? (
          <>
            <ErrorState
              title={needsSignIn ? "Sign in to view guests" : "Guest list unavailable"}
              body={
                needsSignIn
                  ? "The guest list is restricted to signed-in scanner staff. Sign in on the Scanner tab, then retry."
                  : listError
              }
              onRetry={() => void loadGuests()}
            />
            <AppButton
              label={needsSignIn ? "Sign in to scanner" : "Connect to server"}
              variant="secondary"
              onPress={() => router.push(needsSignIn ? "/(volunteer)/scanner" : "/connect-server")}
            />
          </>
        ) : guests === null ? (
          <LoadingState label="Loading guests..." />
        ) : guests.length === 0 ? (
          <EmptyState
            icon="people-outline"
            title="No guests registered yet"
            body="Registered guests appear here with their live pass state."
          />
        ) : (
          <>
            {/* 35I (T.6): no label — the placeholder + proximity to the
                list make the field's purpose obvious. 33-QA (I20): the
                placeholder reads "Name or phone" — the fields volunteers
                actually search by; roll/host matching still works
                server-side and in the filter below. */}
            <Field
              placeholder="Name or phone"
              value={query}
              onChangeText={setQuery}
              autoCapitalize="none"
            />
            <View style={styles.filterRow}>
              <SegmentedControl
                options={[
                  { label: "All", value: "all" },
                  { label: "Ready", value: "ready" },
                  { label: "Used", value: "used" },
                ]}
                value={statusFilter}
                onChange={setStatusFilter}
              />
            </View>
            {query.trim() !== "" || statusFilter !== "all" ? (
              <AppButton
                label="Clear filters"
                variant="ghost"
                size="md"
                onPress={() => {
                  setQuery("");
                  setStatusFilter("all");
                }}
              />
            ) : null}
            {filtered.length === 0 ? (
              <EmptyState
                icon="search-outline"
                title="No guests match"
                body="Try a different name, roll number, or phone — or clear the filters."
              />
            ) : (
              <ScrollView nestedScrollEnabled showsVerticalScrollIndicator={false}>
                {filtered.map((guest) => (
                  <View key={guest.id} style={styles.guestRow}>
                    <View style={styles.flex1}>
                      <View style={styles.guestTitleRow}>
                        {/* Names wrap — never truncated (bug 9). */}
                        <Text style={styles.guestName}>{guest.name}</Text>
                        <StatusPill
                          state={
                            guest.status === "revoked"
                              ? "duplicate"
                              : guest.used
                                ? "nodata"
                                : "accept"
                          }
                          label={
                            guest.status === "revoked"
                              ? "Revoked"
                              : guest.used
                                ? "Used"
                                : "Ready"
                          }
                          size="sm"
                        />
                      </View>
                      {/* 33-QA (I23): the host line carries NAME + roll —
                          the roll alone means nothing at the gate. */}
                      <Text style={styles.guestMeta}>
                        Host{" "}
                        {guest.host_name
                          ? `${guest.host_name} (${guest.host_roll_no})`
                          : guest.host_roll_no}
                      </Text>
                      {/* QA fix cycle 2: no phone on record says so —
                          never an empty row or a fake mask. */}
                      {guest.phone ? (
                        <Pressable
                          accessibilityRole="button"
                          accessibilityLabel={
                            revealedPhones[guest.id]
                              ? `Hide phone number for ${guest.name}`
                              : `Show phone number for ${guest.name}`
                          }
                          onPress={() =>
                            setRevealedPhones((prev) => ({
                              ...prev,
                              [guest.id]: !prev[guest.id],
                            }))
                          }
                        >
                          {/* 35I (T.2): single line — long numbers never
                              ellipsise into a wrong-looking number. */}
                          <Text style={styles.guestMeta} numberOfLines={1}>
                            {revealedPhones[guest.id]
                              ? guest.phone
                              : maskPhone(guest.phone)}
                          </Text>
                        </Pressable>
                      ) : (
                        <Text style={styles.guestMeta}>No phone</Text>
                      )}
                      {guest.used ? (
                        <Text style={styles.guestMeta}>
                          Entered {usedStamp(guest.used_at)}
                          {guest.used_gate ? `, ${guest.used_gate}` : ""}
                        </Text>
                      ) : null}
                    </View>
                    {guest.used ? null : (
                      <View style={styles.passActions}>
                        <Pressable
                          accessibilityRole="button"
                          accessibilityLabel={`Open pass for ${guest.name}`}
                          onPress={() => showPass(guest.id)}
                          style={styles.passLink}
                        >
                          {/* QA fix cycle 3 (Issue 10): an explicit action
                              label — always "Show pass", never a bare
                              "Pass" or an id the operator must decode. */}
                          <Text style={styles.passLinkText}>Show pass</Text>
                        </Pressable>

                      </View>
                    )}
                  </View>
                ))}
              </ScrollView>
            )}
          </>
        )}
      </SectionCard>

    </Screen>
  );
}

const styles = {
  flex1: { flex: 1 },
  formError: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.invalid,
    marginBottom: spacing.sm,
    lineHeight: 18,
  },
  passCreated: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
    marginTop: spacing.md,
    padding: spacing.md,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.track,
    backgroundColor: colors.paper,
  },
  passCreatedTitle: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  passCreatedBody: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    marginTop: 2,
    lineHeight: 18,
  },
  passCreatedButton: {
    minHeight: 48,
  },
  guestRow: {
    flexDirection: "row" as const,
    alignItems: "flex-start" as const,
    gap: spacing.md,
    paddingVertical: spacing.md,
  },
  filterRow: {
    marginBottom: spacing.sm,
  },
  guestTitleRow: {
    flexDirection: "row" as const,
    alignItems: "flex-start" as const,
    gap: spacing.sm,
  },
  guestName: {
    flex: 1,
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  guestMeta: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    marginTop: 2,
    lineHeight: 18,
  },
  // 35J (Q): Pass stays a compact text action — but with a real 48px
  // touch target and an outlined button treatment, aligned with the
  // guest-name row (Used guests still show no Pass action at all).
  passLink: {
    minHeight: 48,
    minWidth: 48,
    paddingHorizontal: spacing.sm,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    alignSelf: "flex-start" as const,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.track,
    backgroundColor: colors.paper,
  },
  passLinkText: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
  },
  // Phase 34 (Part C): stack Show pass / Revoke without widening the row.
  passActions: {
    alignItems: "flex-end" as const,
    justifyContent: "center" as const,
    gap: spacing.xs,
  },
  revokeText: {
    color: colors.invalid,
  },
};
