import { Ionicons } from "@expo/vector-icons";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

export function LoadingState({ message = "Loading..." }: { message?: string }) {
  return (
    <View style={styles.center}>
      <View style={styles.spinnerRing}>
        <ActivityIndicator size="large" color={colors.green} />
      </View>
      <Text style={styles.message}>{message}</Text>
    </View>
  );
}

interface EmptyProps {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  message: string;
}

export function EmptyState({ icon, title, message }: EmptyProps) {
  return (
    <View style={styles.center}>
      <View style={styles.iconRing}>
        <Ionicons name={icon} size={32} color={colors.green} />
      </View>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.message}>{message}</Text>
    </View>
  );
}

interface ErrorProps {
  message: string;
  onRetry: () => void;
}

export function ErrorState({ message, onRetry }: ErrorProps) {
  return (
    <View style={styles.center}>
      <View style={[styles.iconRing, styles.errorRing]}>
        <Ionicons name="cloud-offline-outline" size={32} color={colors.red} />
      </View>
      <Text style={styles.title}>Something went wrong</Text>
      <Text style={styles.message}>{message}</Text>
      <Text style={styles.retry} onPress={onRetry}>
        Tap to retry
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    alignItems: "center",
    flex: 1,
    justifyContent: "center",
    padding: spacing.xl,
  },
  errorRing: {
    backgroundColor: colors.redSoft,
  },
  iconRing: {
    alignItems: "center",
    backgroundColor: colors.tint,
    borderRadius: radius.full,
    height: 76,
    justifyContent: "center",
    marginBottom: spacing.md,
    width: 76,
  },
  message: {
    color: colors.muted,
    fontSize: fontSize.body,
    marginTop: spacing.xs,
    textAlign: "center",
  },
  retry: {
    color: colors.green,
    fontSize: fontSize.body,
    fontWeight: fontWeight.bold,
    marginTop: spacing.md,
    textDecorationLine: "underline",
  },
  spinnerRing: {
    alignItems: "center",
    backgroundColor: colors.tint,
    borderRadius: radius.full,
    height: 76,
    justifyContent: "center",
    marginBottom: spacing.md,
    width: 76,
  },
  title: {
    color: colors.text,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
    textAlign: "center",
  },
});
