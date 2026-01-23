"""Minimal QE report templates for OSS."""

from datetime import datetime
from typing import Dict, Optional


def get_report_template(role_name: str) -> Optional[str]:
    return REPORT_TEMPLATES.get(role_name)


REPORT_TEMPLATES: Dict[str, str] = {
    "default": """
# QE Report

## Summary
- Date: {date}
- Scope: {scope}
- Findings: {findings}

## Findings
{details}

## Notes
{notes}
""",
}


def format_report(role_name: str, **kwargs) -> str:
    template = get_report_template(role_name) or REPORT_TEMPLATES["default"]
    defaults = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": "Project",
        "findings": 0,
        "details": "-",
        "notes": "-",
    }
    defaults.update(kwargs)
    return template.format(**defaults)
