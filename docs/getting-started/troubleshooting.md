# Troubleshooting Guide

This guide helps you resolve common issues when using SuperQode.

## Table of Contents

- [Installation Issues](#installation-issues)
- [Agent Connection Problems](#agent-connection-problems)
- [Validation Analysis Failures](#validation-analysis-failures)
- [Performance Issues](#performance-issues)
- [Configuration Problems](#configuration-problems)
- [Common Error Messages](#common-error-messages)

## Installation Issues

### "ModuleNotFoundError" when running SuperQode

**Problem:**
```bash
ModuleNotFoundError: No module named 'superqode'
```

**Solutions:**

1. **Install in development mode:**
   ```bash
   cd /path/to/superqode
   pip install -e .
   ```

2. **Check Python path:**
   ```bash
   python -c "import superqode; print('Import successful')"
   ```

3. **Reinstall:**
   ```bash
   pip uninstall superqode
   pip install superqode
   ```

### OpenCode Installation Issues

**Problem:**
```bash
❌ OpenCode not found. Install with: npm i -g opencode-ai
```

**Solutions:**

1. **Install OpenCode globally:**
   ```bash
   npm i -g opencode-ai
   ```

2. **Verify Node.js and npm:**
   ```bash
   node --version
   npm --version
   ```

3. **Check npm permissions (macOS/Linux):**
   ```bash
   sudo npm i -g opencode-ai
   ```

4. **Manual installation:**
   ```bash
   # Clone and install manually
   git clone https://github.com/sst/opencode.git
   cd opencode
   npm install
   npm run build
   npm link  # or npm install -g .
   ```

## Agent Connection Problems

### "Agent not found" or "Agent unavailable"

**Problem:**
```bash
❌ Agent 'opencode' not found
```

**Solutions:**

1. **Check OpenCode installation:**
   ```bash
   opencode --version
   ```

2. **Verify agent configuration in YAML:**
   ```yaml
   team:
     qe:
       roles:
         unit_tester:
           enabled: true
   ```

3. **Restart SuperQode:**
   ```bash
   # Exit TUI and restart
   superqode
   ```

### "ACP connection failed"

**Problem:**
```bash
❌ ACP agent not available for unit_tester, providing graceful degradation
```

**Solutions:**

1. **Install OpenCode:**
   ```bash
   npm i -g opencode-ai
   ```

2. **Check OpenCode status:**
   ```bash
   opencode --help
   ```

3. **Verify ACP adapter:**
   ```bash
   npm install -g @josephschmitt/opencode-acp  # If using ACP adapter
   ```

## validation Analysis Failures

### "No tests detected" when tests exist

**Problem:**
```bash
Verdict: 🟠 NO TESTS DETECTED - Add tests for proper validation
```

**Solutions:**

1. **Check test file patterns:**
   - Default patterns: `**/*test* **/*spec* **/test_*`
   - Python: `test_*.py`, `*test*.py`
   - JavaScript: `*.test.js`, `*.spec.js`

2. **Run with verbose logging:**
   ```bash
   ```

3. **Check file permissions:**
   ```bash
   find . -name "*test*" -type f -ls
   ```

### "Failed to parse jest JSON output"

**Problem:**
```bash
Failed to parse jest JSON output: Expecting value: line 1 column 1 (char 0)
```

**Solutions:**

1. **This is usually harmless** - it's just Jest output parsing issues
2. **To suppress warnings, ensure proper Jest configuration**
3. **Use different test runners if needed**

### Deep validation not showing agent activity

**Problem:**
```bash
# Nothing appears in console
```

**Solutions:**

1. **Use verbose flag:**
   ```bash
   ```

2. **Check OpenCode installation:**
   ```bash
   opencode --version
   ```

3. **Verify agent roles are enabled:**
   ```yaml
   team:
     qe:
       roles:
         api_tester:
           enabled: true
         security_tester:
           enabled: true
   ```

## Performance Issues

### Slow startup time

**Problem:** SuperQode takes too long to start

**Solutions:**

1. **Use lazy loading** (already implemented)
2. **Check system resources:**
   ```bash
   top  # or htop
   ```

3. **Close other memory-intensive applications**

### High memory usage during validation

**Problem:** validation analysis uses too much memory

**Solutions:**

1. **Memory limits are already implemented** (50MB per process)
2. **Run smaller analysis scopes:**
   ```bash
   ```

3. **Use worktree isolation:**
   ```bash
   ```

### Agent timeouts

**Problem:**
```bash
⏰ Agent analysis timed out after 30s
```

**Solutions:**

1. **Increase timeout:**
   ```bash
   ```

2. **Use specific roles instead of all:**
   ```bash
   ```

## Configuration Problems

### YAML configuration not loading

**Problem:**
```bash
Configuration error: Invalid YAML format
```

**Solutions:**

1. **Validate YAML syntax:**
   ```bash
   python -c "import yaml; yaml.safe_load(open('superqode.yaml'))"
   ```

2. **Check indentation (YAML is space-sensitive)**
3. **Use online YAML validators**

### Roles not appearing

**Problem:** Expected roles don't show up in TUI

**Solutions:**

1. **Check YAML structure:**
   ```yaml
   team:
     qe:
       roles:
         unit_tester:
           enabled: true
   ```

2. **Restart SuperQode after config changes**
3. **Use `superqode config init` to reset configuration**

## Common Error Messages

### "Another validation session is already running"

**Problem:** Multiple validation sessions conflict

**Solution:**
```bash
# Check running sessions

# View session logs
```

### "Permission denied" errors

**Problem:** File system access issues

**Solutions:**
```bash
# Check permissions
ls -la /path/to/project

# Fix permissions
chmod -R u+rwx /path/to/project

# Or run with sudo (not recommended)
```

### "Connection refused" for MCP servers

**Problem:** MCP servers not accessible

**Solutions:**

1. **Check MCP server configuration in YAML**
2. **Verify MCP server processes are running:**
   ```bash
   ps aux | grep mcp
   ```

3. **Restart MCP servers:**
   ```yaml
   mcp:
     servers:
       filesystem:
         command: "npx -y @modelcontextprotocol/server-filesystem /tmp"
   ```

### "Import error" for custom modules

**Problem:** Python path issues in validation analysis

**Solutions:**

1. **Check Python environment:**
   ```bash
   which python
   python -c "import sys; print(sys.path)"
   ```

2. **Use virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install superqode
   ```

## Getting Help

If these solutions don't resolve your issue:

1. **Check the logs:**
   ```bash
   ```

2. **Run with debug output:**
   ```bash
   superqode --debug qe run .
   ```

3. **Report issues on GitHub:**
   - [GitHub Issues](https://github.com/SuperagenticAI/superqode/issues)
   - Include full error messages and environment details

4. **Email Support:**
   - Reach out to us at [info@super-agentic.ai](mailto:info@super-agentic.ai)

5. **Community support:**
   - Check GitHub Discussions
   - Join the SuperQode community

## Health Check

Run this health check command to diagnose common issues:

```bash
python -c "
import sys
import subprocess
import shutil

print('🔍 SuperQode Health Check')
print('=' * 40)

# Check Python version
print(f'Python: {sys.version}')

# Check required packages
try:
    import textual
    print('✅ Textual available')
except ImportError:
    print('❌ Textual missing')

try:
    import rich
    print('✅ Rich available')
except ImportError:
    print('❌ Rich missing')

# Check OpenCode
if shutil.which('opencode'):
    print('✅ OpenCode available')
    try:
        result = subprocess.run(['opencode', '--version'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f'   Version: {result.stdout.strip()}')
        else:
            print('❌ OpenCode not working')
    except:
        print('❌ OpenCode check failed')
else:
    print('❌ OpenCode not found')

# Check Node.js
if shutil.which('node'):
    try:
        result = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=5)
        print(f'✅ Node.js: {result.stdout.strip()}')
    except:
        print('❌ Node.js check failed')
else:
    print('❌ Node.js not found')

"
```
