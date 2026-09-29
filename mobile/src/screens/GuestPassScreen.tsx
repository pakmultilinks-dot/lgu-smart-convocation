import QRCode from "react-native-qrcode-svg";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { Defs, LinearGradient, Rect, Stop, Svg } from "react-native-svg";
import {
  ApiError,
  fetchGuestPass,
  type GuestPass,
} from "../api/client";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { UNIVERSITY_NAME } from "../config";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

function DetailRow({ icon, label, value }: { icon: keyof typeof Ionicons.glyphMap; label: string; value: string }) {
  return (
    <View style={styles.detailRow}>
      <View style={styles.detailIcon}>
        <Ionicons name={icon} size={18} color={colors.green} />
      </View>
      <View style={styles.detailText}>
        <Text style={styles.detailLabel}>{label}</Text>
        <Text style={styles.detailValue}>{value}</Text>
      </View>
    </View>
  );
}

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
      <View style={styles.pass}>
        <View style={styles.passHeader}>
          <Svg style={StyleSheet.absoluteFill} width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
            <Defs>
              <LinearGradient id="passHead" x1="0" y1="0" x2="1" y2="0">
                <Stop offset="0" stopColor={colors.greenDeep} />
                <Stop offset="1" stopColor={colors.green} />
              </LinearGradient>
            </Defs>
            <Rect x="0" y="0" width="100" height="100" fill="url(#passHead)" />
          </Svg>
          <View style={styles.passHeaderRow}>
            <View style={styles.monogram}>
              <Text style={styles.monogramText}>LGU</Text>
            </View>
            <View style={styles.passHeaderText}>
              <Text style={styles.passUni}>{UNIVERSITY_NAME}</Text>
              <Text style={styles.passKind}>GUEST ENTRY PASS</Text>
            </View>
          </View>
          <View
            style={[
              styles.statusBadge,
              pass.used ? styles.statusUsed : styles.statusActive,
            ]}
          >
            <Ionicons
              name={pass.used ? "close-circle" : "checkmark-circle"}
              size={14}
              color={pass.used ? colors.muted : colors.green}
            />
            <Text
              style={[
                styles.statusText,
                pass.used ? styles.statusTextUsed : styles.statusTextActive,
              ]}
            >
              {pass.used ? "ALREADY USED" : "VALID FOR ONE ENTRY"}
            </Text>
          </View>
        </View>

        <View style={styles.perforation}>
          {Array.from({ length: 24 }).map((_, i) => (
            <View key={i} style={styles.perfDash} />
          ))}
        </View>

        <View style={styles.passBody}>
          <View style={styles.qrWrap}>
            <QRCode value={pass.payload} size={220} />
          </View>
          <Text style={styles.name}>{pass.name}</Text>
          <DetailRow icon="person-outline" label="Guest name" value={pass.name} />
          <DetailRow icon="call-outline" label="Phone" value={pass.phone} />
          <DetailRow icon="id-card-outline" label="Host roll number" value={pass.host_roll_no} />
          <View style={styles.noteBox}>
            <Ionicons name="information-circle-outline" size={18} color={colors.green} />
            <Text style={styles.note}>
              Show this code at any gate. It becomes invalid after the first entry scan.
            </Text>
          </View>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {
    flexGrow: 1,
    justifyContent: "center",
    padding: spacing.lg,
  },
  detailIcon: {
    alignItems: "center",
    backgroundColor: colors.tint,
    borderRadius: radius.full,
    height: 38,
    justifyContent: "center",
    width: 38,
  },
  detailLabel: {
    color: colors.muted,
    fontSize: fontSize.small,
    textTransform: "uppercase",
  },
  detailRow: {
    alignItems: "center",
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.sm,
    width: "100%",
  },
  detailText: {
    flex: 1,
  },
  detailValue: {
    color: colors.text,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
    marginTop: 1,
  },
  monogram: {
    alignItems: "center",
    backgroundColor: colors.white,
    borderRadius: radius.md,
    height: 46,
    justifyContent: "center",
    width: 46,
  },
  monogramText: {
    color: colors.greenDark,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
  },
  name: {
    color: colors.greenDark,
    fontSize: fontSize.title,
    fontWeight: fontWeight.bold,
    marginBottom: spacing.sm,
    marginTop: spacing.md,
    textAlign: "center",
  },
  note: {
    color: colors.muted,
    flex: 1,
    fontSize: fontSize.caption,
    lineHeight: 18,
    marginLeft: spacing.sm,
  },
  noteBox: {
    alignItems: "flex-start",
    backgroundColor: colors.tint,
    borderRadius: radius.md,
    flexDirection: "row",
    marginTop: spacing.md,
    padding: spacing.md,
    width: "100%",
  },
  pass: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    elevation: 5,
    overflow: "hidden",
    shadowColor: colors.greenDark,
    shadowOffset: { height: 4, width: 0 },
    shadowOpacity: 0.18,
    shadowRadius: 14,
  },
  passBody: {
    alignItems: "center",
    padding: spacing.lg,
  },
  passHeader: {
    overflow: "hidden",
    padding: spacing.lg,
  },
  passHeaderRow: {
    alignItems: "center",
    flexDirection: "row",
    gap: spacing.md,
  },
  passHeaderText: {
    flex: 1,
  },
  passKind: {
    color: colors.gold,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    letterSpacing: 2,
    marginTop: 2,
  },
  passUni: {
    color: colors.white,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
  },
  perfDash: {
    backgroundColor: colors.border,
    height: 2,
    width: 8,
  },
  perforation: {
    flexDirection: "row",
    gap: 6,
    justifyContent: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  qrWrap: {
    backgroundColor: colors.white,
    borderColor: colors.border,
    borderRadius: radius.md,
    borderWidth: 1,
    elevation: 2,
    padding: spacing.md,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  statusActive: {
    backgroundColor: colors.white,
  },
  statusBadge: {
    alignItems: "center",
    alignSelf: "flex-start",
    borderRadius: radius.full,
    flexDirection: "row",
    gap: 6,
    marginTop: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
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
