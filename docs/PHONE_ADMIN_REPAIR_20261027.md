# Administrator workflow correction — 27 October 2026

## Failure and corrected design

The earlier dashboard linked Student records to /exam/ and Operational roster to /admin through Linking.openURL. This opened the system browser, lost the native administrator context and exposed separate web authentication and legacy navigation. It did not meet the requested in-app administration design.

Both tiles now render native record management. The same verified administrator PIN authenticates bounded JSON APIs; credentials are never placed in URLs. Admin can search, page, add, review and correct official students or gate-roster students without opening another app. Changes use existing audit tables and uniqueness constraints, with no schema migration. Official registration numbers and operational roll identities cannot be renamed through this editor. The records remain separate; no silent identity bridge or free guest entitlement is introduced. Official status transitions and spreadsheet batch import remain available in the existing separately authenticated web portal, but no mobile tile launches that portal.

Operational message administration also has a standalone protected native route so disabling volunteer scanning does not disable administrator messaging navigation. Paid issuance and publication remain reviewed, explicit actions inside the app.

## All 44 supplied screenshots reviewed

- 1, 2, 5, 6: signup/login/recovery. Empty signup now validates before requesting a code; visible errors use readable field labels. Hidden student tabs previously still suppressed the bottom safe inset. Auth routes now retain it. Email delivery still needs actual server configuration; no code delivery is invented.
- 3, 4: provisional published schedule is correctly labelled as test content. Dates are not silently confirmed.
- 7: volunteer-disabled/live-enabled state is an administrator choice, preserved.
- 8: no published announcements is a valid state; operational message logging is not student publication.
- 9, 10, 11, 12, 17, 19, 44: native hub led into browser-only record management and raw legacy failures. Native record APIs/editors replace those outgoing links. No web login or GET to a POST-only action is required by the repaired mobile flow.
- 13, 14, 15, 16: legacy browser dashboard is a separate surface; mobile administration no longer sends the user there.
- 18, 20, 23: paid pass review requires all guest/host/reference fields plus administrator payment verification. Disabled review with an empty receipt is correct. No pass was issued during audit/testing on the hosted server.
- 21, 22, 24, 27: publication editor is native and requires explicit saved draft/review/publish. No published content is changed by the repair.
- 25, 26: initial Connecting followed by Synced is normal; phone heading fix is visible. Zero counts remain genuine values.
- 28, 30: administrator availability controls retain current settings.
- 29, 34: operational message log explicitly reports save-only behavior; native admin route stays outside volunteer gating.
- 31, 39: scanner authentication protects the directory, then the empty directory displays correctly. Volunteers cannot issue guests.
- 32, 33, 35: camera permission and assigned Main Gate are valid. Gate sheet now pads its action above the system navigation inset.
- 36, 40: selected gate and Entry/Exit state are valid; zero scans are not failures.
- 37, 38, 41, 42, 43: screenshot toolbar, keyboard and volume overlay belong to Android; Settings and new welcome dashboard are visible. No overlays are recreated or manipulated by app code.

## Validation

Disposable synthetic API test covers anonymous/student/scanner denial, admin reads/writes while volunteer scanning is paused, input validation, duplicate identifiers, missing records, immutable identities, preservation of leading zeros, QR assignment and atomic audit trails. Existing paid guest suite continues to pass. Real Expo browser acceptance includes both native tiles and verifies no browser window is opened. Android device validation remains necessary for final keyboard/system-bar behavior.
