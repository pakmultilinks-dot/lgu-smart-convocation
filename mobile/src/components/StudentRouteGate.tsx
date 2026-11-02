import { Redirect, router, useSegments, type Href } from "expo-router";
import { useEffect, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { me } from "../api/studentApi";
import { clearToken, getToken } from "../store/studentSession";
import { rememberPendingReturn } from "../store/pendingReturn";
import { getAppMode, type AppMode } from "../store/appMode";
import { AppButton, ErrorState, LoadingState, Screen } from "../ui";

export const STUDENT_PUBLIC_ROUTES = new Set(["index", "(student)", "welcome", "login", "verify", "code", "recovery"]);

/**
 * Route-collision guard: `(student)` and `(volunteer)` both define `home`
 * and `more`, so a hard reload or history pop on the bare `/home` or `/more`
 * paths resolves to the STUDENT screen regardless of the stored mode. This
 * gate reads the stored mode and sends a volunteer/liveboard device back to
 * its own Home instead of rendering student screens. Public student entry
 * routes (welcome, auth screens) stay reachable, and an unset mode never
 * redirects — the mode picker owns first-run routing.
 */
export function StudentModeGate({ children }: { children: ReactNode }) {
  const segments = useSegments() as readonly string[];
  const current = segments[segments.length - 1] ?? "index";
  const [mode, setMode] = useState<AppMode | null | undefined>(undefined);
  useEffect(() => {
    let active = true;
    void getAppMode().then((value) => { if (active) setMode(value); });
    return () => { active = false; };
  }, []);
  if (STUDENT_PUBLIC_ROUTES.has(current)) return <>{children}</>;
  if (mode === "volunteer" || mode === "liveboard") {
    // A volunteer reloading `/more` should get the volunteer More screen,
    // not Home; every other student route falls back to volunteer Home.
    const sameName = mode === "volunteer" && (current === "home" || current === "more");
    return <Redirect href={(sameName ? `/(volunteer)/${current}` : "/(volunteer)/home") as Href} />;
  }
  return <>{children}</>;
}

/** Authentication screens never expose the account's tab navigation. */
export function StudentRouteGate({ children }: { children: ReactNode }) {
  const segments = useSegments() as readonly string[];
  const isPublic = STUDENT_PUBLIC_ROUTES.has(segments[segments.length - 1] ?? "index");
  return isPublic ? <>{children}</> : <AuthenticatedStudentGate>{children}</AuthenticatedStudentGate>;
}

function AuthenticatedStudentGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<"checking" | "ready" | "missing" | "error">("checking");
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const token = await getToken();
        if (!token) { rememberPendingReturn("/(student)/more"); if (active) setStatus("missing"); return; }
        await me(token);
        if (active) setStatus("ready");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          await clearToken();
          rememberPendingReturn("/(student)/more");
          if (active) setStatus("missing");
        } else if (active) {
          setError(e instanceof Error ? e.message : "Your account could not be loaded.");
          setStatus("error");
        }
      }
    })();
    return () => { active = false; };
  }, [retry]);
  if (status === "ready") return <>{children}</>;
  if (status === "missing") return <Redirect href="/(student)/welcome" />;
  return <Screen>
    {status === "checking" ? <LoadingState label="Opening your account..." /> :
      <><ErrorState title="Unable to reach your account" body={error} onRetry={() => { setStatus("checking"); setRetry((value) => value + 1); }} />
        <AppButton label="Connection settings" variant="secondary" onPress={() => router.push("/connect-server")} />
        <AppButton label="Back to welcome" variant="ghost" onPress={() => { rememberPendingReturn("/(student)/more"); router.replace("/(student)/welcome"); }} /></>}
  </Screen>;
}
