<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Configuration Commands

Commands for creating and adjusting your `superqode.yaml`.

---

## Overview

SuperQode looks for configuration in this order:

1. `./superqode.yaml` (project)
2. `~/.superqode.yaml` (user)
3. `/etc/superqode/superqode.yaml` (system)

For most teams, use project config: `superqe init`.

---

## init

Create `superqode.yaml` in the current directory from the comprehensive role catalog template.

```bash
superqe init [--force] [--guided]
```

Examples:

```bash
superqe init
superqe init --force
```

---

## config init

Initialize a default config (alternative to `superqe init`).

```bash
superqode config init [--force]
```

---

## config list-modes

List configured modes and roles (as defined in `superqode.yaml`).

```bash
superqode config list-modes
```

---

## config set-model

Set the model for a specific `MODE.ROLE`.

```bash
superqode config set-model MODE.ROLE MODEL
```

Example:

```bash
superqode config set-model qe.security_tester gemini-2.5-flash
```

Note: ACP agents manage their own models; use this for non-ACP roles.

---

## config set-agent

Set the ACP agent for a specific `MODE.ROLE`.

```bash
superqode config set-agent MODE.ROLE AGENT [--provider PROVIDER]
```

Example:

```bash
superqode config set-agent qe.fullstack opencode
```

---

## config enable-role / disable-role

Enable or disable a role in `superqode.yaml`.

```bash
superqode config enable-role MODE.ROLE
superqode config disable-role MODE.ROLE
```
