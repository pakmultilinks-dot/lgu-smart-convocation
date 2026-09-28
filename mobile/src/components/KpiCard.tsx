import { StyleSheet, Text, View } from "react-native";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

interface Props {
  title: string;
  value: string;
  accent?: string;
}

export function KpiCard({ title, value, accent = colors.navy }: Props) {
  return (
    <View style={styles.card}>
      <View style={[styles.accentBar, { backgroundColor: accent }]} />
      <Text style={styles.value} numberOfLines={1} adjustsFontSizeToFit>
        {value}
      </Text>
      <Text style={styles.title}>{title}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  accentBar: {
    borderRadius: radius.sm,
    height: 4,
    marginBottom: spacing.sm,
    width: 32,
  },
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.md,
    elevation: 2,
    flex: 1,
    minWidth: 0,
    padding: spacing.md,
    shadowColor: "#0B2447",
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.08,
    shadowRadius: 4,
  },
  title: {
    color: colors.muted,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.medium,
    marginTop: 2,
  },
  value: {
    color: colors.text,
    fontSize: fontSize.title,
    fontWeight: fontWeight.bold,
  },
});
