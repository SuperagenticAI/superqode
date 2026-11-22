# Authenticated issue and monitoring intake

`sq factory intake` admits customer-owned inbound events into the same pinned
WorkOrder engine as Factory Studio. Receiving an event queues work; it does not
start agents, approve a human gate, apply a patch or deploy software.

Opt in through the saved Factory definition:

```yaml
orchestration:
  intake:
    enabled: true
    max_pending: 8
    max_per_hour: 20
    sources:
      github:
        secret_env: SUPERQODE_FACTORY_GITHUB_SECRET
        scope: owner/repository
        actions: [opened, reopened]
      linear:
        secret_env: SUPERQODE_FACTORY_LINEAR_SECRET
        scope: ORGANIZATION_ID
        actions: [create]
      monitor:
        secret_env: SUPERQODE_FACTORY_MONITOR_SECRET
        scope: billing-service
        actions: [incident]
```

Preserve the Factory's stages, checks, budgets and governance alongside this
fragment. Bind each secret through the declared environment variable; never
put its value into the definition. Receivers require at least 32 bytes of secret
material. Use a separate high-entropy secret for each source.

## Delivery contracts

- GitHub accepts `issues` events in the configured repository and action set.
  It verifies raw-body HMAC-SHA256 using `X-Hub-Signature-256` and records
  `X-GitHub-Delivery`. Pull-request payloads are refused.
  [GitHub signature contract](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).
- Linear accepts `Issue` events in the configured organization and action set.
  It verifies `Linear-Signature`, `Linear-Delivery` and the signed body's
  millisecond `webhookTimestamp`. Unknown deliveries must be within 60 seconds.
  [Linear webhook contract](https://linear.app/developers/webhooks).
- Monitoring uses a customer adapter emitting a JSON object with `service`,
  `action`, `event_id`, `title`, optional `description` and a UNIX-seconds
  `timestamp`. Sign the exact bytes with HMAC-SHA256 and send
  `X-SuperQode-Signature: sha256=HEX_DIGEST`. Unknown events require a timestamp
  within 60 seconds. This is a generic envelope, not a provider-specific Sentry
  integration.

All sources verify signatures before parsing or persisting events. Comparisons
are constant-time. The receiver bounds payloads to 64 KB, task titles to 1 KB
and descriptions to 8 KB. It rejects duplicate JSON keys, malformed shapes,
unsupported actions and source-scope changes. Common inline credential patterns
in task text are refused; this is not a general secret scanner.

The durable ledger deduplicates both delivery identifiers and exact payload
fingerprints. Changing only an unsigned delivery header cannot create a second
job. A known authenticated retry reuses its original submission receipt even
after application drift; it does not restart the run. Freshness applies to new
admissions. Interrupted submissions preserve their exact compiled contract for
an idempotent retry, never an implicit recompile against changed sources.

Pending-work and hourly admission limits are independent of each WorkOrder's
execution budget. The local intake ledger has a 1,000-event bound and fails
closed when full. Back it up with runtime checkpoints. There is no automatic
evidence pruning or infinite issue-to-experiment recursion.

## Run the receiver

```sh
sq factory intake serve --project /srv/customer/project --port 8767
```

It binds to loopback only. Put it behind a customer-operated HTTPS reverse proxy
that preserves the raw body and signature headers. Routes are
`/factory/webhook/github`, `/factory/webhook/linear` and
`/factory/webhook/monitor`. Source configuration and endpoint registration with
the external provider are explicit operator tasks. No webhook, external account
or service is installed by opening Studio.

For an existing customer listener that passes project-local payload/header files:

```sh
sq factory intake receive --project /srv/customer/project --source github \
  --body .superqode/incoming/body.json --headers .superqode/incoming/headers.json
```

The files must contain the exact received raw body and a JSON object of headers.
Start a normal bounded Factory worker separately after reviewing the queued
work and source policy. Human waits and signed release authority remain intact.
