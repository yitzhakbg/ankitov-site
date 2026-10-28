# AnkiTov Community Tour — A Developer's Guide to the Project (2026-10-28)

Welcome! This is the end-to-end tour of **AnkiTov** for developers, contributors, and the
curious. It explains what the project is, how every piece works, how to run it yourself, and
where to plug in. No prior knowledge of the project is assumed.

---

## 1. What AnkiTov Is

AnkiTov is **zero-intervention knowledge-retention infrastructure for institutions**, built
around the Anki ecosystem. It adds what schools need but stock Anki lacks:

- **Multi-user administration** — classes, students, institutional oversight
- **Server-side scheduling** — the FSRS-6 spaced-repetition algorithm runs in-house (Rust)
- **The Interleaved Mastery Pipeline (IMP)** — automatically computes remediation "capsules"
  (targeted card sets) per student and delivers them into review sessions
- **Compliance tracking** — institutions can see practice happened, without teachers doing
  any manual work

The design doctrine: **the teacher assigns once; the system schedules, delivers, interleaves,
and reports.** Nearly no burden on teaching staff, no extra class time.

- **Backend:** Rust 2021 + Loco.rs + Axum + SeaORM + SQLite/libSQL
- **License:** code is AGPL-3.0-only; seed deck content is CC0-1.0
- **Docs:** mdBook site (published from the `ankitov-docs` repo), OpenAPI/Scalar served live
  by the backend at `/api/v1/openapi.json` and `/scalar`
- **Not affiliated with Anki** (AnkiMobile/AnkiDesktop/AnkiDroid); "Anki" is a trademark of
  its respective owner. AnkiTov wraps and extends the ecosystem, it does not fork Anki's brain.

## 2. The Big Picture: Five-Layer Isolation

AnkiTov is architected as five isolated layers, so the system stays auditable and the
upstream Anki behavior stays stock:

1. **Cloud Gateway** — routing, authentication, tenancy
2. **Stock Anki Core** — unmodified Anki scheduling and review behavior
3. **Custody Add-on** — server-side enforcement inside the streaming container (no client-side
   DRM code; custody is natural because the enriched library never leaves the server)
4. **HTML5 Stream** — browser streaming of the container's pixels (Selkies)
5. **Client** — any browser; or the student's own Anki client via the sync server

The ecosystem is two-tier: an **open-source core** (this project, AGPL-3.0) plus a separate
commercial gateway (not covered in this tour).

## 3. Inside-Out: How a Practice Session Works

### 3.1 The Interleaved Mastery Pipeline (IMP)
The heart of the backend. Flow: **track library → student profiles → capsule generation →
FSRS-6 urgency sort → compliance tracking.**

- A **capsule** is a pre-computed remediation set of card IDs, computed server-side.
- Scheduling uses **FSRS-6** via an in-house Rust implementation (`fsrs-rs`), so the server —
  not the client — decides what each student reviews next and when.

### 3.2 Capsule delivery: the Session Driver add-on
AnkiConnect alone cannot inject a custom card queue, so a thin Anki add-on (~250–450 lines of
Python, no GUI) bridges the gap inside the streaming container:

```
Backend (Rust)              Session Driver (Python, :18765)      Anki (Qt)
  │  POST /session {card_ids, uuid}  │                              │
  │──────────────────────────────────▶│ validates, aborts prior      │
  │                                   │ session, tags capsule cards  │
  │                                   │──creates filtered deck───────▶
  │                                   │──opens reviewer──────────────▶
  │  ◀──progress/answer events────────│◀──reviewer hooks─────────────│
```

- The add-on listens on **HTTP :18765** inside the container; **AnkiConnect** runs on
  **:8765** for health checks and basic GUI queries.
- Engineering note: AnkiConnect executes on a background thread, so GUI widget switches
  silently fail if called directly — the driver uses a command-file handshake polled by a
  main-thread QTimer instead.

### 3.3 Browser streaming with Selkies (`stream/selkies-anki/`)
Students can practice with **zero install** in any browser:

- Upstream: [selkies-project/selkies](https://github.com/selkies-project/selkies) v2.0.0
  (MPL-2.0), base image `ghcr.io/selkies-project/selkies/base:latest-ubuntu26.04`, desktop-less.
- **App-only variant**: no desktop, no panel, no terminal — the student sees ONLY Anki's
  pixels. Wayland path: labwc with a window rule maximizing Anki; X11 path: Xvfb framebuffer.
- Transport: WebSockets by default (TURN/WebRTC not in the default path).
- Why it works so well: flashcards are 99% static content shown 5–8 seconds, so the stream
  needs only ~150–250 kbps (vs ~2 Mbps for continuous video), and +50–80 ms frame latency is
  under 1% of the human read-think cycle — imperceptible.
- Scale engineering built in:
  - **Shared read-only media mount** — the multi-gigabyte media library (audio, diagrams) is
    mounted read-only across containers; only lightweight text/note rows are injected per
    student (~95% disk/RAM saved per container).
  - **Warm container pool** — pre-booted idle containers attach in under a second when a
    student clicks "Review"; Anki launches chromeless and viewport-responsive for phones.
- Per-container footprint: ~250–350 MB RAM, near-zero idle CPU between card flips.

### 3.4 Continue on your own device: the sync server
A self-hosted Anki sync server (`Dockerfile.sync-server`, container `ankitov-sync-server` on
:8080) uses Anki's built-in multi-user sync (`SYNC_USER1=user:pass`, `SYNC_BASE=/data`):

```
AnkiTov account (id, email)
   └─▶ Anki profile name (e.g. "stu_<id>")  in the stream container
        └─▶ sync-server user                 SYNC_USER1="stu_<id>:<pass>"
             └─▶ student's own device        custom sync URL + same creds
```

One-time setup per device — desktop (paste add-on code + sync URL + login), AnkiDroid
(Settings → Advanced → custom sync server), AnkiMobile (custom sync server). Same collection,
same progress, no re-download, no export/import. Sync triggers: session end + "Sync now";
conflicts resolve with Anki's native last-write-wins. Isolation model: pooled container with
per-user profiles first; container-per-student only if compliance demands.

## 4. The Student Journey, End to End

1. **Signup** — the backend provisions a sync account (`stu_<id>` + a stable password shown
   once in the "Continue on your device" flow).
2. **Click "Review"** — the stream's SSO handshake resolves the account → Anki profile name;
   the `svc/anki/run` service launches Anki as that profile.
3. **Warm attach (<1 s)** — a pre-booted container from the pool is assigned.
4. **Review** — Anki opens straight into the deck; the backend `POST /session` delivers the
   capsule; the Session Driver creates a filtered deck and opens the reviewer.
5. **Answers flow back** — telemetry updates FSRS-6 state and compliance records.
6. **Session end** — the profile syncs to the sync server; the container returns to the pool.
7. **Any device, anytime** — the student's own Anki client syncs against the same server.

## 5. The Content Engine

- **Seed decks** live in `content/seed/` (CC0-1.0, public domain) with `manifest.json` as the
  metadata source.
- The **deck factory** pipeline turns textbooks into verified decks: Clean-Text Minimum
  Information Principle (precise Basic + Cloze cards), hierarchical tags
  (`Textbook::<Book>::Ch01`), QA gates, capsule slicing, and optional enrichment (neural TTS
  audio, diagrams, image occlusion, misconception callouts).
- Quality doctrine: zero slop, verified factual citations, no third-party shared decks in the
  curated catalog.

## 6. Run It Yourself

```bash
# 1. Check prerequisites
bash scripts/bootstrap.sh --status

# 2. Full bootstrap (checks tools, builds, runs tests)
bash scripts/bootstrap.sh

# 3. Start the dev server
cd backend && cargo run start
# → Dashboard at http://localhost:5150/dashboard
# → IMP Console at http://localhost:5150/imp-console
# → OpenAPI/Scalar at http://localhost:5150/scalar
```

- Tools: Rust 2021+, Jujutsu (`jj`) for version control, `cargo-nextest` recommended, Docker
  for production.
- Production stack: `docker-compose.yml` (backend, sync server, streaming container, reverse
  proxy). The streaming container build is in `stream/selkies-anki/` (`Dockerfile.anki-base`,
  `docker-compose.anki.yml`, s6 services, boot scripts).
- Health check inside a streaming container:
  `curl -s -X POST http://127.0.0.1:8765 -d '{"action":"guiCurrentCard","version":6}'`
- Deployment shape: any Linux host with Docker works — a small **cloud VPS** serves a
  classroom; a larger **cloud VPS or bare-metal server** serves hundreds of concurrent
  streamers (the math: ~104 average / 300–350 peak concurrent sessions per 10,000 daily
  learners fits on 1–2 bare-metal servers); a **GPU workstation** is optional and only
  needed for local LLM-assisted content tooling, not for the practice pipeline itself.

## 7. The 7-Prong Roadmap

| # | Prong | Status |
|---|-------|--------|
| 1 | Management Console + IMP | Active |
| 2 | Class-Wide Practice Sessions | Planned |
| 3 | Web Deployment Infrastructure | Active |
| 4 | Gaming Console Streaming | Planned |
| 5 | Commercial Analytics | Planned |
| 6 | Content Clearing House | Planned |
| 7 | Public Platform & Blog | Planned |

## 8. Where to Plug In (Contributors)

- **Repo layout**: `backend/` (Loco.rs API crate), `ankitov-budget-gate/` (MCP rate-limiting
  sidecar), `addons/` (Anki integration assets), `toolchains/`, `docs/` (mdBook), `scripts/`,
  `specs/` (research/design/plans), `stream/selkies-anki/` (streaming container),
  `content/seed/` (CC0 decks).
- **Good first surfaces**: the student web reviewer (browser practice surface), IMP
  analytics, the streaming container UX, deck-factory QA gates, documentation.
- **Conventions**: all commits use Jujutsu (`jj`); no `unsafe`; no new `unwrap()`/`expect()`
  in production paths; new public APIs need doc comments; event/kind registries are
  centralized; the dashboard lives at `/dashboard` (imp-console).
- **Testing**: `cargo nextest run` for the backend; the streaming container has health
  checks; E2E flows exercise signup → session → sync.
- **Communication**: the mdBook docs and OpenAPI surface are the contract; ask in the
  community channels before large architectural changes.

## 9. Glossary

| Term | Meaning |
|---|---|
| IMP | Interleaved Mastery Pipeline: tracks → profiles → capsules → FSRS → compliance |
| Capsule | Server-computed remediation card-set delivered to a student session |
| FSRS-6 | The spaced-repetition scheduling algorithm (in-house Rust implementation) |
| Session Driver | In-container Anki add-on (:18765) that injects capsules into the reviewer |
| Selkies | Browser streaming tech; the container shows only Anki's pixels |
| Sync server | Self-hosted Anki sync (:8080) so students continue on their own devices |
| Custody add-on | Server-side enforcement inside the container (no client DRM code) |
| Seed decks | CC0 starter decks in `content/seed/` |
| Warm pool | Pre-booted idle containers for <1 s student attach |
| MIP | Minimum Information Principle — the deck quality doctrine |
