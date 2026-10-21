import { Redirect, type Href } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../src/api/client";
import * as studentApi from "../../src/api/studentApi";
import { clearToken, getToken } from "../../src/store/studentSession";
import { ErrorState, LoadingState, Screen } from "../../src/ui";

type Step =
  | { kind: "checking" }
  | { kind: "welcome" }
  | { kind: "next"; href: Href }
  | { kind: "error"; message: string };

/**
 * Student entry gate (Phase 5). A session is only trusted after /me
 * confirms it: network failures land on a retryable error state — NEVER
 * on the welcome/"unregistered" path.
 */
export default function StudentGate() {
  const [step, setStep] = useState<Step>({ kind: "checking" });

  const load = useCallback(async () => {
    const token = await getToken();
    setStep({ kind: "checking" });
    if (!token) {
      setStep({ kind: "welcome" });
      return;
    }
    try {
      const me = await studentApi.me(token);
      setStep({ kind: "next", href: studentApi.homePath(me) });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await clearToken();
        setStep({ kind: "welcome" });
      } else {
        setStep({
          kind: "error",
          message:
            e instanceof Error
              ? e.message
              : "The student portal could not be loaded. Check the connection.",
        });
      }
    }
  }, []);

  useEffect(() => {
    void (async () => {
      await load();
    })();
  }, [load]);

  if (step.kind === "checking") {
    return (
      <Screen scroll={false}>
        <LoadingState label="Opening your student account..." />
      </Screen>
    );
  }
  if (step.kind === "error") {
    return (
      <Screen scroll={false}>
        <ErrorState
          title="Connection problem"
          body={step.message}
          onRetry={() => void load()}
        />
      </Screen>
    );
  }
  if (step.kind === "welcome") return <Redirect href="/(student)/welcome" />;
  return <Redirect href={step.href} />;
}
