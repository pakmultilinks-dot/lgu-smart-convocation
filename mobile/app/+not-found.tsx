import { useEffect, useState } from "react";
import { router, usePathname } from "expo-router";
import { Text } from "react-native";
import { getAppMode, type AppMode } from "../src/store/appMode";
import { getToken } from "../src/store/studentSession";
import { AppButton, AppHeader, LoadingState, Screen } from "../src/ui";

type Recovery = { mode: AppMode | null; signedInStudent: boolean };

export default function NotFound() {
  const pathname = usePathname();
  const [recovery, setRecovery] = useState<Recovery | null>(null);

  useEffect(() => {
    let active = true;
    void Promise.all([getAppMode(), getToken()])
      .then(([mode, token]) => {
        if (active) setRecovery({ mode, signedInStudent: Boolean(token) });
      })
      .catch(() => {
        if (active) setRecovery({ mode: null, signedInStudent: false });
      });
    return () => { active = false; };
  }, []);

  if (!recovery) return <Screen><LoadingState label="Finding the right place to return..." /></Screen>;

  const adminPath = /admin|administration|liveboard/i.test(pathname);
  const destination = adminPath
    ? "/administration"
    : recovery.mode === "student"
    ? recovery.signedInStudent ? "/(student)/home" : "/(student)/welcome"
    : recovery.mode === "liveboard"
      ? "/(liveboard)"
      : recovery.mode === "volunteer"
        ? "/(volunteer)/home"
        : "/mode-picker";

  return (
    <Screen>
      <AppHeader title="Page not found" subtitle="This destination is not available." />
      <Text>The link may be incorrect or this page may have moved. Your account and current session have not been changed.</Text>
      <AppButton label="Return to your workspace" onPress={() => router.replace(destination)} />
    </Screen>
  );
}
