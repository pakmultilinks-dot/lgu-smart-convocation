import { StyleSheet, Text, View } from "react-native";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

interface Props {
  label: string;
  count: number;
  maxCount: number;
}

export function GateBar({ label, count, maxCount }: Props) {
  const width = maxCount > 0 ? Math.max(4, (count / maxCount) * 100) : 0;
  return (
    <View style={styles.row}>
      <Text style={styles.label} numberOfLines={1}>
        {label}
      </Text>
      <View style={styles.track}>
        <View style={[styles.fill, { width: `${width}%` }]} />
      </View>
      <Text style={styles.count}>{count}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  count: {
    color: colors.text,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
    minWidth: 36,
    textAlign: "right",
  },
  fill: {
    backgroundColor: colors.green,
    borderRadius: radius.full,
    height: "100%",
  },
  label: {
    color: colors.text,
    flex: 1,
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
    backgroundColor: colors.border,
    borderRadius: radius.full,
    flex: 2,
    height: 10,
    overflow: "hidden",
  },
});
