import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { colors, fonts } from "../theme";

export function DashboardTile({ title, detail, icon, onPress }: {
  title: string; detail: string; icon: keyof typeof Ionicons.glyphMap; onPress: () => void;
}) {
  return <Pressable accessibilityRole="button" accessibilityLabel={title} onPress={onPress} style={({ pressed }) => [styles.tile, pressed && { opacity: 0.7 }]}>
    <Ionicons name={icon} size={22} color={colors.ink} />
    <Text style={styles.title}>{title}</Text><Text style={styles.detail}>{detail}</Text>
  </Pressable>;
}
export function DashboardGrid({ children }: { children: React.ReactNode }) {
  return <View style={styles.grid}>{children}</View>;
}
export function DashboardStat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <View style={styles.tile}><Text style={styles.detail}>{label}</Text><Text style={styles.value}>{value}</Text>{detail ? <Text style={styles.detail}>{detail}</Text> : null}</View>;
}
const styles = StyleSheet.create({
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  tile: { flexBasis: "46%", flexGrow: 1, minWidth: 125, padding: 14, gap: 7, borderRadius: 14, borderWidth: 1, borderColor: colors.track, backgroundColor: colors.paper },
  title: { fontFamily: fonts.display, fontSize: 15, color: colors.ink },
  value: { fontFamily: fonts.display, fontSize: 24, color: colors.ink },
  detail: { fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 18, color: colors.muted },
});
