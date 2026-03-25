from enum import Enum

class TaskDomain(str, Enum):
    CODE = "code"
    RESEARCH = "research"
    WRITING = "writing"
    EXPERIMENT = "experiment"
    ANALYSIS = "analysis"
    GENERIC = "generic"

class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"

class AdvanceAction(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    REVISE = "revise"
    ROLLBACK = "rollback"
    PROMOTE = "promote"

class VerificationVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"

class AssetKind(str, Enum):
    INLINE_TEXT = "inline_text"
    FILE = "file"
    JSON = "json"
    DIRECTORY = "directory"
