"""CLI adapter package is not importable on the Opticycle live profile."""

raise ImportError(
    "Alpaca CLI is not importable on the Opticycle live profile; "
    "it is not a live execution channel"
)
