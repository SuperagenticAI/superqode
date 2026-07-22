# Contextual Policy and Credential-Safe Execution

SuperQode applies one explainable policy engine across harness requests, responses, tool calls, tool results, and harness promotion. Policies are repository-owned YAML and remain useful without a hosted control plane.

## Initialize a project policy

```bash
sq policy init
sq policy show
```

This creates `.superqode/policy.yaml` with builder-safe defaults: model-spawned shells do not inherit secret-looking environment variables, untrusted network destinations are denied, and models cannot send credential-bearing HTTP headers directly.

WorkOrders enable the secret-filtering and strict-network defaults even before a project policy exists. A project policy makes those choices explicit and extends them to ordinary HarnessSpec runs.

## Policy layers

Layers are evaluated in this order:

1. organization policy from `SUPERQODE_ORG_POLICY`
2. `.superqode/policy.yaml` in the repository
3. the active HarnessSpec permission rules
4. WorkOrder policy stored in `metadata.governance`
5. an optional session policy

Every matching rule is retained in the decision trace. `deny` overrides `ask`, and `ask` overrides `allow`, so a project or session cannot weaken an organization denial.

```yaml
version: 1

defaults:
  request: allow
  response: allow
  tool_result: allow

guardrails:
  shell_env: filter-secrets
  network_strict: true
  allowed_hosts:
    - api.internal.example
  block_model_credentials: true

rules:
  - id: deny-critical-tools
    phases: [tool_call]
    action: deny
    risks: [critical]
    message: Critical operations require a different controlled worker pool.

  - id: internal-api-only
    phases: [tool_call]
    action: allow
    tools: [fetch, web_fetch]
    hosts: [api.internal.example]

  - id: protect-promotion
    phases: [promotion]
    action: deny
    arguments:
      candidate_id: [experimental-*]
```

Rules can match `phases`, tool-name globs, tool groups, destination hosts, risks, providers, runtimes, and argument globs.

## Explain without executing

```bash
sq policy explain tool_call \
  --tool fetch \
  --tool-group network \
  --host api.internal.example \
  --risk medium

sq policy explain promotion \
  --arg candidate_id=experimental-routing \
  --json
```

These commands are read-only. Runtime policy decisions are also written as harness events, while WorkOrder budget decisions remain available through `sq work policy`.

## Host-bound credentials

Credential bindings contain a symbolic name, a secret source, allowed destination hosts, and the header format. Literal secrets are not supported in policy files.

```yaml
credentials:
  github-api:
    source: env:GITHUB_TOKEN
    hosts: [api.github.com]
    header: Authorization
    prefix: Bearer

  internal-api:
    source: auth:internal-provider
    hosts: [api.internal.example]
    header: X-API-Key
    prefix: ""
```

The model calls a supported HTTP tool with the binding name:

```json
{
  "url": "https://api.github.com/user",
  "credential": "github-api"
}
```

SuperQode verifies the URL host, resolves the secret at execution time, injects the header behind the model boundary, and records only the binding name, host, header name, and source type. The secret is absent from prompts, tool arguments visible to the model, policy output, and governance evidence.

The first brokered tools are `fetch` and `web_fetch`. Shell commands receive a filtered environment in governed WorkOrders; use a dedicated tool binding instead of exposing a secret to `bash`.

## Enforcement boundaries

- Built-in and bridged SuperQode tools use the same governed execution wrapper.
- HarnessKernel enforces request and response phases for normal harness runs.
- WorkOrders add their own policy layer and secure defaults.
- A sandbox remains necessary for operating-system-level filesystem and network confinement.
- External native runtimes can enforce their own additional rules; SuperQode never interprets a runtime's weaker result as permission to override an organization denial.

