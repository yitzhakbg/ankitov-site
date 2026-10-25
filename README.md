# ankitov-site

Source of truth for the **ankitov.org** marketing site — a Cloudflare Workers
static-assets deployment (Worker `white-rice-9fa6`, custom domains
`ankitov.org` + `www.ankitov.org`).

## Layout

| Path | What it is |
|------|------------|
| `site/` | The real site (homepage, about/blog/community, assets, tooling). **Not deployed until launch.** |
| `waiting/` | The pre-launch "Coming soon" overlay — what ankitov.org serves until the owner green-lights launch. |
| `site/scripts/check-orphans.py` | Orphaned-word gate (T-188): a block text element whose last rendered line is exactly one word is a deploy blocker. Widths 390/768/1024/1280/1440. |
| `site/scripts/check-links.py` | Link checker: internal links/anchors must resolve; external links probed (warnings only unless `--strict-external`). |

## Deploy doctrine

- **Pre-launch (now):** every push to `main` deploys the `waiting/` overlay.
  The real site in `site/` is reviewed and gated but stays dark.
- **At launch:** the owner sets the repo variable `SITE_LAUNCH_ENABLED=true`;
  the next push to `main` (or a manual `workflow_dispatch` run) deploys `site/`
  via `site/deploy.sh` — which runs the orphan gate first and refuses to
  deploy on findings.
- Deploy credentials live only as the `CLOUDFLARE_API_TOKEN` **GitHub Actions
  secret**. No credential is ever committed to this repo.

## CI (`.github/workflows/ci.yml`)

On every push and PR:

1. **Orphan gate** — detector selftest + all `site/*.html` + `waiting/*.html`
   at widths 390/768/1024/1280/1440 (T-188 doctrine: `text-wrap: pretty`
   globally + `<span class="nb">` hard bindings; never bare `&nbsp;` —
   Chromium breaks lines at `&nbsp;` under `text-wrap: pretty`).
2. **Link check** — internal links/anchors hard-fail; external links warn.
3. **Deploy** (push to `main` only) — waiting overlay pre-launch, real site
   post-launch, followed by a curl verification of the live domain.

## Relationship to the AnkiTov monorepo (staging)

The private AnkiTov monorepo (`AnkiTov-C`, `specs/launch/site-org/`) is the
**staging ground**: the working copy where iterations are developed and
previewed locally (no-cache preview server on `:8098`). Changes graduate to
this repo — this repo is the source of truth that deploys. The staging copy
keeps the internal-only files that must never be published here
(`SETUP-CHECKLIST.md`, `.wrangler/` state) and the deploy credentials
(macOS Keychain `Cloudflare_AnkiTov_Dual_Entity_Token`).

## License

AGPL-3.0 — same as the main AnkiTov project (see `LICENSE`).
