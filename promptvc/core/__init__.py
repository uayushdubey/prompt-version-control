"""
promptvc.core — version control engine for LLM prompts.
"""

from promptvc.core.repo import (
    PromptRepo,
    get_tokenizer,
    register_tokenizer,
    unregister_tokenizer,
    list_tokenizers,
    get_tokenizer_info,
)
from promptvc.core.storage import (
    StorageEngine,
    PromptVCError,
    PromptSpaceNotFoundError,
    VersionNotFoundError,
    RepoNotInitializedError,
    LockError,
    VersionLockedError,
    AlreadyLockedError,
    TraceRecord,
    TraceStore,
)
from promptvc.core.evaluator import (
    AssertionResult,
    CaseResult,
    run_assertion,
    run_case_assertions,
    PipelineStep,
    Pipeline,
    load_pipeline,
    validate_pipeline,
    execute_pipeline,
    StepResult,
    run_evaluation,
)
from promptvc.core.comparator import compare_versions
from promptvc.core.validator import validate_dataset, validate_prompt
from promptvc.utils.diff import compute_diff, format_diff, compute_diff_stats

__all__ = [
    # Main interface
    "PromptRepo",
    # Storage & Tracing
    "StorageEngine",
    "TraceRecord",
    "TraceStore",
    # Tokenizer
    "get_tokenizer",
    "register_tokenizer",
    "unregister_tokenizer",
    "list_tokenizers",
    "get_tokenizer_info",
    # Diff
    "compute_diff",
    "format_diff",
    "compute_diff_stats",
    # Exceptions
    "PromptVCError",
    "PromptSpaceNotFoundError",
    "VersionNotFoundError",
    "RepoNotInitializedError",
    "LockError",
    "VersionLockedError",
    "AlreadyLockedError",
    # Testing & Evaluation & Pipeline
    "AssertionResult",
    "CaseResult",
    "run_assertion",
    "run_case_assertions",
    "PipelineStep",
    "Pipeline",
    "load_pipeline",
    "validate_pipeline",
    "execute_pipeline",
    "StepResult",
    "run_evaluation",
    # Comparison
    "compare_versions",
    # Validation
    "validate_dataset",
    "validate_prompt",
]