import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef } from "react";
import { Animated, Pressable, StyleSheet, Text } from "react-native";
import type { ScanLevel, ScanResult } from "../api/client";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

const levelStyle: Record<ScanLevel, { bg: string; icon: keyof typeof Ionicons.glyphMap }> = {
  green: { bg: colors.green, icon: "checkmark-circle" },
  red: { bg: colors.red, icon: "close-circle" },
  amber: { bg: colors.amber, icon: "alert-circle" },
};

interface Props {
  result: ScanResult;
  onDismiss: () => void;
}

export function ResultCard({ result, onDismiss }: Props) {
  const style = levelStyle[result.level];
  const scale = useRef(new Animated.Value(0.85)).current;
  const opacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.spring(scale, { damping: 14, toValue: 1, useNativeDriver: true }),
      Animated.timing(opacity, { duration: 180, toValue: 1, useNativeDriver: true }),
    ]).start();
  }, [opacity, scale]);

  return (
    <Pressable style={styles.backdrop} onPress={onDismiss}>
      <Animated.View
        style={[
          styles.card,
          { backgroundColor: style.bg, opacity, transform: [{ scale }] },
        ]}
      >
        <Ionicons name={style.icon} size={64} color={colors.white} />
        <Text style={styles.title}>{result.title}</Text>
        {result.name ? <Text style={styles.name}>{result.name}</Text> : null}
        {result.sub ? <Text style={styles.sub}>{result.sub}</Text> : null}
        {result.detail ? <Text style={styles.detail}>{result.detail}</Text> : null}
        {(result.gate || result.time) && (
          <Text style={styles.meta}>
            {[result.gate, result.time].filter(Boolean).join("  \u00B7  ")}
          </Text>
        )}
        <Text style={styles.hint}>Tap to dismiss</Text>
      </Animated.View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    alignItems: "center",
    backgroundColor: colors.overlay,
    bottom: 0,
    justifyContent: "center",
    left: 0,
    padding: spacing.lg,
    position: "absolute",
    right: 0,
    top: 0,
    zIndex: 20,
  },
  card: {
    alignItems: "center",
    borderRadius: radius.lg,
    elevation: 8,
    padding: spacing.xl,
    shadowColor: "#000",
    shadowOffset: { height: 4, width: 0 },
    shadowOpacity: 0.3,
    shadowRadius: 12,
    width: "100%",
  },
  detail: {
    color: colors.white,
    fontSize: fontSize.body,
    marginTop: spacing.sm,
    opacity: 0.92,
    textAlign: "center",
  },
  hint: {
    color: colors.white,
    fontSize: fontSize.caption,
    marginTop: spacing.lg,
    opacity: 0.7,
  },
  meta: {
    color: colors.white,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginTop: spacing.sm,
    opacity: 0.85,
  },
  name: {
    color: colors.white,
    fontSize: fontSize.heading,
    fontWeight: fontWeight.bold,
    marginTop: spacing.sm,
    textAlign: "center",
  },
  sub: {
    color: colors.white,
    fontSize: fontSize.body,
    marginTop: spacing.xs,
    opacity: 0.9,
    textAlign: "center",
  },
  title: {
    color: colors.white,
    fontSize: fontSize.title,
    fontWeight: fontWeight.bold,
    marginTop: spacing.md,
    textAlign: "center",
  },
});
