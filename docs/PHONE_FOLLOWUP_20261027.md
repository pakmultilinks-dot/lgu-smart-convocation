# Phone follow-up — 27 October 2026

All 13 supplied screenshots reviewed.

- 1, 4, 12: availability request pending/failing. Current health, availability and dashboard endpoints return HTTP 200. This does not prove historical failures were device Wi-Fi faults. Keep failure guidance neutral and retain automatic foreground/poll recovery.
- 3, 5: connection setup used a five-second health probe, shorter than normal API requests. Raised to twenty seconds so a slow hosted response has the same budget. Failed requests still terminate. No automatic server changes or credential retries.
- 2, 10: confirmation followed by server-verified administrator PIN is the intended protected display exit. Retained.
- 6: volunteer disabled and liveboard enabled match administrator settings. Retained; do not enable tools as a connectivity fix.
- 7: marketing welcome shown is superseded by the already implemented dashboard. An installed APK must be updated to receive it.
- 8: email recovery requires configured mail delivery. Do not claim demo email is delivered.
- 9: activation remains constrained to the official registration list. Existing scrolling/safe-area repair is in the latest dashboard build.
- 11: Connecting badge squeezed the live attendance title mid-word. Phone liveboard headers now stack the badge below the full-width heading; wide displays keep side-by-side presentation.
- 13: zero gate counts are valid for the synthetic fixture. No scans invented.

Changes are source fixes pending a new native APK; the previous released binary does not contain this follow-up. Hosted availability/settings and existing records were not modified.
