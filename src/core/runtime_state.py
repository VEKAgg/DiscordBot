import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import List


def _load_git_metadata() -> str:
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=os.getcwd(),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return commit or 'unknown'
    except Exception:
        return os.getenv('COMMIT_SHA', 'unknown')


def _load_git_branch() -> str:
    try:
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=os.getcwd(),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return branch or os.getenv('GIT_BRANCH', 'unknown')
    except Exception:
        return os.getenv('GIT_BRANCH', 'unknown')


@dataclass
class RuntimeState:
    db_available: bool = False
    loaded_cogs: List[str] = field(default_factory=list)
    failed_cogs: List[str] = field(default_factory=list)
    degraded_features: List[str] = field(default_factory=list)
    startup_time: datetime = field(default_factory=datetime.utcnow)
    version: str = field(default_factory=lambda: os.getenv('BOT_VERSION', '1.0.0'))
    commit: str = field(default_factory=_load_git_metadata)
    branch: str = field(default_factory=_load_git_branch)
    
    # New state fields for production observability
    startup_check_results: List[dict] = field(default_factory=list)
    last_db_error: str | None = None
    last_recovery_time: datetime | None = None
    alert_state_cache: dict = field(default_factory=dict)

runtime_state = RuntimeState()
