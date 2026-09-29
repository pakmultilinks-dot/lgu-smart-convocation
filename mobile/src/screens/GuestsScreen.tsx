import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
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

function GuestRow({ guest }: { guest: Guest }) {
  return (
    <Pressable
      style={styles.row}
      onPress={() =>
        router.push({ params: { gid: String(guest.id) }, pathname: "/guest-pass" })
      }
    >
      <View style={styles.rowMain}>
        <Text style={styles.name} numberOfLines={1}>
          {guest.name}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          Host: {guest.host_roll_no} · {guest.phone}
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

export function GuestsScreen() {
  const [guests, setGuests] = useState<Guest[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
      <FlatList
        data={guests}
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
          />
        }
        ListEmptyComponent={
          <EmptyState
            icon="people-outline"
            title="No guests yet"
            message="Register a guest with the button below to issue a single-use entry pass."
          />
        }
      />

      <Pressable
        style={styles.fab}
        onPress={() => {
          resetForm();
          setFormOpen(true);
        }}
      >
        <Ionicons name="add" size={28} color={colors.white} />
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
              autoCapitalize="words"
            />

            <Text style={styles.label}>Phone</Text>
            <TextInput
              style={styles.input}
              value={phone}
              onChangeText={setPhone}
              placeholder="03001234567"
              keyboardType="phone-pad"
            />

            <Text style={styles.label}>Host roll number</Text>
            <TextInput
              style={styles.input}
              value={hostRoll}
              onChangeText={setHostRoll}
              placeholder="Student roll number of the host"
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
  badge: {
    borderRadius: radius.full,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  badgeActive: {
    backgroundColor: colors.greenSoft,
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
  fab: {
    alignItems: "center",
    backgroundColor: colors.navy,
    borderRadius: radius.full,
    bottom: spacing.lg,
    elevation: 6,
    height: 60,
    justifyContent: "center",
    position: "absolute",
    right: spacing.lg,
    shadowColor: "#0B2447",
    shadowOffset: { height: 3, width: 0 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    width: 60,
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
    color: colors.navy,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    marginTop: spacing.md,
    textTransform: "uppercase",
  },
  list: {
    flexGrow: 1,
    padding: spacing.md,
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
    backgroundColor: colors.gold,
    borderRadius: radius.sm,
    height: 3,
    marginTop: spacing.xs,
    width: 40,
  },
  modalTitle: {
    color: colors.navy,
    fontSize: fontSize.heading,
    fontWeight: fontWeight.bold,
  },
  name: {
    color: colors.text,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  row: {
    alignItems: "center",
    backgroundColor: colors.card,
    borderRadius: radius.md,
    elevation: 1,
    flexDirection: "row",
    gap: spacing.sm,
    marginBottom: spacing.sm,
    padding: spacing.md,
    shadowColor: "#0B2447",
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
  },
  rowMain: {
    flex: 1,
    minWidth: 0,
  },
});
