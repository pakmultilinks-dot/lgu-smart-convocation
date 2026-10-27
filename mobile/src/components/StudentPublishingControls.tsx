import { useCallback, useState } from "react";
import { useFocusEffect } from "expo-router";
import { Text } from "react-native";
import { request } from "../api/client";
import { getAdminPin } from "../store/adminAccess";
import { AppButton, Field, SectionCard, SectionEyebrow } from "../ui";
import { colors, fonts } from "../theme";

type Draft = Record<string, string | null>;
type EventState = { draft: Draft; published: { name: string; published_at: string } | null; has_changes: boolean };
async function adminRequest<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const pin = await getAdminPin();
  if (!pin) throw new Error("Unlock administrator access first.");
  return request<T>(path, { method, headers: { "X-Admin-Pin": pin }, body: body === undefined ? undefined : JSON.stringify(body) });
}
const fields = [
  ["name", "Student event name", "LGU Convocation 2026"],
  ["expected_date", "Provisional ceremony date", "YYYY-MM-DD"],
  ["confirmed_date", "Confirmed ceremony date", "YYYY-MM-DD, only when official"],
  ["ceremony_time", "Ceremony time", "HH:MM (24-hour Pakistan time)"],
  ["rehearsal_date", "Rehearsal date", "YYYY-MM-DD"],
  ["rehearsal_time", "Rehearsal time", "HH:MM"],
  ["venue", "Student event venue", "Venue"],
  ["instructions", "Student instructions", "Arrival and entry instructions"],
] as const;
const bodyStyle = { fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, color: colors.muted };

export function StudentPublishingControls() {
  const [event, setEvent] = useState<EventState | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [open, setOpen] = useState(false);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [confirm, setConfirm] = useState<"event" | "update" | null>(null);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const next = await adminRequest<EventState>("/api/admin/student-event");
      setEvent(next); setDraft(next.draft); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Cannot load student event."); }
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));
  const edited = JSON.stringify(draft) !== JSON.stringify(event?.draft ?? {});
  const act = async (action: "save" | "event" | "update") => {
    if (busy) return;
    setBusy(true); setError(null); setNote(null);
    try {
      if (action === "update") {
        const result = await adminRequest<{ note: string }>("/api/admin/student-announcements", "POST", { title: title.trim(), body: message.trim() });
        setNote(result.note); setTitle(""); setMessage("");
      } else {
        const next = await adminRequest<EventState>(`/api/admin/student-event${action === "event" ? "/publish" : ""}`, action === "event" ? "POST" : "PUT", action === "save" ? draft : undefined);
        setEvent(next); setDraft(next.draft);
        setNote(action === "save" ? "Draft saved. Students still see the last published event." : "Event published. Eligible students can now issue their entry QR.");
      }
      setConfirm(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save publication."); }
    finally { setBusy(false); }
  };
  return <SectionCard>
    <SectionEyebrow>Student event & updates</SectionEyebrow>
    <Text style={bodyStyle}>{event?.published ? `Published: ${event.published.name}${event.has_changes ? " · Unpublished draft changes" : ""}` : "Student event is not published. Entry passes remain unavailable until publication."}</Text>
    <Text style={bodyStyle}>Operational settings do not publish the student schedule. Save a draft, review it, then publish explicitly.</Text>
    <AppButton label={open ? "Close event editor" : "Edit student event"} variant="secondary" onPress={() => setOpen(!open)} />
    {open && event ? <>
      {fields.map(([key, label, placeholder]) => <Field key={key} label={label} placeholder={placeholder} value={draft[key] ?? ""} onChangeText={(value) => { setDraft({ ...draft, [key]: value }); setConfirm(null); }} multiline={key === "instructions"} autoCapitalize={key.includes("date") || key.includes("time") ? "none" : "sentences"} hint={key.includes("date") ? "Use year-month-day, for example 2026-12-12. Leave blank when not announced." : key.includes("time") ? "Pakistan time, 24-hour format; for example 09:00." : undefined} />)}
      <AppButton label="Save student event draft" disabled={!edited || busy} loading={busy} onPress={() => void act("save")} />
      <AppButton label="Review event publication" variant="secondary" disabled={edited || busy} onPress={() => setConfirm("event")} />
    </> : null}
    <AppButton label={updateOpen ? "Close student update" : "Write student update"} variant="secondary" onPress={() => setUpdateOpen(!updateOpen)} />
    {updateOpen ? <>
      <Text style={bodyStyle}>Published messages appear in the student Updates tab. This does not send SMS, email or push notifications.</Text>
      <Field label="Student update title" value={title} onChangeText={setTitle} maxLength={140} />
      <Field label="Student update message" value={message} onChangeText={setMessage} multiline maxLength={4000} />
      <AppButton label="Review student update" disabled={!title.trim() || !message.trim() || busy} onPress={() => setConfirm("update")} />
    </> : null}
    {confirm ? <>
      <Text style={bodyStyle}>{confirm === "event" ? `Publish saved event “${event?.draft.name}” to students?` : `Publish “${title.trim()}” in student Updates?`}</Text>
      <AppButton label={confirm === "event" ? "Publish saved event" : "Publish student update"} loading={busy} onPress={() => void act(confirm)} />
      <AppButton label="Cancel publication" variant="ghost" disabled={busy} onPress={() => setConfirm(null)} />
    </> : null}
    {error ? <><Text style={{ ...bodyStyle, color: colors.invalid }}>{error}</Text><AppButton label="Retry student event" variant="secondary" onPress={() => void load()} /></> : null}
    {note ? <Text accessibilityLiveRegion="polite" style={bodyStyle}>{note}</Text> : null}
  </SectionCard>;
}
