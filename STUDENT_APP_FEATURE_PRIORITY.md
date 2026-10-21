# LGU Student App — Feature Prioritization (Phase 8)

Grounded in the actual routes in `app/web/student_api.py`, the screens in
`mobile/app/(student)/`, and the API client in `mobile/src/api/studentApi.ts`.
Each feature is marked **Implemented**, **Incomplete**, or **Not implemented**.

Legend: a feature is *Implemented* when the server route and the app UI both
exist and the flow was verified this phase; *Incomplete* when part of the flow
exists but a step is missing or manual; *Not implemented* when there is no
server route and no screen.

---

## Tier 0 — Core identity (all Implemented)

| Feature | State | Notes |
|---|---|---|
| Email verification (signup) | **Implemented** | `/verify` + `/resend` + `/complete`; fake-email mode tested. |
| Login | **Implemented** | `/login`; wrong password 401 + throttling verified. |
| Session (`/me`) | **Implemented** | Bearer token, SecureStore on native; `me()` on every focus. |
| Logout | **Implemented** | Server-side revocation + token clear. Fixed this phase: profile sign-out previously left the token behind. |
| Password recovery | **Implemented** | `/recovery/request` + `/recovery/complete`; fails closed without email config. |
| Profile: phone | **Implemented** | `/profile` POST; half-typed value preserved during silent refresh. |
| Profile: photo | **Implemented** | `/profile/photo` GET+POST, 2 MB cap, auth-header fetch. |

## Tier 1 — Event information (all Implemented)

| Feature | State | Notes |
|---|---|---|
| Event details | **Implemented** | `/event` from the published snapshot only; live-refreshes. |
| Date state (expected vs confirmed) | **Implemented** | Distinct labels; provisional never reads as confirmed. |
| Rehearsal details | **Implemented** | Date/time/venue in the snapshot. |
| Announcements feed | **Implemented** | Published + students-audience only; live-refreshes. |

## Tier 2 — Honours (all Implemented)

| Feature | State | Notes |
|---|---|---|
| Medalist board | **Implemented** | `/medalists`; filter by department/category; live-refreshes. |
| Medalist photo | **Implemented** | `/medalists/photo/<id>`; 404-safe for drafts. |

## Tier 3 — Registration status (Implemented, read-only)

| Feature | State | Notes |
|---|---|---|
| View my registration | **Implemented** | `/me` returns the claimed registration + status. |
| See corrections applied | **Implemented** | Admin corrections reach the open session immediately (verified). |
| See cancel/revoke status | **Implemented** | Served honestly to the session; revoked cannot be reinstated. |
| Registration readiness checklist | **Incomplete** | `/me.completion` returns the steps (`verified`, `claimed`, `photo`) but there is no dedicated checklist UI — it is only implied on the home screen. |

## Tier 4 — Not implemented (no server route, no screen)

| Feature | State | Notes |
|---|---|---|
| Registration help / correction *requests* | **Not implemented** | Students can *see* corrections but cannot *request* one; no inbound request route. |
| Personalized reminders | **Not implemented** | No per-student reminder scheduling or push; no server route. |
| Digital invitation / QR pass | **Not implemented** | QR identities exist for volunteers/guests only; no student invitation pass route. |
| Convocation history | **Not implemented** | `/event` serves the active convocation only; no archive listing. |
| Approved post-event content | **Not implemented** | No post-event/media section route. |

---

## Recommended order for the next phase

1. **Registration readiness checklist UI** — the data (`completion`) already
   ships in `/me`; this is the cheapest Tier-3 win and directly reduces
   "incomplete profile" issues on the admin dashboard.
2. **Registration correction requests** — closes the loop between the student
   app and the admin correction workflow that was verified this phase.
3. **Digital invitation / QR pass** — reuses the existing signed-payload
   scanner infrastructure; high student value.
4. **Personalized reminders** — needs a scheduling story; keep server-driven
   (no push service) unless a paid/new dependency is approved.
5. **Convocation history + approved post-event content** — lowest urgency;
   both need new "archived convocation" concepts on the server.
