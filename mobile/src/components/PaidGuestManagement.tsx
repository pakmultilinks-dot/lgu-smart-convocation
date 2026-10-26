import { useFocusEffect, router } from "expo-router";
import { useCallback, useState } from "react";
import { Text } from "react-native";
import { request, revokeGuestPass, type Guest } from "../api/client";
import { getAdminPin } from "../store/adminAccess";
import { colors, fonts } from "../theme";
import { AppButton, Field, SectionCard, SectionEyebrow } from "../ui";

async function admin<T>(method = "GET", body?: unknown): Promise<T> {
  const pin = await getAdminPin();
  if (!pin) throw new Error("Administrator access required.");
  return request<T>("/api/admin/guests", { method, headers: { "X-Admin-Pin": pin }, body: body === undefined ? undefined : JSON.stringify(body) });
}
export function PaidGuestManagement() {
  const [name, setName] = useState(""); const [phone, setPhone] = useState("");
  const [host, setHost] = useState(""); const [reference, setReference] = useState("");
  const [review, setReview] = useState(false); const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const [guests, setGuests] = useState<Guest[]>([]); const [note, setNote] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<Guest | null>(null);
  const load = useCallback(async () => { try { setGuests((await admin<{ guests: Guest[] }>()).guests); } catch (e) { setError(e instanceof Error ? e.message : "Guest directory unavailable."); } }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));
  const issue = async () => {
    if (busy || !verified) return;
    setBusy(true); setError(null);
    try {
      const result = await admin<{ gid: number }>("POST", { name: name.trim(), phone: phone.trim(), host_roll_no: host.trim(), payment_reference: reference.trim(), payment_verified: true });
      setNote("Paid guest pass issued. Payment verification recorded.");
      setName(""); setPhone(""); setHost(""); setReference(""); setVerified(false); setReview(false);
      await load(); router.push({ pathname: "/guest-pass", params: { gid: String(result.gid) } });
    } catch (e) { setError(e instanceof Error ? e.message : "Could not issue pass."); }
    finally { setBusy(false); }
  };
  const revoke = async () => {
    if (!revoking || busy) return;
    setBusy(true); setError(null);
    try { await revokeGuestPass(revoking.id); setRevoking(null); setNote("Guest pass revoked."); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not revoke pass."); }
    finally { setBusy(false); }
  };
  const edit = (setter: (text: string) => void) => (text: string) => { setter(text); setReview(false); setVerified(false); };
  return <>
    <SectionCard>
      <SectionEyebrow>Issue a paid guest pass</SectionEyebrow>
      <Text style={body}>Verify payment in the institution payment records first. This form records your verification; it does not collect or settle payment. Student and volunteer accounts cannot issue passes.</Text>
      <Field label="Guest name" value={name} onChangeText={edit(setName)} maxLength={120} />
      <Field label="Guest phone" value={phone} onChangeText={edit(setPhone)} keyboardType="phone-pad" maxLength={32} />
      <Field label="Host roll number" value={host} onChangeText={edit(setHost)} maxLength={32} hint="Existing operational roster student. Official student records remain separate." />
      <Field label="Payment reference" value={reference} onChangeText={edit(setReference)} maxLength={80} hint="Use the receipt or transaction reference verified by the administration." />
      <AppButton label={verified ? "Payment verified by administrator" : "I verified this payment"} variant={verified ? "primary" : "secondary"} onPress={() => { setVerified(!verified); setReview(false); }} disabled={busy} />
      <AppButton label="Review paid guest pass" disabled={busy || !verified || !name.trim() || !phone.trim() || !host.trim() || !reference.trim()} onPress={() => setReview(true)} />
      {review ? <><Text style={body}>Issue one paid pass for {name.trim()}, hosted by {host.trim()}, against payment {reference.trim()}? The current limit is one guest pass per host.</Text><AppButton label="Issue paid guest pass" loading={busy} onPress={() => void issue()} /><AppButton label="Cancel issuance" variant="ghost" disabled={busy} onPress={() => setReview(false)} /></> : null}
      {error ? <Text accessibilityRole="alert" style={{ ...body, color: colors.invalid }}>{error}</Text> : null}
      {note ? <Text accessibilityLiveRegion="polite" style={body}>{note}</Text> : null}
    </SectionCard>
    <SectionCard><SectionEyebrow>Existing guest passes</SectionEyebrow><Text style={body}>Existing passes retain their recorded status. Historical passes are not automatically labelled payment-verified.</Text>
      {guests.length ? guests.map(g => <SectionCard key={g.id}><Text style={body}>{g.name} · Host {g.host_roll_no} · {g.status === "revoked" ? "Revoked" : g.used ? "Used" : "Ready"}</Text><AppButton label={`Open pass for ${g.name}`} variant="secondary" onPress={() => router.push({ pathname: "/guest-pass", params: { gid: String(g.id) } })} />{!g.used && g.status !== "revoked" ? <AppButton label={`Revoke pass for ${g.name}`} variant="ghost" onPress={() => setRevoking(g)} /> : null}</SectionCard>) : <Text style={body}>No guest passes issued.</Text>}
      {revoking ? <><Text style={body}>Revoke {revoking.name} unused pass? It will be refused at the gate.</Text><AppButton label="Confirm guest revocation" variant="danger" loading={busy} onPress={() => void revoke()} /><AppButton label="Cancel revocation" variant="ghost" onPress={() => setRevoking(null)} /></> : null}
    </SectionCard>
  </>;
}
const body = { fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 19, color: colors.muted };
