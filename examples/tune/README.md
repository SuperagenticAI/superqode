# Free SystemOne Tune demo data

Original synthetic routing tickets for the `factory_route` pack.
No third-party corpus. Free to use in demos and tests.

- `factory-route-free.csv`: 70 labeled examples (35 development / 35 test)
- Tune deterministically reserves 8 of the 35 development rows for validation,
  leaving 27 search rows. Both subsets are optimizer-visible; the 35 test rows
  remain sealed until the final comparison.
- Columns: `id`, `state`, `label`, `split`, `rationale`
- Labels: `private`, `local`, `cheap`, `best`, `review`, `long-context`, `no-subscription`
