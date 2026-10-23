import { router, useFocusEffect } from "expo-router";
import { useCallback, useState, type ReactNode } from "react";
import { AppState } from "react-native";
import { fetchDashboardAccess } from "../api/client";
import { AppButton, AppHeader, ErrorState, LoadingState, Screen } from "../ui";

/** Unmount disabled dashboards, including their camera and live polling. */
export function DashboardAccessGate({ mode, children }: {
  mode: "volunteer" | "liveboard"; children: ReactNode;
}) {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useFocusEffect(useCallback(() => {
    if (retry > 0) setError(null);
    let active = true;
    let checking = false;
    const check = async () => {
      if (checking || AppState.currentState === "background") return;
      checking = true;
      try {
        const access = await fetchDashboardAccess();
        if (active) {
          setAllowed(access[mode] === true);
          setError(null);
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : "Cannot check dashboard access.");
      } finally { checking = false; }
    };
    void check();
    const timer = setInterval(() => void check(), 15000);
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") void check();
    });
    return () => { active = false; clearInterval(timer); subscription.remove(); };
  }, [mode, retry]));

  if (allowed === true) return <>{children}</>;
  return <Screen>
    <AppHeader title={mode === "volunteer" ? "Volunteer Operations" : "Live Dashboard"}
      subtitle="Student Portal remains available at all times." />
    {allowed === null && !error ? <LoadingState label="Checking availability…" /> :
      <ErrorState title={allowed === false ? "Currently disabled" : "Connection unavailable"}
        body={allowed === false ? "The administrator has temporarily disabled this dashboard." : error ?? "Try again."}
        onRetry={() => setRetry((value) => value + 1)} />}
    <AppButton label="Open Student Portal" onPress={() => router.replace("/(student)")} />
    <AppButton label="Choose dashboard" variant="secondary" onPress={() => router.replace("/mode-picker")} />
    <AppButton label="Administrator access" variant="ghost" onPress={() => router.push("/administration")} />
  </Screen>;
}
