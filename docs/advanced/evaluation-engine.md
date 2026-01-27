<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode.png" alt="SuperQode Banner" />

# Evaluation Engine

The evaluation engine provides a framework for testing SuperQode's QE capabilities through structured scenarios and behavior verification. This is used for benchmarking, regression testing, and validating QE role effectiveness.

---

## Overview

The evaluation engine (`evaluation/`) enables systematic testing of:

- QE role effectiveness
- Finding accuracy
- Fix quality
- False positive rates
- Performance benchmarks

```
┌─────────────────────────────────────────────────────────────┐
│                    EVALUATION ENGINE                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Scenarios                                                   │
│       │                                                      │
│       ▼                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │  Behaviors  │ ── │   Engine    │ ── │  Adapters   │     │
│  │ (Expected)  │    │ (Runner)    │    │ (Output)    │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                            │                                 │
│                            ▼                                 │
│                     ┌─────────────┐                         │
│                     │   Results   │                         │
│                     │  (Metrics)  │                         │
│                     └─────────────┘                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Components

### Scenarios

Scenarios (`evaluation/scenarios.py`) define test cases:

```python
@dataclass
class Scenario:
    id: str                      # Unique identifier
    name: str                    # Human-readable name
    description: str             # What this tests
    setup: SetupConfig           # How to prepare
    target_path: str             # What to analyze
    roles: list[str]             # Roles to run
    expected_behaviors: list[Behavior]  # What should happen
    timeout: int                 # Max duration
```

**Example Scenario:**

```yaml
scenarios:
  - id: sql-injection-basic
    name: "SQL Injection Detection"
    description: "Verify security_tester finds SQL injection"
    setup:
      template: vulnerable-flask-app
      inject_vulnerabilities:
        - type: sql_injection
          location: src/api.py
          line: 45
    target_path: src/
    roles:
      - security_tester
    expected_behaviors:
      - type: finding
        severity: critical
        pattern: "SQL injection"
        file: src/api.py
    timeout: 120
```

### Behaviors

Behaviors (`evaluation/behaviors.py`) define expected outcomes:

| Behavior Type | Description | Validation |
|---------------|-------------|------------|
| **Finding** | Should detect specific issue | Pattern match in findings |
| **No Finding** | Should NOT detect (false positive test) | Absence check |
| **Fix** | Should suggest valid fix | Fix verification |
| **Test Generation** | Should generate test | File existence |
| **Performance** | Should complete within time | Duration check |

```python
@dataclass
class FindingBehavior(Behavior):
    type: str = "finding"
    severity: str          # critical, high, medium, low
    pattern: str           # Regex to match in finding
    file: str | None       # Expected file
    line: int | None       # Expected line

@dataclass  
class PerformanceBehavior(Behavior):
    type: str = "performance"
    max_duration_seconds: int
    max_token_usage: int | None
```

### Engine

The engine (`evaluation/engine.py`) runs evaluations:

```python
class EvaluationEngine:
    async def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        # Setup test environment
        workspace = await self.setup_workspace(scenario.setup)

        # Run QE session
        qe_result = await self.run_qe(
            workspace=workspace,
            roles=scenario.roles,
            timeout=scenario.timeout
        )

        # Verify behaviors
        behavior_results = []
        for behavior in scenario.expected_behaviors:
            result = await self.verify_behavior(behavior, qe_result)
            behavior_results.append(result)

        # Cleanup
        await workspace.cleanup()

        return ScenarioResult(
            scenario_id=scenario.id,
            passed=all(r.passed for r in behavior_results),
            behavior_results=behavior_results,
            qe_result=qe_result
        )
```

### Adapters

Adapters (`evaluation/adapters.py`) format output for different systems:

| Adapter | Output Format | Use Case |
|---------|---------------|----------|
| **JSON** | Raw JSON | Programmatic access |
| **JUnit XML** | JUnit format | CI/CD integration |
| **Markdown** | Readable report | Documentation |
| **Console** | Colored terminal | Local development |

---

## Running Evaluations

### Run All Scenarios

```bash
superqode eval run --all
```

### Run Specific Scenario

```bash
superqode eval run --scenario sql-injection-basic
```

### Run Category

```bash
superqode eval run --category security
```

### Output Formats

```bash
# Console output (default)
superqode eval run --all

# JSON output
superqode eval run --all --format json > results.json

# JUnit XML (for CI)
superqode eval run --all --format junit > results.xml
```

---

## Scenario Templates

Pre-built vulnerable code templates for testing:

| Template | Vulnerabilities | Roles Tested |
|----------|-----------------|--------------|
| `vulnerable-flask-app` | SQL injection, XSS, auth bypass | security_tester |
| `buggy-api` | Missing validation, error handling | api_tester |
| `untested-module` | Low coverage, edge cases | unit_tester |
| `slow-queries` | N+1, missing indexes | performance_tester |

### Creating Custom Templates

```yaml
# .superqode/eval-templates/my-template.yaml
template:
  name: my-custom-template
  base: python-fastapi
  files:
    - path: src/vulnerable.py
      content: |
        def unsafe_query(user_id):
            # SQL injection vulnerability
            return db.execute(f"SELECT * FROM users WHERE id = {user_id}")
```

---

## Metrics

Evaluation produces these metrics:

| Metric | Description | Target |
|--------|-------------|--------|
| **Detection Rate** | % of issues found | > 90% |
| **False Positive Rate** | % of incorrect findings | < 10% |
| **Fix Accuracy** | % of valid fixes | > 80% |
| **Time to Detection** | Seconds to first finding | < 30s |
| **Token Efficiency** | Findings per 1K tokens | > 0.5 |

### Metric Calculation

```python
metrics = EvaluationMetrics(
    total_scenarios=len(scenarios),
    passed_scenarios=len([s for s in results if s.passed]),
    detection_rate=true_positives / total_expected,
    false_positive_rate=false_positives / total_findings,
    avg_duration=sum(r.duration for r in results) / len(results),
    total_tokens=sum(r.tokens_used for r in results)
)
```

---

## CI/CD Integration

### GitHub Actions

```yaml
- name: Run SuperQode Evaluation
  run: |
    superqode eval run --all --format junit > eval-results.xml

- name: Upload Results
  uses: actions/upload-artifact@v3
  with:
    name: evaluation-results
    path: eval-results.xml

- name: Publish Test Results
  uses: mikepenz/action-junit-report@v3
  with:
    report_paths: eval-results.xml
```

### Benchmark Comparison

```bash
# Save baseline
superqode eval run --all --format json > baseline.json

# Compare after changes
superqode eval compare baseline.json current.json
```

---

## Configuration

```yaml
evaluation:
  # Scenarios directory
  scenarios_dir: .superqode/eval-scenarios

  # Templates directory  
  templates_dir: .superqode/eval-templates

  # Parallelism
  max_parallel: 4

  # Timeout multiplier (for slow machines)
  timeout_multiplier: 1.5

  # Results storage
  results_dir: .superqode/eval-results

  # Thresholds for pass/fail
  thresholds:
    detection_rate: 0.9
    false_positive_rate: 0.1
    fix_accuracy: 0.8
```

---

## Extending the Engine

### Adding Custom Behaviors

```python
# evaluation/behaviors.py

@dataclass
class CustomBehavior(Behavior):
    type: str = "custom"
    custom_check: str

    def verify(self, qe_result: QEResult) -> BehaviorResult:
        # Custom verification logic
        passed = self.run_custom_check(qe_result)
        return BehaviorResult(passed=passed)
```

### Adding Custom Adapters

```python
# evaluation/adapters.py

class CustomAdapter(OutputAdapter):
    def format(self, results: list[ScenarioResult]) -> str:
        # Custom formatting logic
        return custom_formatted_output
```

---

## Related Documentation

- [Architecture Overview](architecture.md) - System architecture
- [QE Roles](../concepts/roles.md) - Role definitions
- [CI/CD Integration](../integration/cicd.md) - Pipeline integration
