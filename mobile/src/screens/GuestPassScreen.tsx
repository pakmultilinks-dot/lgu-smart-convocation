import QRCode from "react-native-qrcode-svg";
import { useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import {
  ApiError,
  fetchGuestPass,
  type GuestPass,
} from "../api/client";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

export function GuestPassScreen() {
  const { gid } = useLocalSearchParams<{ gid?: string }>();
  const [pass, setPass] = useState<GuestPass | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const id = Number(gid);
    if (!gid || Number.isNaN(id)) {
      setError("No guest selected.");
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      setPass(await fetchGuestPass(id));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the pass.");
    } finally {
      setLoading(false);
    }
  }, [gid]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <LoadingState message="Loading guest pass..." />;
  }

  if (error) {
    return <ErrorState message={error} onRetry={() => void load()} />;
  }

  if (!pass) {
    return (
      <EmptyState
        icon="ticket-outline"
        title="Pass not found"
        message="This guest pass could not be loaded."
      />
    );
  }

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.content}>
      <View style={styles.card}>
        <Text style={styles.singleUse}>SINGLE USE</Text>
        <View style={styles.qrWrap}>
          <QRCode value={pass.payload} size={232} />
        </View>
        <Text style={styles.name}>{pass.name}</Text>
        <Text style={styles.meta}>Host roll: {pass.host_roll_no}</Text>
        <Text style={styles.meta}>Phone: {pass.phone}</Text>
        <View
          style={[
            styles.statusBadge,
            pass.used ? styles.statusUsed : styles.statusActive,
          ]}
        >
          <Text
            style={[
              styles.statusText,
              pass.used ? styles.statusTextUsed : styles.statusTextActive,
            ]}
          >
            {pass.used ? "ALREADY USED" : "VALID FOR ONE ENTRY"}
          </Text>
        </View>
        <Text style={styles.note}>
          Show this code at any gate. It becomes invalid after the first entry
          scan.
        </Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  card: {
    alignItems: "center",
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    elevation: 3,
    padding: spacing.xl,
    shadowColor: "#0B2447",
    shadowOffset: { height: 2, width: 0 },
    shadowOpacity: 0.1,
    shadowRadius: 6,
  },
  content: {
    flexGrow: 1,
    justifyContent: "center",
    padding: spacing.md,
  },
  meta: {
    color: colors.muted,
    fontSize: fontSize.body,
    marginTop: spacing.xs,
  },
  name: {
    color: colors.navy,
    fontSize: fontSize.title,
    fontWeight: fontWeight.bold,
    marginTop: spacing.md,
    textAlign: "center",
  },
  note: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: spacing.md,
    textAlign: "center",
  },
  qrWrap: {
    backgroundColor: colors.white,
    borderColor: colors.border,
    borderRadius: radius.md,
    borderWidth: 1,
    marginTop: spacing.md,
    padding: spacing.md,
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  singleUse: {
    backgroundColor: colors.navy,
    borderRadius: radius.full,
    color: colors.goldSoft,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    letterSpacing: 2,
    overflow: "hidden",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  statusActive: {
    backgroundColor: colors.greenSoft,
  },
  statusBadge: {
    borderRadius: radius.full,
    marginTop: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  statusText: {
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
  },
  statusTextActive: {
    color: colors.green,
  },
  statusTextUsed: {
    color: colors.muted,
  },
  statusUsed: {
    backgroundColor: colors.border,
  },
});
