import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Pressable, ScrollView, Text, View } from "react-native";
import {
  ApiError,
  fetchGuests,
  isValidPhone,
  registerGuest,
  revokeGuestPass,
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

/**
 * Guests — Screen 4 of the institutional system (Phase 35C).
 * List FIRST: full name (wraps, never truncated), host roll on its own
 * line, masked phone (tap to reveal — Phase 35H; single line, never
 * ellipsised — 35I T.2), live pass state + pass action. Used passes show
 * "Entered [date, ]HH:MM, gate" — 12h local clock; the DATE prefix appears
 * when the entry is not from today (35I T.4). Top action is the primary
 * "+ Add guest" toggle; the registration form sits below the list on
 * paper/ink. Submit/showPass/list logic is unchanged from Phase 35B
 * (single-use pass truth comes from the backend). 35M R2 (item 4): the
 * phone mask lives in src/utils/phone.ts — the guest list and the guest
 * pass artwork share one convention.
 */

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

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [hostRoll, setHostRoll] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [lastPass, setLastPass] = useState<{ gid: number; payload: string } | null>(
    null,
  );
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

  const submit = useCallback(async () => {
    const trimmedName = name.trim();
    const trimmedPhone = phone.trim();
    const trimmedHost = hostRoll.trim().toUpperCase();
    if (!trimmedName) {
      setFormError("Enter the guest's name.");
      return;
    }
    if (!isValidPhone(trimmedPhone)) {
      setFormError("Enter a valid Pakistani mobile number, e.g. 03001234567.");
      return;
    }
    if (!trimmedHost) {
      setFormError("Enter the host student's roll number.");
      return;
    }
    setSaving(true);
    setFormError(null);
    setFormOpen(true);
    try {
      const pass = await registerGuest({
        name: trimmedName,
        phone: trimmedPhone,
        host_roll_no: trimmedHost,
      });
      if (pass.ok && pass.gid != null && pass.payload) {
        setLastPass({ gid: pass.gid, payload: pass.payload });
      }
      setName("");
      setPhone("");
      setHostRoll("");
      await loadGuests();
    } catch (e) {
      setFormError(
        e instanceof ApiError
          ? e.message
          : "The guest could not be registered. Check the connection and retry.",
      );
    } finally {
      setSaving(false);
    }
  }, [name, phone, hostRoll, loadGuests]);

  const showPass = useCallback((gid: number) => {
    router.push({ pathname: "/guest-pass", params: { gid: String(gid) } });
  }, []);

  // Phase 34 (Part C): revoke an UNUSED active pass. Scanner-staff gated
  // server-side; the confirm step keeps a shared gate device from revoking
  // on a mis-tap. A used pass has no revoke (it keeps its 'used' meaning).
  const revoke = useCallback((guest: Guest) => {
    Alert.alert(
      "Revoke guest pass?",
      `${guest.name}'s pass will be refused at every gate. This cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Revoke",
          style: "destructive",
          onPress: () => {
            void revokeGuestPass(guest.id)
              .then(() => loadGuests())
              .catch((e: unknown) =>
                Alert.alert(
                  "Could not revoke",
                  e instanceof Error ? e.message : "Try again.",
                ),
              );
          },
        },
      ],
    );
  }, [loadGuests]);

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
        title="Guest registration"
        subtitle="Single-use passes, tied to a host."
      />

      {/* Top action — primary (35I T.3), no icon, never a hero card. */}
      <AppButton
        label="+ Add guest"
        variant="primary"
        onPress={() => setFormOpen((open) => !open)}
      />

      {/* 1 — Guest list FIRST. */}
      <SectionCard>
        <SectionEyebrow>
          {guests
            ? `Guest list · ${guests.length} registered · ${guests.filter(isReady).length} ready · ${guests.filter((g) => g.used).length} used${guests.some((g) => g.status === "revoked") ? ` · ${guests.filter((g) => g.status === "revoked").length} revoked` : ""}`
            : "Guest list"}
        </SectionEyebrow>
        {listError ? (
          <ErrorState
            title={needsSignIn ? "Sign in to view guests" : "Guest list unavailable"}
            body={
              needsSignIn
                ? "The guest list is restricted to signed-in scanner staff. Sign in on the Scanner tab, then retry."
                : listError
            }
            onRetry={() => void loadGuests()}
          />
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
                        {/* Phase 34 (Part C): revoke is only offered for an
                            active pass — a revoked pass offers nothing. */}
                        {guest.status === "revoked" ? null : (
                          <Pressable
                            accessibilityRole="button"
                            accessibilityLabel={`Revoke pass for ${guest.name}`}
                            onPress={() => revoke(guest)}
                            style={styles.passLink}
                          >
                            <Text style={[styles.passLinkText, styles.revokeText]}>
                              Revoke
                            </Text>
                          </Pressable>
                        )}
                      </View>
                    )}
                  </View>
                ))}
              </ScrollView>
            )}
          </>
        )}
      </SectionCard>

      {/* 2 — Registration form below the list, paper/ink, revealed by the
          inline Add guest action. Submit/showPass logic unchanged. */}
      {formOpen ? (
        <SectionCard tone="tint">
          <SectionEyebrow>Register a guest</SectionEyebrow>
          <Field
            label="Guest name"
            placeholder="Full name"
            value={name}
            onChangeText={setName}
            autoCapitalize="words"
          />
          <Field
            label="Mobile number"
            placeholder="03XXXXXXXXX"
            value={phone}
            onChangeText={setPhone}
            keyboardType="phone-pad"
            hint="Used to verify the pass at the gate."
          />
          <Field
            label="Host roll number"
            placeholder="LGU-2024-XXXX"
            value={hostRoll}
            onChangeText={(t) => setHostRoll(t.toUpperCase())}
            autoCapitalize="characters"
            hint="The host student must already exist in the system."
          />
          {formError ? <Text style={styles.formError}>{formError}</Text> : null}
          <AppButton
            label={saving ? "Registering..." : "Register guest"}
            icon="person-add-outline"
            loading={saving}
            onPress={() => void submit()}
          />
          {lastPass ? (
            <View style={styles.passCreated}>
              <Ionicons name="checkmark-circle" size={18} color={colors.valid} />
              <View style={styles.flex1}>
                <Text style={styles.passCreatedTitle}>Guest registered</Text>
                <Text style={styles.passCreatedBody} numberOfLines={2}>
                  Pass created. Show the QR pass to the guest now.
                </Text>
              </View>
              <AppButton
                label="Show pass"
                variant="secondary"
                size="md"
                onPress={() => showPass(lastPass.gid)}
                style={styles.passCreatedButton}
              />
            </View>
          ) : null}
        </SectionCard>
      ) : null}
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
