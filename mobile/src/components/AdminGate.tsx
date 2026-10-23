import { router } from "expo-router";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Text } from "react-native";
import { verifyAdminPin, ApiError } from "../api/client";
import { getAdminPin, setAdminPin, WRONG_PIN } from "../store/adminAccess";
import {
  initialLockState,
  isLocked,
  lockSecondsRemaining,
  registerFailure,
  resetOnSuccess,
  type AdminLockState,
} from "../store/adminLockout";
import { colors } from "../theme";
import { text } from "../theme/typography";
import {
  AppButton,
  AppHeader,
  Field,
  LoadingState,
  Screen,
  SectionCard,
} from "../ui";

/**
 * Administrator gate (Phase 35G). Wraps the Broadcast and Admin routes:
 * unlocked devices render the screen directly; locked devices get an
 * explicit PIN check against the backend before anything admin-shaped is
 * shown. The PIN lives only on this device (AsyncStorage) and is attached
 * to admin POSTs as the X-Admin-Pin header.
 */
export function AdminGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [unlocked, setUnlocked] = useState(false);
  const [pin, setPin] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Wrong-PIN lockout (Phase 35H item 23): pure clock-injected state from
  // ../store/adminLockout — 3 consecutive wrong PINs lock for 30 seconds.
  const [lock, setLock] = useState<AdminLockState>(initialLockState);
  const [now, setNow] = useState(() => Date.now());
  const locked = isLocked(lock, now);

  // QA fix cycle 4 (Finding 6): a locally stored PIN is NEVER treated as
  // authorization on its own. On mount, if a PIN is saved on this device,
  // it is re-verified against the SERVER (/api/admin/verify) before the
  // gate opens. Only a server `ok` grants access — a stale/rejected PIN,
  // a changed server PIN, or an unreachable server all keep the gate
  // closed and fall back to the explicit PIN screen (safe default).
  useEffect(() => {
    let alive = true;
    void (async () => {
      const saved = await getAdminPin();
      if (!alive) return;
      if (saved) {
        try {
          const verified = await verifyAdminPin(saved);
          if (alive && verified.ok) setUnlocked(true);
        } catch {
          // Server unreachable / rate-limited / wrong — stay locked.
        }
      }
      if (alive) setReady(true);
    })();
    return () => {
      alive = false;
    };
  }, []);

  // Lock countdown clock (Phase 35H item 23): ticks every second while
  // locked so the remaining-seconds display stays live; interval is
  // cleared automatically when the lock expires or the gate unmounts.
  useEffect(() => {
    if (!locked) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [locked]);

  const unlock = useCallback(async () => {
    const candidate = pin.trim();
    if (!candidate) {
      setError("Enter the administrator PIN.");
      return;
    }
    setChecking(true);
    setError(null);
    try {
      const verified = await verifyAdminPin(candidate);
      if (!verified.ok) {
        // Defensive: a 200 with ok:false is still a wrong PIN.
        throw new ApiError(WRONG_PIN, 401);
      }
      await setAdminPin(candidate);
      setPin("");
      setLock(resetOnSuccess());
      setUnlocked(true);
    } catch (e) {
      // Wrong PIN (backend 401 / ok:false) counts toward the lockout;
      // network failures never reached the verifier and do NOT count.
      if (e instanceof ApiError && (e.status === 401 || e.status === 400)) {
        setLock((prev) => registerFailure(prev, Date.now()));
        setNow(Date.now());
        setError(WRONG_PIN);
      } else {
        setError(
          e instanceof ApiError
            ? e.message
            : "Could not verify the PIN. Check the connection and try again.",
        );
      }
    } finally {
      setChecking(false);
    }
  }, [pin]);

  if (!ready) {
    return (
      <Screen>
        <LoadingState label="Checking administrator access..." />
      </Screen>
    );
  }
  if (unlocked) {
    return <>{children}</>;
  }
  return (
    <Screen>
      <AppHeader
        title="Administrator access"
        subtitle="Enter the administrator PIN to continue."
      />
      <SectionCard>
        <Field
          label="Administrator PIN"
          placeholder="Enter the PIN"
          value={pin}
          onChangeText={(t) => {
            setPin(t);
            setError(null);
          }}
          secureTextEntry
          keyboardType="numeric"
          autoComplete="off"
          autoCapitalize="none"
          error={error}
          returnKeyType="done"
          onSubmitEditing={() => void unlock()}
        />
        {locked ? (
          <Text style={styles.lockNote}>
            Too many attempts. Try again in {lockSecondsRemaining(lock, now)}s.
          </Text>
        ) : null}
        <AppButton
          label="Unlock"
          icon="lock-open-outline"
          loading={checking}
          disabled={locked}
          onPress={() => void unlock()}
        />
      </SectionCard>
      <AppButton
        label="Connect to server"
        variant="secondary"
        icon="cloud-outline"
        onPress={() => router.push("/connect-server")}
      />
      <Text style={[text.body, styles.gateNote]}>
        Administrator tools stay locked on this device until access is granted.
      </Text>
    </Screen>
  );
}

const styles = {
  gateNote: {
    color: colors.muted,
    lineHeight: 21,
  },
  lockNote: {
    ...text.helper,
    color: colors.invalid,
    lineHeight: 18,
  },
};
