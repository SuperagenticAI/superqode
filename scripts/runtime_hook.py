import os
import sys

# CRITICAL: Set these BEFORE any other imports to prevent Pydantic/Logfire introspection crashes in PyInstaller
os.environ["LOGFIRE_DISABLE"] = "1"
os.environ["LOGFIRE_IGNORE_NO_CONFIG"] = "1"
os.environ["PYDANTIC_DISABLE_ERRORS"] = "1"
os.environ["PYDANTIC_SKIP_VALIDATING_CORE_SCHEMAS"] = "1"
os.environ["PYDANTIC_DISABLE_VALIDATION_ON_REPR"] = "1"

# Also disable some other problematic things in frozen environments
os.environ["LITELLM_LOG_SILENT"] = "True"
os.environ["LITELLM_LOCAL_RESOURCES"] = "True"
