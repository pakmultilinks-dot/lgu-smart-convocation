import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { getAppMode } from "../src/store/appMode";
import { colors } from "../src/theme";

export default function Index() {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const mode = await getAppMode();
      if (cancelled) return;
      if (mode === null) {
        router.replace("/mode-picker");
      } else if (mode === "volunteer") {
        router.replace("/(volunteer)/home");
      } else {
        router.replace("/(liveboard)");
      }
      setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (!ready) {
    return (
      <View style={styles.root}>
        <ActivityIndicator size="large" color={colors.green} />
      </View>
    );
  }
  return null;
}

const styles = StyleSheet.create({
  root: {
    alignItems: "center",
    backgroundColor: colors.background,
    flex: 1,
    justifyContent: "center",
  },
});
