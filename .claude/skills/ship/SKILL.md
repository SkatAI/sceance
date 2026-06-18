---
name: ship
description: Use when the user types /ship or asks to test, commit, and deploy the sceance backend — runs the full pre-deploy checklist before pushing to the production branch.
---

# Ship

One-command path from a clean working change to a deployed sceance backend.
Deployment is **push-to-deploy**: DigitalOcean App Platform (`seal-app` /
`sceance`) rebuilds the image automatically when the **`production`** branch is
pushed. There is no `doctl deploy` step — pushing IS the deploy.

> The Makefile `push` comment says "redeploy on main" — that is stale. The
> watched branch is `production` (`main` is dev-only). Confirm before pushing if
> unsure.

## Steps

Run these in order. Stop and report if any step fails — never push on red.

1. **Tests** — `make test` (= `cd server && uv run pytest`). Must be green.
2. **Rebuild + smoke-test the image** if frontend/dashboard assets
   (`server/static/*`) or persona params (`personas/*.json`) changed — there is
   no hot-reload, so a stale container hides breakage:
   `make build && make restart && make test-health`
3. **Changelog** — add an entry to `changelog.md` under today's date for any
   user- or developer-facing change (new features, providers, schema/migrations,
   behavior changes). Skip purely internal edits.
4. **Commit** on the current branch with a descriptive message summarizing what
   changed and why.
5. **Merge to production** — `git checkout production && git pull && git merge <branch>`.
6. **Deploy** — `git push origin production`. App Platform picks it up and
   rebuilds.
7. **Verify** — watch the rollout with `make prod-logs` (=
   `doctl apps logs seal-app sceance --type run --follow`); confirm `/health`
   and the new behavior once live.
8. Switch back to the working branch (`git checkout <branch>`).

## Report

After shipping, tell the user: what changed (1–2 lines), test result, the
commit, and that `production` was pushed / the deploy is rolling.

## Common mistakes

- Running `pytest` from the repo root — it must be `cd server && uv run pytest`.
- Pushing `main` expecting a deploy — only `production` is watched.
- Skipping the image rebuild after editing `static/` or `personas/` — the
  running container keeps serving stale assets.
- Verifying model IDs: if a persona config changed providers/models, confirm the
  model still exists on the provider before shipping (removed Groq models have
  broken prod before).
