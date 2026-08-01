# Pi Builder container POC

Purpose: verify Pi core as a short-lived Builder runtime before connecting Kimi, GitHub or n8n.

Security baseline:

- Pi runs only inside Docker, as the unprivileged `node` user.
- Only `./workspace` is mounted from Windows.
- The Windows home directory and Docker socket are not mounted.
- Linux capabilities are dropped and privilege escalation is disabled.
- The bootstrap check has no network access and receives no API key.
- No Pi packages, memory extensions or permission extensions are installed.

Bootstrap check after Docker Desktop is running:

```powershell
docker compose build
docker compose run --rm pi-builder
```

Expected result: Pi prints version `0.82.1` and the temporary container exits. This does not yet test Kimi or grant Builder write authority.

Verified on 2026-08-01:

- Pi output: `0.82.1`
- Exit code: `0`
- Remaining POC containers: `0`
- Model/API key used: no
- Runtime network: disabled

Do not add API keys to this directory or commit them to Git. The later Kimi test must inject the key at runtime and replace `network_mode: none` with a separately documented network policy.

`models.json` contains only the public Moonshot endpoint and model metadata. Its API-key field references the runtime-only `KIMI_API_KEY` environment variable; the secret itself must never be written to this directory.

Kimi connectivity smoke test verified on 2026-08-01:

- Provider/model: `moonshotai/kimi-k2.6`
- Expected and actual response: `PI_KIMI_OK`
- Exit code: `0`
- Remaining POC containers: `0`
- Workspace changes: none
- Credential handling: inherited into the one container process and removed from the launcher environment afterward; never written here
- Network limitation: Docker's ordinary outbound bridge was used for this connectivity test. Endpoint-level egress restriction remains required before real Builder work.

## Restricted egress POC

`compose.egress.yaml` places the worker only on an internal Docker network. A separate Squid container bridges that network to an external Docker network and permits HTTPS `CONNECT` only to `api.moonshot.ai:443`. The worker enables Node 24's environment-proxy support with `NODE_USE_ENV_PROXY=1`.

This topology must pass two keyless checks before another model call:

- `https://api.moonshot.ai/v1/models` is reachable through the proxy and returns an authentication response.
- `https://example.com` is rejected by the proxy.

Verified on 2026-08-01:

- Keyless allow test: Moonshot returned HTTP 401 through the proxy.
- Keyless deny test: `example.com` was rejected with proxy HTTP 403.
- Authenticated model test: `moonshotai/kimi-k2.6` returned exactly `PI_KIMI_OK`.
- Proxy evidence: one successful `CONNECT api.moonshot.ai:443`; the worker had no external network attachment.
- Cleanup: zero remaining POC containers and networks; workspace unchanged.

## First bounded write test

The write-test override is intentionally reusable and contains no personal
Windows path. Before using it, set `PI_BUILDER_WORKSPACE` to one explicitly
approved absolute task directory. Inject `KIMI_API_KEY` into the launcher
process only; never place it in an `.env` file in this directory.

Example composition check (does not run a model):

```powershell
$env:PI_BUILDER_WORKSPACE = "C:/absolute/path/to/approved-task-workspace"
docker compose -f compose.egress.yaml -f compose.write-test.yaml config --quiet
Remove-Item Env:PI_BUILDER_WORKSPACE
```

The checked-in prompt is a fixture for the completed Issue #3 proof of
concept, not a general-purpose task interface. A dispatcher must supply future
task prompts and workspace paths without editing this fixture.

Verified on 2026-08-01 after separate approval:

- Runtime/model: short-lived Pi 0.82.1 worker with `moonshotai/kimi-k2.6`.
- Writable scope: only `C:/Users/rikar/Cortxt/scratch/builder-codex-poc` mounted at `/workspace`.
- Intended and actual change: only `artifact.md`, set to `BUILDER_IMPLEMENTED` with evidence `SINGLE_FILE_WRITE_OK`.
- Post-run directory contents: one file; no unexpected files created.
- Result SHA-256: `31177F7AFA30D7FFAA85FB5C004E18F1702125B9F73D59BB3B5A9F3095B3D8D5`.
- Credential handling: the existing Hermes Kimi key was injected only for this one run and then cleared.
- Cleanup: zero remaining write-test containers and networks.
- Independent review: Codex CLI 0.146.0 with `gpt-5.6-sol`, `sandbox: read-only`, `approval: never` returned `CODEX_REVIEW: PASS`.
- Integrity after review: the SHA-256 and write timestamp were unchanged; the review created no files.
- GitHub final state: operator acceptance recorded; Issue #3 is closed as completed and both Project status fields are `Done`.
- Known gap: observed model cost is `unknown`; cost telemetry is required before automated budget enforcement.
- Buzz Builder remains stopped.

## Reproducibility and remaining limitations

- Pi is pinned to `0.82.1`; the Node and Debian base images currently use
  release tags rather than immutable digests. Pin image digests before treating
  this as a production runner.
- The Squid allowlist limits the worker to `api.moonshot.ai:443`, but it does
  not inspect encrypted request content.
- Docker is the security boundary. Pi itself is not a sandbox.
- The POC does not yet enforce a measured model-cost ceiling.
- `depends_on` controls startup order, not full proxy readiness. A production
  dispatcher needs a readiness check and bounded retry policy.
