# Phase 4: Admin UI - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-14
**Phase:** 4-Admin UI
**Areas discussed:** Editing interaction, Status workflow, Invoice image display, Frontend routing

---

## Editing Interaction

Context provided before questions: full walkthrough of what data gets stored (Invoice + InvoiceLineItem tables) and the two DB levels where AI errors can occur.

| Option | Description | Selected |
|--------|-------------|----------|
| Inline edit | Click any field → input appears in place, save on blur/Enter | |
| Edit-mode toggle | "Edit" button puts whole page into edit mode, one Save/Cancel | |
| Separate edit form | "Edit" navigates to a different route or modal with a full form | |

**User's choice (via freeform):** A modal with a pre-filled form opens for the line/section being edited. On Save, the PUT endpoint is called.

**Follow-up — structure:**

| Option | Description | Selected |
|--------|-------------|----------|
| Two separate edit modals | One for document header fields, one per line-item row | ✓ |
| One big edit modal | All document fields + all line items in one form | |
| Inline on detail page | Fields editable directly in the page | |

**Notes:** User initially described a modal approach in freeform before seeing the structured options. After clarification on two DB levels (Invoice vs InvoiceLineItem), chose two separate modals as the natural fit.

---

## Status Workflow

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated Confirm/Reject buttons | Prominent buttons on detail page when status is pending_review | ✓ |
| Status as editable field | Status dropdown in the Edit document modal | |
| Quick actions from list view | Approve/Reject buttons on the list row | |

**User's choice:** Dedicated Confirm / Reject buttons on the detail page.

**Follow-up — reason required?**

| Option | Description | Selected |
|--------|-------------|----------|
| One-click, no reason | Fast, no friction | ✓ |
| Optional reason on Reject | Small text input for optional note | |
| Required reason on both | Mandatory note for audit trail | |

**Notes:** User wants minimal friction for the review workflow. No note/reason required.

---

## Invoice Image Display

| Option | Description | Selected |
|--------|-------------|----------|
| Side-by-side with data fields | Image on the right, data on the left — simultaneous view | ✓ |
| Thumbnail that opens lightbox | Compact thumbnail, full image on click | |
| Separate section below | Collapsible image section below the data | |

**User's choice:** Side-by-side layout.

**Follow-up — how backend serves the image:**

| Option | Description | Selected |
|--------|-------------|----------|
| FastAPI static files mount | Mount storage dir as /static/... — zero business logic | |
| Dedicated /images/{filename} endpoint | Proper route streaming the file, hook for future auth | ✓ |
| You decide | Leave to planner | |

**Notes:** User chose dedicated endpoint despite it being slightly more code, presumably to preserve the access-control hook for v2.

---

## Frontend Routing

| Option | Description | Selected |
|--------|-------------|----------|
| React Router with URL routes | / list, /invoices/:id detail — back button works, bookmarkable | ✓ |
| Single-page state | No router — conditional rendering via React state | |

**User's choice:** React Router v7 with URL routes.

**Follow-up — state management:**

| Option | Description | Selected |
|--------|-------------|----------|
| TanStack Query v5 | Caching, refetch, mutation invalidation — recommended in CLAUDE.md | ✓ |
| Plain fetch + useState | No new dependency, manual re-fetch coordination | |

**Notes:** Both React Router v7 and TanStack Query v5 confirmed. Neither is in package.json yet — must be installed in this phase.

---

## Claude's Discretion

- UI component library / CSS approach (no library installed; planner picks minimal approach)
- Exact component file structure and folder layout
- Pagination detail (offset-based is simplest for v1)
- Whether to add optimistic updates on Confirm/Reject or just re-fetch
- Internal TanStack Query hook naming conventions

## Deferred Ideas

- Authentication (UI-07) — already deferred to v2
- CSV export (EXP-01, EXP-02) — v2 requirements
- Allowlist management UI — no v1 requirement
- Optional Reject reason/note — v2 enhancement if team wants it
