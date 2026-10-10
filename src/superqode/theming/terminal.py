"""Consume terminal colour responses separately from keys and bracketed paste."""

from __future__ import annotations

import os
import re
import sys
import time

from textual.message import Message

QUERY = "\x1b]10;?\x07\x1b]11;?\x07" + "".join(f"\x1b]4;{index};?\x07" for index in range(16))
# DEC mode 2031: the terminal sends CSI ? 997 ; 1 n (dark) or ; 2 n (light)
# when its colour scheme changes. CSI ? 996 n asks for the current scheme.
SCHEME_ENABLE = "\x1b[?2031h\x1b[?996n"
SCHEME_DISABLE = "\x1b[?2031l"
SCHEME_REPORT = re.compile(r"\x1b\[\?997;([12])n")
PASTE_START, PASTE_END = "\x1b[200~", "\x1b[201~"
COLOR_PREFIXES = ("\x1b]10;", "\x1b]11;", "\x1b]4;")
REPLY = re.compile(
    r"\x1b](?:(10|11);|4;(\d{1,2});)rgb:([0-9a-fA-F]{1,4})/"
    r"([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})(?:\x07|\x1b\\)$"
)


def tmux_wrap(sequence: str) -> str:
    """DCS passthrough so the outer terminal answers (needs tmux
    allow-passthrough). tmux 3.3+ also answers OSC 10/11 itself, so callers
    send both forms; duplicate replies are de-duplicated by the app."""
    return "\x1bPtmux;" + sequence.replace("\x1b", "\x1b\x1b") + "\x1b\\"


def query_sequence(environ=None) -> str:
    environ = os.environ if environ is None else environ
    if environ.get("TMUX"):
        return QUERY + tmux_wrap(QUERY)
    return QUERY


def _partial_color_reply(value: str) -> bool:
    """Recognize incomplete RGB framing so interrupted reports cannot eat keys."""
    namespace, _, payload = value.partition(";")
    if namespace == "\x1b]4":
        index, separator, payload = payload.partition(";")
        if len(index) > 2 or any(char not in "0123456789" for char in index):
            return False
        if not separator:
            return True
        if not index:
            return False
    if len(payload) < 4:
        return "rgb:".startswith(payload)
    if not payload.startswith("rgb:"):
        return False
    channels = payload[4:]
    awaiting_st = channels.endswith("\x1b")
    if awaiting_st:
        channels = channels[:-1]
    parts = channels.split("/")
    if len(parts) > 3 or any(not part for part in parts[:-1]):
        return False
    if awaiting_st and (len(parts) != 3 or not parts[-1]):
        return False
    return all(
        len(part) <= 4 and all(char in "0123456789abcdefABCDEF" for char in part) for part in parts
    )


class TerminalColorReply(Message):
    def __init__(self, colors: dict[str, str]):
        super().__init__()
        self.colors = colors


class ColorInputFilter:
    """Incremental framing; never treat a pasted escape sequence as a reply."""

    def __init__(self, callback):
        self.callback = callback
        self.buffer = ""
        self.pasting = False
        self.pending_since = 0.0
        self._possible_keys = ""

    def feed(self, data: str) -> str:
        previous_pending = self.buffer
        if len(previous_pending) >= 3 and any(
            previous_pending.startswith(prefix) or prefix.startswith(previous_pending)
            for prefix in COLOR_PREFIXES
        ):
            self._possible_keys += data
        else:
            self._possible_keys = ""
        self.buffer += data
        if "\x1b[?997;" in self.buffer and not self.pasting:
            for match in SCHEME_REPORT.finditer(self.buffer):
                self.callback({"scheme": "dark" if match[1] == "1" else "light"})
            self.buffer = SCHEME_REPORT.sub("", self.buffer)
        output = []
        while self.buffer:
            if self.pasting:
                end = self.buffer.find(PASTE_END)
                if end >= 0:
                    output.append(self.buffer[: end + len(PASTE_END)])
                    self.buffer = self.buffer[end + len(PASTE_END) :]
                    self.pasting = False
                    continue
                suffix = max(
                    (n for n in range(1, len(PASTE_END)) if self.buffer.endswith(PASTE_END[:n])),
                    default=0,
                )
                output.append(self.buffer[:-suffix] if suffix else self.buffer)
                self.buffer = self.buffer[-suffix:] if suffix else ""
                break
            escape = self.buffer.find("\x1b")
            if escape < 0:
                output.append(self.buffer)
                self.buffer = ""
                break
            if escape:
                output.append(self.buffer[:escape])
                self.buffer = self.buffer[escape:]
            if self.buffer.startswith(PASTE_START):
                output.append(PASTE_START)
                self.buffer = self.buffer[len(PASTE_START) :]
                self.pasting = True
                continue
            prefixes = (PASTE_START, *COLOR_PREFIXES)
            if any(prefix.startswith(self.buffer) for prefix in prefixes):
                break
            if (
                len(previous_pending) >= 3
                and any(prefix.startswith(previous_pending) for prefix in COLOR_PREFIXES)
                and self.buffer.startswith(previous_pending)
                and not self.buffer.startswith(COLOR_PREFIXES)
            ):
                # Recover keys even if transport stopped inside the OSC header.
                self.buffer = self._possible_keys or self.buffer[len(previous_pending) :]
                self._possible_keys = ""
                previous_pending = ""
                continue
            if self.buffer.startswith(COLOR_PREFIXES):
                terminator = re.search(r"\x07|\x1b\\", self.buffer)
                # A new escape sequence interrupts an unfinished report. Leave
                # navigation, paste markers and fresh reports for normal framing.
                interrupt = re.search(r"\x1b[^\\]", self.buffer[1:])
                if interrupt and (terminator is None or interrupt.start() + 1 < terminator.start()):
                    self.buffer = self.buffer[interrupt.start() + 1 :]
                    self._possible_keys = ""
                    previous_pending = ""
                    continue
                if terminator is None:
                    invalid = next(
                        (
                            end - 1
                            for end in range(self.buffer.index(";") + 1, len(self.buffer) + 1)
                            if not _partial_color_reply(self.buffer[:end])
                        ),
                        None,
                    )
                    if invalid is not None:
                        # Restore candidate keys across reads, including early
                        # letters indistinguishable from hexadecimal RGB data.
                        if self._possible_keys and self.buffer.startswith(previous_pending):
                            self.buffer = self._possible_keys
                        else:
                            self.buffer = self.buffer[invalid:]
                        self._possible_keys = ""
                        previous_pending = ""
                        continue
                    if len(self.buffer) <= 160:
                        break
                    self.buffer = ""  # Malformed terminal reply, bounded memory.
                    continue
                response = self.buffer[: terminator.end()]
                self.buffer = self.buffer[terminator.end() :]
                self._possible_keys = ""
                match = REPLY.fullmatch(response)
                if match and (match[2] is None or int(match[2]) < 16):
                    key = (
                        "fg"
                        if match[1] == "10"
                        else "bg"
                        if match[1] == "11"
                        else str(int(match[2]))
                    )
                    rgb = [
                        round(int(channel, 16) * 255 / (16 ** len(channel) - 1))
                        for channel in match.group(3, 4, 5)
                    ]
                    self.callback({key: "#" + "".join(f"{channel:02x}" for channel in rgb)})
                continue
            output.append(self.buffer[0])
            self.buffer = self.buffer[1:]
        self.pending_since = self.pending_since or time.monotonic() if self.buffer else 0
        return "".join(output)

    def tick(self) -> str:
        if self.buffer and not self.pasting and time.monotonic() - self.pending_since > 0.1:
            # Colour replies can cross slow transport reads. A recognized OSC
            # prefix has its own bounded framing, independent of the Escape key.
            if len(self.buffer) >= 3 and any(
                self.buffer.startswith(prefix) or prefix.startswith(self.buffer)
                for prefix in COLOR_PREFIXES
            ):
                return ""
            pending, self.buffer = self.buffer, ""
            self.pending_since = 0
            return pending
        return ""


def terminal_driver():
    """Use native Textual drivers for Windows, web and non-terminal hosts."""
    if sys.platform == "win32" or not sys.stdin.isatty():
        return None
    from codecs import getincrementaldecoder
    import selectors
    from textual._xterm_parser import XTermParser
    from textual.drivers.linux_driver import LinuxDriver

    class ThemeLinuxDriver(LinuxDriver):
        def run_input_thread(self):
            parser = XTermParser(self._debug)
            framing = ColorInputFilter(
                lambda colors: self.process_message(TerminalColorReply(colors))
            )
            decode = getincrementaldecoder("utf-8")().decode
            with selectors.SelectSelector() as selector:
                selector.register(self.fileno, selectors.EVENT_READ)
                while not self.exit_event.is_set():
                    for _key, _mask in selector.select(0.05):
                        chunk = os.read(self.fileno, 4096)
                        if not chunk:
                            return
                        data = framing.feed(decode(chunk))
                        if data:
                            for event in parser.feed(data):
                                self.process_message(event)
                    pending = framing.tick()
                    if pending:
                        for event in parser.feed(pending):
                            self.process_message(event)
                    for event in parser.tick():
                        self.process_message(event)

    return ThemeLinuxDriver
