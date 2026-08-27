import re


STUDENT_ID_PATTERN = re.compile(r"^\d{7}$", re.ASCII)


def is_student_id_used_as_github_id(value):
    """Return True when a GitHub ID field contains a seven-digit student ID."""
    return isinstance(value, str) and STUDENT_ID_PATTERN.fullmatch(value.strip()) is not None
