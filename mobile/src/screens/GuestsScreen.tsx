import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  FlatList,
  Modal,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import {
  ApiError,
  fetchGuests,
  isValidPhone,
  registerGuest,
  type Guest,
} from "../api/client";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { PrimaryButton } from "../components/PrimaryButton";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

const AVATAR_COLORS = [colors.green, colors.emerald, colors.greenDeep, "#4C8056", "#7BA98C"];

function avatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) {
    return parts[0].slice(0, 1).toUpperCase();
  }
  return (parts[0].slice(0, 1) + parts[parts.length - 1].slice(0, 1)).toUpperCase();
}

type Filter = "all" | "active" | "used";

function GuestRow({ guest }: { guest: Guest }) {
  return (
    <Pressable
      onPress={() =>
        router.push({ params: { gid: String(guest.id) }, pathname: "/guest-pass" })
      }
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
    >
      <View style={[styles.avatar, { backgroundColor: avatarColor(guest.name) }]}>
        <Text style={styles.avatarText}>{initials(guest.name)}</Text>
      </View>
      <View style={styles.rowMain}>
        <Text style={styles.name} numberOfLines={1}>
          {guest.name}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          Host: {guest.host_roll_no} {"\u00B7"} {guest.phone}
        </Text>
      </View>
      <View
        style={[
          styles.badge,
          guest.used ? styles.badgeUsed : styles.badgeActive,
        ]}
      >
        <Text
          style={[
            styles.badgeText,
            guest.used ? styles.badgeTextUsed : styles.badgeTextActive,
          ]}
        >
          {guest.used ? "USED" : "ACTIVE"}
        </Text>
      </View>
      <Ionicons name="chevron-forward" size={20} color={colors.muted} />
    </Pressable>
  );
}

const FILTERS: { label: string; value: Filter }[] = [
  { label: "All", value: "all" },
  { label: "Active", value: "active" },
  { label: "Used", value: "used" },
];

export function GuestsScreen() {
  const [guests, setGuests] = useState<Guest[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [hostRoll, setHostRoll] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async (showSpinner: boolean) => {
    if (showSpinner) {
      setLoading(true);
    }
    try {
      setGuests(await fetchGuests());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load guests.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void load(true);
    }, [load]),
  );

  // Search runs against the already-fetched list; the 300 ms debounce
  // keeps the filter from re-running on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  const visible = useMemo(() => {
    const q = debouncedQuery.trim().toLowerCase();
    return guests.filter((g) => {
      if (filter === "active" && g.used) return false;
      if (filter === "used" && !g.used) return false;
      if (q.length === 0) return true;
      return (
        g.name.toLowerCase().includes(q) ||
        g.host_roll_no.toLowerCase().includes(q) ||
        g.phone.includes(q)
      );
    });
  }, [guests, debouncedQuery, filter]);

  const activeCount = guests.filter((g) => !g.used).length;

  const resetForm = () => {
    setName("");
    setPhone("");
    setHostRoll("");
    setFormError(null);
  };

  const submit = async () => {
    if (name.trim().length === 0) {
      setFormError("Guest name is required.");
      return;
    }
    if (!isValidPhone(phone)) {
      setFormError("Enter a valid mobile number, for example 03001234567.");
      return;
    }
    if (hostRoll.trim().length === 0) {
      setFormError("Host roll number is required.");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const result = await registerGuest({
        host_roll_no: hostRoll.trim(),
        name: name.trim(),
        phone: phone.trim(),
      });
      setFormOpen(false);
      resetForm();
      await load(false);
      router.push({
        params: { gid: String(result.gid) },
        pathname: "/guest-pass",
      });
    } catch (e) {
      setFormError(
        e instanceof ApiError ? e.message : "Registration failed. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <LoadingState message="Loading guest list..." />;
  }

  if (error) {
    return <ErrorState message={error} onRetry={() => void load(true)} />;
  }

  return (
    <View style={styles.root}>
      <View style={styles.searchWrap}>
        <Ionicons name="search" size={20} color={colors.muted} />
        <TextInput
          style={styles.searchInput}
          value={query}
          onChangeText={setQuery}
          placeholder="Search name, roll number, phone"
          placeholderTextColor={colors.muted}
          returnKeyType="search"
        />
        {query.length > 0 && (
          <Pressable onPress={() => setQuery("")}>
            <Ionicons name="close-circle" size={20} color={colors.muted} />
          </Pressable>
        )}
      </View>

      <View style={styles.filterRow}>
        {FILTERS.map((f) => {
          const active = filter === f.value;
          return (
            <Pressable
              key={f.value}
              onPress={() => setFilter(f.value)}
              style={[styles.filterChip, active && styles.filterChipActive]}
            >
              <Text style={[styles.filterText, active && styles.filterTextActive]}>
                {f.label}
              </Text>
            </Pressable>
          );
        })}
        <Text style={styles.countText}>
          {activeCount} active of {guests.length}
        </Text>
      </View>

      <FlatList
        data={visible}
        keyExtractor={(g) => String(g.id)}
        renderItem={({ item }) => <GuestRow guest={item} />}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              void load(false);
            }}
            colors={[colors.green]}
          />
        }
        ListEmptyComponent={
          <EmptyState
            icon="people-outline"
            title={debouncedQuery ? "No matches" : "No guests yet"}
            message={
              debouncedQuery
                ? "Try a different name, roll number, or phone number."
                : "Register a guest with the button below to issue a single-use entry pass."
            }
          />
        }
      />

      <Pressable
        style={({ pressed }) => [styles.fab, pressed && styles.fabPressed]}
        onPress={() => {
          resetForm();
          setFormOpen(true);
        }}
      >
        <Ionicons name="add" size={30} color={colors.white} />
      </Pressable>

      <Modal visible={formOpen} animationType="slide" transparent>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Register Guest</Text>
            <View style={styles.modalRule} />

            <Text style={styles.label}>Guest name</Text>
            <TextInput
              style={styles.input}
              value={name}
              onChangeText={setName}
              placeholder="Full name"
              placeholderTextColor={colors.muted}
              autoCapitalize="words"
            />

            <Text style={styles.label}>Phone</Text>
            <TextInput
              style={styles.input}
              value={phone}
              onChangeText={setPhone}
              placeholder="03001234567"
              placeholderTextColor={colors.muted}
              keyboardType="phone-pad"
            />

            <Text style={styles.label}>Host roll number</Text>
            <TextInput
              style={styles.input}
              value={hostRoll}
              onChangeText={setHostRoll}
              placeholder="Student roll number of the host"
              placeholderTextColor={colors.muted}
              autoCapitalize="characters"
            />

            {formError && <Text style={styles.formError}>{formError}</Text>}

            <View style={styles.modalButtons}>
              <PrimaryButton
                title="Cancel"
                onPress={() => setFormOpen(false)}
                variant="outline"
                style={styles.modalButton}
              />
              <PrimaryButton
                title="Register"
                onPress={() => void submit()}
                loading={submitting}
                style={styles.modalButton}
              />
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  avatar: {
    alignItems: "center",
    borderRadius: radius.full,
    height: 48,
    justifyContent: "center",
    width: 48,
  },
  avatarText: {
    color: colors.white,
    fontSize: fontSize.body,
    fontWeight: fontWeight.bold,
  },
  badge: {
    borderRadius: radius.full,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  badgeActive: {
    backgroundColor: colors.emeraldSoft,
  },
  badgeText: {
    fontSize: fontSize.small,
    fontWeight: fontWeight.bold,
  },
  badgeTextActive: {
    color: colors.green,
  },
  badgeTextUsed: {
    color: colors.muted,
  },
  badgeUsed: {
    backgroundColor: colors.border,
  },
  countText: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginLeft: "auto",
  },
  fab: {
    alignItems: "center",
    backgroundColor: colors.green,
    borderRadius: radius.full,
    bottom: spacing.lg,
    elevation: 6,
    height: 62,
    justifyContent: "center",
    position: "absolute",
    right: spacing.lg,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 3, width: 0 },
    shadowOpacity: 0.35,
    shadowRadius: 8,
    width: 62,
  },
  fabPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.94 }],
  },
  filterChip: {
    backgroundColor: colors.tint,
    borderRadius: radius.full,
    marginRight: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  filterChipActive: {
    backgroundColor: colors.green,
  },
  filterRow: {
    alignItems: "center",
    flexDirection: "row",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  filterText: {
    color: colors.muted,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
  },
  filterTextActive: {
    color: colors.white,
  },
  formError: {
    color: colors.red,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginTop: spacing.sm,
  },
  input: {
    backgroundColor: colors.inputBg,
    borderColor: colors.border,
    borderRadius: radius.md,
    borderWidth: 1,
    color: colors.text,
    fontSize: fontSize.body,
    marginTop: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  label: {
    color: colors.greenDark,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    marginTop: spacing.md,
    textTransform: "uppercase",
  },
  list: {
    flexGrow: 1,
    padding: spacing.md,
    paddingTop: spacing.sm,
  },
  meta: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: 2,
  },
  modalBackdrop: {
    backgroundColor: colors.overlay,
    flex: 1,
    justifyContent: "flex-end",
  },
  modalButton: {
    flex: 1,
  },
  modalButtons: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
  modalCard: {
    backgroundColor: colors.white,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: spacing.lg,
  },
  modalRule: {
    backgroundColor: colors.emerald,
    borderRadius: radius.sm,
    height: 3,
    marginTop: spacing.xs,
    width: 44,
  },
  modalTitle: {
    color: colors.greenDark,
    fontSize: fontSize.heading,
    fontWeight: fontWeight.bold,
  },
  name: {
    color: colors.text,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
  },
  pressed: {
    opacity: 0.9,
    transform: [{ scale: 0.99 }],
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  row: {
    alignItems: "center",
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    elevation: 2,
    flexDirection: "row",
    gap: spacing.sm,
    marginBottom: spacing.sm,
    padding: spacing.md,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.08,
    shadowRadius: 6,
  },
  rowMain: {
    flex: 1,
    minWidth: 0,
  },
  searchInput: {
    color: colors.text,
    flex: 1,
    fontSize: fontSize.body,
    marginLeft: spacing.sm,
  },
  searchWrap: {
    alignItems: "center",
    backgroundColor: colors.white,
    borderColor: colors.border,
    borderRadius: radius.lg,
    borderWidth: 1,
    flexDirection: "row",
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
});
