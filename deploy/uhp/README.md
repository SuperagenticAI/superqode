# Public UHP Core bind (`superqode-uhp`)

Brand-new Cloud Run service. Do not edit or retarget the A2A service,
`Dockerfile`, or `cloudbuild.yaml`.

## Create the service (Google Cloud Console)

1. Cloud Run → **Create service** (not the existing `superqode-a2a` service).
2. **Connect repository** (GitHub, this repo).
3. Build type: **Dockerfile**.
4. Dockerfile path: `Dockerfile.uhp` (not `Dockerfile`).
5. Cloud Build configuration file: `cloudbuild.uhp.yaml` (not `cloudbuild.yaml`).
6. Service name: `superqode-uhp`.
7. Region: `us-central1` (domain mapping). Keep A2A on `europe-west1`.
8. Autoscaling: min 0, **max 1**.
9. Request timeout: 300–900 seconds. CPU only during request.
10. Secrets: `SUPERQODE_UHP_API_KEY` from Secret Manager, exposed as env
    `SUPERQODE_UHP_API_KEY`. Do **not** add `GEMINI_API_KEY`, `GOOGLE_API_KEY`,
    or any other model key. The bind is Google `gemini-flash-latest`; callers
    send their own Gemini key as `X-Provider-Api-Key`.

The container reads that secret from the environment. It is deliberately not
passed as `--api-key`, which would publish the bearer in `/proc/1/cmdline`
where the harness's own shell tool can read it. The bind refuses to start
without it, so a missing secret fails the deploy instead of opening the host.

Then map `uhp.superqode.dev` on this service (Cloud Run domain mapping).
GoDaddy CNAME Host `uhp` → the record Google shows (`ghs.googlehosted.com.`
unless the console lists something else).

Anonymous catalog: `GET https://uhp.superqode.dev/v1/uhp`.
A harness turn needs `Authorization: Bearer …` and `X-Provider-Api-Key`
(the caller’s Gemini / Google AI Studio key).

## What the bind does with a caller's key

The key is written into the process environment for the length of one turn,
because LiteLLM resolves provider credentials from there. That environment is
shared by everything in the container, so turns carrying a caller key are
serialised: one runs at a time per instance. Throughput on this bind is one
turn at a time by design, and raising Cloud Run's concurrency does not change
that. It is not a correctness setting, so leave it at the default.

## Isolation between callers

Every session gets its own directory under the working directory instead of
sharing `/app`. The harness reads, writes and shells in that directory and
leaves its transcript there, so one directory for all callers would let each
of them read the others' work.

Two things this does **not** give you, worth knowing before the bind takes
traffic that matters:

- **One shared bearer.** Every caller presents the same token, so nothing
  binds a response or a session to who created it. A caller who learns another
  caller's response id can read it.
- **A container, not a sandbox.** The bound harness runs with `allow_shell`
  and `approval_profile: yolo`, so anyone who can run a turn can run commands
  in the container. That is the intended shape of a BYOK runner, and it is why
  no model key or other secret beyond the bearer belongs on this service.

## Iteration ceiling

`deploy/uhp/core.yaml` sets `max_iterations: 0`, which means unlimited: a turn
runs until the model stops. On a public bind with one instance, one caller can
hold that instance for as long as their key keeps paying. Set a bounded value
before the host takes untrusted traffic.
