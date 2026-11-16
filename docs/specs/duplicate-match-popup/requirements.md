# Saved Expense Match Popup — Requirements

Status: In review
Owner: Finance app owner
Last updated: 2026-11-02

## 1. Summary

During screenshot review, the user needs to inspect the saved expense behind a
possible duplicate warning. A popup will show the saved expense's useful details
and source screenshot, helping the user decide whether the new row is truly the
same purchase.

## 2. Background and problem

The import review can show a warning such as `Looks like “LAVANDERIA 60 MINUTOS”
already in the system`. The user currently cannot conveniently inspect which
saved expense caused that warning. The app also has a separate exact-match
message, `Same purchase already in the system`, whose rule is stronger than the
possible-match rule. The popup must show the specific saved record and clarify
that distinction.

## 3. Goals

- G1: Let the user inspect the saved expense that caused a possible-match warning.
- G2: Show its useful expense details and a way to inspect its source screenshot.
- G3: Explain why a row was marked as an exact match versus a possible match.
- G4: Keep the review row visible as the spatial reference for the popup.

## 4. Non-goals (out of scope)

- NG1: Display internal database IDs, storage paths, or other technical metadata.
- NG2: Change the duplicate matching rules as part of the popup feature.
- NG3: Edit or delete the saved expense from the popup.
- NG4: Add a historical database re-evaluation or migration.

## 5. Users and scenarios

- As a person reviewing screenshot imports, I want to see the saved expense behind
  a possible-match warning, so I can decide whether the new expense is separate.
- As a person reviewing imports, I want to understand the difference between an
  exact duplicate and a possible match, so I know why the app blocked or warned me.

## 6. Functional requirements

| ID | Requirement (EARS) | Priority |
|----|--------------------|----------|
| FR-1 | When a review row has a possible-match warning for a saved system expense, the system shall provide an action beside that warning to open that specific saved expense. | MUST |
| FR-2 | When the user opens the match popup, the system shall show the saved expense's purchase date, time when available, merchant, amount, category, notes, and upload date. | MUST |
| FR-3 | When the saved expense has a source screenshot, the system shall provide a link from the popup to that screenshot. | MUST |
| FR-4 | If the saved expense has no available source screenshot, the system shall say that no source screenshot is attached. | MUST |
| FR-5 | When a match popup opens, the system shall place it next to its review row when space permits and keep the popup within the visible browser viewport. | MUST |
| FR-6 | When the match popup is open, the system shall visually distinguish it from the page with a lightly blurred, dimmed background and styling consistent with the application's Windows 98 theme. | MUST |
| FR-7 | When the popup is open, the system shall let the user close it using a close control, Escape, or a click on the backdrop. | MUST |
| FR-8 | When the review page explains an exact duplicate, the system shall identify the exact rule as same purchase date, canonical merchant, and amount to the cent. | MUST |
| FR-9 | When the review page explains a possible match, the system shall identify it as a non-blocking warning based on the same date and amount and related but non-identical merchant names. | MUST |

## 7. Business rules and decision table

The popup is associated with the saved system transaction that caused the warning;
it must not choose a different transaction based only on a similar display name.

| Conditions | Review result | Popup behavior |
|------------|---------------|----------------|
| Same purchase date, canonical merchant, and amount in cents | Exact match; row is blocked | No possible-match popup action is required for this rule. Explain the exact rule in the review page. |
| Same date and amount, and normalized merchant names are related but not identical | Possible match; row remains reviewable | Show the action beside the warning; open the specific saved expense and explain the possible-match rule. |
| Screenshot source is available for the matched saved expense | Either match kind above | Provide a link to the source screenshot in the popup. |
| Screenshot source is unavailable | Either match kind above | Show the expense details and state that no source screenshot is attached. |

For merchant relatedness in the existing rule, names are considered related when
one normalized name is a prefix of the other, both share the same first token of
at least three characters, or their normalized token sets share at least half of
the union. Normalization removes accents and punctuation and folds text to
lowercase. These thresholds are recorded here to make the current decision rule
auditable; changing them is outside this feature's scope.

## 8. Acceptance criteria

- AC-1 (FR-1): Given a possible-match warning linked to a saved system expense,
  when the user activates the adjacent action, then the popup shows that linked
  saved expense rather than another transaction with a similar name.
- AC-2 (FR-2): Given a saved expense with date, time, merchant, amount, category,
  notes, and upload timestamp, when the popup opens, then those user-facing values
  are shown; a missing time or notes value is represented as unavailable/none.
- AC-3 (FR-3): Given a saved expense whose import screenshot exists, when the user
  activates the source link or preview, then the source screenshot opens.
- AC-4 (FR-4): Given a saved expense without an available screenshot, when the
  popup opens, then it displays an explicit no-screenshot message.
- AC-5 (FR-5): Given the warning is near any viewport edge, when the popup opens,
  then it is placed beside the row where possible, flips to the other side when
  needed, and remains visible within the viewport.
- AC-6 (FR-6): Given the review page is visible, when the popup opens, then its
  background is lightly dimmed and blurred and the popup uses the application's
  classic Windows 98 visual style.
- AC-7 (FR-7): Given the popup is open, when the user presses Escape, clicks a
  close control, or clicks the backdrop, then it closes and returns focus to its
  opening action.
- AC-8 (FR-8): Given an exact duplicate is reported, when the review explanation
  is read, then it states same purchase date, canonical merchant, and amount to
  the cent.
- AC-9 (FR-9): Given a possible match is reported, when the review explanation is
  read, then it says the rule is a warning based on same date and amount with
  related merchant names, and that it is not automatically blocked.

## 9. Edge cases and error handling

- Missing optional time or notes must not prevent the popup from opening.
- Missing screenshot metadata or a missing screenshot file must not prevent the
  expense details from being shown; the popup must communicate that the source is
  unavailable.
- The matched transaction must have been loaded from the database; a batch-only
  related-name warning does not meet the system-match scenario in FR-1.
- Long merchant names and narrow viewports must not place the popup outside the
  viewport; its content must remain readable and scrollable.
- If the upload timestamp is missing, display an explicit unavailable value.
- The popup does not save or mutate transaction or import data.

## 10. Data requirements

- Read the saved transaction's date, optional time, merchant, integer-cent amount,
  currency, category, and optional notes.
- Read the associated import's upload timestamp and source screenshot reference
  when available.
- Do not expose internal transaction IDs, import IDs, or storage paths as user
  facing fields.
- No schema migration or data backfill is required by this feature.

## 11. Non-functional requirements

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-1 | Usability | The popup shall remain usable by keyboard for opening and closing, and shall return focus to the action that opened it. |
| NFR-2 | Privacy | The popup shall show only the user's expense details and source information; it shall not expose technical database metadata. |
| NFR-3 | Compatibility | The popup shall work within the app's existing server-rendered page and browser asset setup without requiring an external service. |

## 12. Dependencies and impact

- Import review route and match preparation in `app/main.py`.
- Duplicate match identity and explanation in `app/dedupe.py`.
- Expense/import reads in `app/db.py`.
- Import confirmation markup in `app/templates/confirm.html`.
- Existing theme styles and popup positioning in `app/static/style.css` and the
  confirmation page script.
- Existing screenshot-serving route for imported images.

## 13. Risks and mitigations

- Premortem: The most likely six-month failure is a match warning becoming linked
  to the wrong saved expense after duplicate candidate selection changes. Keep a
  stable saved transaction identity with the match and cover that link in the
  regression checks.
- Old imports may not retain a direct match ID; any compatibility lookup must
  resolve using the same duplicate rule and avoid showing a guessed unrelated row.
- Long details or small screens may crowd the warning; constrain popup dimensions,
  allow internal scrolling, and clamp its position to the viewport.
- Screenshot retention may differ from import metadata; handle a missing file as
  an unavailable source while preserving transaction details.

## 14. Assumptions

- **Confirmed by owner:** Show useful expense details and source information, not
  all database fields or technical metadata.
- **Confirmed by owner:** The possible-match action belongs next to its warning;
  the popup should stay near the associated expense and remain on screen.
- **Confirmed by owner:** Use the application's Windows 98 style with a subtle
  background blur.
- **Unconfirmed:** Display upload timestamps as UTC, explicitly labeled. This is
  the current implementation's timestamp convention; a local-time preference was
  not specified.
- **Unconfirmed:** Keep the popup scoped to possible matches against saved system
  expenses; batch-only possible matches do not have an already-saved source record.

## 15. Open questions

- Is UTC the desired display timezone for upload timestamps, or should they use
  the user's local timezone?
- Should a likely match against another row in the same not-yet-saved upload batch
  receive a popup in a future change? This draft scopes the popup to saved system
  expenses.

## 16. Change log

| Date | Change | Reason |
|------|--------|--------|
| 2026-11-02 | Initial requirements draft for saved expense match popup. | Record the owner's requested popup behavior and current duplicate-rule distinction before technical design approval. |
