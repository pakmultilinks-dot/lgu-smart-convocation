import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  type TextStyle,
  type ViewStyle,
} from "react-native";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

type Variant = "primary" | "gold" | "danger" | "outline";

const variantStyle: Record<Variant, { bg: string; fg: string; border?: string }> = {
  primary: { bg: colors.navy, fg: colors.white },
  gold: { bg: colors.gold, fg: colors.navyDark },
  danger: { bg: colors.red, fg: colors.white },
  outline: { bg: colors.white, fg: colors.navy, border: colors.navy },
};

interface Props {
  title: string;
  onPress: () => void;
  variant?: Variant;
  disabled?: boolean;
  loading?: boolean;
  style?: ViewStyle;
  textStyle?: TextStyle;
}

export function PrimaryButton({
  title,
  onPress,
  variant = "primary",
  disabled = false,
  loading = false,
  style,
  textStyle,
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
        <ActivityIndicator size="small" color={v.fg} />
      ) : (
        <Text style={[styles.text, { color: v.fg }, textStyle]}>{title}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: "center",
    borderRadius: radius.md,
    borderWidth: 1.5,
    justifyContent: "center",
    minHeight: 48,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  disabled: {
    opacity: 0.5,
  },
  pressed: {
    opacity: 0.85,
  },
  text: {
    fontSize: fontSize.body,
    fontWeight: fontWeight.bold,
  },
});
