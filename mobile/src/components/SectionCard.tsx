import type { ReactNode } from "react";
import { StyleSheet, Text, View, type ViewStyle } from "react-native";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

interface Props {
  title: string;
  children: ReactNode;
  style?: ViewStyle;
}

/** White card with a gold rule under the section title. */
export function SectionCard({ title, children, style }: Props) {
  return (
    <View style={[styles.card, style]}>
      <Text style={styles.title}>{title}</Text>
      <View style={styles.rule} />
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.md,
    elevation: 2,
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
    padding: spacing.md,
    shadowColor: "#0B2447",
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.08,
    shadowRadius: 4,
  },
  rule: {
    backgroundColor: colors.gold,
    borderRadius: radius.sm,
    height: 3,
    marginBottom: spacing.sm,
    marginTop: spacing.xs,
    width: 40,
  },
  title: {
    color: colors.navy,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
  },
});
