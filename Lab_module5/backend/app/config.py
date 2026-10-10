import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    google_api_key: str | None
    gemini_model: str
    llm_mode: str  # gemini | fake
    llm_min_interval_s: float
    llm_timeout_s: int
    fake_llm_delay_s: float
    model_supervisor: str
    model_workers: str
    database_path: str
    default_max_iterations: int
    max_iterations_limit: int
    task_min_chars: int
    task_max_chars: int
    delegation_task_max_chars: int
    max_parallel_delegations: int
    revision_iterations: int
    approval_timeout_min: int
    supervisor_context_tokens: int
    worker_context_tokens: int
    wiki_mode: str  # live | fake
    wiki_lang: str
    wiki_max_pages: int
    wiki_max_chars_per_page: int
    wiki_cache_ttl_h: int
    wiki_timeout_s: float
    memory_enabled: bool
    memory_recall_limit: int
    prompt_secret: str | None
    rate_limit_runs_per_minute: int
    rate_limit_runs_per_day: int
    run_retention_days: int
    max_queued_jobs: int
    sync_wait_timeout_s: int
    llm_daily_request_limit: int
    price_input_per_m: float
    price_output_per_m: float
    runner_mode: str  # thread | inline (tests)
    sweep_every_s: float
    base_url: str
    frontend_origins: list[str]

    @property
    def fake(self) -> bool:
        return self.llm_mode == "fake"

    def model_label(self, model: str) -> str:
        return "demo" if self.fake else model


def get_settings() -> Settings:
    llm_mode = os.getenv("LLM_MODE", "gemini")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    return Settings(
        google_api_key=os.getenv("GOOGLE_API_KEY") or None,
        gemini_model=model,
        llm_mode=llm_mode,
        llm_min_interval_s=_float("LLM_MIN_INTERVAL_S", 4.0),
        llm_timeout_s=_int("LLM_TIMEOUT_S", 90),
        fake_llm_delay_s=_float("FAKE_LLM_DELAY_S", 0.0),
        model_supervisor=os.getenv("MODEL_SUPERVISOR") or model,
        model_workers=os.getenv("MODEL_WORKERS") or model,
        database_path=os.getenv("DATABASE_PATH", "research.db"),
        default_max_iterations=_int("DEFAULT_MAX_ITERATIONS", 5),
        max_iterations_limit=_int("MAX_ITERATIONS_LIMIT", 8),
        task_min_chars=_int("TASK_MIN_CHARS", 10),
        task_max_chars=_int("TASK_MAX_CHARS", 2000),
        delegation_task_max_chars=_int("DELEGATION_TASK_MAX_CHARS", 1000),
        max_parallel_delegations=_int("MAX_PARALLEL_DELEGATIONS", 2),
        revision_iterations=_int("REVISION_ITERATIONS", 2),
        approval_timeout_min=_int("APPROVAL_TIMEOUT_MIN", 30),
        supervisor_context_tokens=_int("SUPERVISOR_CONTEXT_TOKENS", 6000),
        worker_context_tokens=_int("WORKER_CONTEXT_TOKENS", 5000),
        wiki_mode=os.getenv("WIKI_MODE", "fake" if llm_mode == "fake" else "live"),
        wiki_lang=os.getenv("WIKI_LANG", "en"),
        wiki_max_pages=_int("WIKI_MAX_PAGES", 3),
        wiki_max_chars_per_page=_int("WIKI_MAX_CHARS_PER_PAGE", 6000),
        wiki_cache_ttl_h=_int("WIKI_CACHE_TTL_H", 168),
        wiki_timeout_s=_float("WIKI_TIMEOUT_S", 8),
        memory_enabled=_bool("MEMORY_ENABLED", True),
        memory_recall_limit=_int("MEMORY_RECALL_LIMIT", 3),
        prompt_secret=os.getenv("PROMPT_SECRET") or None,
        rate_limit_runs_per_minute=_int("RATE_LIMIT_RUNS_PER_MINUTE", 3),
        rate_limit_runs_per_day=_int("RATE_LIMIT_RUNS_PER_DAY", 15),
        run_retention_days=_int("RUN_RETENTION_DAYS", 30),
        max_queued_jobs=_int("MAX_QUEUED_JOBS", 5),
        sync_wait_timeout_s=_int("SYNC_WAIT_TIMEOUT_S", 180),
        llm_daily_request_limit=_int("LLM_DAILY_REQUEST_LIMIT", 900),
        price_input_per_m=_float("PRICE_INPUT_PER_M", 0.10),
        price_output_per_m=_float("PRICE_OUTPUT_PER_M", 0.40),
        runner_mode=os.getenv("RUNNER_MODE", "thread"),
        sweep_every_s=_float("SWEEP_EVERY_S", 60),
        base_url=os.getenv("BASE_URL", "http://localhost:8000").rstrip("/"),
        frontend_origins=[
            origin.strip().rstrip("/")
            for origin in os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").split(",")
            if origin.strip()
        ],
    )
