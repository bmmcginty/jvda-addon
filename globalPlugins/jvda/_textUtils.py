"""Pure text classifiers used by JVDA speech presentation."""

import re


_TIME_POSITION_RE = re.compile(
	r"\b\d{1,2}:\d{2}(?::\d{2})?\b"
	r"|\b\d+\s*(?:hours?|minutes?|seconds?)\b",
	re.IGNORECASE,
)
_MEDIA_WORD_RE = re.compile(
	r"\b(?:seek|playback|media|elapsed|duration|remaining|position)\b",
	re.IGNORECASE,
)


def isMediaPosition(*values):
	"""Return whether accessible text looks like a media time position."""
	text = " ".join(str(value) for value in values if value)
	positions = _TIME_POSITION_RE.findall(text)
	return len(positions) >= 2 or bool(positions and _MEDIA_WORD_RE.search(text))
