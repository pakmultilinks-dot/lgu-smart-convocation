import { useEffect, useRef } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";
import type { FeedItem } from "../api/client";

function badgeColor(mode: string): { bg: string; fg: string; icon: keyof typeof Ionicons.glyphMap } {
  if (mode === "entry") {
    return { bg: colors.emeraldSoft, fg: colors.green, icon: "log-in-outline" };
  }
  return { bg: colors.amberSoft, fg: colors.amber, icon: "log-out-outline" };
}

/** One scan row that slides in when it first appears. */
export function ScanFeedItem({ item }: { item: FeedItem }) {
  const badge = badgeColor(item.mode);
  const slide = useRef(new Animated.Value(28)).current;
  const fade = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(slide, { duration: 320, toValue: 0, useNativeDriver: true }),
      Animated.timing(fade, { duration: 320, toValue: 1, useNativeDriver: true }),
    ]).start();
  }, [slide, fade]);

  return (
    <Animated.View style={[styles.row, { opacity: fade, transform: [{ translateY: slide }] }]}>
      <View style={[styles.iconWrap, { backgroundColor: badge.bg }]}>
        <Ionicons name={badge.icon} size={18} color={badge.fg} />
      </View>
      <View style={styles.main}>
        <Text style={styles.name} numberOfLines={1}>
          {item.person_name}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          {item.person_type === "guest" ? "Guest" : "Student"} {"\u00B7"} {item.gate_label} {"\u00B7"} {item.scanned_at}
        </Text>
      </View>
      <View style={[styles.badge, { backgroundColor: badge.bg }]}>
        <Text style={[styles.badgeText, { color: badge.fg }]}>
          {item.mode === "entry" ? "ENTRY" : "EXIT"}
        </Text>
      </View>
    </Animated.View>
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
  iconWrap: {
    alignItems: "center",
    borderRadius: radius.full,
    height: 36,
    justifyContent: "center",
    width: 36,
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
