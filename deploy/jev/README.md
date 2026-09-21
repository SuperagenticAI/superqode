# Jev Tool Routing on Cloud Run

You do not need to push the repository for a manual deployment. `gcloud builds
submit` uploads the current local checkout. Push first only when deploying from
a Git-connected Cloud Build trigger; for a release deployment, deploy the
reviewed release commit or tag rather than an uncommitted checkout.

This deployment hosts one stateless routing implementation through two
interfaces:

- `POST /v1/route-tools` for the Python SDK and other HTTP clients.
- `/mcp` for Streamable HTTP MCP clients.
- `GET /healthz` for an unauthenticated health check.

Every route except `/healthz` requires
`Authorization: Bearer $SUPERQODE_JEV_SERVICE_TOKEN`. The service stores no
prompts, tool definitions, provider credentials, or decisions. A stable
`turn_id` only lives in an in-memory TTL cache and may be lost when Cloud Run
scales or restarts; callers should accept a safe repeat decision.

## Prepare the project

Prerequisites are a billing-enabled Google Cloud project, the `gcloud` CLI,
and an account allowed to enable APIs and administer IAM, Artifact Registry,
Secret Manager, Cloud Build, and Cloud Run. Install or update the CLI from the
official Google Cloud SDK instructions before continuing.

Choose the project and region, authenticate the Google Cloud CLI, enable the
required APIs, and create the image repository and dedicated runtime identity:

```bash
export PROJECT_ID="your-google-cloud-project"
export REGION="europe-west1"

gcloud auth login
gcloud config set project "$PROJECT_ID"
gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com

gcloud artifacts repositories create cloud-run-source-deploy \
  --repository-format=docker \
  --location="$REGION" \
  --description="SuperQode Cloud Run images"

gcloud iam service-accounts create superqode-jev \
  --display-name="SuperQode Jev Tool Routing"
```

If the repository or service account already exists, keep it and continue.

## Create secrets

Create the secrets once. Add the TypeSafe key from a local file so it never
appears in shell history:

```bash
export TYPESAFE_KEY_FILE="/secure/path/to/typesafe-key.txt"

gcloud secrets create superqode-typesafe-api-key --replication-policy=automatic
gcloud secrets versions add superqode-typesafe-api-key \
  --data-file="$TYPESAFE_KEY_FILE"

export SERVICE_TOKEN_FILE="$(mktemp)"
chmod 600 "$SERVICE_TOKEN_FILE"
openssl rand -hex 32 > "$SERVICE_TOKEN_FILE"
gcloud secrets create superqode-jev-service-token --replication-policy=automatic
gcloud secrets versions add superqode-jev-service-token \
  --data-file="$SERVICE_TOKEN_FILE"
```

Grant the dedicated Cloud Run service identity access to only these two
secrets:

```bash
export RUNTIME_SA="superqode-jev@$PROJECT_ID.iam.gserviceaccount.com"

gcloud secrets add-iam-policy-binding superqode-typesafe-api-key \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding superqode-jev-service-token \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/secretmanager.secretAccessor"
```

The Cloud Build substitutions deliberately pin secret version `1`; update the
version substitutions when rotating credentials.

## Permit Cloud Build to deploy

Google Cloud projects may use either the legacy Cloud Build identity or the
Compute Engine default identity for builds. Resolve the actual identity instead
of assuming its name, then grant it permission to push the image, deploy Cloud
Run, and attach the dedicated runtime identity:

```bash
export BUILD_SA="$(gcloud builds get-default-service-account)"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" \
  --role="roles/artifactregistry.writer"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" \
  --role="roles/run.admin"
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:$BUILD_SA" \
  --role="roles/iam.serviceAccountUser"
```

## Build and deploy

Use `cloudbuild.jev.yaml` in a dedicated Cloud Build trigger, or submit it
manually:

```bash
gcloud builds submit \
  --config cloudbuild.jev.yaml \
  --region="$REGION" \
  --substitutions="_DEPLOY_REGION=$REGION"
```

The build uses its always-present build ID as the immutable image tag, so the
same file works for both manual submissions and Git triggers.

The service permits unauthenticated Cloud Run invocation because the
application bearer token protects its data endpoints. This avoids requiring
every third-party harness to implement Google identity tokens. Keep the token
secret and rotate it if exposed.

## Call it

Fetch the deployed URL and check the public health endpoint:

```bash
export SERVICE_URL="$(gcloud run services describe superqode-jev \
  --region="$REGION" \
  --format='value(status.url)')"

curl -fsS "$SERVICE_URL/healthz"
```

Keep `$SERVICE_TOKEN_FILE` local and use its value as the SDK token. All routing
and MCP requests require it:

```python
from superqode.jev_tools import JevToolRoutingClient

client = JevToolRoutingClient(
    "https://superqode-jev-PROJECT.REGION.run.app",
    token="...",
)
result = await client.route(
    "Fix the failing parser test",
    tools,
    turn_id="turn-123",
)
```

After the smoke test, remove the temporary token file or move it into your
normal secret-management system. Do not commit it.

## Add continuous deployment later

Once the release commit is pushed, create a Cloud Build repository trigger
that points to `cloudbuild.jev.yaml`. Configure the trigger substitutions if
the region, repository, service, or secret versions differ from the defaults.
The same build identity permissions above apply to triggered builds.

For a local-only deployment use `superqode serve jev`. For stdio MCP use
`superqode optimize mcp`.
