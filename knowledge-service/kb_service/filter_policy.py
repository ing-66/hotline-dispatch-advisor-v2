"""Retrieval filter policy shared by the Knowledge API engine."""

# (payload_key, excluded_value) pairs applied to every normal /retrieval search.
# Document-header points are not business cases and must never enter an
# Evidence Pack. They are filtered at retrieval time only; points are not
# deleted and vectors/IDs are untouched.
RETRIEVAL_EXCLUSIONS: tuple[tuple[str, bool], ...] = (
    ("active", False),
    ("document_header", True),
)
