# Dashboard availability

Open **Choose dashboard → Administrator access → Dashboard availability**.
The administrator PIN protects the controls. Volunteer Operations and Live
Dashboard each have an independent Enable/Disable button; pressing it saves
immediately. Student Portal is always enabled and has no off switch.

The server stores switches in the existing settings table, so no database
migration, rebuild, or service restart is needed when changing availability.
Existing installations default to enabled until an administrator changes them.
Administration lives outside either operational dashboard and remains reachable
even with both disabled. A disabled screen provides links to Student Portal,
dashboard selection, and administration.

The picker shows unavailable dashboards. Already-open operational screens check
availability every 15 seconds while focused and on returning to the foreground.
The lightweight `/api/dashboard-access` endpoint reads only settings and does
not compute attendance analytics. Responses disable caching. When disabled,
dashboards unmount their camera, data polling, and other screen effects.
The backend enforces disabled access on subsequent operational requests, including
direct API calls and the web scanner/dashboard. Requests already in progress can
finish. Existing authentication requirements still apply when enabled again.

Volunteer summary and Live Dashboard data have separate endpoints and switches.
Disabling Live Dashboard does not block Volunteer Operations. Shared public
configuration, health checks, student APIs, and administrator settings remain
available. A disabled sync returns a top-level 403 without processing any scans;
the mobile client retains its queue for reopening rather than deleting it.

Student verification still requires an active official registration matching the
registration number, university email, roll number and student name. Verification
codes, claim uniqueness, rate limits and session checks are unchanged. Real email
verification and recovery need the existing SMTP configuration; an availability
switch does not configure delivery or provide round-the-clock hosting.

Validation: `app/scripts/test_dashboard_access.py` tests independent switches,
protected changes, rejected invalid settings, persistence, disabled operational
APIs, administrator recovery, student login and eligible signup while both modes
are off, unmatched registration rejection, and reopening. The existing student
account regression suite covers the remaining account restrictions.
