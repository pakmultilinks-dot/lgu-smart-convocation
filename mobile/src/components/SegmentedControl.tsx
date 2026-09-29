import { Pressable, StyleSheet, Text, View } from "react-native";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

interface Props<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
}: Props<T>) {
  return (
    <View style={styles.container}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <Pressable
            key={option.value}
            onPress={() => onChange(option.value)}
            style={[styles.option, active && styles.optionActive]}
          >
            <Text style={[styles.label, active && styles.labelActive]}>
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.tint,
    borderRadius: radius.lg,
    flexDirection: "row",
    padding: spacing.xs,
  },
  label: {
    color: colors.muted,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
  },
  labelActive: {
    color: colors.white,
  },
  option: {
    alignItems: "center",
    borderRadius: radius.md,
    flex: 1,
    paddingVertical: spacing.sm,
  },
  optionActive: {
    backgroundColor: colors.green,
    elevation: 2,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.2,
    shadowRadius: 3,
  },
});
