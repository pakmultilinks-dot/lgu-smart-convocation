import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Text, View } from "react-native";
import { request } from "../api/client";
import { getAdminPin } from "../store/adminAccess";
import { colors, fonts } from "../theme";
import { AppButton, Field, SectionCard, SectionEyebrow } from "../ui";

type Row = Record<string, string | number> & { id: number };
const officialFields = [["registration_number", "Registration number"], ["university_email", "University email"], ["roll_number", "Roll number"], ["student_name", "Student name"], ["department", "Department"]];
const rosterFields = [["roll_no", "Roll number"], ["name", "Student name"], ["gender", "Gender"], ["program", "Program"]];
export function StudentRecordManagement({ kind }: { kind: "registrations" | "roster" }) {
  const official = kind === "registrations";
  const fields = official ? officialFields : rosterFields;
  const [rows, setRows] = useState<Row[]>([]);
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [form, setForm] = useState<Record<string, string> | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const api = useCallback(async <T,>(suffix: string, method = "GET", body?: unknown): Promise<T> => {
    const pin = await getAdminPin();
    if (!pin) throw new Error("Unlock administrator access again.");
    return request<T>("/api/admin/records/" + kind + suffix, { method, headers: { "X-Admin-Pin": pin }, body: body === undefined ? undefined : JSON.stringify(body) });
  }, [kind]);
  const load = useCallback(async (search: string, start: number) => {
    setBusy(true); setError(null);
    try { const result = await api<{ records: Row[]; has_more: boolean }>("?q=" + encodeURIComponent(search.trim()) + "&offset=" + start); setRows(result.records); setMore(result.has_more); setOffset(start); }
    catch (e) { setError(e instanceof Error ? e.message : "Records could not be loaded."); }
    finally { setBusy(false); }
  }, [api]);
  useFocusEffect(useCallback(() => { void load("", 0); }, [load]));
  const edit = (row?: Row) => {
    setSelected(row?.id ?? null); setReview(false); setError(null); setNote(null);
    setForm(Object.fromEntries(fields.map(([key]) => [key, String(row?.[key] ?? (key === "gender" ? "Male" : ""))])));
  };
  const save = async () => {
    if (!form || busy) return;
    setBusy(true); setError(null);
    try { await api(selected === null ? "" : "/" + selected, selected === null ? "POST" : "PUT", form); setForm(null); setReview(false); await load(query, 0); setNote("Student record saved. The change was recorded in the audit history."); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not save the record."); }
    finally { setBusy(false); }
  };
  const bodyStyle = { fontFamily: fonts.displayMedium, fontSize: 15, color: colors.ink };
  return <>
    <Text style={bodyStyle}>{official ? "Manage the official convocation list here. Adding a record allows the student to activate an account after email verification." : "Manage the gate roster and guest hosts here. These records are separate from the official convocation list."}</Text>
    {error ? <Text accessibilityRole="alert" style={{ ...bodyStyle, color: colors.invalid }}>{error}</Text> : null}
    {note ? <Text accessibilityRole="alert" style={bodyStyle}>{note}</Text> : null}
    {form ? <SectionCard>
      <SectionEyebrow>{review ? "Review student record" : selected === null ? "Add student" : "Edit student"}</SectionEyebrow>
      {fields.map(([key, label]) => review ? <Text key={key} style={bodyStyle}>{label}: {form[key] || "—"}</Text> : key === "gender" ? <View key={key} style={{ gap: 8 }}><Text style={bodyStyle}>Gender</Text>{["Male", "Female"].map(value => <AppButton key={value} label={value} variant={form.gender === value ? "primary" : "secondary"} onPress={() => setForm({ ...form, gender: value })} />)}</View> : <Field key={key} label={label} value={form[key]} editable={selected === null || key !== (official ? "registration_number" : "roll_no")} maxLength={key.includes("email") ? 254 : key.includes("roll") ? 32 : key === "registration_number" ? 64 : 120} autoCapitalize={key.includes("email") ? "none" : "sentences"} keyboardType={key.includes("email") ? "email-address" : "default"} onChangeText={value => setForm({ ...form, [key]: value })} />)}
      <AppButton label={review ? "Confirm and save student" : "Review student record"} disabled={busy || fields.some(([key]) => key !== "department" && !form[key]?.trim())} loading={busy} onPress={() => review ? void save() : setReview(true)} />
      {review ? <AppButton label="Back to editing" variant="secondary" disabled={busy} onPress={() => setReview(false)} /> : null}
      <AppButton label="Cancel editing" variant="ghost" disabled={busy} onPress={() => setForm(null)} />
    </SectionCard> : <AppButton label="Add student" onPress={() => edit()} disabled={busy} />}
    <SectionCard>
      <Field label="Search students" value={query} onChangeText={setQuery} placeholder="Name or roll number" onSubmitEditing={() => void load(query, 0)} />
      <AppButton label="Search" variant="secondary" onPress={() => void load(query, 0)} disabled={busy} loading={busy} />
      {!busy && !rows.length ? <Text style={bodyStyle}>No matching students.</Text> : null}
      {rows.map(row => <View key={row.id} style={{ gap: 6, paddingVertical: 12 }}><Text style={bodyStyle}>{String(row.student_name ?? row.name)}</Text><Text style={bodyStyle}>{String(row.registration_number ?? row.roll_no)}{official ? " · " + row.status : ""}</Text><AppButton label={"Edit " + String(row.student_name ?? row.name)} variant="secondary" disabled={busy} onPress={() => edit(row)} /></View>)}
      {offset > 0 ? <AppButton label="Previous page" variant="secondary" disabled={busy} onPress={() => void load(query, Math.max(0, offset - 50))} /> : null}
      {more ? <AppButton label="Next page" variant="secondary" disabled={busy} onPress={() => void load(query, offset + 50)} /> : null}
    </SectionCard>
  </>;
}
