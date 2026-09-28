import { StyleSheet, Text, View } from "react-native";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";
import type { FeedItem } from "../api/client";

function badgeColor(mode: string): { bg: string; fg: string } {
  if (mode === "entry") {
    return { bg: colors.greenSoft, fg: colors.green };
  }
  return { bg: colors.amberSoft, fg: colors.amber };
}

export function ScanFeedItem({ item }: { item: FeedItem }) {
  const badge = badgeColor(item.mode);
  return (
    <View style={styles.row}>
      <View style={styles.main}>
        <Text style={styles.name} numberOfLines={1}>
          {item.person_name}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          {item.person_type === "guest" ? "Guest" : "Student"} · {item.gate_label} ·{" "}
          {item.scanned_at}
        </Text>
      </View>
      <View style={[styles.badge, { backgroundColor: badge.bg }]}>
        <Text style={[styles.badgeText, { color: badge.fg }]}>
          {item.mode === "entry" ? "ENTRY" : "EXIT"}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    borderRadius: radius.full,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  badgeText: {
    fontSize: fontSize.small,
    fontWeight: fontWeight.bold,
  },
  main: {
    flex: 1,
    minWidth: 0,
  },
  meta: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: 2,
  },
  name: {
    color: colors.text,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
  },
  row: {
    alignItems: "center",
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
    flexDirection: "row",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
  },
});
