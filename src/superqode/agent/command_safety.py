"""Shell command safety classification ("execpolicy-lite").

Classifies a shell command so the harness can auto-run known read-only commands
(no approval prompt), require approval for writes/network, and hard-block
destructive ones.

Design goals:
- Conservative: an unknown command defaults to WRITE (requires approval), never
  SAFE. Severity escalates across a compound command — the riskiest segment wins.
- Obfuscation-aware enough for the common cases: split on shell operators, peel
  leading ``env VAR=x`` / ``sudo`` / ``command`` prefixes, and inspect
  redirections so ``echo x > /dev/sda`` is DESTRUCTIVE, not SAFE.
"""

from __future__ import annotations

import re
import shlex
from enum import Enum


class CommandSafety(str, Enum):
    """Severity of a shell command, ascending."""

    SAFE = "safe"  # read-only; auto-allow
    WRITE = "write"  # mutates the workspace; ask
    NETWORK = "network"  # touches the network; ask
    DESTRUCTIVE = "destructive"  # dangerous; deny / strong warning


_SEVERITY_ORDER = {
    CommandSafety.SAFE: 0,
    CommandSafety.WRITE: 1,
    CommandSafety.NETWORK: 2,
    CommandSafety.DESTRUCTIVE: 3,
}

# Read-only commands that are safe to run without approval.
READ_ONLY_COMMANDS = {
    "ls", "pwd", "echo", "cat", "bat", "head", "tail", "wc", "less", "more",
    "grep", "egrep", "fgrep", "rg", "ag", "ack", "find", "fd", "locate",
    "which", "type", "whereis", "file", "stat", "du", "df", "tree", "realpath",
    "readlink", "basename", "dirname", "date", "whoami", "id", "uname",
    "hostname", "env", "printenv", "uptime", "ps", "top", "htop", "free",
    "sort", "uniq", "cut", "tr", "column", "tee", "diff", "cmp", "comm",
    "md5sum", "sha1sum", "sha256sum", "cksum", "nl", "fold", "expand",
    "man", "help", "history", "true", "false", "test", "yes", "seq", "printf",
    "jq", "yq", "xxd", "od", "strings", "tac", "rev", "paste", "join",
}

# Read-only subcommands for common multi-verb tools.
READ_ONLY_SUBCOMMANDS = {
    "git": {
        "status", "diff", "log", "show", "branch", "remote", "rev-parse",
        "describe", "blame", "ls-files", "ls-tree", "cat-file", "config",
        "shortlog", "reflog", "tag", "whatchanged", "grep", "show-ref",
        "symbolic-ref", "name-rev", "var", "help", "rev-list", "merge-base",
    },
    "npm": {"ls", "list", "view", "show", "outdated", "audit", "doctor", "ping", "root", "config"},
    "pnpm": {"ls", "list", "outdated", "audit", "why"},
    "yarn": {"list", "info", "why", "outdated"},
    "pip": {"list", "show", "freeze", "check"},
    "pip3": {"list", "show", "freeze", "check"},
    "cargo": {"tree", "metadata", "search"},
    "go": {"list", "version", "env", "doc", "vet"},
    "kubectl": {"get", "describe", "logs", "explain", "version", "config"},
    "docker": {"ps", "images", "logs", "inspect", "version", "info"},
    "brew": {"list", "info", "search", "outdated", "config", "doctor"},
}

# Commands that reach the network.
NETWORK_COMMANDS = {
    "curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "ncat", "telnet",
    "ftp", "ping", "dig", "nslookup", "host", "traceroute", "http", "https",
    "aria2c", "youtube-dl", "yt-dlp",
}
_NETWORK_SUBCOMMANDS = {
    "git": {"push", "pull", "fetch", "clone", "remote"},
    "npm": {"install", "i", "publish", "update", "ci", "add"},
    "pnpm": {"install", "i", "add", "update", "publish"},
    "yarn": {"add", "install", "publish", "upgrade"},
    "pip": {"install", "download", "wheel"},
    "pip3": {"install", "download", "wheel"},
    "cargo": {"publish", "install", "update", "fetch"},
    "go": {"get", "install", "mod"},
    "brew": {"install", "upgrade", "update", "tap"},
    "apt": {"install", "update", "upgrade"},
    "apt-get": {"install", "update", "upgrade"},
    "docker": {"pull", "push", "run"},
}

# Destructive patterns checked against the full command string.
_DESTRUCTIVE_PATTERNS = [
    r"\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-rf|-fr)\b",  # rm -rf / -fr
    r"\bsudo\b",
    r"\bdoas\b",
    r"\bmkfs\.",
    r"\bdd\b[^|]*\bof=",
    r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",  # fork bomb
    r">\s*/dev/(sd|nvme|disk|hd)",
    r"\bchmod\s+(-R\s+)?0?777\b",
    r"\bchown\s+-R\b",
    r"\b(shutdown|reboot|halt|poweroff)\b",
    r"\bshred\b",
    r"\b(mkfs|fdisk|parted|wipefs)\b",
    r"rm\s+-[a-z]*\s+/\s*$",  # rm -r /
    r">\s*/etc/",
]
_DESTRUCTIVE_RE = [re.compile(p, re.IGNORECASE) for p in _DESTRUCTIVE_PATTERNS]

# Leading prefixes that wrap another command.
_WRAPPER_PREFIXES = {"sudo", "doas", "command", "nice", "nohup", "time", "timeout", "xargs", "env"}

# Dynamic / obfuscation constructs that defeat static analysis. A command using
# any of these can never be classified SAFE; pipe-to-interpreter is destructive.
_PIPE_TO_SHELL_RE = re.compile(
    r"\|\s*(sh|bash|zsh|fish|dash|python3?|node|ruby|perl|php)\b", re.IGNORECASE
)
_EVAL_RE = re.compile(r"\b(eval|exec)\b", re.IGNORECASE)
_BASE64_DECODE_RE = re.compile(r"\bbase64\s+(-d|-D|--decode)\b", re.IGNORECASE)
_DYNAMIC_RE = re.compile(r"\$\(|`|\$\{|<\(")  # command substitution / process subst


def canonicalize_command(command: str) -> str:
    """Normalise a command for *safety analysis* (not execution).

    Defeats common obfuscation so the classifier can't be fooled into marking a
    dangerous command SAFE: unescapes backslash-escaped chars (``\\rm`` → ``rm``)
    and drops empty quote pairs (``r""m`` → ``rm``). Aggressive on purpose —
    over-normalising only ever makes a command look *riskier*, which is safe.
    """
    s = re.sub(r"\\([A-Za-z0-9/._-])", r"\1", command)  # \rm -> rm
    # Drop quote characters entirely for analysis: collapses r""m -> rm and
    # '/bin/rm' -> /bin/rm so quoting can't hide a verb. Safe because this form
    # is only ever used to classify, never to execute.
    s = s.replace('"', "").replace("'", "")
    return s


def _strip_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    return token


def _split_segments(command: str) -> list[str]:
    """Split a compound command on shell operators into individual segments."""
    # Split on ; && || | & and newlines, keeping it simple and robust.
    parts = re.split(r"(?:\|\||&&|[;\n|&])", command)
    return [p.strip() for p in parts if p.strip()]


def _leading_token(segment: str) -> tuple[str, list[str]]:
    """Return (command, args) for a segment, peeling wrapper prefixes."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    # Peel wrappers and leading VAR=value assignments.
    while tokens:
        head = tokens[0]
        if "=" in head and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", head):
            tokens = tokens[1:]
            continue
        if head in _WRAPPER_PREFIXES:
            # sudo/doas themselves are destructive; handled by pattern scan too,
            # but peel so we still classify the inner command.
            tokens = tokens[1:]
            continue
        break
    if not tokens:
        return "", []
    head = _strip_quotes(tokens[0])
    cmd = head.split("/")[-1]  # strip path: /bin/ls -> ls
    return cmd, tokens[1:]


def _classify_segment(segment: str) -> CommandSafety:
    cmd, args = _leading_token(segment)
    if not cmd:
        return CommandSafety.WRITE

    # Redirection to a file in this segment implies a write at minimum.
    has_file_redirect = bool(re.search(r">>?\s*[^&\s]", segment))

    first_arg = next((a for a in args if not a.startswith("-")), "")

    if cmd in READ_ONLY_SUBCOMMANDS or cmd in _NETWORK_SUBCOMMANDS:
        net_subs = _NETWORK_SUBCOMMANDS.get(cmd, set())
        ro_subs = READ_ONLY_SUBCOMMANDS.get(cmd, set())
        if first_arg in net_subs:
            return CommandSafety.NETWORK
        if first_arg in ro_subs and not has_file_redirect:
            return CommandSafety.SAFE
        return CommandSafety.WRITE

    if cmd in NETWORK_COMMANDS:
        return CommandSafety.NETWORK

    if cmd in READ_ONLY_COMMANDS:
        # `tee`/`sed -i`-style writes or any redirect demote to WRITE.
        if has_file_redirect or (cmd == "tee"):
            return CommandSafety.WRITE
        if cmd == "sed" and any(a.startswith("-i") or a == "--in-place" for a in args):
            return CommandSafety.WRITE
        return CommandSafety.SAFE

    # Unknown command -> conservative: requires approval.
    return CommandSafety.WRITE


def classify_command(command: str) -> CommandSafety:
    """Classify a (possibly compound) shell command by its riskiest segment.

    The command is canonicalised first to defeat obfuscation, and dynamic
    constructs (pipe-to-shell, eval, command substitution, base64-decode) prevent
    a SAFE verdict.
    """
    if not command or not command.strip():
        return CommandSafety.SAFE

    canon = canonicalize_command(command)

    # Piping into an interpreter (curl … | sh) is treated as destructive.
    if _PIPE_TO_SHELL_RE.search(canon) or _BASE64_DECODE_RE.search(canon):
        return CommandSafety.DESTRUCTIVE

    # Hard destructive patterns scanned across the canonicalised command.
    for pattern in _DESTRUCTIVE_RE:
        if pattern.search(canon):
            return CommandSafety.DESTRUCTIVE

    worst = CommandSafety.SAFE
    for segment in _split_segments(canon):
        level = _classify_segment(segment)
        if _SEVERITY_ORDER[level] > _SEVERITY_ORDER[worst]:
            worst = level

    # Dynamic constructs we can't statically verify must never auto-run.
    if worst == CommandSafety.SAFE and (_DYNAMIC_RE.search(canon) or _EVAL_RE.search(canon)):
        worst = CommandSafety.WRITE
    return worst


def is_auto_safe(command: str) -> bool:
    """True when the command is read-only and safe to run without approval."""
    return classify_command(command) == CommandSafety.SAFE


def is_destructive(command: str) -> bool:
    """True when the command is destructive and should be blocked."""
    return classify_command(command) == CommandSafety.DESTRUCTIVE
