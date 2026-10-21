// Public event information + official announcements feed (Phase 7).
// No auth — both endpoints are unauthenticated public GETs on the
// student API, served only from published records: event info comes
// from the publication snapshot, the feed from published student
// announcements. Drafts, staff-only and archived rows never appear.

import { request } from "./client";

const EVENT_BASE = "/api/student/event";
const FEED_BASE = "/api/student/announcements";

export type DateState = "not_announced" | "expected" | "confirmed";

export interface Rehearsal {
  date: string;
  time: string | null;
  venue: string | null;
}

/** One occasion of the annual cycle (Phase 29): rehearsal or main
    convocation, with a server-computed phase and UTC start instant. */
export interface OccasionInfo {
  key: "rehearsal" | "ceremony";
  label: string;
  date: string | null;
  time: string | null;
  venue: string | null;
  state: "not_announced" | "announced" | "expected" | "confirmed";
  phase: "upcoming" | "live" | "completed" | null;
  days_until: number | null;
  /** ISO-8601 UTC instant — present only when date AND start time are
      published; a date alone never yields a fabricated clock. */
  starts_at: string | null;
}

export interface EventInfo {
  date_state: DateState;
  date_state_label: string;
  expected_date: string | null;
  confirmed_date: string | null;
  ceremony_time: string | null;
  rehearsal: Rehearsal | null;
  venue: string | null;
  instructions: string;
  published_at: string;
  occasions?: OccasionInfo[];
  /** Portal timezone the phases/days_until were computed in. */
  portal_tz?: string;
}

export interface EventPayload {
  convocation: { id: number; name: string; year: string } | null;
  event: EventInfo | null;
}

export interface Announcement {
  id: number;
  title: string;
  body: string;
  /** Audience the row was published for (server: always 'students' here). */
  audience: string;
  is_important: boolean;
  created_at: string;
  updated_at: string;
  published_at: string;
}

export interface FeedPayload {
  convocation: { name: string; year: string } | null;
  total: number;
  announcements: Announcement[];
}

export function fetchEvent(): Promise<EventPayload> {
  return request<EventPayload>(EVENT_BASE);
}

export function fetchAnnouncements(): Promise<FeedPayload> {
  return request<FeedPayload>(FEED_BASE);
}
