import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { AppState } from "react-native";
import { fetchDashboardAccess, type DashboardAccess } from "../api/client";

/** One lifecycle policy for dashboard access: foreground, focused, one request. */
export function useDashboardAvailability() {
  const [access, setAccess] = useState<DashboardAccess | null>(null);
  const [state, setState] = useState<"checking" | "online" | "offline">("checking");
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  useFocusEffect(useCallback(() => {
    let active = true;
    let checking = false;
    if (revision > 0) { setState("checking"); setError(null); }
    const check = async () => {
      if (checking || AppState.currentState === "background" || AppState.currentState === "inactive") return;
      checking = true;
      try {
        const next = await fetchDashboardAccess();
        if (active) { setAccess(next); setState("online"); setError(null); }
      } catch (e) {
        if (active) {
          setState("offline");
          setError(e instanceof Error ? e.message : "Cannot reach the university server.");
        }
      } finally { checking = false; }
    };
    void check();
    const timer = setInterval(() => void check(), 15000);
    const subscription = AppState.addEventListener("change", (next) => {
      if (next === "active") void check();
    });
    return () => { active = false; clearInterval(timer); subscription.remove(); };
  }, [revision]));
  return { access, state, error, refresh };
}
