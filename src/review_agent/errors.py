"""The base error for failures that `run_review` reports to the Reviewer."""


class ReviewAgentError(Exception):
    """A failure with a message that the Reviewer can act on."""
