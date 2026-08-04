"""PiPy session tree.

Phase 2 ships the tree semantics and in-memory storage. Phase 3 adds JSONL
persistence and the repository that maps a working directory to its sessions,
behind the same :class:`~superqode.pipy.session.storage.SessionStorage` protocol.
"""

from .entries import (
    ActiveToolsChangeEntry,
    BranchSummaryEntry,
    CompactionEntry,
    CustomEntry,
    CustomMessageEntry,
    LabelEntry,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    SessionContext,
    SessionInfoEntry,
    SessionMetadata,
    SessionModelRef,
    SessionStats,
    SessionTreeEntry,
    ThinkingLevelChangeEntry,
)
from .codec import SessionCodecError, decode_entry, decode_message, encode_entry, encode_message
from .jsonl import (
    SESSION_FORMAT_VERSION,
    JsonlSessionStorage,
    decode_header,
    encode_header,
    read_session_metadata,
)
from .memory import MemorySessionStorage
from .repository import (
    SessionRecord,
    SessionRepository,
    import_pi_sessions,
    write_session_file,
)
from .session import (
    CustomEntryProjector,
    Session,
    build_session_context,
    create_session,
    default_context_entry_transform,
    derive_session_state,
    entry_to_context_messages,
)
from .storage import SessionError, SessionStorage

__all__ = [
    "SESSION_FORMAT_VERSION",
    "ActiveToolsChangeEntry",
    "BranchSummaryEntry",
    "CompactionEntry",
    "CustomEntry",
    "CustomEntryProjector",
    "CustomMessageEntry",
    "LabelEntry",
    "JsonlSessionStorage",
    "LeafEntry",
    "MemorySessionStorage",
    "MessageEntry",
    "ModelChangeEntry",
    "Session",
    "SessionCodecError",
    "SessionContext",
    "SessionError",
    "SessionInfoEntry",
    "SessionMetadata",
    "SessionModelRef",
    "SessionRecord",
    "SessionRepository",
    "SessionStats",
    "SessionStorage",
    "SessionTreeEntry",
    "ThinkingLevelChangeEntry",
    "build_session_context",
    "create_session",
    "decode_entry",
    "decode_header",
    "decode_message",
    "default_context_entry_transform",
    "derive_session_state",
    "encode_entry",
    "encode_header",
    "encode_message",
    "entry_to_context_messages",
    "import_pi_sessions",
    "read_session_metadata",
    "write_session_file",
]
