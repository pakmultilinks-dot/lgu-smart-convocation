import type { ReactNode } from "react";
import { StyleSheet, Text, View, type ViewStyle } from "react-native";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

interface Props {
  title: string;
  subtitle?: string;
  children: ReactNode;
  style?: ViewStyle;
}

/** White card with a green rule under the section title. */
export function SectionCard({ title, subtitle, children, style }: Props) {
  return (
    <View style={[styles.card, style]}>
      <Text style={styles.title}>{title}</Text>
      {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      <View style={styles.rule} />
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    elevation: 2,
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
    padding: spacing.md,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 2, width: 0 },
    shadowOpacity: 0.08,
    shadowRadius: 8,
  },
  rule: {
    backgroundColor: colors.emerald,
    borderRadius: radius.sm,
    height: 3,
    marginBottom: spacing.sm,
    marginTop: spacing.xs,
    width: 44,
  },
  subtitle: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: 2,
  },
  title: {
    color: colors.greenDark,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
  },
});
