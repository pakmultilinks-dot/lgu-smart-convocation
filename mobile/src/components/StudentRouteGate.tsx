import { Redirect, router, useSegments } from "expo-router";
import { useEffect, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { me } from "../api/studentApi";
import { clearToken, getToken } from "../store/studentSession";
import { AppButton, ErrorState, LoadingState, Screen } from "../ui";

export const STUDENT_PUBLIC_ROUTES = new Set(["index", "(student)", "welcome", "login", "verify", "code", "recovery"]);

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
        if (!token) { if (active) setStatus("missing"); return; }
        await me(token);
        if (active) setStatus("ready");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          await clearToken();
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
        <AppButton label="Back to welcome" variant="ghost" onPress={() => router.replace("/(student)/welcome")} /></>}
  </Screen>;
}
