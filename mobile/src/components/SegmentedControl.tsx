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
    backgroundColor: colors.border,
    borderRadius: radius.md,
    flexDirection: "row",
    padding: spacing.xs,
  },
  label: {
    color: colors.muted,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
  },
  labelActive: {
    color: colors.navy,
  },
  option: {
    alignItems: "center",
    borderRadius: radius.sm,
    flex: 1,
    paddingVertical: spacing.sm,
  },
  optionActive: {
    backgroundColor: colors.white,
    elevation: 2,
    shadowColor: "#0B2447",
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.12,
    shadowRadius: 3,
  },
});
