# Frontend UI Migration Plan

## Goal

Rebuild the frontend from a repo-centric demo workflow into a PR-centric product flow that:

- looks deliberate and premium on 14"+ screens;
- does not collapse the sidebar into a top strip on medium widths;
- removes the explicit "sync first, then configure, then analyze" friction from the main path;
- shows synchronized PRs in the main navigation instead of only recently opened repositories;
- hides debug tooling by default;
- fixes stale snapshot/job state when the user switches to another PR;
- keeps the current backend contract working during the first UI migration.

## Recommended Product Direction

Use a **single immersive onboarding/connect screen** instead of a plain token form and keep the main app **PR-centric** after connection.

Why this direction:

- it reduces steps without adding another dead-end route;
- it gives us room to present the product before asking for credentials;
- it keeps implementation smaller than a full separate onboarding funnel;
- it matches the new "Analyze PR" flow where the user should feel they are entering a review workspace, not operating a demo console.

## Current Reality In The Code

### 1. Connect screen is too form-like

Current file:

- `frontend/src/pages/ConnectPage.tsx`

Current behavior:

- simple provider select;
- PAT input;
- basic action buttons;
- no product narrative;
- no visual hierarchy beyond a standard card.

### 2. Sidebar is not a real responsive navigation

Current files:

- `frontend/src/components/AppShell.tsx`
- `frontend/src/styles.css`

Current problem:

- on widths below `1190px` the sidebar is turned into a normal top block via media query;
- there is no compact rail;
- there is no drawer;
- there is no burger interaction model at all.

This is why the "burger/menu on smaller diagonals ends up on top" problem exists: the layout does not have a burger menu, it just stacks the sidebar above content.

### 3. Navigation is repo-centric, not review-centric

Current file:

- `frontend/src/components/AppShell.tsx`

Current behavior:

- nav shows sections for connect and repos;
- rail shows `recentRepos`;
- there is no first-class concept of "recent synchronized PRs".

### 4. Store shape is the main blocker for a proper PR-centric sidebar

Current file:

- `frontend/src/store/app-store.tsx`

Current behavior:

- workspace state is keyed by `repoId`;
- each repository can hold only one active PR workspace at a time;
- if you sync PR `#10` and then sync PR `#11`, the repo-level workspace is overwritten.

Implication:

- the current architecture cannot correctly represent multiple synchronized PR workspaces from the same repo in the sidebar;
- this is also one of the reasons the UI feels like a demo flow rather than a real working surface.

### 5. Snapshot metrics do not reset when selecting another PR

Current root cause:

- `selectPullRequest(repoId, prNumber)` only updates `selectedPrNumber`;
- it does **not** clear `syncData`, `job`, `suggestions`, `comments`, `feedbackSummary`, or `publishResult`.

Current file:

- `frontend/src/store/app-store.tsx`

Visible bug:

- snapshot/file/idempotent block still shows data from the previous PR after the user clicks another PR.

### 6. Sync exists because backend needs an immutable snapshot

Current files:

- `frontend/src/lib/api.ts`
- `backend/app/main.py`

Why sync exists:

- analysis job creation requires `snapshotId`;
- `snapshotId` only appears after `/sync`;
- sync materializes the PR diff into an immutable review artifact.

Conclusion:

- the sync step is technically valid;
- it should disappear from the UI as a separate decision point.

### 7. Params screen has demo-only clutter

Current file:

- `frontend/src/pages/RepoWorkspacePage.tsx`

Current problems:

- separate step only for params;
- `maxComments`, `minSeverity`, `fileFilter` are not core UX;
- these controls make the product feel like an internal tool.

### 8. Debug suite is always visible

Current files:

- `frontend/src/pages/ReposPage.tsx`
- `frontend/src/store/app-store.tsx`
- `frontend/src/debug/presets.ts`

Current problem:

- debug tools are mixed into the primary user surface.

### 9. Job events require a manual refresh button

Current file:

- `frontend/src/pages/RepoWorkspacePage.tsx`

Current behavior:

- job status auto-refreshes while running;
- events still have a separate manual "refresh events" button.

This should be automatic.

### 10. Visual system is underused

Current files:

- `frontend/index.html`
- `frontend/src/styles.css`

Current observation:

- `Space Grotesk` and `IBM Plex Mono` are already loaded;
- global CSS still uses `Inter`/system-like styling;
- the visual language is too safe for a product that wants to feel premium.

## Target UX

### A. Entry experience

Replace the current plain connect screen with a **hybrid onboarding/connect screen**:

- left side or top hero explains product value;
- right side contains provider selection and token connection;
- once connected, the screen transitions into "Open your review workspace" instead of just showing a static status box.

Recommended structure:

1. Product hero
2. Provider picker
3. Token field
4. "Connect and continue" CTA
5. Trust/details band:
   - GitHub and GitLab supported
   - local review flow
   - comments publishing path

### B. Main app shell

The shell should become a **review cockpit**, not a docs-like sidebar.

Desktop:

- persistent left rail;
- strong branding block;
- nav items for:
  - `Home`
  - `Repositories`
  - `Connected Provider`
- synchronized PR section under nav;
- compact activity block at the bottom.

Tablet:

- compact rail or collapsible drawer;
- no top-stacked sidebar.

Mobile:

- real drawer opened from burger button;
- drawer overlays content;
- content keeps its own top app bar.

### C. PR-first workspace

Reduce the early funnel to:

1. choose repository;
2. choose PR;
3. choose review scopes;
4. click `Analyze PR`.

Do not force the user through:

- explicit sync button;
- separate params page;
- non-essential controls.

### D. Job screen

Keep the job screen, but simplify it:

- no "refresh events" button;
- events are polled automatically while status is `queued` or `running`;
- once `done`, keep one manual `Refresh job` button if needed, but default behavior should already be enough.

### E. Debug tooling

Hide debug suite behind a feature flag:

- default off in all normal builds;
- visible only when explicitly enabled.

## Recommended Information Architecture

### Routes

Recommended target:

- `/` -> onboarding/connect entry
- `/repos` -> repository gallery / repo chooser
- `/repos/:repoId/reviews/:prNumber` -> PR workspace

Why:

- route becomes PR-centric;
- sidebar can navigate to a specific synchronized PR;
- stale UI state becomes easier to reason about.

Backward compatibility:

- keep `/repos/:repoId/workspace` temporarily and redirect it to the last selected PR for that repo if present.

## State Model Refactor

This is the most important structural change.

### Current problem

State is keyed by `repoId`, but the UI you want is keyed by `review workspace`.

### Target model

Split state into two layers:

1. `repoViews`
   - repo-level PR list
   - search
   - PR filters
   - repo metadata

2. `reviewWorkspaces`
   - key: `workspaceKey = ${repoId}:${prNumber}`
   - selected scopes
   - sync data
   - job
   - suggestions
   - comments
   - publish result
   - feedback state

3. `recentReviews`
   - sidebar source
   - label: `owner/repo #prNumber`
   - status
   - updatedAt
   - route target

### Why this refactor is worth doing early

- fixes the stale PR snapshot bug correctly;
- enables sidebar with synchronized PRs;
- removes ambiguity about which PR the user is currently editing;
- allows reopening history entries into distinct workspaces cleanly.

## UX Changes Mapped To Your Requests

### Request 1. Redesign GitHub/GitLab connection flow

Decision:

- use one hybrid onboarding/connect screen;
- do not create a separate onboarding route in the first pass.

Implementation notes:

- keep `ConnectPage.tsx` route, but rebuild its content;
- add a hero section with product positioning and a visual preview;
- keep provider connection in the same screen.

### Request 2. Make 14"+ look good and fix medium-width nav behavior

Implementation notes:

- stop collapsing sidebar into a top block at `1190px`;
- introduce three layout modes:
  - `>= 1440px`: full rail
  - `1024px - 1439px`: compact rail
  - `< 1024px`: drawer
- increase content max width to the `1500-1600px` range;
- use stronger spacing, larger cards, and more deliberate typography.

### Request 3. Sidebar should show synchronized PRs, not open repos

Implementation notes:

- replace `recentRepos` UI block with `recentReviews`;
- only include workspaces that already have `syncData` or `job` or `results`;
- label each item as `owner/repo #123`;
- show status badge:
  - `ready`
  - `running`
  - `results`
  - `published`

### Request 4. Remove or hide debug suite

Implementation notes:

- add `VITE_ENABLE_DEBUG_SUITE=false` to frontend env handling;
- gate debug section in `ReposPage.tsx`;
- keep debug actions in store, but do not surface them when flag is off.

### Request 5. Snapshot panel does not update when another PR is selected

Implementation notes:

Immediate fix:

- if selected PR changes, clear review-bound state.

Required reset on PR switch:

- `syncData`
- `job`
- `jobBooting`
- `jobBootStartedAt`
- `jobEvents`
- `suggestions`
- `selectedSuggestionIds`
- `activeSuggestionId`
- `publishResult`
- `comments`
- `feedbackSummary`

Better fix:

- move to `reviewWorkspaces` keyed by PR.

### Request 6. Why sync exists

Answer:

- sync creates the immutable snapshot required by analysis;
- without it, backend cannot create a job because it has no snapshot ID to analyze.

Product decision:

- keep sync at the API level;
- remove sync as a separate UX step.

### Request 7. Merge params and sync into one analyze action

Implementation notes:

- replace `Sync` button with `Analyze PR`;
- move scope toggles into the PR selection view;
- remove standalone params step;
- only keep these user-facing scope toggles:
  - `Безопасность`
  - `Стиль`
  - `Баги`
- remove the rest from the primary UI:
  - `performance`
  - `maxComments`
  - `minSeverity`
  - `fileFilter`

Internal handling:

- `performance` stays off by default;
- `maxComments` becomes an internal constant for now, for example `30`;
- advanced tuning can come back later behind an internal flag if needed.

## Recommended UI Structure After Migration

### 1. Connect screen

Suggested composition:

- `OnboardingHero`
- `ProviderConnectPanel`
- `ConnectedStatePanel`

### 2. Repo gallery

Suggested composition:

- repository search and filters;
- clean cards with provider markers;
- no debug suite by default.

### 3. PR workspace

Suggested composition:

- top header with repo and PR identity;
- left pane: PR list and selection;
- right pane: PR details + scope chips + `Analyze PR` CTA;
- once synced/job created, snapshot facts appear as passive metadata, not as a separate decision block.

### 4. Job view

Suggested composition:

- summary strip;
- progress cards;
- timeline/event console;
- CTA to results when done.

### 5. Results view

Keep the strong split layout, but restyle it:

- better visual grouping;
- wider left list on desktop;
- cleaner detail panel;
- keep evidence/diff panel because it is useful.

## Store And Action Changes

### New preferred actions

- `selectRepository(repoId)`
- `loadPullRequests(repoId)`
- `openReviewWorkspace(repoId, prNumber)`
- `analyzePullRequest(repoId, prNumber)`
- `pollJobAndEvents(workspaceKey)`
- `openRecentReview(workspaceKey)`

### `analyzePullRequest` should do this

1. validate repo and PR selection
2. create or activate workspace
3. call sync endpoint
4. store `syncData`
5. call create-analysis-job endpoint
6. switch UI to `job`
7. start automatic polling for both job and events

This keeps backend unchanged while removing the extra UI step.

## API / Backend Impact

### Phase 1

No backend changes required.

Frontend orchestration can call:

1. `/sync`
2. `/analysis-jobs`

in sequence.

### Optional backend improvement later

Add a composite endpoint like:

- `POST /repos/{repoId}/prs/{prNumber}/analyze`

This would:

- perform sync;
- create the job;
- return both sync metadata and initial job payload.

This is optional, not required for the first UI migration.

## Files To Change

### Existing files to refactor

- `frontend/src/App.tsx`
- `frontend/src/components/AppShell.tsx`
- `frontend/src/pages/ConnectPage.tsx`
- `frontend/src/pages/ReposPage.tsx`
- `frontend/src/pages/RepoWorkspacePage.tsx`
- `frontend/src/store/app-store.tsx`
- `frontend/src/styles.css`
- `frontend/src/types.ts`
- `frontend/.env.example`

### Recommended new components

- `frontend/src/components/OnboardingHero.tsx`
- `frontend/src/components/ProviderConnectPanel.tsx`
- `frontend/src/components/ReviewRail.tsx`
- `frontend/src/components/PrSelectionPanel.tsx`
- `frontend/src/components/AnalyzePrCard.tsx`
- `frontend/src/components/JobTimeline.tsx`

The current workspace page is too large; splitting it is part of the migration, not optional polish.

## Visual Direction

Recommended design language:

- bold editorial headings with `Space Grotesk`;
- operational metadata in `IBM Plex Mono`;
- dark graphite shell;
- warm light content surfaces;
- sharper hierarchy between hero, rail, workspace, and detail panels;
- purposeful gradients and soft panel glows, not flat default cards.

Avoid:

- default SaaS white/blue boredom;
- tiny pills everywhere with identical emphasis;
- generic form-first screens.

## Responsive Rules

### Large desktop

- max content width around `1560px`;
- persistent rail;
- roomy grid;
- wider results list/detail split.

### 14" laptops

- full experience should still fit without crowding;
- prefer compact but still persistent navigation;
- avoid pushing the rail above content.

### Tablet

- compact rail or drawer;
- preserve one strong primary column for content.

### Mobile

- true overlay drawer;
- sticky top app bar with burger;
- results split collapses into stacked sections.

## Rollout Plan

### Phase 0. Safety and flags

- add `VITE_ENABLE_DEBUG_SUITE=false`
- keep old route working temporarily
- do not change backend contract

### Phase 1. State cleanup

- introduce workspace key model
- add `recentReviews`
- fix PR-switch reset bug

Acceptance:

- selecting another PR never shows stale snapshot/job data
- synchronized PRs can appear in sidebar

### Phase 2. Shell redesign

- rebuild `AppShell`
- add drawer / compact rail behavior
- move from recent repos to recent synchronized PRs

Acceptance:

- no top-stacked sidebar on medium widths
- navigation works on desktop, tablet, and mobile

### Phase 3. Connect screen redesign

- replace utilitarian token form with onboarding/connect hybrid screen
- connect CTA becomes more product-like

Acceptance:

- screen communicates product value before asking for token
- connect flow still works with current backend

### Phase 4. PR flow simplification

- merge sync + params into PR selection view
- replace `Sync` with `Analyze PR`
- keep only three visible scope toggles

Acceptance:

- user can go from repo selection to analysis in one clear CTA
- no separate params step in the primary path

### Phase 5. Job/results cleanup

- remove manual events refresh button
- auto-poll events while job is active
- keep job screen but make it cleaner

Acceptance:

- user sees events without manual refresh
- job screen feels live

### Phase 6. Visual refinement

- typography switch
- spacing tuning
- card hierarchy tuning
- stronger responsive polish

Acceptance:

- the app no longer looks like an internal admin demo

## Recommended First Implementation Order

If we want the fastest path with the biggest UX impact, do work in this order:

1. fix PR switch reset bug
2. hide debug suite behind a flag
3. merge sync + params into `Analyze PR`
4. redesign shell and introduce recent synchronized PRs
5. redesign connect screen
6. visual polish and responsive tuning

This order gives user-facing progress quickly while keeping the larger shell/state refactor under control.

## Non-Goals For This Pass

- backend contract rewrite
- publish/feedback workflow redesign from scratch
- full design system extraction
- adding more review controls to replace the removed params

The correct first move is to simplify, not to replace one cluttered setup with another.
