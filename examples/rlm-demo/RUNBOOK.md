# Release-health rules

The deployment feed is append-only and can contain retries, duplicate delivery
and malformed records. Reports follow these rules:

1. Ignore malformed records and count how many were ignored.
2. Group valid records by service and deployment ID.
3. For a deployment with several attempts, only its highest numbered attempt
   is authoritative. If that attempt appears more than once, keep the record
   with the latest timestamp.
4. A service is evaluated from its most recent deployment, ordered by the
   authoritative record's timestamp. Older successful deployments do not hide
   a newer failure.
5. A service is healthy when its authoritative status is `succeeded` and its
   duration is no more than 300 seconds.
6. An otherwise successful deployment over 300 seconds is unhealthy with the
   reason `slow`. Other unhealthy reasons use the authoritative status.
7. Healthy service names are sorted. The unhealthy mapping is emitted in
   service-name order so command-line output and tests remain deterministic.

The returned dictionary has four keys: `services`, `healthy`, `unhealthy`, and
`ignored_records`.

