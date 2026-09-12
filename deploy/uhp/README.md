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
    `SUPERQODE_UHP_API_KEY`. Do **not** add `DEEPSEEK_API_KEY` or any other
    model key.

Then map `uhp.superqode.dev` on this service (Cloud Run domain mapping).
GoDaddy CNAME Host `uhp` → the record Google shows (`ghs.googlehosted.com.`
unless the console lists something else).

Anonymous catalog: `GET https://uhp.superqode.dev/v1/uhp`.
A harness turn needs `Authorization: Bearer …` and `X-Provider-Api-Key`
(the caller’s DeepSeek key).
