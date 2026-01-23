"""
Core QE Skills - Essential quality engineering skills.

Skills included:
- testability-scoring: Assess code testability
- tdd-london-chicago: TDD methodology guidance
- api-testing-patterns: API testing best practices
- accessibility-testing: A11y testing patterns
- shift-left-testing: Early testing strategies
- chaos-engineering-resilience: Chaos testing
- visual-testing-advanced: Visual regression
- compliance-testing: Regulatory compliance
"""

from typing import Any, Dict, List, Optional
from pathlib import Path
import ast

from .base import Skill, SkillConfig, SkillResult


class TestabilityScoring(Skill):
    """
    Testability Scoring Skill.

    Assesses code testability before writing tests,
    identifying areas that need refactoring for better testing.
    """

    NAME = "testability-scoring"
    DISPLAY_NAME = "Testability Scoring"
    DESCRIPTION = "Pre-test code testability assessment"
    CATEGORY = "analysis"
    TAGS = ["testability", "code-quality", "pre-test"]

    # Scoring factors
    FACTORS = {
        "cyclomatic_complexity": {"weight": 0.2, "ideal": 5, "max": 20},
        "dependency_count": {"weight": 0.15, "ideal": 3, "max": 10},
        "method_length": {"weight": 0.15, "ideal": 20, "max": 50},
        "nesting_depth": {"weight": 0.15, "ideal": 2, "max": 5},
        "global_state": {"weight": 0.15, "ideal": 0, "max": 3},
        "side_effects": {"weight": 0.1, "ideal": 0, "max": 5},
        "documentation": {"weight": 0.1, "ideal": 1, "max": 1},
    }

    async def execute(self, **kwargs) -> SkillResult:
        """
        Score code testability.

        Args:
            file_path: Path to file to analyze
            code: Code string to analyze (alternative)

        Returns:
            SkillResult with testability score
        """
        file_path = kwargs.get("file_path")
        code = kwargs.get("code")

        if file_path:
            code = Path(file_path).read_text()

        if not code:
            return SkillResult(skill_name=self.NAME, success=False, errors=["No code provided"])

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return SkillResult(skill_name=self.NAME, success=False, errors=[f"Syntax error: {e}"])

        # Analyze testability
        scores = {}
        recommendations = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_score = self._score_function(node, code)
                scores[node.name] = func_score

                if func_score["overall"] < 0.7:
                    recommendations.append(
                        f"Function '{node.name}' has low testability ({func_score['overall']:.2f}). "
                        f"Consider refactoring."
                    )

        # Calculate overall score
        overall = sum(s["overall"] for s in scores.values()) / len(scores) if scores else 0

        return SkillResult(
            skill_name=self.NAME,
            success=True,
            output=f"Testability Score: {overall:.2f}/1.00",
            metrics={
                "overall_score": overall,
                "function_scores": scores,
                "recommendations": recommendations,
            },
        )

    def _score_function(self, node: ast.FunctionDef, code: str) -> Dict[str, float]:
        """Score a single function."""
        scores = {}

        # Cyclomatic complexity
        complexity = self._calculate_complexity(node)
        scores["complexity"] = self._normalize(complexity, self.FACTORS["cyclomatic_complexity"])

        # Method length
        lines = len(code.splitlines())
        scores["length"] = self._normalize(lines, self.FACTORS["method_length"])

        # Nesting depth
        depth = self._calculate_nesting(node)
        scores["nesting"] = self._normalize(depth, self.FACTORS["nesting_depth"])

        # Calculate overall
        overall = sum(scores.values()) / len(scores)
        scores["overall"] = overall

        return scores

    def _calculate_complexity(self, node: ast.AST) -> int:
        """Calculate cyclomatic complexity."""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, (ast.And, ast.Or)):
                complexity += 1
        return complexity

    def _calculate_nesting(self, node: ast.AST, depth: int = 0) -> int:
        """Calculate max nesting depth."""
        max_depth = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.With, ast.Try)):
                child_depth = self._calculate_nesting(child, depth + 1)
                max_depth = max(max_depth, child_depth)
            else:
                child_depth = self._calculate_nesting(child, depth)
                max_depth = max(max_depth, child_depth)
        return max_depth

    def _normalize(self, value: float, factor: Dict[str, Any]) -> float:
        """Normalize a value to 0-1 score (1 is best)."""
        ideal = factor["ideal"]
        max_val = factor["max"]

        if value <= ideal:
            return 1.0
        elif value >= max_val:
            return 0.0
        else:
            return 1.0 - (value - ideal) / (max_val - ideal)

    def get_prompt(self) -> str:
        return """You are an expert in code testability analysis.

Evaluate code for testability by considering:
1. Cyclomatic complexity (lower is better)
2. Dependency injection (prefer constructor injection)
3. Pure functions (no side effects)
4. Single responsibility (one purpose per function)
5. Minimal global state
6. Clear interfaces

Provide specific recommendations for improving testability."""


class TDDLondonChicago(Skill):
    """
    TDD London/Chicago Skill.

    Guides TDD implementation using both London (mockist)
    and Chicago (classicist) schools.
    """

    NAME = "tdd-london-chicago"
    DISPLAY_NAME = "TDD London/Chicago"
    DESCRIPTION = "TDD methodology guidance for both schools"
    CATEGORY = "methodology"
    TAGS = ["tdd", "testing", "methodology", "best-practices"]

    async def execute(self, **kwargs) -> SkillResult:
        """
        Provide TDD guidance.

        Args:
            style: "london" or "chicago"
            feature: Feature to implement
            context: Additional context

        Returns:
            SkillResult with TDD guidance
        """
        style = kwargs.get("style", "chicago")
        feature = kwargs.get("feature", "")

        if style == "london":
            guidance = self._london_style_guidance(feature)
        else:
            guidance = self._chicago_style_guidance(feature)

        return SkillResult(
            skill_name=self.NAME, success=True, output=guidance, metrics={"style": style}
        )

    def _london_style_guidance(self, feature: str) -> str:
        return f"""# TDD London Style (Mockist) for: {feature}

## Approach
The London school focuses on behavior and uses mocks extensively.

## RED Phase
1. Write a failing test that specifies expected behavior
2. Mock all collaborators
3. Focus on the unit's interaction with dependencies

## GREEN Phase
1. Implement minimum code to pass
2. Focus on correct message passing
3. Don't worry about implementation details

## REFACTOR Phase
1. Improve design while tests pass
2. Extract interfaces if needed
3. Consider dependency injection

## Key Principles
- Test behavior, not implementation
- Mock external dependencies
- Verify interactions
- One mock per test (usually)

## Example Pattern
```python
def test_should_notify_when_order_placed():
    # Arrange
    notifier = Mock(spec=Notifier)
    order_service = OrderService(notifier=notifier)

    # Act
    order_service.place_order(order)

    # Assert
    notifier.send.assert_called_once_with(order.customer_email)
```
"""

    def _chicago_style_guidance(self, feature: str) -> str:
        return f"""# TDD Chicago Style (Classicist) for: {feature}

## Approach
The Chicago school focuses on state and uses real objects.

## RED Phase
1. Write a failing test with real assertions
2. Test the final state/outcome
3. Use real collaborators when possible

## GREEN Phase
1. Implement the simplest thing that works
2. Let the design emerge
3. Triangulate with more tests

## REFACTOR Phase
1. Remove duplication
2. Improve naming
3. Extract methods/classes

## Key Principles
- Test state, not interactions
- Use real objects (not mocks)
- Triangulate to generalize
- Let design emerge from tests

## Example Pattern
```python
def test_order_total_includes_tax():
    # Arrange
    order = Order()
    order.add_item(Product("Widget", price=100))

    # Act
    total = order.calculate_total(tax_rate=0.1)

    # Assert
    assert total == 110  # Price + 10% tax
```
"""

    def get_prompt(self) -> str:
        return """You are a TDD expert familiar with both London and Chicago schools.

London School (Mockist):
- Focus on behavior and interactions
- Heavy use of mocks
- Outside-in development
- Verify messages between objects

Chicago School (Classicist):
- Focus on state and outcomes
- Use real objects
- Inside-out development
- Assert on final state

Guide the user through RED/GREEN/REFACTOR cycles."""


class APITestingPatterns(Skill):
    """
    API Testing Patterns Skill.

    Provides patterns for comprehensive API testing.
    """

    NAME = "api-testing-patterns"
    DISPLAY_NAME = "API Testing Patterns"
    DESCRIPTION = "API testing best practices and patterns"
    CATEGORY = "testing"
    TAGS = ["api", "testing", "rest", "patterns"]

    async def execute(self, **kwargs) -> SkillResult:
        """
        Provide API testing patterns.

        Args:
            endpoint: API endpoint to test
            method: HTTP method
            pattern: Specific pattern to apply

        Returns:
            SkillResult with testing patterns
        """
        endpoint = kwargs.get("endpoint", "/api/resource")
        method = kwargs.get("method", "GET")

        patterns = self._get_patterns(endpoint, method)

        return SkillResult(
            skill_name=self.NAME,
            success=True,
            output=patterns,
            metrics={"endpoint": endpoint, "method": method},
        )

    def _get_patterns(self, endpoint: str, method: str) -> str:
        return f"""# API Testing Patterns for {method} {endpoint}

## 1. Happy Path Testing
Test successful scenarios with valid inputs.

## 2. Validation Testing
- Missing required fields
- Invalid data types
- Boundary values
- Malformed requests

## 3. Authentication/Authorization
- Missing auth token
- Invalid token
- Expired token
- Insufficient permissions

## 4. Error Handling
- 400 Bad Request
- 401 Unauthorized
- 403 Forbidden
- 404 Not Found
- 500 Internal Server Error

## 5. Performance Testing
- Response time < 200ms
- Concurrent requests
- Rate limiting

## 6. Contract Testing
- Schema validation
- Field presence
- Data types
- Nullable fields

## Example Test Structure
```python
class Test{method.capitalize()}{endpoint.replace("/", "_").title()}:

    def test_success_returns_200(self, client):
        response = client.{method.lower()}("{endpoint}")
        assert response.status_code == 200

    def test_missing_auth_returns_401(self, client):
        response = client.{method.lower()}("{endpoint}", headers={{}})
        assert response.status_code == 401

    def test_invalid_input_returns_400(self, client):
        response = client.{method.lower()}("{endpoint}", json={{"invalid": True}})
        assert response.status_code == 400
```
"""

    def get_prompt(self) -> str:
        return """You are an API testing expert.

Key areas to cover:
1. Happy path scenarios
2. Error handling (4xx, 5xx)
3. Input validation
4. Authentication/authorization
5. Rate limiting
6. Pagination
7. Caching headers
8. Content negotiation

Provide specific test cases for each endpoint."""


class AccessibilityTesting(Skill):
    """
    Accessibility Testing Skill.

    Guides A11y testing for WCAG compliance.
    """

    NAME = "accessibility-testing"
    DISPLAY_NAME = "Accessibility Testing"
    DESCRIPTION = "A11y testing patterns for WCAG compliance"
    CATEGORY = "testing"
    TAGS = ["accessibility", "a11y", "wcag", "testing"]

    async def execute(self, **kwargs) -> SkillResult:
        """
        Provide accessibility testing guidance.

        Args:
            level: WCAG level (A, AA, AAA)
            component: Component type to test

        Returns:
            SkillResult with A11y guidance
        """
        level = kwargs.get("level", "AA")
        component = kwargs.get("component", "form")

        guidance = self._get_guidance(level, component)

        return SkillResult(
            skill_name=self.NAME,
            success=True,
            output=guidance,
            metrics={"level": level, "component": component},
        )

    def _get_guidance(self, level: str, component: str) -> str:
        return f"""# Accessibility Testing for {component} (WCAG {level})

## Essential Checks

### 1. Keyboard Navigation
- All interactive elements focusable
- Logical focus order
- No keyboard traps
- Visible focus indicators

### 2. Screen Reader Compatibility
- Proper ARIA labels
- Meaningful alt text
- Correct heading structure
- Live regions for dynamic content

### 3. Color and Contrast
- 4.5:1 contrast for text (AA)
- 3:1 contrast for large text
- Information not conveyed by color alone

### 4. Form Accessibility
- Labels associated with inputs
- Error messages identified
- Required fields indicated
- Form validation accessible

## Testing Tools
- axe-core for automated testing
- NVDA/VoiceOver for screen reader testing
- Keyboard-only navigation testing
- Color contrast analyzers

## Example Test
```python
def test_form_has_accessible_labels():
    page.goto("/form")
    inputs = page.locator("input")

    for input_elem in inputs.all():
        # Check for associated label
        label = page.locator(f'label[for="{{input_elem.get_attribute("id")}}"]')
        assert label.count() > 0, f"Input missing label"
```
"""

    def get_prompt(self) -> str:
        return """You are an accessibility expert.

Test for WCAG compliance:
1. Perceivable - content accessible to all senses
2. Operable - keyboard navigable
3. Understandable - clear and consistent
4. Robust - works with assistive technology

Use axe-core for automated testing."""


class ShiftLeftTesting(Skill):
    """
    Shift-Left Testing Skill.

    Promotes early testing practices.
    """

    NAME = "shift-left-testing"
    DISPLAY_NAME = "Shift-Left Testing"
    DESCRIPTION = "Early testing strategies and practices"
    CATEGORY = "methodology"
    TAGS = ["shift-left", "early-testing", "prevention"]

    async def execute(self, **kwargs) -> SkillResult:
        """
        Provide shift-left testing guidance.

        Args:
            phase: Development phase
            context: Project context

        Returns:
            SkillResult with guidance
        """
        phase = kwargs.get("phase", "design")

        guidance = self._get_guidance(phase)

        return SkillResult(
            skill_name=self.NAME, success=True, output=guidance, metrics={"phase": phase}
        )

    def _get_guidance(self, phase: str) -> str:
        return f"""# Shift-Left Testing for {phase.title()} Phase

## Core Principle
Find defects earlier when they're cheaper to fix.

## Activities by Phase

### Requirements Phase
- Requirements review
- Testability assessment
- Risk analysis
- Acceptance criteria definition

### Design Phase
- Design review
- API contract definition
- Test strategy creation
- Architecture testing

### Development Phase
- Unit testing (TDD)
- Static analysis
- Code review
- Pair programming

### Integration Phase
- Integration testing
- Contract testing
- Performance testing
- Security scanning

## Benefits
- 10x cheaper to fix bugs in design vs production
- Faster feedback loops
- Better code quality
- Reduced technical debt

## Implementation
1. Include QE in planning
2. Define test cases during design
3. Automate early and often
4. Continuous integration
5. Quality gates at each phase
"""

    def get_prompt(self) -> str:
        return """You are a shift-left testing advocate.

Key principles:
1. Test early and often
2. Prevention over detection
3. Collaboration between dev and QE
4. Automation from the start
5. Continuous feedback

Help integrate testing into every phase."""


class ChaosEngineeringResilience(Skill):
    """
    Chaos Engineering Skill.

    Guides chaos testing for system resilience.
    """

    NAME = "chaos-engineering-resilience"
    DISPLAY_NAME = "Chaos Engineering"
    DESCRIPTION = "Chaos testing for system resilience"
    CATEGORY = "testing"
    TAGS = ["chaos", "resilience", "reliability"]

    async def execute(self, **kwargs) -> SkillResult:
        """
        Provide chaos engineering guidance.

        Args:
            target: System component to test
            experiment: Type of chaos experiment

        Returns:
            SkillResult with chaos testing guidance
        """
        target = kwargs.get("target", "service")
        experiment = kwargs.get("experiment", "latency")

        guidance = self._get_guidance(target, experiment)

        return SkillResult(
            skill_name=self.NAME,
            success=True,
            output=guidance,
            metrics={"target": target, "experiment": experiment},
        )

    def _get_guidance(self, target: str, experiment: str) -> str:
        return f"""# Chaos Engineering for {target}

## Experiment: {experiment.title()} Injection

### Hypothesis
"When {experiment} is introduced to {target}, the system should..."

### Steady State
Define normal behavior metrics:
- Response time < 200ms
- Error rate < 0.1%
- Throughput > 1000 req/s

### Experiment Types
1. **Latency**: Add network delays
2. **Failure**: Kill processes/containers
3. **Resource**: CPU/memory stress
4. **Network**: Partition, packet loss
5. **Dependency**: External service failure

### Safety Measures
- Start in staging environment
- Use canary deployments
- Have rollback plan
- Monitor closely
- Limit blast radius

### Tools
- Chaos Monkey (Netflix)
- Gremlin
- Litmus
- Chaos Toolkit

### Example Experiment
```yaml
experiment:
  name: "{target}-{experiment}-test"
  hypothesis:
    title: "Service remains available under {experiment}"
  method:
    - type: action
      name: inject-{experiment}
      provider:
        type: python
        module: chaoslib.{experiment}
  rollbacks:
    - type: action
      name: restore-normal
```
"""

    def get_prompt(self) -> str:
        return """You are a chaos engineering expert.

Guide chaos experiments:
1. Define steady state
2. Form hypothesis
3. Run experiment
4. Measure impact
5. Improve resilience

Always prioritize safety and have rollback plans."""


class VisualTestingAdvanced(Skill):
    """
    Visual Testing Skill.

    Advanced visual regression testing patterns.
    """

    NAME = "visual-testing-advanced"
    DISPLAY_NAME = "Visual Testing Advanced"
    DESCRIPTION = "Advanced visual comparison techniques"
    CATEGORY = "testing"
    TAGS = ["visual", "regression", "ui", "screenshot"]

    async def execute(self, **kwargs) -> SkillResult:
        """
        Provide visual testing guidance.

        Args:
            component: Component to test
            strategy: Testing strategy

        Returns:
            SkillResult with visual testing guidance
        """
        component = kwargs.get("component", "page")
        strategy = kwargs.get("strategy", "full-page")

        guidance = self._get_guidance(component, strategy)

        return SkillResult(
            skill_name=self.NAME,
            success=True,
            output=guidance,
            metrics={"component": component, "strategy": strategy},
        )

    def _get_guidance(self, component: str, strategy: str) -> str:
        return f"""# Visual Testing for {component}

## Strategy: {strategy.title()}

### Comparison Algorithms
1. **Pixel Diff**: Direct pixel comparison
2. **Perceptual**: Human-perception based
3. **AI-based**: ML for smart comparison
4. **Layout**: Structural comparison

### Best Practices
- Consistent viewport sizes
- Stable test data
- Font loading wait
- Animation handling
- Cross-browser testing

### Handling Flakiness
- Ignore dynamic regions
- Wait for stability
- Use tolerance thresholds
- Retry on failure

### Tools
- Percy
- Applitools
- BackstopJS
- Playwright visual comparisons

### Example Implementation
```python
def test_visual_regression():
    page.goto("/component")
    page.wait_for_load_state("networkidle")

    # Capture screenshot
    screenshot = page.screenshot()

    # Compare with baseline
    assert_visual_match(
        screenshot,
        baseline="component-baseline.png",
        threshold=0.98  # 98% similarity required
    )
```
"""

    def get_prompt(self) -> str:
        return """You are a visual testing expert.

Cover:
1. Baseline management
2. Diff handling
3. Cross-browser testing
4. Responsive testing
5. Dynamic content handling

Use appropriate tools and thresholds."""


class ComplianceTesting(Skill):
    """
    Compliance Testing Skill.

    Regulatory compliance testing patterns.
    """

    NAME = "compliance-testing"
    DISPLAY_NAME = "Compliance Testing"
    DESCRIPTION = "Regulatory compliance test patterns"
    CATEGORY = "testing"
    TAGS = ["compliance", "regulatory", "gdpr", "hipaa"]

    async def execute(self, **kwargs) -> SkillResult:
        """
        Provide compliance testing guidance.

        Args:
            regulation: Regulation to comply with
            area: Area of compliance

        Returns:
            SkillResult with compliance guidance
        """
        regulation = kwargs.get("regulation", "GDPR")
        area = kwargs.get("area", "data-privacy")

        guidance = self._get_guidance(regulation, area)

        return SkillResult(
            skill_name=self.NAME,
            success=True,
            output=guidance,
            metrics={"regulation": regulation, "area": area},
        )

    def _get_guidance(self, regulation: str, area: str) -> str:
        return f"""# Compliance Testing for {regulation}

## Focus Area: {area.title()}

### {regulation} Requirements
- Data subject rights
- Consent management
- Data minimization
- Right to erasure
- Data portability

### Test Categories

#### 1. Data Privacy Tests
- PII identification
- Data encryption
- Access controls
- Audit logging

#### 2. Consent Tests
- Consent collection
- Consent withdrawal
- Preference center
- Cookie consent

#### 3. Security Tests
- Authentication
- Authorization
- Data encryption
- Secure transmission

#### 4. Audit Tests
- Access logs
- Change history
- Data lineage
- Retention policies

### Example Tests
```python
def test_pii_is_encrypted_at_rest():
    user = create_user(email="test@example.com")
    raw_data = database.get_raw_record(user.id)
    assert user.email not in raw_data  # Should be encrypted

def test_user_can_request_data_deletion():
    user = create_user()
    request_deletion(user.id)
    assert user_data_deleted(user.id)
```
"""

    def get_prompt(self) -> str:
        return """You are a compliance testing expert.

Cover regulations:
- GDPR (EU data protection)
- HIPAA (healthcare)
- SOC 2 (security)
- PCI DSS (payment cards)

Ensure tests validate compliance requirements."""
