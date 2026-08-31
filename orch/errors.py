"""Exit codes from SPEC.md §6.1. The exit code never encodes the verdict."""

EXIT_OK = 0
EXIT_BUG = 1
EXIT_CONTRACT = 10
EXIT_PERMISSION = 11
EXIT_BUDGET = 12
EXIT_TIMEOUT = 13
EXIT_VERIFY = 14
EXIT_NO_PROGRESS = 20
EXIT_WALL = 21
EXIT_RATE_LIMIT = 30
EXIT_PREFLIGHT = 40
EXIT_BASELINE = 41
EXIT_GRAPH = 50
EXIT_USAGE = 64


class OrchError(Exception):
    exit_code = EXIT_BUG

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class GraphError(OrchError):
    exit_code = EXIT_GRAPH

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class PreflightError(OrchError):
    exit_code = EXIT_PREFLIGHT


class UsageError(OrchError):
    exit_code = EXIT_USAGE


class BareForbidden(OrchError):
    exit_code = EXIT_BUG

    def __init__(self) -> None:
        super().__init__(
            "adapter refused --bare: that flag forces ANTHROPIC_API_KEY and "
            "blocks subscription OAuth. Use --safe-mode + --setting-sources + "
            "--strict-mcp-config instead."
        )


class SessionError(OrchError):
    exit_code = EXIT_USAGE
