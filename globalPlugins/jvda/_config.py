"""JVDA setting defaults and user-choice provenance."""


DEFAULT_VALUES = {
	"repeatedSymbolLimit": 3,
	"mouseMovementIncrement": 5,
	"tetherJawsToPc": False,
	"capsLockFix": True,
	"suppressModifierDoubleTap": True,
	"skipBlankLinesNotLinkBlock": True,
	"skipBlankLinesBrowseMode": True,
	"suppressTableCoordsArrowing": True,
	"suppressAutocomplete": True,
	"suppressStatusAndProgressPositions": True,
	"suppressAltTabPositionInfo": True,
	"columnSeparatorFix": True,
	"debugLogEnabled": False,
	"jawsVirtualQuickKeys": False,
	"limitPreviousHeadingSpeech": True,
	"spaceLayerEnabled": True,
	"noNvdaKeys": False,
}

# Stored state which is not a user setting: it has no panel control and no
# provenance, so it is deliberately absent from DEFAULT_VALUES.
INTERNAL_STATE = frozenset({"showWelcomeDialog"})

CONFIG_SPEC = {
	"repeatedSymbolLimit": "integer(default=3, min=1, max=20)",
	"mouseMovementIncrement": "integer(default=5, min=1, max=100)",
	"tetherJawsToPc": "boolean(default=False)",
	"capsLockFix": "boolean(default=True)",
	"suppressModifierDoubleTap": "boolean(default=True)",
	"skipBlankLinesNotLinkBlock": "boolean(default=True)",
	"skipBlankLinesBrowseMode": "boolean(default=True)",
	"suppressTableCoordsArrowing": "boolean(default=True)",
	"suppressAutocomplete": "boolean(default=True)",
	"suppressStatusAndProgressPositions": "boolean(default=True)",
	"suppressAltTabPositionInfo": "boolean(default=True)",
	"columnSeparatorFix": "boolean(default=True)",
	"debugLogEnabled": "boolean(default=False)",
	"jawsVirtualQuickKeys": "boolean(default=False)",
	"limitPreviousHeadingSpeech": "boolean(default=True)",
	"spaceLayerEnabled": "boolean(default=True)",
	"noNvdaKeys": "boolean(default=False)",
	# Shown once, then cleared; deliberately outside DEFAULT_VALUES so that
	# applyDefaultValues can never turn the welcome dialog back on.
	"showWelcomeDialog": "boolean(default=True)",
	"isDefault": {
		name: "boolean(default=True)" for name in DEFAULT_VALUES
	},
}


def applyDefaultValues(section):
	"""Update settings which have never been customized to current defaults."""
	isDefault = section["isDefault"]
	for name, defaultValue in DEFAULT_VALUES.items():
		if isDefault[name] and section[name] != defaultValue:
			section[name] = defaultValue


def setUserValue(section, name, value):
	"""Store an explicit user choice, including one equal to the default."""
	if name not in DEFAULT_VALUES:
		raise KeyError(name)
	section[name] = value
	section["isDefault"][name] = False


def resetToDefault(section, name):
	"""Discard a user choice and resume following future default changes."""
	if name not in DEFAULT_VALUES:
		raise KeyError(name)
	section[name] = DEFAULT_VALUES[name]
	section["isDefault"][name] = True
