import { router } from "expo-router";
import { type ReactNode } from "react";
import { useDashboardAvailability } from "../hooks/useDashboardAvailability";
import { AppButton, AppHeader, ErrorState, LoadingState, Screen } from "../ui";

/** Unmount disabled dashboards, including their camera and live polling. */
export function DashboardAccessGate({ mode, children }: {
  mode: "volunteer" | "liveboard"; children: ReactNode;
}) {
  const { access, state, error, refresh } = useDashboardAvailability();
  const allowed = access?.[mode] ?? null;

  if (allowed === true) return <>{children}</>;
  return <Screen>
    <AppHeader title={mode === "volunteer" ? "Volunteer Operations" : "Live Dashboard"}
      subtitle="Student Portal remains available at all times." />
    {allowed === null && state === "checking" ? <LoadingState label="Checking availability…" /> :
      <ErrorState title={allowed === false ? "Currently disabled" : "Connection unavailable"}
        body={allowed === false ? "The administrator has temporarily disabled this dashboard." : error ?? "Try again."}
        onRetry={refresh} />}
    {state === "offline" ? <AppButton label="Connect to server" variant="secondary"
      onPress={() => router.push("/connect-server")} /> : null}
    <AppButton label="Open Student Portal" onPress={() => router.replace("/(student)")} />
    <AppButton label="Choose dashboard" variant="secondary" onPress={() => router.replace("/mode-picker")} />
    <AppButton label="Administrator access" variant="ghost" onPress={() => router.push("/administration")} />
  </Screen>;
}
