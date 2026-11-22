# Take your Factory to your environment

The macOS app is an authoring and review client. Customers can operate a Factory
through the SuperQode CLI, MCP or their own supervised worker without keeping
the app open or depending on a SuperQode-hosted control plane.

## Export editable files

Use **Export → Portable package** in Factory Studio, then **Save a copy**. The
same engine operation is available without the app:

```sh
sq factory export --project /path/to/application
```

The ZIP contains editable declared sources under `factory/`, a resolved
snapshot, a checksum manifest and operating instructions. It does not include
a live queue, release approval, credential stores, runtime installer or application
backup. Declared context and evaluator code may be private; review before sharing.

Restore or clone the application separately, inspect the package in a new
folder, and copy its Factory sources while preserving their paths. Install the
reviewed engine build and dependencies, bind model access and credentials on the
target, and run validation and protected host checks before preparing new work.
An engine version number alone does not establish identical implementation;
the manifest includes a Factory-module fingerprint for build-provenance checks.

macOS and Linux workers require their supported protected isolation backends.
A copied definition does not establish target-host readiness or customer quality.
Existing human gates, budgets, protected evaluators and release authority remain
part of the operating contract.

## Use another platform

The files are editable and may be converted for another platform. Their syntax,
harness tools, workflows, evaluator isolation and permission policies follow
SuperQode's execution contracts. Another platform needs an adapter and new
execution/acceptance validation; this export does not claim universal or
vendor-specific compatibility. Preserve the original controls when evaluating
such a conversion.
