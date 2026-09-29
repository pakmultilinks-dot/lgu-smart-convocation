import { StyleSheet, Text, View } from "react-native";
import { CountUp } from "./CountUp";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

interface Props {
  title: string;
  value: number;
  accent?: string;
  icon?: React.ReactNode;
  subtext?: string;
}

/** Stat card with an animated count-up number and a colour accent bar. */
export function KpiCard({ title, value, accent = colors.green, icon, subtext }: Props) {
  return (
    <View style={styles.card}>
      <View style={[styles.accentBar, { backgroundColor: accent }]} />
      <View style={styles.topRow}>
        <CountUp
          value={value}
          style={styles.value}
        />
        {icon ?? null}
      </View>
      <Text style={styles.title}>{title}</Text>
      {subtext ? <Text style={styles.subtext}>{subtext}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  accentBar: {
    borderRadius: radius.sm,
    height: 4,
    marginBottom: spacing.sm,
    width: 36,
  },
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    elevation: 3,
    flex: 1,
    minWidth: 0,
    padding: spacing.md,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 2, width: 0 },
    shadowOpacity: 0.1,
    shadowRadius: 8,
  },
  subtext: {
    color: colors.muted,
    fontSize: fontSize.small,
    marginTop: 2,
  },
  title: {
    color: colors.muted,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.medium,
    marginTop: 2,
  },
  topRow: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
  },
  value: {
    color: colors.text,
    fontSize: fontSize.display,
    fontWeight: fontWeight.bold,
  },
});
