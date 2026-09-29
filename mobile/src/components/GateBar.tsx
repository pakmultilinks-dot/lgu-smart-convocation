import { useEffect, useRef } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

interface Props {
  label: string;
  count: number;
  maxCount: number;
}

/** Throughput row with a smoothly animating green progress bar. */
export function GateBar({ label, count, maxCount }: Props) {
  const widthAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const target = maxCount > 0 ? Math.max(4, (count / maxCount) * 100) : 0;
    Animated.timing(widthAnim, {
      duration: 700,
      toValue: target,
      useNativeDriver: false,
    }).start();
  }, [count, maxCount, widthAnim]);

  return (
    <View style={styles.row}>
      <Text style={styles.label} numberOfLines={1}>
        {label}
      </Text>
      <View style={styles.track}>
        <Animated.View
          style={[styles.fill, { width: widthAnim.interpolate({
            inputRange: [0, 100],
            outputRange: ["0%", "100%"],
          }) }]}
        />
      </View>
      <Text style={styles.count}>{count}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  count: {
    color: colors.greenDark,
    fontSize: fontSize.body,
    fontWeight: fontWeight.bold,
    minWidth: 36,
    textAlign: "right",
  },
  fill: {
    backgroundColor: colors.emerald,
    borderRadius: radius.full,
    height: "100%",
  },
  label: {
    color: colors.text,
    flex: 1.2,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.medium,
  },
  row: {
    alignItems: "center",
    flexDirection: "row",
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  track: {
    backgroundColor: colors.tint,
    borderRadius: radius.full,
    flex: 2,
    height: 12,
    overflow: "hidden",
  },
});
