# QE Roles

SuperQode uses a role-based model where different AI agents specialize in specific types of quality engineering. This page explains each role and how they work together.

The default template ships with a comprehensive role catalog. Only roles with implementations can run, so leave unimplemented roles disabled or remove them.

---

## Role Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      QE ROLES                                │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              EXECUTION ROLES                         │    │
│  │  (Deterministic - Run Existing Tests)               │    │
│  │                                                      │    │
│  │  smoke_tester │ sanity_tester │ regression_tester   │    │
│  │  lint_tester                                      │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              DETECTION ROLES                         │    │
│  │  (AI-Powered Issue Discovery)                        │    │
│  │                                                      │    │
│  │  security │ api │ unit │ e2e │ performance          │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              HEURISTIC ROLE                          │    │
│  │  (Senior QE Comprehensive Review)                    │    │
│  │                                                      │    │
│  │                   fullstack                          │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Execution Roles

Execution roles run existing tests deterministically. They don't use AI for discovery-just execute what's already defined.

### smoke_tester

**Purpose:** Fast critical path validation

| Property | Value |
|----------|-------|
| Timeout | ~10 seconds |
| Depth | Minimal |
| Test Generation | No |
| Destructive | No |

**Focus Areas:**
- Application startup
- Critical endpoints respond
- Database connectivity
- Essential services available

**Usage:**
```bash
superqe run . -r smoke_tester
```

**When to Use:**
- Pre-commit hooks
- Deployment validation
- Quick health checks

---

### sanity_tester

**Purpose:** Quick core functionality verification

| Property | Value |
|----------|-------|
| Timeout | ~30 seconds |
| Depth | Shallow |
| Test Generation | No |
| Destructive | No |

**Focus Areas:**
- Core user flows work
- Recent changes don't break basics
- Main features functional

**Usage:**
```bash
superqe run . -r sanity_tester
```

**When to Use:**
- After code changes
- Before merging PRs
- Quick validation

---

### regression_tester

**Purpose:** Full test suite execution

| Property | Value |
|----------|-------|
| Timeout | Varies (full suite) |
| Depth | Full |
| Test Generation | No |
| Destructive | No |

**Focus Areas:**
- Complete test suite
- All existing tests pass
- Flaky test detection

**Usage:**
```bash
superqe run . -r regression_tester
```

**When to Use:**
- Nightly builds
- Pre-release validation
- Major changes

---

### lint_tester

**Purpose:** Fast static linting across detected languages

| Property | Value |
|----------|-------|
| Timeout | Varies by repo size |
| Depth | Static analysis |
| Test Generation | No |
| Destructive | No |

**Focus Areas:**
- Style and correctness issues
- Lint rule violations
- Language-specific best practices

**Usage:**
```bash
superqe run . -r lint_tester
```

**When to Use:**
- Always-on checks in CI
- Pre-commit lint validation
- Early signal on AI-generated code

---

## Detection Roles

Detection roles use AI to analyze code and discover issues. They can generate tests on demand.

### security_tester

**Purpose:** Security vulnerability detection

| Property | Value |
|----------|-------|
| Timeout | 5-10 minutes |
| Depth | Deep |
| Test Generation | Yes |
| Destructive | Simulated attacks |

**Focus Areas:**

| Category | Examples |
|----------|----------|
| Injection | SQL, XSS, Command, LDAP |
| Authentication | Bypass, weak passwords, session |
| Authorization | Privilege escalation, IDOR |
| Data Exposure | Secrets, PII, sensitive data |
| Configuration | Insecure defaults, debug mode |

**Usage:**
```bash
superqe run . -r security_tester
```

**Typical Findings:**
```
[CRITICAL] SQL Injection in /api/users
[HIGH] Hardcoded API key in config.py
[HIGH] Missing authentication on /admin
[MEDIUM] Weak password requirements
[LOW] Verbose error messages in production
```

---

### api_tester

**Purpose:** API contract and security testing

| Property | Value |
|----------|-------|
| Timeout | 5-10 minutes |
| Depth | Thorough |
| Test Generation | Yes |
| Destructive | Fuzzing |

**Focus Areas:**

| Category | Examples |
|----------|----------|
| Schema | Request/response validation |
| Authentication | Token handling, OAuth flows |
| Input Validation | Type checking, boundaries |
| Error Handling | Proper error codes, messages |
| Rate Limiting | Throttling, quotas |

**Usage:**
```bash
superqe run . -r api_tester
```

**Typical Findings:**
```
[HIGH] Missing input validation on POST /users
[HIGH] No rate limiting on authentication endpoint
[MEDIUM] Inconsistent error response format
[MEDIUM] Missing CORS headers
[LOW] API version not in response headers
```

---

### unit_tester

**Purpose:** Test coverage and unit test gaps

| Property | Value |
|----------|-------|
| Timeout | 5-10 minutes |
| Depth | Thorough |
| Test Generation | Yes |
| Destructive | No |

**Focus Areas:**

| Category | Examples |
|----------|----------|
| Coverage Gaps | Untested functions, branches |
| Edge Cases | Boundaries, null handling |
| Error Paths | Exception handling |
| Mocking | External dependency handling |

**Usage (Enterprise):**
```bash
superqe run . -r unit_tester --generate
```

**Typical Findings:**
```
[MEDIUM] No tests for UserService.delete()
[MEDIUM] Edge case not tested: empty input
[LOW] Missing null check test for config loader
[LOW] Error path not covered in payment module
```

---

### e2e_tester

**Purpose:** End-to-end workflow testing

| Property | Value |
|----------|-------|
| Timeout | 10-20 minutes |
| Depth | Full workflows |
| Test Generation | Yes |
| Destructive | Limited |

**Focus Areas:**

| Category | Examples |
|----------|----------|
| User Journeys | Complete flows work |
| Integration | Services communicate correctly |
| Data Flow | Data persists across steps |
| State | Application state management |

**Usage:**
```bash
superqe run . -r e2e_tester
```

**Typical Findings:**
```
[HIGH] Checkout flow fails on payment step
[MEDIUM] User session lost after page refresh
[MEDIUM] Form data not persisted on back navigation
[LOW] Inconsistent loading states
```

---

### performance_tester

**Purpose:** Performance bottleneck detection

| Property | Value |
|----------|-------|
| Timeout | 10-30 minutes |
| Depth | Profiling |
| Test Generation | Benchmarks |
| Destructive | Stress testing |

**Focus Areas:**

| Category | Examples |
|----------|----------|
| Query Performance | N+1 queries, slow queries |
| Memory | Leaks, excessive allocation |
| Complexity | O(n²) algorithms, deep nesting |
| Concurrency | Race conditions, deadlocks |
| Resource Usage | CPU, I/O, network |

**Usage:**
```bash
superqe run . -r performance_tester
```

**Typical Findings:**
```
[HIGH] N+1 query in user list endpoint
[HIGH] Memory leak in connection pool
[MEDIUM] O(n²) complexity in search function
[MEDIUM] Unoptimized database index
[LOW] Synchronous I/O in async context
```

---

## Heuristic Role

### fullstack

**Purpose:** Senior QE comprehensive review

| Property | Value |
|----------|-------|
| Timeout | 10-15 minutes |
| Depth | Holistic |
| Test Generation | Recommendations |
| Destructive | No |

**Focus Areas:**
- Cross-cutting concerns
- Architecture issues
- Trade-off awareness
- Risk prioritization
- Overall quality assessment

**Usage:**
```bash
superqe run . -r fullstack
```

**Typical Output:**
```
[SUMMARY] Overall Quality Assessment

Strengths:
- Good test coverage for core functionality
- Consistent error handling patterns
- Well-structured API design

Concerns:
- Security testing gaps in admin features
- Performance optimization needed for list endpoints
- Missing integration tests for payment flow

Priority Recommendations:
1. [CRITICAL] Address SQL injection in user search
2. [HIGH] Add authentication to admin endpoints
3. [MEDIUM] Optimize N+1 queries in product listing

Production Readiness: NOT READY
Blocking Issues: 2
```

---

## Running Roles

### Single Role

```bash
superqe run . -r security_tester
```

### Multiple Roles

```bash
superqe run . -r security_tester -r api_tester -r fullstack
```

### All Detection Roles

```bash
superqe run . --mode deep
```

### Quick Scan (Selected Roles)

```bash
superqe run . --mode quick
```

Quick scan runs a subset of roles optimized for speed.

---

## Role Configuration

### Custom Role Settings

```yaml
team:
  modes:
    qe:
      roles:
        security_tester:
          description: "Security vulnerability detection"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: true
          job_description: |
            You are a senior security engineer specializing in:
            - OWASP Top 10 vulnerability detection
            - SQL injection and XSS prevention
            - Authentication and authorization flaws
            - Sensitive data exposure analysis

            Focus on findings that could be exploited in production.
            Prioritize critical and high severity issues.
```

### Enable/Disable Roles

```bash
# Enable a role
superqode config enable-role qe.performance_tester

# Disable a role
superqode config disable-role qe.e2e_tester
```

### View Role Configuration

```bash
superqode roles info qe.security_tester
```

---

## Cross-Model Validation

For higher confidence, run the same role with different models:

```yaml
team:
  modes:
    qe:
      roles:
        security_tester:
          cross_validation:
            enabled: true
            exclude_same_model: true
```

This runs the role with multiple models and cross-validates findings.

---

## Expert Prompts (Enterprise)

Expert prompt packs are available in SuperQode Enterprise. OSS ignores these fields.

---

## Role Specializations

### Specialized QE Agents

SuperQode includes additional specialized agents:

| Agent | Focus |
|-------|-------|
| `AccessibilityAlly` | Accessibility (a11y) testing |
| `CodeComplexity` | Code complexity analysis |
| `ContractTester` | API contract testing |
| `DeploymentReadiness` | Deployment validation |
| `MutationTester` | Mutation testing |
| `RequirementsValidator` | Requirements validation |
| `VisualTester` | Visual regression testing |

---

## Next Steps

- [Quality Reports](qr.md) - Understanding QR output
- [Allow Suggestions](suggestions.md) - Fix demonstration workflow
- [Role Configuration](../configuration/team.md) - Configure QE roles
