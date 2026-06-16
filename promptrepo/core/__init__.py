"""
promptrepo.core — version control engine for LLM prompts.
"""

from promptrepo.core.repo import (
    PromptRepo,
    get_tokenizer,
    register_tokenizer,
    unregister_tokenizer,
    list_tokenizers,
    get_tokenizer_info,
)
from promptrepo.core.storage import (
    StorageEngine,
    PromptRepoError,
    PromptSpaceNotFoundError,
    VersionNotFoundError,
    RepoNotInitializedError,
    LockError,
    VersionLockedError,
    AlreadyLockedError,
    TraceRecord,
    TraceStore,
)
from promptrepo.core.evaluator import (
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
from promptrepo.core.comparator import compare_versions
from promptrepo.core.validator import validate_dataset, validate_prompt
from promptrepo.utils.diff import compute_diff, format_diff, compute_diff_stats

# New production modules
from promptrepo.core.prompt_format import (
    PromptFormat,
    ChatMessage,
    render_prompt,
    messages_to_plain,
    extract_variables_from_prompt,
    validate_chat_messages,
    prompt_to_storage,
    prompt_from_storage,
)
from promptrepo.core.matrix import (
    MatrixConfig,
    MatrixResult,
    MatrixCell,
    VersionStats,
    run_matrix_eval,
    format_matrix_table,
    save_matrix_report,
)
from promptrepo.core.analytics import (
    SpaceAnalytics,
    GlobalAnalytics,
    VersionAnalytics,
    ModelUsage,
    LatencyStats,
    compute_space_analytics,
    compute_global_analytics,
)
from promptrepo.core.budget import (
    BudgetGuard,
    BudgetExceededError,
    BudgetWarning,
    get_session_guard,
    reset_session_guard,
)
from promptrepo.core.tokenizer_registry import (
    TiktokenTokenizer,
    get_tokenizer_for_model,
    TokenizerRegistry,
)

__all__ = [
    # Main interface
    "PromptRepo",
    # Storage & Tracing
    "StorageEngine",
    "TraceRecord",
    "TraceStore",
    # Tokenizers
    "get_tokenizer",
    "register_tokenizer",
    "unregister_tokenizer",
    "list_tokenizers",
    "get_tokenizer_info",
    "TiktokenTokenizer",
    "get_tokenizer_for_model",
    "TokenizerRegistry",
    # Diff
    "compute_diff",
    "format_diff",
    "compute_diff_stats",
    # Exceptions
    "PromptRepoError",
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
    # Prompt Formats
    "PromptFormat",
    "ChatMessage",
    "render_prompt",
    "messages_to_plain",
    "extract_variables_from_prompt",
    "validate_chat_messages",
    "prompt_to_storage",
    "prompt_from_storage",
    # Matrix Evaluation
    "MatrixConfig",
    "MatrixResult",
    "MatrixCell",
    "VersionStats",
    "run_matrix_eval",
    "format_matrix_table",
    "save_matrix_report",
    # Analytics
    "SpaceAnalytics",
    "GlobalAnalytics",
    "VersionAnalytics",
    "ModelUsage",
    "LatencyStats",
    "compute_space_analytics",
    "compute_global_analytics",
    # Budget
    "BudgetGuard",
    "BudgetExceededError",
    "BudgetWarning",
    "get_session_guard",
    "reset_session_guard",
]