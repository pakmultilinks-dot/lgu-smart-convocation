import { Pressable, StyleSheet, Text, type ViewStyle } from "react-native";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

type Variant = "primary" | "accent" | "gold" | "danger" | "outline" | "ghost";

const variantStyle: Record<Variant, { bg: string; fg: string; border?: string }> = {
  primary: { bg: colors.green, fg: colors.white },
  accent: { bg: colors.emerald, fg: colors.white },
  gold: { bg: colors.gold, fg: colors.greenDark },
  danger: { bg: colors.red, fg: colors.white },
  outline: { bg: colors.white, fg: colors.green, border: colors.green },
  ghost: { bg: colors.tint, fg: colors.greenDark },
};

interface Props {
  title: string;
  onPress: () => void;
  variant?: Variant;
  disabled?: boolean;
  loading?: boolean;
  style?: ViewStyle;
}

export function PrimaryButton({
  title,
  onPress,
  variant = "primary",
  disabled = false,
  loading = false,
  style,
}: Props) {
  const v = variantStyle[variant];
  const inactive = disabled || loading;
  return (
    <Pressable
      onPress={onPress}
      disabled={inactive}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: v.bg, borderColor: v.border ?? "transparent" },
        pressed && !inactive ? styles.pressed : null,
        inactive ? styles.disabled : null,
        style,
      ]}
    >
      {loading ? (
        <Text style={[styles.text, { color: v.fg }]}>Please wait...</Text>
      ) : (
        <Text style={[styles.text, { color: v.fg }]}>{title}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: "center",
    borderRadius: radius.lg,
    borderWidth: 1.5,
    elevation: 2,
    justifyContent: "center",
    minHeight: 52,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 2, width: 0 },
    shadowOpacity: 0.18,
    shadowRadius: 6,
  },
  disabled: {
    opacity: 0.5,
  },
  pressed: {
    opacity: 0.88,
    transform: [{ scale: 0.98 }],
  },
  text: {
    fontSize: fontSize.body,
    fontWeight: fontWeight.bold,
  },
});
