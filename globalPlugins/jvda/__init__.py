# JVDA: JAWS-style cursor commands for NVDA.

import addonHandler
import api
import browseMode
import config
import ctypes
import ctypes.wintypes
from displayModel import DisplayModelTextInfo
import controlTypes
import globalCommands
import globalPluginHandler
import gui
import inputCore
import keyboardHandler
from keyLabels import localizedKeyLabels
from locationHelper import Point
import mouseHandler
import queue
import re
import review
import scriptHandler
from speech import sayAll
from speech import speech as _speechCore
import speech as _speechModule
import textInfos
import threading
import time
import ui
import winBindings.kernel32
import winKernel
import winUser
import winsound
from winAPI import _powerTracking
import wx
from NVDAObjects.IAccessible import getNVDAObjectFromEvent
from NVDAObjects.window import Window
from speech.commands import PitchCommand
from speech.extensions import filter_speechSequence

from ._config import applyDefaultValues, CONFIG_SPEC, setUserValue
from ._noNvdaKeys import _NoNvdaKeysMixin
from ._patches import _PatchesMixin
from ._spaceLayer import _SpaceLayerMixin
from ._timing import timedClass
from ._gui import (
	_CommandCompatibilityDialog, _tryRegisterSettingsPanel,
	_unregisterSettingsPanel,
	_TrayListDialog, _WindowsListDialog, showWelcomeDialog,
)
from ._virtualWindow import VirtualWindow

addonHandler.initTranslation()

# Register config spec early so it's available even if the GUI panel fails.
config.conf.spec["jvda"] = CONFIG_SPEC
applyDefaultValues(config.conf["jvda"])
JAWS_CURSOR_PITCH_MULTIPLIER = 57 / 64
_DEBUG_LOG_PATH = None  # resolved lazily when logging is enabled


@timedClass
class GlobalPlugin(
	_PatchesMixin, _SpaceLayerMixin, _NoNvdaKeysMixin,
	globalPluginHandler.GlobalPlugin,
):
	"""JAWS-style modes plus a separate NVDA Object Navigation mode.

	Every JAWSKey gesture is bound when the add-on starts, so a command
	answers the same way whether or not a cursor has been used yet this
	session, and reaching plain NVDA behaviour is the job of the
	interception toggle, JAWSKey+grave.

	The bare navigation keys are the exception, and it is forced. A global
	plugin's binding is found before the tree interceptor's
	(nvda/source/scriptHandler.py:186-205), so holding ``upArrow`` in PC
	cursor mode would take the key away from browse mode with no way to
	hand it back. They belong to whichever cursor is reading, and
	``_bindBaseGestures`` is the single place that decides.
	"""

	MODE_PC = "pc"
	MODE_JAWS = "jaws"
	MODE_INVISIBLE = "invisible"
	MODE_TOUCH = "touch"
	MODE_SCRIPT = "objectNavigation"

	scriptCategory = _("JVDA")

	__gestures = {
		# ---- Mode switching ----
		"kb:numpadMinus": "activateJawsCursor",
		"kb:numLock+numpadMinus": "activateJawsCursor",
		"kb:numpadPlus": "deactivateJawsCursor",
		"kb:numLock+numpadPlus": "deactivateJawsCursor",
		"kb:NVDA+numpadMinus": "moveJawsCursorToPCcursor",
		"kb:numLock+NVDA+numpadMinus": "moveJawsCursorToPCcursor",
		"kb:NVDA+numpadPlus": "routePCcursorToJawsCursor",
		"kb:numLock+NVDA+numpadPlus": "routePCcursorToJawsCursor",
		"kb:control+NVDA+numpadMinus": "toggleJawsToPcTether",
		"kb:control+numLock+NVDA+numpadMinus": "toggleJawsToPcTether",
		"kb:NVDA+z": "toggleVirtualPCcursor",
		"kb:NVDA+`": "toggleKeyboardInterception",
		"kb:windows+NVDA+-": "toggleScriptMode",
		"kb:shift+numpadPlus": "activateTouchCursor",
		"kb:numLock+shift+numpadPlus": "activateTouchCursor",
		"kb:NVDA+r": "cycleRestriction",
		"kb:alt+delete": "reportActiveCursor",
		"kb:control+shift+NVDA+c": "reportCursorType",
		"kb:NVDA+delete": "routeVirtualToPCcursor",
		"kb:control+NVDA+delete": "routePCcursorToVirtual",
		"kb:control+f": "findInVirtualBuffer",
		"kb:f3": "findNextInVirtualBuffer",
		"kb:shift+f3": "findPreviousInVirtualBuffer",
		"kb:NVDA+5": "reportColor",
		"kb:control+windows+k": "setTemporaryPlaceMarker",
		# ---- JAWS table reading aliases ----
		"kb:alt+control+numpad5": "tableSpeakCell",
		"kb:windows+alt+upArrow": "tablePreviousRowAndRead",
		"kb:windows+alt+downArrow": "tableNextRowAndRead",
		"kb:windows+alt+leftArrow": "tablePreviousColumnAndRead",
		"kb:windows+alt+rightArrow": "tableNextColumnAndRead",
		"kb:NVDA+shift+upArrow": "tableSpeakRow",
		"kb:NVDA+shift+numpad5": "tableSpeakColumn",
		"kb:alt+control+shift+leftArrow": "tableFirstColumn",
		"kb:alt+control+shift+rightArrow": "tableLastColumn",
		"kb:alt+control+shift+upArrow": "tableFirstRow",
		"kb:alt+control+shift+downArrow": "tableLastRow",
		"kb:alt+control+home": "tableFirstCell",
		"kb:alt+control+end": "tableLastCell",
		# ---- Temporary speech rate ----
		"kb:control+alt+pageUp": "increaseTemporarySpeechRate",
		"kb:control+alt+pageDown": "decreaseTemporarySpeechRate",
		# ---- Physical numpad navigation passthrough ----
		"kb:numpadDelete": "passNumpadNavigationKey",
		"kb:numpad1": "passNumpadNavigationKey",
		"kb:numpad2": "passNumpadNavigationKey",
		"kb:numpad3": "passNumpadNavigationKey",
		"kb:numpad4": "passNumpadNavigationKey",
		"kb:numpad5": "currentCharacter",
		"kb:numpad6": "passNumpadNavigationKey",
		"kb:numpad7": "passNumpadNavigationKey",
		"kb:numpad8": "passNumpadNavigationKey",
		"kb:numpad9": "passNumpadNavigationKey",
		# ---- Windows / tray ----
		"kb:NVDA+f10": "openWindowsList",
		"kb:NVDA+f11": "openSystemTrayIconsList",
		"kb:NVDA+alt+w": "virtualizeCurrentWindow",
		"kb:NVDA+alt+shift+w": "virtualizeCurrentWindowRaw",
		"kb:NVDA+shift+f1": "debugCurrentControl",
		"kb:control+shift+NVDA+f1": "reportDiagnostics",
		"kb:control+shift+NVDA+f2": "openCommandCompatibility",
	}

	# Gestures bound only while a review or Object Navigation mode is active.
	# In PC mode the bare arrow / numpad keys behave normally.
	_MODE_GESTURES = {
		"kb:upArrow": "previousLine",
		"kb:downArrow": "nextLine",
		"kb:leftArrow": "previousCharacter",
		"kb:rightArrow": "nextCharacter",
		"kb:control+home": "topOfWindow",
		"kb:control+end": "bottomOfWindow",
		"kb:pageUp": "reviewPreviousPage",
		"kb:pageDown": "reviewNextPage",
	}

	# Optional JAWS quick-key overrides where NVDA's native letter has a
	# different meaning. All matching Shift reverse variants are included.
	_VIRTUAL_QUICK_GESTURES = {
		"kb:a": "jawsVirtualQuickKey",
		"kb:shift+a": "jawsVirtualQuickKey",
		"kb:o": "jawsVirtualQuickKey",
		"kb:shift+o": "jawsVirtualQuickKey",
		"kb:k": "moveToTemporaryPlaceMarker",
		"kb:shift+k": "moveToTemporaryPlaceMarker",
		"kb:t": "jawsVirtualQuickKey",
		"kb:shift+t": "jawsVirtualQuickKey",
		"kb:z": "jawsVirtualQuickKey",
		"kb:shift+z": "jawsVirtualQuickKey",
	}

	_VIRTUAL_QUICK_SCRIPTS = {
		"a": "RadioButton",
		"o": "Article",
		"t": "Table",
		"z": "Grouping",
	}

	# NVDA can include an ancestor heading's text when reporting a heading
	# reached in reverse. Reporting the destination object instead of its
	# full text range avoids that extra text.
	_PREVIOUS_HEADING_GESTURES = {
		"kb:shift+h": "previousHeadingOnly",
	}

	_TOUCH_GESTURES = {
		"kb:rightArrow": "touchNextElement",
		"kb:tab": "touchNextElement",
		"kb:leftArrow": "touchPreviousElement",
		"kb:shift+tab": "touchPreviousElement",
		"kb:downArrow": "touchNextElementByType",
		"kb:upArrow": "touchPreviousElementByType",
		"kb:control+home": "touchFirstElement",
		"kb:control+end": "touchLastElement",
		"kb:pageUp": "touchPreviousMovementType",
		"kb:pageDown": "touchNextMovementType",
		"kb:space": "touchActivate",
		"kb:enter": "touchActivate",
		"kb:applications": "touchRightClick",
		"kb:shift+f10": "touchRightClick",
		"kb:NVDA+upArrow": "touchReportCurrentElement",
		"kb:NVDA+numpad5": "touchReportCurrentElement",
		"kb:NVDA+numpadPlus": "touchRouteToFocus",
		"kb:numpadMultiply": "toggleTouchAdvancedNavigation",
		"kb:numLock+numpadMultiply": "toggleTouchAdvancedNavigation",
		"kb:numpadDivide": "activateTouchTextReview",
		"kb:numLock+numpadDivide": "activateTouchTextReview",
		"kb:NVDA+enter": "activateTouchTextReview",
	}

	_TOUCH_TEXT_GESTURES = {
		"kb:escape": "deactivateTouchTextReview",
		"kb:rightArrow": "touchTextNextCharacter",
		"kb:tab": "touchTextNextCharacter",
		"kb:leftArrow": "touchTextPreviousCharacter",
		"kb:shift+tab": "touchTextPreviousCharacter",
		"kb:control+rightArrow": "touchTextNextWord",
		"kb:control+leftArrow": "touchTextPreviousWord",
		"kb:downArrow": "touchTextNextLine",
		"kb:upArrow": "touchTextPreviousLine",
		"kb:home": "touchTextStartOfLine",
		"kb:end": "touchTextEndOfLine",
		"kb:numpad5": "touchTextCurrentCharacter",
	}

	_TOUCH_MOVEMENT_TYPES = (
		("all", None),
		("button", controlTypes.Role.BUTTON),
		("check box", controlTypes.Role.CHECKBOX),
		("combo box", controlTypes.Role.COMBOBOX),
		("edit", controlTypes.Role.EDITABLETEXT),
		("heading", controlTypes.Role.HEADING),
		("link", controlTypes.Role.LINK),
		("list", controlTypes.Role.LIST),
		("table", controlTypes.Role.TABLE),
	)

	# Physical-keyboard JAWS cursor commands. These are not bound in
	# Object Navigation mode, where normal Ctrl/navigation keys remain
	# available for object navigation.
	_JAWS_GESTURES = {
		"kb:control+leftArrow": "previousWord",
		"kb:control+rightArrow": "nextWord",
		"kb:NVDA+leftArrow": "previousWord",
		"kb:NVDA+rightArrow": "nextWord",
		"kb:NVDA+upArrow": "currentLine",
		"kb:NVDA+downArrow": "sayAll",
		# JAWSKey+numpad uses the JAWS reading grid rather than NVDA's
		# object-navigator commands.
		"kb:NVDA+numpad1": "previousCharacter",
		"kb:NVDA+numpad2": "currentCharacter",
		"kb:NVDA+numpad3": "nextCharacter",
		"kb:NVDA+numpad4": "previousWord",
		"kb:NVDA+numpad5": "currentWord",
		"kb:NVDA+numpad6": "nextWord",
		"kb:NVDA+numpad7": "previousLine",
		"kb:NVDA+numpad8": "currentLine",
		"kb:NVDA+numpad9": "nextLine",
		"kb:control+numpad5": "currentParagraph",
		"kb:alt+numpadMinus": "previousSentence",
		"kb:numLock+alt+numpadMinus": "previousSentence",
		"kb:alt+numpad5": "currentSentence",
		"kb:numLock+alt+numpad5": "currentSentence",
		"kb:alt+numpadPlus": "nextSentence",
		"kb:numLock+alt+numpadPlus": "nextSentence",
		"kb:NVDA+a": "sayAll",
		"kb:NVDA+shift+a": "saySelectedText",
		"kb:home": "startOfLine",
		"kb:end": "endOfLine",
		"kb:NVDA+home": "sayToCursor",
		"kb:NVDA+pageUp": "sayFromCursor",
		"kb:NVDA+end": "sayTopLineOfWindow",
		"kb:NVDA+pageDown": "sayBottomLineOfWindow",
		"kb:NVDA+shift+b": "reportBatteryLevel",
		"kb:NVDA+shift+v": "virtualizeCurrentControl",
		"kb:NVDA+shift+,": "reportCurrentAccessKey",
		"kb:NVDA+tab": "reportWindowPromptAndText",
		"kb:NVDA+t": "reportWindowTitle",
		"kb:NVDA+b": "readBoxInTabOrder",
		"kb:NVDA+c": "readWordInContext",
		"kb:NVDA+e": "reportDefaultButton",
		"kb:NVDA+f": "reportFont",
		"kb:control+NVDA+f": "find",
		"kb:NVDA+f3": "findNext",
		"kb:NVDA+shift+f3": "findPrevious",
		"kb:NVDA+2": "cycleTypingEcho",
		"kb:NVDA+3": "passNextKeyThrough",
		"kb:control+NVDA+n": "toggleJawsVirtualQuickKeys",
		"kb:NVDA+4": "activateAtJawsCursor",
		"kb:NVDA+d": "openDictionaryManager",
		"kb:NVDA+v": "openQuickSettings",
		"kb:NVDA+w": "unavailableWindowKeysHelp",
		"kb:NVDA+q": "reportApplicationFileName",
		"kb:NVDA+s": "unavailableJawsCommand",
		"kb:NVDA+g": "unavailableJawsCommand",
		"kb:control+shift+NVDA+j": "unavailableJawsCommand",
		"kb:NVDA+f1": "contextSensitiveHelp",
		"kb:NVDA+f2": "unavailableJawsCommand",
		"kb:NVDA+7": "unavailableJawsCommand",
		"kb:NVDA+0": "unavailableJawsCommand",
		"kb:NVDA+f4": "showShutdownDialog",
		"kb:NVDA+f5": "listFormFields",
		"kb:NVDA+f6": "listHeadings",
		"kb:NVDA+f7": "listLinks",
		"kb:control+NVDA+b": "listButtons",
		"kb:control+NVDA+r": "listLandmarks",
		"kb:NVDA+f9": "unavailableJawsCommand",
		"kb:NVDA+6": "openSettingsCenter",
		"kb:NVDA+f12": "reportSystemTime",
		"kb:control+NVDA+f12": "reportSystemTimeWithSeconds",
		"kb:NVDA+escape": "refreshScreen",
		"kb:NVDA+x": "reportFrameAtCursor",
		"kb:numpadDivide": "leftMouseClickAtJawsCursor",
		"kb:numLock+numpadDivide": "leftMouseClickAtJawsCursor",
		"kb:numpadMultiply": "rightMouseClickAtJawsCursor",
		"kb:numLock+numpadMultiply": "rightMouseClickAtJawsCursor",
		"kb:NVDA+numpadDivide": "toggleLeftMouseButtonAtJawsCursor",
		"kb:numLock+NVDA+numpadDivide": "toggleLeftMouseButtonAtJawsCursor",
		"kb:NVDA+numpadMultiply": "toggleRightMouseButtonAtJawsCursor",
		"kb:numLock+NVDA+numpadMultiply": "toggleRightMouseButtonAtJawsCursor",
		"kb:control+windows+8": "toggleLeftMouseButtonAtJawsCursor",
		"kb:control+windows+9": "toggleRightMouseButtonAtJawsCursor",
		"kb:alt+shift+upArrow": "moveMouseUp",
		"kb:alt+shift+downArrow": "moveMouseDown",
		"kb:alt+shift+leftArrow": "moveMouseLeft",
		"kb:alt+shift+rightArrow": "moveMouseRight",
	}

	# Explicit profiles follow NVDA's configured desktop or laptop keyboard
	# layout. Keeping these separate makes conflicting JAWS gestures auditable.
	_JAWS_DESKTOP_GESTURES = {
		"kb(desktop):NVDA+h": "hotKeyHelp",
		"kb(desktop):NVDA+j": "showNVDAMenu",
		"kb(desktop):NVDA+8": "unavailableJawsCommand",
		"kb(desktop):NVDA+9": "unavailableJawsCommand",
	}

	_JAWS_LAPTOP_GESTURES = {
		# Cursor switching and always-safe reading-grid navigation.
		"kb(laptop):NVDA+;": "deactivateJawsCursor",
		"kb(laptop):NVDA+p": "activateJawsCursor",
		"kb(laptop):NVDA+[": "moveJawsCursorToPCcursor",
		"kb(laptop):NVDA+'": "routePCcursorToJawsCursor",
		"kb(laptop):control+NVDA+[": "toggleJawsToPcTether",
		"kb(laptop):shift+NVDA+;": "activateTouchCursor",
		"kb(laptop):NVDA+u": "previousLine",
		"kb(laptop):NVDA+i": "currentLine",
		"kb(laptop):NVDA+o": "nextLine",
		"kb(laptop):NVDA+k": "currentWord",
		"kb(laptop):NVDA+l": "nextWord",
		"kb(laptop):NVDA+m": "previousCharacter",
		"kb(laptop):NVDA+,": "currentCharacter",
		"kb(laptop):NVDA+.": "nextCharacter",
		# Laptop-only reading and mouse commands.
		"kb(laptop):control+NVDA+u": "previousParagraph",
		"kb(laptop):control+NVDA+i": "currentParagraph",
		"kb(laptop):control+NVDA+o": "nextParagraph",
		"kb(laptop):NVDA+y": "previousSentence",
		"kb(laptop):NVDA+h": "currentSentence",
		"kb(laptop):NVDA+n": "nextSentence",
		"kb(laptop):NVDA+shift+y": "sayTopLineOfWindow",
		"kb(laptop):NVDA+shift+n": "sayBottomLineOfWindow",
		"kb(laptop):NVDA+shift+j": "sayToCursor",
		"kb(laptop):NVDA+shift+l": "sayFromCursor",
		"kb(laptop):NVDA+j": "previousWord",
		"kb(laptop):NVDA+8": "leftMouseClickAtJawsCursor",
		"kb(laptop):NVDA+9": "rightMouseClickAtJawsCursor",
		"kb(laptop):NVDA+shift+8": "dragAndDropAtJawsCursor",
		"kb(laptop):control+NVDA+9": "rightMouseClickAtJawsCursor",
	}

	# The JAWSKey+Space prefix. It is bound only while the layer setting is
	# on, so switching the setting off hands NVDA+Space back to NVDA's own
	# browse/focus mode toggle. JAWSKey+Z remains JVDA's Virtual PC Cursor
	# toggle and is the documented replacement while the layer is on.
	_SPACE_LAYER_GESTURES = {
		"kb:NVDA+space": "spaceLayer",
	}

	# ---- Layered JAWSKey+Space commands ----
	# Each table maps a layer name to the JVDA method implementing each key of
	# that layer, keyed by NVDA gesture spelling. A key is nested under its
	# layer because one key means different things in different sublayers:
	# upArrow raises the JAWS volume in the JAWS volume sublayer and restores
	# the sound balance in the sound balance sublayer. Keys which appear in
	# _spaceLayer.LAYER_INVENTORY but not here report "command invalid"; keys
	# in neither report "command unassigned".
	_LAYER_COMMANDS = {
		"basic": {
			"c": "layerViewClipboardText",
			"d": "layerToggleAudioDucking",
			"f11": "layerScreenShade",
			"j": "layerCommandsSearch",
			"l": "layerLockKeyboard",
			"printScreen": "layerScreenShade",
			"s": "layerMuteSynthesizer",
			"shift+/": "layerHelp",
			"shift+s": "layerSpeechOnDemandToggle",
		},
	}

	_LAYER_VOLUME_COMMANDS = {
		"volume": {
			"shift+/": "layerHelp",
		},
		"volumeJaws": {
			"downArrow": "layerVolumeDownSmall",
			"leftArrow": "layerVolumeDownSmall",
			"numpad2": "layerVolumeDownSmall",
			"numpad3": "layerVolumeDownLarge",
			"numpad4": "layerVolumeDownSmall",
			"numpad6": "layerVolumeUpSmall",
			"numpad8": "layerVolumeUpSmall",
			"numpad9": "layerVolumeUpLarge",
			"pageDown": "layerVolumeDownLarge",
			"pageUp": "layerVolumeUpLarge",
			"rightArrow": "layerVolumeUpSmall",
			"upArrow": "layerVolumeUpSmall",
			"shift+/": "layerHelp",
		},
		"volumeBalance": {
			"leftArrow": "layerSoundBalanceLeft",
			"numpad4": "layerSoundBalanceLeft",
			"numpad6": "layerSoundBalanceRight",
			"numpad8": "layerSoundBalanceRestore",
			"rightArrow": "layerSoundBalanceRight",
			"upArrow": "layerSoundBalanceRestore",
			"shift+/": "layerHelp",
		},
		"volumeSoundCard": {
			"downArrow": "layerNextSoundCard",
			"numpad2": "layerNextSoundCard",
			"numpad8": "layerPreviousSoundCard",
			"upArrow": "layerPreviousSoundCard",
			"shift+/": "layerHelp",
		},
	}

	_LAYER_TABLE_COMMANDS = {
		"table": {
			",": "layerTableSayCell",
			".": "layerTableNextColumn",
			"downArrow": "layerTableNextRow",
			"end": "layerTableLastColumn",
			"home": "layerTableFirstColumn",
			"leftArrow": "layerTablePreviousColumn",
			"m": "layerTablePreviousColumn",
			"n": "layerTableNextRow",
			"numpad1": "layerTableLastColumn",
			"numpad2": "layerTableNextRow",
			"numpad4": "layerTablePreviousColumn",
			"numpad5": "layerTableSayCell",
			"numpad6": "layerTableNextColumn",
			"numpad7": "layerTableFirstColumn",
			"numpad8": "layerTablePreviousRow",
			"rightArrow": "layerTableNextColumn",
			"upArrow": "layerTablePreviousRow",
			"y": "layerTablePreviousRow",
			"alt+,": "layerTableSayCell",
			"control+downArrow": "layerTableLastRow",
			"control+end": "layerTableLastCell",
			"control+home": "layerTableFirstCell",
			"control+leftArrow": "layerTableFirstColumn",
			"control+numpad1": "layerTableLastCell",
			"control+numpad2": "layerTableLastRow",
			"control+numpad4": "layerTableFirstColumn",
			"control+numpad6": "layerTableLastColumn",
			"control+numpad7": "layerTableFirstCell",
			"control+numpad8": "layerTableFirstRow",
			"control+rightArrow": "layerTableLastColumn",
			"control+upArrow": "layerTableFirstRow",
			"NVDA+,": "layerTableSayCell",
			"shift+,": "layerTableSpeakColumn",
			"shift+/": "layerHelp",
			"shift+numpad3": "layerTableSayAllColumn",
			"shift+numpad5": "layerTableSpeakColumn",
			"shift+numpad8": "layerTableSpeakRow",
			"shift+numpad9": "layerTableSayAllRow",
			"shift+pageDown": "layerTableSayAllColumn",
			"shift+pageUp": "layerTableSayAllRow",
			"shift+upArrow": "layerTableSpeakRow",
			"windows+,": "layerTableSpeakRow",
			"windows+.": "layerTableSpeakColumn",
			"alt+control+downArrow": "layerTableNextRow",
			"alt+control+end": "layerTableLastCell",
			"alt+control+home": "layerTableFirstCell",
			"alt+control+leftArrow": "layerTablePreviousColumn",
			"alt+control+numpad1": "layerTableLastCell",
			"alt+control+numpad2": "layerTableNextRow",
			"alt+control+numpad4": "layerTablePreviousColumn",
			"alt+control+numpad5": "layerTableSayCell",
			"alt+control+numpad6": "layerTableNextColumn",
			"alt+control+numpad7": "layerTableFirstCell",
			"alt+control+numpad8": "layerTablePreviousRow",
			"alt+control+rightArrow": "layerTableNextColumn",
			"alt+control+upArrow": "layerTablePreviousRow",
			"alt+shift+,": "layerTableSayCell",
			"alt+shift+.": "layerTableNextColumn",
			"alt+shift+m": "layerTablePreviousColumn",
			"alt+shift+n": "layerTableNextRow",
			"alt+shift+y": "layerTablePreviousRow",
			"shift+NVDA+numpad3": "layerTableSayAllColumn",
			"shift+NVDA+numpad5": "layerTableSpeakColumn",
			"shift+NVDA+numpad8": "layerTableSpeakRow",
			"shift+NVDA+numpad9": "layerTableSayAllRow",
			"shift+NVDA+pageDown": "layerTableSayAllColumn",
			"shift+NVDA+pageUp": "layerTableSayAllRow",
			"shift+NVDA+upArrow": "layerTableSpeakRow",
			"alt+control+shift+downArrow": "layerTableLastRow",
			"alt+control+shift+leftArrow": "layerTableFirstColumn",
			"alt+control+shift+numpad2": "layerTableLastRow",
			"alt+control+shift+numpad4": "layerTableFirstColumn",
			"alt+control+shift+numpad6": "layerTableLastColumn",
			"alt+control+shift+numpad8": "layerTableFirstRow",
			"alt+control+shift+rightArrow": "layerTableLastColumn",
			"alt+control+shift+upArrow": "layerTableFirstRow",
		},
	}

	# JAWSKey is NVDA/Insert in this add-on. Its commands must work in
	# every cursor mode, including PC cursor; otherwise NVDA's unrelated
	# global bindings win (for example, NVDA+Q quits NVDA). Copying them
	# here binds them through NVDA's own class gesture map, before any
	# cursor has been used. Bare gestures cannot join them: see
	# ``_bindBaseGestures``.
	for _gestureMap in (
		_JAWS_GESTURES,
		_JAWS_DESKTOP_GESTURES,
		_JAWS_LAPTOP_GESTURES,
	):
		for _gesture, _script in _gestureMap.items():
			if "NVDA" in _gesture:
				__gestures[_gesture] = _script
	del _gestureMap, _gesture, _script

	# JAWS restriction cycle, in its spoken order. A restriction change
	# never moves the cursor; it takes effect when the cursor next moves.
	_RESTRICTIONS = (
		"unrestricted", "application", "real", "current", "focus",
		"frame",
	)

	# CapsLock double-tap state machine (used by _PatchesMixin).
	_CS_IDLE = 0
	_CS_FIRST_DOWN = 1
	_CS_FIRST_UP = 2
	_CS_SECOND_DOWN = 3

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def __init__(self):
		super().__init__()
		self._mode = self.MODE_PC
		self._reviewPositionBeforeJawsCursor = None
		self._reviewModeBeforeJawsCursor = None
		self._jawsCursorPosition = None
		self._invisibleCursorPosition = None
		self._touchCursorObject = None
		self._navigatorObjectBeforeTouchCursor = None
		self._touchMovementIndex = 0
		self._touchAdvancedNavigation = False
		self._touchTextReview = False
		self._reviewModeBeforeTouchText = None
		self._preserveRoutedPCcursor = False
		self._tetherUpdateInProgress = False
		self._navigatorObjectBeforeJawsCursor = None
		self._leftButtonLockedByJvda = False
		self._rightButtonLockedByJvda = False
		self._dragSource = None
		self._restrictionIndex = self._RESTRICTIONS.index("focus")
		self._restrictionPending = False
		self._virtualRestriction = None
		self._virtualRestrictionTree = None
		self._virtualRestrictionRoot = None
		self._virtualRestrictionBounds = None
		self._virtualRestrictionSuppressedRoot = None
		self._originalBrowseModeSetSelection = None
		self._browseModeSetSelectionWrapper = None
		self._keyboardInterceptionEnabled = True
		self._virtualQuickKeysSuspended = False
		self._temporaryPlaceMarker = None
		self._temporaryPlaceMarkerTree = None
		# JAWSKey+Space layer state. It is set up before _bindBaseGestures so
		# that the prefix script and the layer's raw keyboard handler can
		# never see a half-built plugin.
		self._layerStack = []
		self._layerSwallowedKeys = set()
		self._layerDeadline = None
		self._layerTimeoutPending = False
		self._layerHelpTarget = "basic"
		self._layerSoundCardDevices = None
		self._noNvdaKeysSwallowed = set()
		self._bindBaseGestures()
		self._temporarySpeechRate = False
		self._temporarySpeechRateWindow = None
		self._logQueue = queue.Queue()
		self._logThread = threading.Thread(
			target=self._writeLog, daemon=True,
		)
		self._logThread.start()
		self._log("JVDA started")
		_tryRegisterSettingsPanel()
		self._welcomeHandlerRegistered = False
		self._scheduleWelcomeDialog()
		self._patchRepeatedSymbols()
		self._patchDisplayModelCollapsedRanges()
		self._patchSpeechSymbolsDialog()
		self._patchCapsLockFix()
		self._log("CapsLock fix patched")
		self._patchSpaceLayer()
		# Registered after the layer, so that layer keys are consumed first.
		self._patchNoNvdaKeys()
		self._patchColumnSeparator()
		self._patchNotLinkBlockSkipBlankLines()
		self._patchLineMoveSkipBlankLines()
		self._patchSuppressTableCoords()
		self._patchSuppressAutocomplete()
		self._patchSuppressStatusAndProgressPositions()
		self._patchImprovedInputHelp()
		self._patchJawsCursorReviewFollow()
		self._patchVirtualCursorRestriction()
		filter_speechSequence.register(self._lowerPitchForJawsCursor)

	def terminate(self):
		filter_speechSequence.unregister(self._lowerPitchForJawsCursor)
		self._unpatchNoNvdaKeys()
		self._unpatchSpaceLayer()
		self._unpatchDisplayModelCollapsedRanges()
		self._unpatchRepeatedSymbols()
		self._unpatchSpeechSymbolsDialog()
		self._unpatchCapsLockFix()
		self._unpatchColumnSeparator()
		self._unpatchNotLinkBlockSkipBlankLines()
		self._unpatchLineMoveSkipBlankLines()
		self._unpatchSuppressTableCoords()
		self._unpatchSuppressStatusAndProgressPositions()
		self._unpatchSuppressAutocomplete()
		self._unpatchImprovedInputHelp()
		self._resetTemporarySpeechRate()
		self._releaseLockedMouseButtons()
		self._setMode(self.MODE_PC)
		self._clearVirtualCursorRestriction()
		self._unpatchVirtualCursorRestriction()
		self._unpatchJawsCursorReviewFollow()
		self._unregisterWelcomeHandler()
		_unregisterSettingsPanel()
		self._log("JVDA stopped")
		self._logQueue.put(None)
		self._logThread.join(timeout=1)
		super().terminate()

	# ------------------------------------------------------------------
	# First-run message
	# ------------------------------------------------------------------

	def _scheduleWelcomeDialog(self):
		"""Arrange for the first-run message once NVDA has finished starting.

		The message must not appear while NVDA is still starting: speech and
		the main frame are not ready, and a modal dialog would block the rest
		of startup. When the add-on is loaded outside startup (a plugin
		reload, for instance) nothing is shown and the message waits for the
		next NVDA start."""
		try:
			if not config.conf["jvda"]["showWelcomeDialog"]:
				return
			import core

			core.postNvdaStartup.register(self._onNvdaStartupForWelcome)
			self._welcomeHandlerRegistered = True
		except Exception as error:
			self._log(f"Unable to schedule the welcome dialog: {error!r}")

	def _unregisterWelcomeHandler(self):
		if not getattr(self, "_welcomeHandlerRegistered", False):
			return
		try:
			import core

			core.postNvdaStartup.unregister(self._onNvdaStartupForWelcome)
		except Exception:
			pass
		self._welcomeHandlerRegistered = False

	def _onNvdaStartupForWelcome(self):
		"""Record that the message has been shown, then show it."""
		self._unregisterWelcomeHandler()
		try:
			config.conf["jvda"]["showWelcomeDialog"] = False
			config.conf.save()
		except Exception as error:
			# Without a stored flag the message would return on every start,
			# so give up on showing it rather than nag.
			self._log(f"Unable to record the welcome dialog: {error!r}")
			return
		self._log("Showing the JVDA welcome dialog")
		wx.CallAfter(showWelcomeDialog)

	# ------------------------------------------------------------------
	# Logging
	# ------------------------------------------------------------------

	def _writeLog(self):
		while (message := self._logQueue.get()) is not None:
			if not config.conf["jvda"]["debugLogEnabled"]:
				continue
			global _DEBUG_LOG_PATH
			if _DEBUG_LOG_PATH is None:
				import os
				_DEBUG_LOG_PATH = os.path.join(
					os.environ.get("TEMP", "."), "jvda.log",
				)
			try:
				with open(
					_DEBUG_LOG_PATH, "a", encoding="utf-8",
				) as logFile:
					logFile.write(message + "\n")
			except OSError:
				pass

	def _log(self, message):
		self._logQueue.put(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}")

	def _describePosition(self, position):
		try:
			point = position.pointAtStart
			pointText = f"({point.x}, {point.y})"
		except Exception:
			pointText = "unavailable"
		try:
			text = position.copy()
			text.expand(textInfos.UNIT_LINE)
			line = repr(text.text)
		except Exception:
			line = "unavailable"
		return (
			f"type={type(position).__name__} "
			f"obj={type(position.obj).__name__} "
			f"start={position.start} end={position.end} "
			f"point={pointText} line={line}"
		)

	def _describeBrowseModeState(self):
		"""Return non-sensitive state useful for cursor-transition logs."""
		try:
			focus = api.getFocusObject()
			treeInterceptor = focus.treeInterceptor
			return (
				f"focus={type(focus).__name__} role={focus.role} "
				f"treeInterceptor={type(treeInterceptor).__name__} "
				f"passThrough={getattr(treeInterceptor, 'passThrough', None)}"
			)
		except Exception as error:
			return f"browse-mode state unavailable: {error!r}"

	# ------------------------------------------------------------------
	# Alt+Tab position-info suppression
	# ------------------------------------------------------------------

	@staticmethod
	def _isAltTabWindow(obj):
		"""Return True if *obj* or any ancestor is an Alt+Tab window."""
		# Check the object and its ancestors (up to 5 levels).
		for _ in range(5):
			wc = getattr(obj, "windowClassName", "")
			if wc in ("MultitaskingViewFrame", "TaskSwitcherWnd"):
				return True
			if hasattr(obj, "UIAElement"):
				try:
					cn = obj.UIAElement.cachedClassName
				except Exception:
					cn = ""
				if cn in (
					"MultitaskingViewFrame",
					"Windows.UI.Input.InputSite.WindowClass",
				):
					return True
			try:
				obj = obj.parent
			except Exception:
				break
			if obj is None:
				break
		return False

	def event_foreground(self, obj, nextHandler):
		nextHandler()
		# Alt+Tab makes its switcher foreground before the user releases
		# Alt to select a window. Do not reset until then.
		if (
			not (winUser.getAsyncKeyState(winUser.VK_MENU) & 32768)
			and self._temporarySpeechRateWindow
			!= winUser.getForegroundWindow()
		):
			self._resetTemporarySpeechRate()

	def event_caret(self, obj, nextHandler):
		nextHandler()
		self._updateTetheredJawsCursor()

	def event_mouseMove(self, obj, nextHandler, x, y):
		# JAWS layers are keyboard-modal: reaching for the mouse ends one.
		self._closeLayer()
		nextHandler()

	def event_gainFocus(self, obj, nextHandler):
		# A JAWSKey+Space layer belongs to the window it was opened in.
		self._closeLayer()
		if (
			self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE)
			and self._RESTRICTIONS[self._restrictionIndex] != "unrestricted"
		):
			# Focus can also change the frame, current/real window, or owning
			# application. Keep review still until movement resolves the new root.
			self._restrictionPending = True
		if config.conf["jvda"]["suppressAltTabPositionInfo"]:
			if self._isAltTabWindow(obj):
				presConf = config.conf["presentation"]
				fmtConf = config.conf["documentFormatting"]
				oldPos = presConf["reportObjectPositionInformation"]
				oldCoords = fmtConf["reportTableCellCoords"]
				if oldPos:
					presConf["reportObjectPositionInformation"] = False
				if oldCoords:
					fmtConf["reportTableCellCoords"] = False
				try:
					nextHandler()
				finally:
					if oldPos:
						presConf[
							"reportObjectPositionInformation"
						] = oldPos
					if oldCoords:
						fmtConf["reportTableCellCoords"] = oldCoords
				self._updateTetheredJawsCursor()
				self._updateVirtualCursorRestrictionForFocus(obj)
				return
		nextHandler()
		self._updateTetheredJawsCursor()
		self._updateVirtualCursorRestrictionForFocus(obj)

	# ------------------------------------------------------------------
	# Temporary speech rate
	# ------------------------------------------------------------------

	def _resetTemporarySpeechRate(self):
		"""Restore the configured rate after a foreground-window change."""
		if not self._temporarySpeechRate:
			return
		self._temporarySpeechRate = False
		self._temporarySpeechRateWindow = None
		import synthDriverHandler

		synth = synthDriverHandler.getSynth()
		if synth is None or not synth.isSupported("rate"):
			return
		defaultRate = config.conf["speech"][synth.name].get("rate")
		if defaultRate is not None:
			synth.rate = defaultRate

	def script_showNVDAMenu(self, gesture):
		"""Show the NVDA menu."""
		globalCommands.commands.script_showGui(gesture)

	def script_toggleKeyboardInterception(self, gesture):
		"""Toggle JVDA keyboard command interception."""
		self._keyboardInterceptionEnabled = (
			not self._keyboardInterceptionEnabled
		)
		# Close any open JAWSKey+Space layer before announcing the new state,
		# so the layer's exit tones cannot run over the announcement.
		self._closeLayer()
		self._rebindGestures()
		ui.message(
			_("JVDA keyboard commands {}")
			.format(_("on") if self._keyboardInterceptionEnabled else _("off")),
		)

	def _rebindGestures(self):
		"""Bind every gesture the current settings and mode call for."""
		self.clearGestureBindings()
		self._bindBaseGestures()
		if self._keyboardInterceptionEnabled and self._mode == self.MODE_TOUCH:
			self.bindGestures(self._TOUCH_GESTURES)
			if self._touchTextReview:
				self.bindGestures(self._TOUCH_TEXT_GESTURES)
		# Keep this gesture active so keyboard interception can be restored.
		self.bindGesture("kb:NVDA+`", "toggleKeyboardInterception")

	def _applySettingsChange(self):
		"""Apply a settings change that decides which gestures are bound.

		The JAWSKey+Space layer and the JAWS-only keyboard are switched on and
		off from the settings panel without an NVDA restart, so the panel calls
		this method after saving."""
		self._closeLayer(silent=True)
		self._rebindGestures()

	def _changeTemporarySpeechRate(self, change):
		"""Change the live synth rate without saving it to configuration."""
		import synthDriverHandler

		synth = synthDriverHandler.getSynth()
		if synth is None or not synth.isSupported("rate"):
			return
		synth.rate = max(0, min(100, synth.rate + change))
		self._temporarySpeechRate = True
		self._temporarySpeechRateWindow = winUser.getForegroundWindow()
		ui.message(_("Speech rate {}%").format(synth.rate))

	def script_increaseTemporarySpeechRate(self, gesture):
		"""Increase the temporary speech rate by 5 percent."""
		self._changeTemporarySpeechRate(5)

	def script_decreaseTemporarySpeechRate(self, gesture):
		"""Decrease the temporary speech rate by 5 percent."""
		self._changeTemporarySpeechRate(-5)

	# ------------------------------------------------------------------
	# Pitch filter
	# ------------------------------------------------------------------

	def _lowerPitchForJawsCursor(self, sequence):
		if self._mode not in (self.MODE_JAWS, self.MODE_INVISIBLE):
			return sequence
		loweredSequence = [
			PitchCommand(multiplier=JAWS_CURSOR_PITCH_MULTIPLIER),
		]
		for item in sequence:
			if isinstance(item, PitchCommand):
				loweredSequence.append(
					PitchCommand(
						multiplier=item.multiplier
						* JAWS_CURSOR_PITCH_MULTIPLIER,
					),
				)
			else:
				loweredSequence.append(item)
		loweredSequence.append(PitchCommand())
		return loweredSequence

	def _resetJawsCursorPitch(self):
		"""Reset pitch after canceling JAWS-cursor speech.

		Canceling an utterance can prevent its trailing PitchCommand from
		reaching a synthesizer, leaving its runtime pitch lowered.
		"""
		_speechModule.speak([PitchCommand()])

	# ------------------------------------------------------------------
	# Mode state machine
	# ------------------------------------------------------------------

	def _bindBaseGestures(self):
		"""Bind every gesture that no transient mode currently owns.

		A JAWSKey command answers the same way whichever cursor is active,
		so those gestures are bound once and never withheld. The bare
		navigation keys cannot be: JVDA is a global plugin, and a global
		plugin's binding is found before the tree interceptor's
		(nvda/source/scriptHandler.py:186-205), so owning ``upArrow`` in PC
		cursor mode takes it from browse mode with nothing to hand it back
		to. Those go to whichever cursor is reading.

		Every caller rebinds this whole set rather than unbinding the one
		map it happened to overlap, which is what used to leave a command
		dead for the rest of the session after Touch Cursor borrowed its
		key once.
		"""
		if not self._keyboardInterceptionEnabled:
			return
		self.bindGestures(self.__gestures)
		if config.conf["jvda"]["spaceLayerEnabled"]:
			self.bindGestures(self._SPACE_LAYER_GESTURES)
		if config.conf["jvda"]["jawsVirtualQuickKeys"]:
			self.bindGestures(self._VIRTUAL_QUICK_GESTURES)
		if config.conf["jvda"]["limitPreviousHeadingSpeech"]:
			self.bindGestures(self._PREVIOUS_HEADING_GESTURES)
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self.bindGestures(self._MODE_GESTURES)
			self.bindGestures(self._JAWS_GESTURES)
		elif self._mode == self.MODE_SCRIPT:
			self.bindGestures(self._MODE_GESTURES)

	def _setMode(self, newMode, announce=True):
		"""Transition to *newMode*, always leaving the previous mode.

		Review positions can become invalid when their window closes. A
		failure to restore such state must never leave JAWS-mode gestures
		bound or the add-on logically stuck in JAWS mode.
		"""
		if newMode == self._mode:
			return
		prevSpeechMode = _speechCore.SpeechMode.talk
		oldMode = self._mode
		self._log(
			f"Mode transition {oldMode} → {newMode}: "
			f"{self._describeBrowseModeState()}",
		)
		_speechModule.cancelSpeech()
		try:
			_speechModule.setSpeechMode(_speechCore.SpeechMode.off)
			try:
				if oldMode in (self.MODE_JAWS, self.MODE_INVISIBLE):
					self._deactivateJawsMode()
				elif oldMode == self.MODE_TOUCH:
					self._deactivateTouchMode()
				elif oldMode == self.MODE_SCRIPT:
					self._deactivateScriptMode()
			except Exception as error:
				self._log(
					f"Unable to leave {oldMode} mode: {error!r}",
				)
			finally:
				# The old mode is no longer allowed to own any gestures.
				self._mode = self.MODE_PC

			try:
				if newMode == self.MODE_JAWS:
					self._activateJawsMode()
				elif newMode == self.MODE_INVISIBLE:
					self._activateInvisibleMode()
				elif newMode == self.MODE_TOUCH:
					self._activateTouchMode()
				elif newMode == self.MODE_SCRIPT:
					self._activateScriptMode()
			except Exception as error:
				self._log(
					f"Unable to enter {newMode} mode: {error!r}",
				)
				if newMode in (self.MODE_JAWS, self.MODE_INVISIBLE):
					try:
						self._deactivateJawsMode()
					except Exception as cleanupError:
						self._log(
							"Unable to clean up failed JAWS activation: "
							f"{cleanupError!r}",
						)
				elif newMode == self.MODE_TOUCH:
					self._deactivateTouchMode()
				elif newMode == self.MODE_SCRIPT:
					self._deactivateScriptMode()
				self._releaseLockedMouseButtons()
				newMode = self.MODE_PC
			self._mode = newMode
			if newMode == self.MODE_PC and oldMode != self.MODE_PC:
				self._releaseLockedMouseButtons()
		finally:
			_speechModule.cancelSpeech()
			_speechModule.setSpeechMode(prevSpeechMode)
		if oldMode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._resetJawsCursorPitch()
		self._log(
			f"Mode → {self._mode}: {self._describeBrowseModeState()}",
		)
		if announce:
			messages = {
				self.MODE_PC: _("PC"),
				self.MODE_JAWS: _("JAWS"),
				self.MODE_INVISIBLE: _("Invisible"),
				self.MODE_TOUCH: _("Touch"),
				self.MODE_SCRIPT: _("Object navigation"),
			}
			ui.message(messages[self._mode])

	def _activateJawsMode(self):
		if self._keyboardInterceptionEnabled:
			self.bindGestures(self._MODE_GESTURES)
			self.bindGestures(self._JAWS_GESTURES)
		# The state PC cursor mode is restored to is cached here as a
		# convenience, not as a precondition: the JAWS Cursor is screen
		# review and needs none of it to work. Each lookup reaches an
		# application through COM or RPC and can fail transiently -- a null
		# RPC context handle while a document is still loading is the one
		# seen in practice -- so an escape from here would abandon the
		# activation and drop the user back into PC cursor mode while the
		# command that asked for the JAWS Cursor still reports success.
		# Deactivation already treats every cached value as optional, so
		# record what can be read and leave the rest unset.
		try:
			self._reviewPositionBeforeJawsCursor = (
				api.getReviewPosition().copy()
			)
		except Exception as error:
			self._log(
				"Unable to save review position before JAWS: "
				f"{error!r}",
			)
			self._reviewPositionBeforeJawsCursor = None
		# Also cache the PC cursor and navigator object. JAWS cursor
		# activity must not replace NVDA's independent object-navigation
		# location when PC cursor mode resumes.
		try:
			self._pcCursorBeforeJawsCursor = (
				self._getPCcursorPosition()
			)
		except Exception as error:
			self._log(f"Unable to save PC cursor before JAWS: {error!r}")
			self._pcCursorBeforeJawsCursor = None
		try:
			self._navigatorObjectBeforeJawsCursor = api.getNavigatorObject()
		except Exception as error:
			self._log(
				f"Unable to save navigator object before JAWS: {error!r}",
			)
			self._navigatorObjectBeforeJawsCursor = None
		try:
			self._reviewModeBeforeJawsCursor = review.getCurrentMode()
		except Exception as error:
			self._log(f"Unable to save review mode before JAWS: {error!r}")
			self._reviewModeBeforeJawsCursor = None
		if self._jawsCursorPosition is not None:
			try:
				api.setReviewPosition(
					self._jawsCursorPosition.copy(), clearNavigatorObject=False,
				)
				self._restrictionPending = False
				return
			except Exception as error:
				self._log(f"Unable to restore JAWS cursor: {error!r}")
		if self._pcCursorBeforeJawsCursor is None:
			# Without a PC cursor there is nowhere to seed the JAWS Cursor
			# from. Leave it wherever review already is and keep the
			# restriction pending, so the first movement resolves it.
			self._log("No PC cursor to place the JAWS cursor at")
			return
		self._positionJawsCursorAt(self._pcCursorBeforeJawsCursor.copy())

	def _activateInvisibleMode(self):
		"""Activate independent screen review without moving the mouse."""
		self._activateJawsMode()
		position = self._invisibleCursorPosition or self._jawsCursorPosition
		if position is not None:
			try:
				api.setReviewPosition(position.copy(), clearNavigatorObject=False)
				self._restrictionPending = False
			except Exception as error:
				self._log(f"Unable to restore Invisible cursor: {error!r}")

	def _deactivateJawsMode(self):
		try:
			position = api.getReviewPosition().copy()
			if self._mode == self.MODE_JAWS:
				self._jawsCursorPosition = position
			elif self._mode == self.MODE_INVISIBLE:
				self._invisibleCursorPosition = position
		except Exception as error:
			self._log(f"Unable to save review cursor: {error!r}")
		self.bindGestures(
			{gesture: None for gesture in self._MODE_GESTURES},
		)
		self.bindGestures(
			{
				gesture: None
				for gesture in self._JAWS_GESTURES
				if "NVDA" not in gesture
			},
		)
		# Restore the PC cursor position we saved on activation.
		pcPos = getattr(
			self, "_pcCursorBeforeJawsCursor", None,
		)
		if pcPos is not None and not self._preserveRoutedPCcursor:
			try:
				pcPos.updateCaret()
			except Exception as error:
				self._log(f"Unable to restore PC cursor: {error!r}")
		self._pcCursorBeforeJawsCursor = None
		self._preserveRoutedPCcursor = False
		try:
			if self._navigatorObjectBeforeJawsCursor is not None:
				api.setNavigatorObject(
					self._navigatorObjectBeforeJawsCursor,
				)
		except Exception as error:
			self._log(f"Unable to restore navigator object: {error!r}")
		self._navigatorObjectBeforeJawsCursor = None
		try:
			if self._reviewModeBeforeJawsCursor is not None:
				review.setCurrentMode(
					self._reviewModeBeforeJawsCursor,
					updateReviewPosition=False,
				)
		except Exception as error:
			self._log(f"Unable to restore review mode: {error!r}")
		self._reviewModeBeforeJawsCursor = None
		try:
			if self._reviewPositionBeforeJawsCursor is not None:
				# Do not pass a TextInfo whose weakly-referenced object has
				# been cleaned up to NVDA's setReviewPosition.
				if (
					getattr(
						self._reviewPositionBeforeJawsCursor, "obj", None,
					)
					is None
				):
					raise TypeError("cached review position has no object")
				api.setReviewPosition(
					self._reviewPositionBeforeJawsCursor,
					clearNavigatorObject=False,
				)
		except Exception as error:
			self._log(f"Unable to restore review position: {error!r}")
		self._reviewPositionBeforeJawsCursor = None

	def _activateTouchMode(self):
		"""Activate flat object traversal without moving system focus."""
		self._navigatorObjectBeforeTouchCursor = api.getNavigatorObject()
		obj = self._touchCursorObject
		if obj is None or not self._touchObjectIsInScope(obj):
			obj = api.getFocusObject()
		# Accessing role catches stale/dead accessibility objects that still
		# appear under the current foreground root.
		try:
			obj.role
		except Exception:
			obj = api.getFocusObject()
		self._touchCursorObject = obj
		api.setNavigatorObject(obj)
		if self._keyboardInterceptionEnabled:
			self.bindGestures(self._MODE_GESTURES)
			self.bindGestures(self._TOUCH_GESTURES)

	def _deactivateTouchMode(self):
		if self._touchTextReview:
			self._deactivateTouchTextReview(announce=False)
		try:
			self._touchCursorObject = api.getNavigatorObject()
		except Exception:
			pass
		self.bindGestures({gesture: None for gesture in self._TOUCH_GESTURES})
		self._bindBaseGestures()
		try:
			if self._navigatorObjectBeforeTouchCursor is not None:
				api.setNavigatorObject(self._navigatorObjectBeforeTouchCursor)
		except Exception as error:
			self._log(f"Unable to restore navigator after Touch Cursor: {error!r}")
		self._navigatorObjectBeforeTouchCursor = None

	def _activateScriptMode(self):
		if self._keyboardInterceptionEnabled:
			self.bindGestures(self._MODE_GESTURES)
		api.setNavigatorObject(api.getFocusObject())

	def _deactivateScriptMode(self):
		self.bindGestures(
			{gesture: None for gesture in self._MODE_GESTURES},
		)

	def _patchVirtualCursorRestriction(self):
		"""Constrain browse-mode selections while a web scope is active."""
		cls = browseMode.BrowseModeDocumentTreeInterceptor
		original = cls._set_selection
		self._originalBrowseModeSetSelection = original

		def restrictedSetSelection(treeInterceptor, info, *args, **kwargs):
			info, constrained = self._constrainVirtualCursorSelection(
				treeInterceptor, info,
			)
			if constrained:
				winsound.MessageBeep()
			return original(treeInterceptor, info, *args, **kwargs)

		self._browseModeSetSelectionWrapper = restrictedSetSelection
		cls._set_selection = restrictedSetSelection

	def _unpatchVirtualCursorRestriction(self):
		cls = browseMode.BrowseModeDocumentTreeInterceptor
		if (
			self._browseModeSetSelectionWrapper is not None
			and cls._set_selection is self._browseModeSetSelectionWrapper
		):
			cls._set_selection = self._originalBrowseModeSetSelection
		self._browseModeSetSelectionWrapper = None
		self._originalBrowseModeSetSelection = None

	def _virtualRestrictionCandidate(self, obj, treeInterceptor):
		"""Return the nearest restrictable web dialog or nested document."""
		if treeInterceptor is None or obj is None:
			return None, None
		# Walking the ancestor chain fetches roles and parents over COM, so
		# a control that dies mid-walk raises rather than simply ending it.
		# Fall through to the buffer scan below instead of failing the focus
		# event this runs in.
		document = None
		try:
			root = treeInterceptor.rootNVDAObject
			candidate = obj
			for _level in range(100):
				if candidate is None:
					break
				role = getattr(candidate, "role", None)
				if role == controlTypes.Role.DIALOG:
					return "dialog", candidate
				if (
					document is None
					and role == controlTypes.Role.DOCUMENT
					and candidate != root
				):
					document = candidate
				if candidate == root:
					break
				candidate = getattr(
					candidate, "simpleParent", None,
				) or getattr(candidate, "parent", None)
		except Exception as error:
			self._log(f"Unable to walk web scope ancestors: {error!r}")
		if document is not None:
			return "document", document
		# Some browser accessibility providers expose a focused edit with a
		# broken parent chain. The virtual buffer still contains reliable
		# dialog/document control fields, so locate the smallest scope that
		# encloses its caret offset.
		try:
			caret = treeInterceptor.makeTextInfo(textInfos.POSITION_CARET)
			allInfo = treeInterceptor.makeTextInfo(textInfos.POSITION_ALL)
			candidates = []
			for item in allInfo.getTextWithFields():
				if (
					not isinstance(item, textInfos.FieldCommand)
					or item.command != "controlStart"
					or item.field.get("role") not in (
						controlTypes.Role.DIALOG,
						controlTypes.Role.DOCUMENT,
					)
				):
					continue
				docHandle = item.field.get("controlIdentifier_docHandle")
				nodeId = item.field.get("controlIdentifier_ID")
				if docHandle is None or nodeId is None:
					continue
				start, end = allInfo._getOffsetsFromFieldIdentifier(
					int(docHandle), int(nodeId),
				)
				if start <= caret._startOffset <= end:
					kind = (
						"dialog"
						if item.field.get("role") == controlTypes.Role.DIALOG
						else "document"
					)
					# Do not treat the outer browse document as a nested scope.
					if (
						kind == "document"
						and start == 0
						and end >= allInfo._endOffset
					):
						continue
					candidates.append(
						(end - start, kind, (int(docHandle), int(nodeId))),
					)
			if candidates:
				_size, kind, identifier = min(candidates)
				return kind, identifier
		except Exception as error:
			# Reading a virtual buffer is an RPC into the browser's content
			# process. A buffer being torn down or rebuilt raises OSError
			# (WinError 1775, null context handle), which is not one of the
			# TextInfo errors; leaving it uncaught kills the focus event.
			self._log(f"Unable to locate web scope from buffer: {error!r}")
		return None, None

	def _setVirtualCursorRestriction(self, kind, root, treeInterceptor):
		try:
			if isinstance(root, tuple):
				bounds = treeInterceptor.makeTextInfo(textInfos.POSITION_ALL)
				start, end = bounds._getOffsetsFromFieldIdentifier(*root)
				bounds = treeInterceptor.makeTextInfo(
					textInfos.offsets.Offsets(start, end),
				)
			else:
				bounds = treeInterceptor.makeTextInfo(root)
		except (LookupError, NotImplementedError, RuntimeError, TypeError) as error:
			self._log(f"Unable to restrict Virtual cursor: {error!r}")
			return False
		self._virtualRestriction = kind
		self._virtualRestrictionTree = treeInterceptor
		self._virtualRestrictionRoot = root
		self._virtualRestrictionBounds = bounds
		self._virtualRestrictionSuppressedRoot = None
		try:
			position = treeInterceptor.makeTextInfo(textInfos.POSITION_CARET)
			position, constrained = self._constrainVirtualCursorSelection(
				treeInterceptor, position,
			)
			if constrained:
				treeInterceptor._set_selection(position)
		except (LookupError, NotImplementedError, RuntimeError, TypeError):
			pass
		return True

	def _clearVirtualCursorRestriction(self, suppressCurrent=False):
		if suppressCurrent:
			self._virtualRestrictionSuppressedRoot = self._virtualRestrictionRoot
		self._virtualRestriction = None
		self._virtualRestrictionTree = None
		self._virtualRestrictionRoot = None
		self._virtualRestrictionBounds = None

	def _constrainVirtualCursorSelection(self, treeInterceptor, info):
		bounds = self._virtualRestrictionBounds
		if bounds is None or treeInterceptor is not self._virtualRestrictionTree:
			return info, False
		try:
			before = info.compareEndPoints(bounds, "startToStart") < 0
			after = info.compareEndPoints(bounds, "endToEnd") > 0
			if not before and not after:
				return info, False
			adjusted = info.copy()
			if before:
				adjusted.setEndPoint(bounds, "startToStart")
			if after:
				adjusted.setEndPoint(bounds, "endToEnd")
			if (
				adjusted.compareEndPoints(adjusted, "startToEnd") > 0
			):
				adjusted = bounds.copy()
				adjusted.collapse(end=after)
			return adjusted, True
		except (LookupError, NotImplementedError, RuntimeError, TypeError) as error:
			self._log(f"Unable to enforce Virtual cursor restriction: {error!r}")
			self._clearVirtualCursorRestriction()
			return info, False

	def _updateVirtualCursorRestrictionForFocus(self, obj):
		treeInterceptor = self._getBrowseModeTreeInterceptor()
		kind, root = self._virtualRestrictionCandidate(obj, treeInterceptor)
		if self._virtualRestriction is not None:
			if (
				treeInterceptor is not self._virtualRestrictionTree
				or root != self._virtualRestrictionRoot
			):
				self._clearVirtualCursorRestriction()
		if self._virtualRestrictionSuppressedRoot is not None:
			if root == self._virtualRestrictionSuppressedRoot:
				return
			self._virtualRestrictionSuppressedRoot = None
		if self._virtualRestriction is None and root is not None:
			self._setVirtualCursorRestriction(kind, root, treeInterceptor)

	def _getRestrictionRoot(self):
		"""Return the NVDA object that bounds the selected JAWS cursor."""
		focus = api.getFocusObject()
		restriction = self._RESTRICTIONS[self._restrictionIndex]
		if restriction == "focus":
			return focus
		if restriction == "frame":
			obj = focus
			while obj:
				if getattr(obj, "role", None) in (
					controlTypes.Role.FRAME,
					controlTypes.Role.TEXTFRAME,
					controlTypes.Role.INTERNALFRAME,
				):
					return obj
				obj = getattr(obj, "parent", None)
			return focus
		if restriction == "unrestricted":
			hwnd = winUser.getDesktopWindow()
		elif restriction == "application":
			hwnd = winUser.getAncestor(
				focus.windowHandle, winUser.GA_ROOTOWNER,
			) or focus.windowHandle
		elif restriction == "real":
			hwnd = winUser.getAncestor(
				focus.windowHandle, winUser.GA_ROOT,
			) or focus.windowHandle
		else:  # Current window: the immediate focused child window/pane.
			hwnd = focus.windowHandle
		root = Window(windowHandle=hwnd)
		root.redraw()
		return root

	def _applyJawsCursorRestriction(self):
		"""Validate a restriction change without repositioning review."""
		root = self._getRestrictionRoot()
		self._restrictionPending = True
		return root

	def _setJawsCursorRestrictionScope(self, root):
		"""Apply the selected scope immediately before positioning review."""
		api.setNavigatorObject(root)
		mode = {
			"focus": "object",
			"frame": "document",
		}.get(self._RESTRICTIONS[self._restrictionIndex], "screen")
		review.setCurrentMode(mode, updateReviewPosition=False)

	def _prepareJawsCursorMovement(self):
		"""Enter a newly selected scope only when navigation begins."""
		if not self._restrictionPending:
			return
		root = self._getRestrictionRoot()
		self._restrictionPending = False
		self._setJawsCursorRestrictionScope(root)
		try:
			if self._RESTRICTIONS[self._restrictionIndex] in ("focus", "frame"):
				position = root.makeTextInfo(textInfos.POSITION_CARET)
			else:
				position = DisplayModelTextInfo(root, textInfos.POSITION_FIRST)
		except (LookupError, NotImplementedError, RuntimeError, TypeError):
			position = root.makeTextInfo(textInfos.POSITION_FIRST)
		api.setReviewPosition(position, clearNavigatorObject=False)

	def _positionJawsCursorAt(self, position):
		"""Place the JAWS cursor at *position* (a TextInfo from PC cursor).

		Resolving and entering the restriction scope is as fragile as the
		mapping that follows it: both reach the application, and
		``_getRestrictionRoot`` can also return a dead window. Keep the whole
		sequence inside the guard, because an escape from here aborts JAWS
		mode activation and leaves the add-on silently back in PC mode.
		"""
		try:
			root = self._applyJawsCursorRestriction()
			self._setJawsCursorRestrictionScope(root)
			if self._RESTRICTIONS[self._restrictionIndex] == "focus":
				screenPosition = position
			else:
				screenPosition = DisplayModelTextInfo(root, position.pointAtStart)
			api.setReviewPosition(screenPosition, clearNavigatorObject=False)
			self._restrictionPending = False
		except Exception as error:
			self._log(f"Unable to map PC cursor into restriction: {error!r}")

	# ------------------------------------------------------------------
	# Shared PC-cursor helpers
	# ------------------------------------------------------------------

	_NUMPAD_NAVIGATION_KEYS = {
		"numpadDelete": "delete",
		"numpad1": "end",
		"numpad2": "downArrow",
		"numpad3": "pageDown",
		"numpad4": "leftArrow",
		"numpad6": "rightArrow",
		"numpad7": "home",
		"numpad8": "upArrow",
		"numpad9": "pageUp",
	}

	def script_passNumpadNavigationKey(self, gesture):
		keyName = self._NUMPAD_NAVIGATION_KEYS[gesture.mainKeyName]
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			if keyName == "pageUp":
				self.script_reviewPreviousPage(gesture)
				return
			if keyName == "pageDown":
				self.script_reviewNextPage(gesture)
				return
		keyboardHandler.KeyboardInputGesture.fromName(keyName).send()

	def _moveAndReportReviewPage(self, direction):
		"""Move by a native page, or ten lines when pages are unsupported."""
		self._prepareJawsCursorMovement()
		position = api.getReviewPosition().copy()
		position.collapse()
		try:
			page = position.copy()
			page.expand(textInfos.UNIT_PAGE)
			page.collapse()
			moved = page.move(textInfos.UNIT_PAGE, direction)
		except (
			LookupError, NotImplementedError, RuntimeError, TypeError, ValueError,
		):
			page = position
			moved = page.move(textInfos.UNIT_LINE, direction * 10)
		if moved == 0:
			ui.reviewMessage(_("Top") if direction < 0 else _("Bottom"))
			return
		api.setReviewPosition(page)
		page.expand(textInfos.UNIT_LINE)
		_speechModule.speakTextInfo(
			page, unit=textInfos.UNIT_LINE,
			reason=controlTypes.OutputReason.CARET,
		)

	def script_reviewPreviousPage(self, gesture):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._moveAndReportReviewPage(-1)
		else:
			gesture.send()

	def script_reviewNextPage(self, gesture):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._moveAndReportReviewPage(1)
		else:
			gesture.send()

	def _getPCcursorPosition(self):
		"""Return a TextInfo at the PC cursor, falling back as needed.

		Every step reaches an application through COM or RPC, which raises
		far more than the documented TextInfo errors: OSError from the
		nvdaHelper RPC layer, COMError, and watchdog CallCancelled during
		freeze recovery all surface here and none of them are RuntimeError.
		Catch broadly so a transient application fault falls through to the
		next strategy instead of aborting the caller.
		"""
		try:
			return api.getCaretPosition()
		except Exception:
			# Do not use review here. In JAWS mode it can be restricted to a
			# different window, while PC cursor commands must remain tied to
			# the focused control.
			focus = api.getFocusObject()
			try:
				return focus.makeTextInfo(textInfos.POSITION_CARET)
			except Exception:
				return focus.makeTextInfo(textInfos.POSITION_FIRST)

	def _getActiveCursorPosition(self):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			return api.getReviewPosition().copy()
		return self._getPCcursorPosition()

	def _getVirtualCursorInterceptor(self):
		"""Return the active Virtual Cursor, or None.

		Browse mode is JAWS's Virtual Cursor. Unlike the other JAWS cursors
		it is not a JVDA mode: it lives inside MODE_PC, so self._mode alone
		can never tell a caller which cursor is reading. passThrough is
		JAWS Forms Mode, where the PC cursor reads instead.
		"""
		if self._mode != self.MODE_PC:
			# Every other mode owns a cursor of its own.
			return None
		treeInterceptor = self._getBrowseModeTreeInterceptor()
		if treeInterceptor is None or treeInterceptor.passThrough:
			return None
		return treeInterceptor

	def _getReadingPosition(self):
		"""Return a TextInfo the *active* cursor should report from.

		This is the single answer to "which cursor is reading" for every
		say-current-something command. Prefer it over _getPCcursorPosition
		in anything that reports text to the user.
		"""
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			return api.getReviewPosition().copy()
		treeInterceptor = self._getVirtualCursorInterceptor()
		if treeInterceptor is not None:
			try:
				return treeInterceptor.makeTextInfo(textInfos.POSITION_CARET)
			except Exception as error:
				self._log(f"Unable to read the Virtual cursor: {error!r}")
		# Deliberately the focused object rather than api.getCaretPosition:
		# PuTTY exposes its terminal text through the focused object while
		# the accessibility caret comes back empty.
		focus = api.getFocusObject()
		try:
			return focus.makeTextInfo(textInfos.POSITION_CARET)
		except Exception:
			return focus.makeTextInfo(textInfos.POSITION_FIRST)

	def _movePCcursor(self, gestureName):
		"""Emulate a PC cursor movement key through NVDA.

		Emulating rather than sending keeps NVDA's own handling in play, so
		a browse-mode document moves its cursor instead of receiving a raw
		arrow. That is only safe while JVDA does not hold the emulated key
		itself: a global plugin's binding runs before the tree interceptor's
		(nvda/source/scriptHandler.py:186-205), so binding the bare
		navigation keys here would make this re-enter the calling script.
		"""
		inputCore.manager.emulateGesture(
			keyboardHandler.KeyboardInputGesture.fromName(gestureName),
		)

	@staticmethod
	def _isTreeInterceptorUsable(treeInterceptor):
		"""Whether *treeInterceptor* can answer text queries yet.

		Virtual buffers fill on a background thread, so an interceptor can
		exist while its remote buffer handle is still null. Querying one in
		that state reaches the nvdaHelper RPC layer and raises OSError
		(WinError 1775). NVDA guards its own caret lookups on ``isReady``
		for exactly this reason; anything without the attribute is a
		non-buffered interceptor, which is always ready.
		"""
		return bool(getattr(treeInterceptor, "isReady", True))

	def _getBrowseModeTreeInterceptor(self):
		"""Find the focused document's browse-mode interceptor.

		This never creates an interceptor. It is called from event handlers
		and from commands that only want to inspect the current document, so
		it must not override NVDA's decision about where browse mode belongs.
		Use L{_createBrowseModeTreeInterceptor} where the user has explicitly
		asked to be placed in browse mode.
		"""
		import treeInterceptorHandler

		focus = api.getFocusObject()
		treeInterceptor = focus.treeInterceptor
		if not isinstance(treeInterceptor, browseMode.BrowseModeTreeInterceptor):
			if treeInterceptor:
				# A non-browse-mode document owns the focus.
				return None
			# NVDA caches a failed lookup on the object itself, so a control
			# focused while its document was still building keeps reporting
			# no interceptor even once one exists. Re-scan the running table
			# rather than trusting that cached negative.
			treeInterceptor = treeInterceptorHandler.getTreeInterceptor(focus)
			if not isinstance(
				treeInterceptor, browseMode.BrowseModeTreeInterceptor,
			):
				return None
		if not self._isTreeInterceptorUsable(treeInterceptor):
			self._log("Browse-mode document is not ready yet")
			return None
		return treeInterceptor

	def _createBrowseModeTreeInterceptor(self):
		"""Find the focused document's interceptor, creating one if needed.

		Focused web controls do not always cache their ancestor document's
		interceptor, particularly while Firefox is updating its accessibility
		tree. Match NVDA's lookup and force-creation fallback.

		Forcing creation overrides ``shouldCreateTreeInterceptor``, the
		``enableOnPageLoad`` setting and any app module's
		``disableBrowseModeByDefault``, so this belongs only in commands
		whose whole purpose is to put the user in browse mode -- the same
		rule NVDA applies to it in NVDA+space.
		"""
		import treeInterceptorHandler

		treeInterceptor = self._getBrowseModeTreeInterceptor()
		if treeInterceptor is not None:
			return treeInterceptor
		focus = api.getFocusObject()
		if focus.treeInterceptor or treeInterceptorHandler.getTreeInterceptor(
			focus,
		):
			# A document already owns the focus. It is either not browse mode
			# or still loading, and in neither case may we build a second one.
			return None
		for obj in (focus, *reversed(api.getFocusAncestors())):
			try:
				obj.treeInterceptorClass
			except Exception:
				continue
			break
		else:
			return None
		treeInterceptor = treeInterceptorHandler.update(obj, force=True)
		if not isinstance(treeInterceptor, browseMode.BrowseModeTreeInterceptor):
			return None
		try:
			if focus in treeInterceptor:
				focus.treeInterceptor = treeInterceptor
				if not self._isTreeInterceptorUsable(treeInterceptor):
					# Freshly created buffers load asynchronously. The caller
					# gets nothing this time; the interceptor is now cached on
					# the focus and will be ready for the next command.
					self._log("Created browse-mode document is still loading")
					return None
				return treeInterceptor
		except Exception as error:
			self._log(f"Unable to resolve browse-mode document: {error!r}")
		return None

	def _returnToBrowseModeForPCcursor(self, gesture):
		# The user asked for the PC (Virtual) cursor, so creating the
		# document's interceptor is the point of the command.
		treeInterceptor = self._createBrowseModeTreeInterceptor()
		if treeInterceptor is None:
			self._log("PC cursor: no browse-mode document")
			return False
		wasPassThrough = treeInterceptor.passThrough
		if wasPassThrough:
			# Calling script_disablePassThrough is insufficient here: NVDA
			# deliberately passes Escape through when the user manually chose
			# Focus Mode. PC cursor must always return to Browse Mode.
			treeInterceptor.disableAutoPassThrough = False
			treeInterceptor.passThrough = False
			browseMode.reportPassThrough(treeInterceptor)
		isBrowseMode = not treeInterceptor.passThrough
		self._log(
			"PC cursor browse-mode transition: "
			f"passThrough {wasPassThrough} → {treeInterceptor.passThrough}",
		)
		if not isBrowseMode:
			ui.message(_("Unable to exit Focus Mode"))
		return isBrowseMode

	def _reportActiveCursorUnit(self, unit):
		"""Report *unit* at whichever cursor is currently reading."""
		repeatCount = scriptHandler.getLastScriptRepeatCount()
		try:
			info = self._getReadingPosition()
			info.expand(unit)
		except Exception as error:
			self._log(f"Unable to read {unit} at the active cursor: {error!r}")
			focus = api.getFocusObject()
			if repeatCount:
				_speechModule.speakSpelling(
					focus.name, useCharacterDescriptions=repeatCount > 1,
				)
			else:
				_speechModule.speakObject(
					focus, reason=controlTypes.OutputReason.QUERY,
				)
			return
		if unit == textInfos.UNIT_CHARACTER and repeatCount > 1:
			values = [ord(character) for character in info.text]
			ui.message(", ".join(
				f"{value}, {hex(value)}" for value in values
			))
		elif unit == textInfos.UNIT_CHARACTER and repeatCount:
			_speechModule.spellTextInfo(
				info, useCharacterDescriptions=True,
			)
		elif repeatCount:
			_speechModule.spellTextInfo(
				info, useCharacterDescriptions=False,
			)
		else:
			_speechModule.speakTextInfo(
				info, unit=unit, reason=controlTypes.OutputReason.CARET,
			)

	# ------------------------------------------------------------------
	# Mode-switch scripts
	# ------------------------------------------------------------------

	def script_activateJawsCursor(self, gesture):
		if (
			self._mode == self.MODE_JAWS
			and scriptHandler.getLastScriptRepeatCount()
		):
			self._setMode(self.MODE_INVISIBLE)
		elif self._mode == self.MODE_JAWS:
			ui.message(_("JAWS"))
		else:
			self._setMode(self.MODE_JAWS)

	def script_deactivateJawsCursor(self, gesture):
		wasPCmode = self._mode == self.MODE_PC
		isVirtual = False
		try:
			isVirtual = self._returnToBrowseModeForPCcursor(gesture)
		except Exception as error:
			self._log(
				"Unable to return to browse mode for PC cursor: "
				f"{error!r}",
			)
		finally:
			if not wasPCmode:
				self._setMode(self.MODE_PC)
		if wasPCmode:
			ui.message(
				_("Virtual PC") if isVirtual else _("PC"),
			)

	def script_activateTouchCursor(self, gesture):
		"""Activate the JAWS-style Touch Cursor compatibility mode."""
		if self._mode == self.MODE_TOUCH:
			ui.message(_("Touch"))
		else:
			self._setMode(self.MODE_TOUCH)

	def _touchObjectIsInScope(self, obj):
		root = api.getForegroundObject()
		candidate = obj
		for _level in range(100):
			if candidate is None:
				return False
			if candidate == root:
				return True
			candidate = getattr(candidate, "simpleParent", None)
		return False

	def _touchNextObject(self, obj):
		candidate = getattr(obj, "simpleFirstChild", None)
		if candidate is None:
			candidate = getattr(obj, "simpleNext", None)
		return candidate if self._touchObjectIsInScope(candidate) else None

	def _touchPreviousObject(self, obj):
		candidate = getattr(obj, "simplePrevious", None)
		if candidate is not None:
			for _level in range(100):
				child = getattr(candidate, "simpleLastChild", None)
				if child is None:
					break
				candidate = child
		else:
			candidate = getattr(obj, "simpleParent", None)
		return candidate if self._touchObjectIsInScope(candidate) else None

	def _setTouchObject(self, obj):
		if obj is None:
			ui.message(_("No more elements"))
			return False
		self._touchCursorObject = obj
		api.setNavigatorObject(obj)
		_speechModule.speakObject(
			obj, reason=controlTypes.OutputReason.FOCUS,
		)
		return True

	def _moveTouchObject(self, direction, matchingType=False):
		obj = self._touchCursorObject or api.getNavigatorObject()
		move = self._touchNextObject if direction > 0 else self._touchPreviousObject
		_roleName, wantedRole = self._TOUCH_MOVEMENT_TYPES[
			self._touchMovementIndex
		]
		for _count in range(10000):
			obj = move(obj)
			if obj is None:
				ui.message(_("No more elements"))
				return
			if not matchingType or wantedRole is None or obj.role == wantedRole:
				self._setTouchObject(obj)
				return
		ui.message(_("No more elements"))

	def _runAdvancedTouchCommand(self, gesture, scriptName):
		script = getattr(
			globalCommands.commands,
			f"script_navigatorObject_{scriptName}",
		)
		script(gesture)
		self._touchCursorObject = api.getNavigatorObject()

	def script_activateTouchTextReview(self, gesture):
		if self._touchTextReview:
			ui.message(_("Touch text review"))
			return
		self._touchTextReview = True
		self._reviewModeBeforeTouchText = review.getCurrentMode()
		review.setCurrentMode("object", updateReviewPosition=True)
		self.bindGestures(self._TOUCH_TEXT_GESTURES)
		ui.message(_("Touch text review"))

	def _deactivateTouchTextReview(self, announce=True):
		self._touchTextReview = False
		self.bindGestures({
			gesture: None for gesture in self._TOUCH_TEXT_GESTURES
		})
		self._bindBaseGestures()
		if self._reviewModeBeforeTouchText is not None:
			try:
				review.setCurrentMode(
					self._reviewModeBeforeTouchText,
					updateReviewPosition=False,
				)
			except Exception as error:
				self._log(f"Unable to restore review after Touch text: {error!r}")
		self._reviewModeBeforeTouchText = None
		if self._mode == self.MODE_TOUCH and self._keyboardInterceptionEnabled:
			self.bindGestures(self._TOUCH_GESTURES)
		if announce:
			ui.message(_("Touch navigation"))

	def script_deactivateTouchTextReview(self, gesture):
		self._deactivateTouchTextReview()

	def script_touchTextNextCharacter(self, gesture):
		globalCommands.commands.script_review_nextCharacter(gesture)

	def script_touchTextPreviousCharacter(self, gesture):
		globalCommands.commands.script_review_previousCharacter(gesture)

	def script_touchTextCurrentCharacter(self, gesture):
		globalCommands.commands.script_review_currentCharacter(gesture)

	def script_touchTextNextWord(self, gesture):
		globalCommands.commands.script_review_nextWord(gesture)

	def script_touchTextPreviousWord(self, gesture):
		globalCommands.commands.script_review_previousWord(gesture)

	def script_touchTextNextLine(self, gesture):
		globalCommands.commands.script_review_nextLine(gesture)

	def script_touchTextPreviousLine(self, gesture):
		globalCommands.commands.script_review_previousLine(gesture)

	def script_touchTextStartOfLine(self, gesture):
		globalCommands.commands.script_review_startOfLine(gesture)

	def script_touchTextEndOfLine(self, gesture):
		globalCommands.commands.script_review_endOfLine(gesture)

	def script_toggleTouchAdvancedNavigation(self, gesture):
		self._touchAdvancedNavigation = not self._touchAdvancedNavigation
		ui.message(
			_("Advanced object navigation")
			if self._touchAdvancedNavigation
			else _("Touch navigation")
		)

	def script_touchNextElement(self, gesture):
		if self._touchAdvancedNavigation:
			self._runAdvancedTouchCommand(gesture, "next")
		else:
			self._moveTouchObject(1)

	def script_touchPreviousElement(self, gesture):
		if self._touchAdvancedNavigation:
			self._runAdvancedTouchCommand(gesture, "previous")
		else:
			self._moveTouchObject(-1)

	def script_touchNextElementByType(self, gesture):
		if self._touchAdvancedNavigation:
			self._runAdvancedTouchCommand(gesture, "firstChild")
		else:
			self._moveTouchObject(1, matchingType=True)

	def script_touchPreviousElementByType(self, gesture):
		if self._touchAdvancedNavigation:
			self._runAdvancedTouchCommand(gesture, "parent")
		else:
			self._moveTouchObject(-1, matchingType=True)

	def script_touchFirstElement(self, gesture):
		root = api.getForegroundObject()
		self._setTouchObject(getattr(root, "simpleFirstChild", None) or root)

	def script_touchLastElement(self, gesture):
		obj = api.getForegroundObject()
		for _level in range(100):
			child = getattr(obj, "simpleLastChild", None)
			if child is None:
				break
			obj = child
		self._setTouchObject(obj)

	def _changeTouchMovementType(self, direction):
		self._touchMovementIndex = (
			self._touchMovementIndex + direction
		) % len(self._TOUCH_MOVEMENT_TYPES)
		name, _role = self._TOUCH_MOVEMENT_TYPES[self._touchMovementIndex]
		ui.message(_("Move by {}").format(name))

	def script_touchPreviousMovementType(self, gesture):
		self._changeTouchMovementType(-1)

	def script_touchNextMovementType(self, gesture):
		self._changeTouchMovementType(1)

	def script_touchReportCurrentElement(self, gesture):
		obj = self._touchCursorObject or api.getNavigatorObject()
		_speechModule.speakObject(
			obj, reason=controlTypes.OutputReason.QUERY,
		)

	def script_touchActivate(self, gesture):
		obj = self._touchCursorObject or api.getNavigatorObject()
		try:
			obj.doAction()
		except Exception:
			ui.message(_("Element cannot be activated"))

	def script_touchRightClick(self, gesture):
		obj = self._touchCursorObject or api.getNavigatorObject()
		try:
			left, top, width, height = obj.location
			x = left + width // 2
			y = top + height // 2
		except Exception:
			ui.message(_("Element has no screen location"))
			return
		winUser.setCursorPos(x, y)
		mouseHandler.executeMouseMoveEvent(x, y)
		mouseHandler.doSecondaryClick()

	def script_touchRouteToFocus(self, gesture):
		obj = self._touchCursorObject or api.getNavigatorObject()
		try:
			obj.setFocus()
		except Exception:
			ui.message(_("Element cannot receive focus"))
			return
		ui.message(_("Focus routed to Touch Cursor"))

	def script_toggleScriptMode(self, gesture):
		"""Toggle NVDA Object Navigation mode."""
		if self._mode == self.MODE_SCRIPT:
			self._setMode(self.MODE_PC)
		else:
			self._setMode(self.MODE_SCRIPT)

	def script_toggleVirtualPCcursor(self, gesture):
		globalCommands.commands.script_toggleVirtualBufferPassThrough(
			gesture,
		)

	def script_sayAll(self, gesture):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			globalCommands.commands.script_review_sayAll(gesture)
		else:
			globalCommands.commands.script_sayAll(gesture)

	def script_cycleTypingEcho(self, gesture):
		globalCommands.commands.script_toggleSpeakTypedCharacters(gesture)

	def script_activateAtJawsCursor(self, gesture):
		# JAWS VKSelect performs a primary click at the JAWS cursor.
		self.script_leftMouseClickAtJawsCursor(gesture)

	def script_openDictionaryManager(self, gesture):
		globalCommands.commands.script_activateDefaultDictionaryDialog(gesture)

	def script_openQuickSettings(self, gesture):
		"""Open NVDA configuration profiles for application-specific settings."""
		globalCommands.commands.script_activateConfigProfilesDialog(gesture)

	def script_openSettingsCenter(self, gesture):
		globalCommands.commands.script_activateGeneralSettingsDialog(gesture)

	def script_reportApplicationFileName(self, gesture):
		foreground = api.getForegroundObject()
		pid, _threadID = winUser.getWindowThreadProcessID(
			foreground.windowHandle,
		)
		fileName = self._getProcessName(pid) if pid else ""
		if fileName:
			ui.message(fileName)
		else:
			ui.message(_("Application file unavailable"))

	def script_hotKeyHelp(self, gesture):
		"""Show the principal JVDA commands for the active keyboard layout."""
		commands = _(
			"Cursor commands\n"
			"Numpad Minus: JAWS Cursor; repeat for Invisible Cursor\n"
			"Numpad Plus: PC Cursor\n"
			"JAWSKey+R: cycle cursor restriction\n"
			"JAWSKey+Numpad Minus: move review cursor to PC Cursor\n"
			"JAWSKey+Numpad Plus: route PC Cursor to review cursor\n\n"
			"Reading commands\n"
			"JAWSKey+Up Arrow: current line\n"
			"JAWSKey+Down Arrow or JAWSKey+A: say all\n"
			"JAWSKey+F: font; JAWSKey+5: color\n"
			"JAWSKey+T: window title\n"
			"JAWSKey+F10: window list\n"
			"JAWSKey+F11: system tray icons\n"
			"JAWSKey+1: NVDA Input Help",
		)
		ui.browseableMessage(commands, _("JVDA Hot Key Help"))

	def _commandCompatibilityEntries(self):
		import json
		import os

		path = os.path.join(
			addonHandler.getCodeAddon().path,
			"command-compatibility.json",
		)
		try:
			with open(path, encoding="utf-8") as compatibilityFile:
				return json.load(compatibilityFile)
		except (OSError, ValueError) as error:
			self._log(f"Unable to load command compatibility: {error!r}")
			return []

	def script_openCommandCompatibility(self, gesture):
		"""Open the searchable JVDA command compatibility dialog."""
		entries = self._commandCompatibilityEntries()
		if not entries:
			ui.message(_("Command compatibility data unavailable"))
			return
		# Defer the modal dialog until the opening gesture's modifiers have
		# been released, so they cannot leak into the search field.
		wx.CallAfter(self._showCommandCompatibility, entries)

	def _showCommandCompatibility(self, entries):
		gui.mainFrame.prePopup()
		dialog = _CommandCompatibilityDialog(
			gui.mainFrame, _("JVDA Command Compatibility"), entries,
		)
		try:
			dialog.ShowModal()
		finally:
			dialog.Destroy()
			gui.mainFrame.postPopup()

	def script_contextSensitiveHelp(self, gesture):
		"""Show practical context-sensitive help for the focused control."""
		focus = api.getFocusObject()
		role = getattr(getattr(focus, "role", None), "displayString", None)
		if not role:
			role = str(getattr(focus, "role", _("unknown role")))
		lines = [
			_("Control: {}").format(
				getattr(focus, "name", None) or _("unnamed"),
			),
			_("Role: {}").format(role),
		]
		description = getattr(focus, "description", None)
		if description:
			lines.append(_("Description: {}").format(description))
		shortcut = getattr(focus, "keyboardShortcut", None)
		if shortcut:
			lines.append(_("Keyboard shortcut: {}").format(shortcut))
		if isinstance(
			getattr(focus, "treeInterceptor", None),
			browseMode.BrowseModeTreeInterceptor,
		):
			lines.append(_(
				"Use JAWS Virtual Cursor quick keys in Browse Mode; "
				"press JAWSKey+Z to toggle Focus Mode.",
			))
		else:
			lines.append(_(
				"Use Tab and Shift+Tab to move between controls; "
				"press JAWSKey+1 for Input Help.",
			))
		ui.browseableMessage("\n".join(lines), _("JVDA Context Help"))

	def script_unavailableWindowKeysHelp(self, gesture):
		self._reportUnavailableJawsCommand()

	def script_unavailableJawsCommand(self, gesture):
		self._reportUnavailableJawsCommand()

	# ------------------------------------------------------------------
	# Layered JAWSKey+Space commands
	# ------------------------------------------------------------------
	# These methods are run by _SpaceLayerMixin._runLayerCommand rather than
	# by NVDA's script dispatcher, so they take no gesture. The NVDA scripts
	# they delegate to all ignore their gesture argument, which is why None
	# can be passed through.

	def layerToggleAudioDucking(self):
		"""JAWS ToggleAudioDucking: switch NVDA's audio ducking on or off."""
		import audioDucking

		if (
			not audioDucking.isAudioDuckingSupported()
			or audioDucking._isAudioDuckingSuspended()
		):
			# Translators: reported when audio ducking cannot be used on this
			# machine. NVDA's own command uses the same wording.
			ui.message(_("Audio ducking not supported"))
			return
		# JAWS's command is a two-state toggle. NVDA's own NVDA+shift+d cycles
		# a third mode, ALWAYS; the JAWS toggle deliberately cannot reach it,
		# and treats ALWAYS as "on" so that one press switches ducking off.
		currentMode = config.conf["audio"]["audioDuckingMode"]
		newMode = (
			audioDucking.AudioDuckingMode.OUTPUTTING
			if currentMode == audioDucking.AudioDuckingMode.NONE
			else audioDucking.AudioDuckingMode.NONE
		)
		audioDucking.setAudioDuckingMode(newMode)
		config.conf["audio"]["audioDuckingMode"] = int(newMode)
		ui.message(
			# Translators: reported when audio ducking has been switched on.
			_("Audio ducking on")
			if newMode != audioDucking.AudioDuckingMode.NONE
			# Translators: reported when audio ducking has been switched off.
			else _("Audio ducking off"),
		)

	def _setLayerSpeechMode(self, newMode):
		"""Announce *newMode* and then switch speech to it.

		The announcement is made while speech is still on, exactly as NVDA's
		own NVDA+S command does, so that switching speech off is still
		audible."""
		_speechModule.setSpeechMode(_speechCore.SpeechMode.talk)
		_speechModule.cancelSpeech()
		# Translators: announced when the speech mode changes. Matches NVDA's
		# own wording for its speech mode command.
		ui.message(_("Speech mode {mode}").format(mode=newMode.displayString))
		_speechModule.setSpeechMode(newMode)

	def layerMuteSynthesizer(self):
		"""JAWS MuteSynthesizer: switch speech off, or back on."""
		currentMode = _speechCore.getState().speechMode
		self._setLayerSpeechMode(
			_speechCore.SpeechMode.talk
			if currentMode == _speechCore.SpeechMode.off
			else _speechCore.SpeechMode.off,
		)

	def layerSpeechOnDemandToggle(self):
		"""JAWS SpeechOnDemandToggle: switch on-demand speech on, or off."""
		currentMode = _speechCore.getState().speechMode
		self._setLayerSpeechMode(
			_speechCore.SpeechMode.off
			if currentMode == _speechCore.SpeechMode.onDemand
			else _speechCore.SpeechMode.onDemand,
		)

	def layerScreenShade(self):
		"""JAWS ScreenShadeToggle: NVDA's screen curtain.

		NVDA's command announces its own state, so nothing is added here."""
		globalCommands.commands.script_toggleScreenCurtain(None)

	def layerLockKeyboard(self):
		"""JAWS LockKeyboard: JVDA's keyboard interception toggle.

		JAWS's keyboard lock stops JAWS from answering keys. JVDA's
		interception toggle is the closest NVDA analogue: it hands every
		JVDA gesture back to NVDA and the application."""
		self.script_toggleKeyboardInterception(None)

	def layerViewClipboardText(self):
		"""JAWS ViewClipboardText: show the clipboard text."""
		try:
			text = api.getClipData()
		except Exception as error:
			self._log(f"Unable to read the clipboard: {error!r}")
			text = ""
		if not text:
			# Translators: reported when the clipboard holds no text.
			ui.message(_("Clipboard is empty"))
			return
		# Translators: title of the window showing the clipboard text.
		ui.browseableMessage(text, _("Clipboard"))

	def layerCommandsSearch(self):
		"""JAWS LaunchCommandsSearch: JVDA's command compatibility search."""
		self.script_openCommandCompatibility(None)

	# ---- Volume layer ----

	#: JAWS volume layer step sizes. They match NVDA's synthesizer settings
	#: ring: SynthDriver.VolumeSetting uses normalStep=5, and
	#: SynthSetting.increaseLarge moves by largeStep * 2, which is 20
	#: (nvda2/source/synthDriverHandler.py:179 and
	#: nvda2/source/synthSettingsRing.py:45).
	_LAYER_VOLUME_SMALL_STEP = 5
	_LAYER_VOLUME_LARGE_STEP = 20

	def _changeLayerVolume(self, change):
		"""Change the synthesizer volume by *change* percent and announce it.

		JAWS stops its own volume at 10 percent. NVDA's synthesizer volume
		range is 0 to 100, and JVDA keeps NVDA's range rather than imposing
		a minimum NVDA users would not expect."""
		import synthDriverHandler

		synth = synthDriverHandler.getSynth()
		if synth is None or not synth.isSupported("volume"):
			# Translators: reported when the synthesizer has no volume setting.
			ui.message(_("Volume not supported"))
			return
		volume = max(0, min(100, synth.volume + change))
		synth.volume = volume
		# Translators: reports the new synthesizer volume as a percentage.
		ui.message(_("Volume {}%").format(volume))

	def layerVolumeUpSmall(self):
		"""JAWS JAWSVolumeUpSmall."""
		self._changeLayerVolume(self._LAYER_VOLUME_SMALL_STEP)

	def layerVolumeDownSmall(self):
		"""JAWS JAWSVolumeDownSmall."""
		self._changeLayerVolume(-self._LAYER_VOLUME_SMALL_STEP)

	def layerVolumeUpLarge(self):
		"""JAWS JAWSVolumeUpLarge."""
		self._changeLayerVolume(self._LAYER_VOLUME_LARGE_STEP)

	def layerVolumeDownLarge(self):
		"""JAWS JAWSVolumeDownLarge."""
		self._changeLayerVolume(-self._LAYER_VOLUME_LARGE_STEP)

	def _setLayerSoundSplit(self, stateName):
		"""Apply the NVDA sound split state named *stateName* and announce it.

		JAWS's sound balance routes JAWS speech to one channel and leaves the
		applications on the other, which is what NVDA calls sound split.
		``audio._setSoundSplitState`` is private to NVDA (NVDA 2026,
		nvda2/source/audio/soundSplit.py:184) and does not store the new
		state, so the configuration is written here exactly as NVDA's own
		``audio._toggleSoundSplitState`` does."""
		import audio

		state = getattr(audio.SoundSplitState, stateName)
		try:
			audio._setSoundSplitState(state)
		except Exception as error:
			self._log(f"Unable to set the sound split state: {error!r}")
			# Translators: reported when the sound balance cannot be changed.
			ui.message(_("Sound balance not supported"))
			return
		config.conf["audio"]["soundSplitState"] = state.value
		ui.message(state.displayString)

	def layerSoundBalanceLeft(self):
		"""JAWS RouteJAWSSoundLeft."""
		self._setLayerSoundSplit("NVDA_LEFT_APPS_RIGHT")

	def layerSoundBalanceRight(self):
		"""JAWS RouteJAWSSoundRight."""
		self._setLayerSoundSplit("NVDA_RIGHT_APPS_LEFT")

	def layerSoundBalanceRestore(self):
		"""JAWS RestoreSoundBalance."""
		self._setLayerSoundSplit("OFF")

	def _layerSoundCards(self):
		"""Return the audio output devices, read once per layer visit."""
		if self._layerSoundCardDevices is None:
			from utils import mmdevice

			try:
				self._layerSoundCardDevices = list(mmdevice.getOutputDevices())
			except Exception as error:
				self._log(f"Unable to list audio output devices: {error!r}")
				self._layerSoundCardDevices = []
		return self._layerSoundCardDevices

	def _applyLayerSoundCard(self, deviceId):
		"""Switch NVDA's audio output device to *deviceId*.

		The synthesizer has to be reloaded and the tone player restarted
		before the new device is used. This is what NVDA's own Audio settings
		panel does on save (nvda2/source/gui/settingsDialogs.py:3681)."""
		import synthDriverHandler
		import tones

		config.conf["audio"]["outputDevice"] = deviceId
		synth = synthDriverHandler.getSynth()
		if synth is not None:
			synthDriverHandler.setSynth(synth.name)
		tones.terminate()
		tones.initialize()

	def _selectLayerSoundCard(self, offset):
		"""Move *offset* places through the audio output devices and announce."""
		devices = self._layerSoundCards()
		if not devices:
			# Translators: reported when no audio output device can be found.
			ui.message(_("No audio output devices"))
			return
		deviceIds = [device.id for device in devices]
		currentId = config.conf["audio"]["outputDevice"]
		try:
			index = deviceIds.index(currentId)
		except ValueError:
			# The configured device is gone; start at whichever end the
			# requested direction comes from.
			index = -1 if offset > 0 else 0
		device = devices[(index + offset) % len(devices)]
		if device.id != currentId:
			try:
				self._applyLayerSoundCard(device.id)
			except Exception as error:
				self._log(f"Unable to select an audio output device: {error!r}")
				# Translators: reported when the audio output device could not
				# be changed.
				ui.message(_("Sound card not available"))
				return
		ui.message(device.friendlyName)

	def layerNextSoundCard(self):
		"""JAWS SelectNextSoundCard."""
		self._selectLayerSoundCard(1)

	def layerPreviousSoundCard(self):
		"""JAWS SelectPreviousSoundCard."""
		self._selectLayerSoundCard(-1)

	# ---- Table layer ----

	def _runLayerTableCommands(self, *scriptNames):
		"""Run NVDA's table navigation scripts for a table layer key.

		NVDA's table scripts ignore their gesture argument, and the layer has
		no gesture to give them, so None is passed."""
		self._runTableCommands(None, *scriptNames)

	def layerTableNextRow(self):
		"""JAWS DownCell: move to the cell below and read it."""
		self._runLayerTableCommands("nextRow")

	def layerTablePreviousRow(self):
		"""JAWS UpCell: move to the cell above and read it."""
		self._runLayerTableCommands("previousRow")

	def layerTableNextColumn(self):
		"""JAWS NextCell: move to the next cell in the row and read it."""
		self._runLayerTableCommands("nextColumn")

	def layerTablePreviousColumn(self):
		"""JAWS PriorCell: move to the previous cell in the row and read it."""
		self._runLayerTableCommands("previousColumn")

	def layerTableFirstRow(self):
		"""JAWS MoveToTopOfColumn."""
		self._runLayerTableCommands("firstRow")

	def layerTableLastRow(self):
		"""JAWS MoveToBottomOfColumn."""
		self._runLayerTableCommands("lastRow")

	def layerTableFirstColumn(self):
		"""JAWS MoveToStartOfRow."""
		self._runLayerTableCommands("firstColumn")

	def layerTableLastColumn(self):
		"""JAWS MoveToEndOfRow."""
		self._runLayerTableCommands("lastColumn")

	def layerTableFirstCell(self):
		"""JAWS FirstCellInTable."""
		self._runLayerTableCommands("firstRow", "firstColumn")

	def layerTableLastCell(self):
		"""JAWS LastCellInTable."""
		self._runLayerTableCommands("lastRow", "lastColumn")

	def layerTableSpeakRow(self):
		"""JAWS ReadCurrentRow: read the row without moving the caret."""
		self._runLayerTableCommands("speakRow")

	def layerTableSpeakColumn(self):
		"""JAWS ReadCurrentColumn: read the column without moving the caret."""
		self._runLayerTableCommands("speakColumn")

	def layerTableSayAllRow(self):
		"""JAWS ReadFromCurrentCell: read the row on from the current cell."""
		self._runLayerTableCommands("sayAllRow")

	def layerTableSayAllColumn(self):
		"""JAWS ReadToBottomOfColumn: read the column down from this cell."""
		self._runLayerTableCommands("sayAllColumn")

	def layerTableSayCell(self):
		"""JAWS SayCell: report the current table cell."""
		self.script_tableSpeakCell(None)

	def script_showShutdownDialog(self, gesture):
		"""Open NVDA's exit-options dialog."""
		globalCommands.commands.script_quit(gesture)

	def script_passNextKeyThrough(self, gesture):
		# JAWS does not announce PassKeyThrough; unlike NVDA's global
		# script, call the keyboard handler directly to preserve that.
		keyboardHandler.passNextKeyThrough()

	def script_reportSystemTime(self, gesture):
		globalCommands.commands.script_dateTime(gesture)

	def script_reportSystemTimeWithSeconds(self, gesture):
		if scriptHandler.getLastScriptRepeatCount():
			from datetime import date

			ui.message(_("Week {}").format(date.today().isocalendar().week))
			return
		ui.message(winKernel.GetTimeFormatEx(
			winKernel.LOCALE_NAME_USER_DEFAULT, None, None, None,
		))

	def script_refreshScreen(self, gesture):
		root = self._getRestrictionRoot()
		try:
			root.redraw()
		except (AttributeError, RuntimeError) as error:
			self._log(f"Unable to refresh JAWS screen: {error!r}")
			ui.message(_("Unable to refresh screen"))
			return
		ui.message(_("Screen refreshed"))

	def script_routePCcursorToVirtual(self, gesture):
		"""Move the PC Cursor to the current Virtual Cursor position."""
		treeInterceptor = self._getBrowseModeTreeInterceptor()
		if treeInterceptor is None or treeInterceptor.passThrough:
			ui.message(_("No Virtual PC cursor"))
			return
		try:
			position = treeInterceptor.makeTextInfo(textInfos.POSITION_CARET)
			# Synchronize focus first, then map the virtual position to the
			# application's real caret where the provider supports it.
			treeInterceptor._focusLastFocusableObject()
			position.updateCaret()
		except (LookupError, NotImplementedError, RuntimeError, TypeError) as error:
			self._log(f"Unable to route PC cursor to Virtual cursor: {error!r}")
			ui.message(_("No caret"))
			return
		treeInterceptor.disableAutoPassThrough = True
		treeInterceptor.passThrough = True
		browseMode.reportPassThrough(treeInterceptor)
		ui.message(_("PC cursor routed to Virtual cursor"))

	def script_routeVirtualToPCcursor(self, gesture):
		"""Move the Virtual Cursor to the current PC Cursor position."""
		treeInterceptor = self._getBrowseModeTreeInterceptor()
		if treeInterceptor is None:
			ui.message(_("No Virtual PC cursor"))
			return
		focus = api.getFocusObject()
		try:
			pcPosition = self._getPCcursorPosition()
			try:
				position = treeInterceptor.makeTextInfo(pcPosition.pointAtStart)
			except (LookupError, NotImplementedError, RuntimeError, TypeError):
				position = treeInterceptor.makeTextInfo(focus)
			position.collapse()
			treeInterceptor._set_selection(position)
		except (LookupError, NotImplementedError, RuntimeError, TypeError) as error:
			self._log(f"Unable to route Virtual cursor to PC cursor: {error!r}")
			ui.message(_("No Virtual PC cursor"))
			return
		treeInterceptor.disableAutoPassThrough = False
		treeInterceptor.passThrough = False
		browseMode.reportPassThrough(treeInterceptor)
		ui.message(_("Virtual cursor routed to PC cursor"))

	def script_saySelectedText(self, gesture):
		globalCommands.commands.script_reportCurrentSelection(gesture)

	def _updateTetheredJawsCursor(self):
		"""Make the saved JAWS Cursor follow a changed PC caret safely."""
		if (
			not config.conf["jvda"]["tetherJawsToPc"]
			or self._tetherUpdateInProgress
		):
			return False
		if self._mode != self.MODE_JAWS:
			# Nothing observes the saved JAWS Cursor until it is next
			# activated, and the Invisible Cursor stays independent of it
			# regardless. Clearing the saved position records "follows PC"
			# and lets activation resolve it, instead of paying a caret
			# lookup -- and, outside the focus restriction, a blocking window
			# redraw and display-model snapshot -- on every caret and focus
			# event in the system.
			self._jawsCursorPosition = None
			return True
		self._tetherUpdateInProgress = True
		try:
			self._positionJawsCursorAt(self._getPCcursorPosition())
			self._jawsCursorPosition = api.getReviewPosition().copy()
			return True
		except Exception as error:
			self._log(f"Unable to tether JAWS cursor to PC: {error!r}")
			return False
		finally:
			self._tetherUpdateInProgress = False

	def script_toggleJawsToPcTether(self, gesture):
		tethered = not config.conf["jvda"]["tetherJawsToPc"]
		setUserValue(config.conf["jvda"], "tetherJawsToPc", tethered)
		if tethered:
			self._updateTetheredJawsCursor()
		ui.message(
			_("The JAWS cursor will follow the PC cursor")
			if tethered
			else _("The JAWS cursor will not follow the PC cursor"),
		)

	def script_moveJawsCursorToPCcursor(self, gesture):
		if self._mode not in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._setMode(self.MODE_JAWS, announce=False)
		self._positionJawsCursorAt(self._getPCcursorPosition())
		ui.message(
			_("Invisible to PC")
			if self._mode == self.MODE_INVISIBLE
			else _("JAWS to PC"),
		)

	def script_routePCcursorToJawsCursor(self, gesture):
		routingSucceeded = False
		wasReviewCursor = self._mode in (
			self.MODE_JAWS, self.MODE_INVISIBLE,
		)
		try:
			# Review retains the JAWS cursor location while PC cursor is
			# active, so Insert+Apostrophe can route from either cursor mode.
			position = api.getReviewPosition().copy()
			self._log(
				"Route JAWS cursor to PC cursor: "
				f"{self._describePosition(position)}",
			)
			try:
				target = api.getCaretObject().makeTextInfo(
					position.pointAtStart,
				)
				target.updateCaret()
				self._log(
					"Routed through caret object: "
					f"{self._describePosition(target)}",
				)
			except (
				LookupError,
				NotImplementedError,
				RuntimeError,
				TypeError,
			) as error:
				self._log(
					f"Caret-object routing failed ({error!r}); "
					"using review position",
				)
				position.updateCaret()
			routingSucceeded = True
		except Exception as error:
			self._log(f"Routing failed: {error!r}")
		else:
			try:
				self._log(
					"PC cursor after routing: "
					f"{self._describePosition(api.getCaretPosition())}",
				)
			except Exception as error:
				self._log(
					"Unable to inspect PC cursor after routing: "
					f"{error!r}",
				)
		finally:
			if routingSucceeded and wasReviewCursor:
				# Leaving review mode normally restores the caret saved on
				# activation. A successful route deliberately replaces it.
				self._preserveRoutedPCcursor = True
			self._setMode(self.MODE_PC, announce=False)
		if routingSucceeded:
			ui.message(_("PC to JAWS"))
		else:
			ui.message(_("No caret"))

	def script_reportCursorType(self, gesture):
		"""Report the shape of the current Windows mouse pointer."""
		class CURSORINFO(ctypes.Structure):
			_fields_ = (
				("cbSize", ctypes.c_uint),
				("flags", ctypes.c_uint),
				("hCursor", ctypes.c_void_p),
				("ptScreenPos", ctypes.wintypes.POINT),
			)

		cursorInfo = CURSORINFO()
		cursorInfo.cbSize = ctypes.sizeof(cursorInfo)
		if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(cursorInfo)):
			ui.message(_("Cursor shape unavailable"))
			return
		loadCursor = ctypes.windll.user32.LoadCursorW
		loadCursor.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
		loadCursor.restype = ctypes.c_void_p
		standardCursors = (
			(32512, _("Arrow cursor")),
			(32513, _("I-beam cursor")),
			(32514, _("Wait cursor")),
			(32515, _("Crosshair cursor")),
			(32650, _("Application starting cursor")),
			(32651, _("Help cursor")),
			(32648, _("Unavailable cursor")),
			(32649, _("Hand cursor")),
		)
		for resourceId, name in standardCursors:
			if cursorInfo.hCursor == loadCursor(None, resourceId):
				ui.message(name)
				return
		ui.message(_("Custom cursor"))

	def _activeCursorName(self):
		if self._mode == self.MODE_JAWS:
			return _("JAWS cursor")
		if self._mode == self.MODE_INVISIBLE:
			return _("Invisible cursor")
		if self._mode == self.MODE_TOUCH:
			return (
				_("Touch text review")
				if self._touchTextReview
				else _("Touch cursor")
			)
		if self._mode == self.MODE_SCRIPT:
			return _("Object navigation cursor")
		try:
			treeInterceptor = api.getFocusObject().treeInterceptor
			isVirtual = (
				isinstance(
					treeInterceptor,
					browseMode.BrowseModeTreeInterceptor,
				)
				and not treeInterceptor.passThrough
			)
		except Exception as error:
			self._log(f"Unable to determine PC cursor type: {error!r}")
			isVirtual = False
		return _("Virtual PC cursor") if isVirtual else _("PC cursor")

	def _activeCursorDetails(self):
		state = self._diagnosticState()
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			positionName = "review"
			getPosition = api.getReviewPosition
		elif self._mode in (self.MODE_TOUCH, self.MODE_SCRIPT):
			positionName = "navigator"
			getPosition = api.getReviewPosition
		else:
			positionName = "caret"
			getPosition = api.getCaretPosition
		try:
			position = getPosition()
			point = position.pointAtStart
			location = f"{point.x}, {point.y}"
		except Exception:
			location = _("unavailable")
		restriction = (
			state["virtualRestriction"] or _("unrestricted")
			if self._mode == self.MODE_PC
			else state["restriction"]
		)
		lines = (
			self._activeCursorName(),
			_("Mode: {}").format(state["mode"]),
			_("Restriction: {}").format(restriction),
			_("Review mode: {}").format(state["reviewMode"]),
			_("Position type: {}").format(positionName),
			_("Screen location: {}").format(location),
			_("Focus: {}").format(state["focus"]),
			_("Navigator: {}").format(state["navigator"]),
			_("Caret: {}").format(state["caret"]),
			_("Review: {}").format(state["review"]),
		)
		return "\n".join(lines)

	def script_reportActiveCursor(self, gesture):
		if scriptHandler.getLastScriptRepeatCount():
			ui.browseableMessage(
				self._activeCursorDetails(),
				_("Active cursor details"),
			)
			return
		ui.message(self._activeCursorName())

	def script_cycleRestriction(self, gesture):
		if self._mode not in (self.MODE_JAWS, self.MODE_INVISIBLE):
			treeInterceptor = self._getBrowseModeTreeInterceptor()
			if treeInterceptor is None:
				# Translators: shown when trying to cycle restriction in PC mode.
				ui.message(_("Not available for PC"))
				return
			if self._virtualRestriction is not None:
				self._clearVirtualCursorRestriction(suppressCurrent=True)
				ui.message(_("Virtual cursor unrestricted"))
				return
			kind, root = self._virtualRestrictionCandidate(
				api.getFocusObject(), treeInterceptor,
			)
			if root is None or not self._setVirtualCursorRestriction(
				kind, root, treeInterceptor,
			):
				ui.message(_("Virtual cursor restriction unavailable"))
				return
			ui.message(
				_("Virtual cursor restricted to web dialog")
				if kind == "dialog"
				else _("Virtual cursor restricted to web document"),
			)
			return
		oldIndex = self._restrictionIndex
		self._restrictionIndex = (
			(oldIndex + 1) % len(self._RESTRICTIONS)
		)
		try:
			self._applyJawsCursorRestriction()
		except Exception as error:
			self._restrictionIndex = oldIndex
			self._log(f"Unable to change cursor restriction: {error!r}")
			try:
				self._applyJawsCursorRestriction()
			except Exception as restoreError:
				self._log(
					"Unable to restore previous cursor restriction: "
					f"{restoreError!r}",
				)
			ui.message(_("Restriction unavailable"))
			return
		restriction = self._RESTRICTIONS[self._restrictionIndex]
		messages = {
			"real": _("Real window restriction"),
			"current": _("Current window restriction"),
			"focus": _("Current focus restriction"),
			"frame": _("Frame restriction"),
			"unrestricted": _("Unrestricted cursor"),
			"application": _("Application restriction"),
		}
		ui.message(messages[restriction])

	# ------------------------------------------------------------------
	# Navigation scripts — dispatch on self._mode
	# ------------------------------------------------------------------

	def _moveAndReportReviewLine(self, direction, gesture=None):
		"""Move the JAWS cursor vertically, keeping its column where it can.

		Holding the column is JAWS behaviour worth having, but it is a
		convenience layered on top of the actual command, which is "move a
		line and read it". Reading a screen-review range to measure the
		column can raise from inside NVDA's display model, so any failure
		here falls back to NVDA's own review-line command rather than
		leaving the cursor where it was and saying nothing.
		"""
		self._prepareJawsCursorMovement()
		try:
			position = api.getReviewPosition().copy()
			position.collapse()
			lineStart = position.copy()
			lineStart.expand(textInfos.UNIT_LINE)
			lineStart.collapse()
			columnRange = lineStart.copy()
			columnRange.setEndPoint(position, "endToStart")
			column = len(columnRange.text)
			if lineStart.move(textInfos.UNIT_LINE, direction) == 0:
				ui.reviewMessage(_("Top") if direction < 0 else _("Bottom"))
				return
			targetLine = lineStart.copy()
			targetLine.expand(textInfos.UNIT_LINE)
			lineStart.move(
				textInfos.UNIT_CHARACTER,
				min(column, len(targetLine.text.rstrip("\r\n"))),
			)
			api.setReviewPosition(lineStart)
			_speechModule.speakTextInfo(
				targetLine,
				unit=textInfos.UNIT_LINE,
				reason=controlTypes.OutputReason.CARET,
			)
		except Exception as error:
			self._log(f"Column-preserving line move failed: {error!r}")
			self._reviewLineWithoutColumn(direction, gesture)

	def _reviewLineWithoutColumn(self, direction, gesture):
		"""Move a review line the way NVDA does, losing the column."""
		command = (
			globalCommands.commands.script_review_nextLine
			if direction > 0
			else globalCommands.commands.script_review_previousLine
		)
		try:
			command(gesture)
		except Exception as error:
			self._log(f"Review line move failed: {error!r}")
			ui.message(_("Unable to move to that line"))

	def script_previousLine(self, gesture):
		if self._mode == self.MODE_SCRIPT:
			globalCommands.commands.script_navigatorObject_previous(
				gesture,
			)
		elif self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._moveAndReportReviewLine(-1, gesture)
		else:
			self._movePCcursor("upArrow")

	def script_currentLine(self, gesture):
		if self._mode == self.MODE_SCRIPT:
			_speechModule.speakObject(api.getNavigatorObject())
		elif self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			globalCommands.commands.script_review_currentLine(gesture)
		else:
			self._reportActiveCursorUnit(textInfos.UNIT_LINE)

	def script_nextLine(self, gesture):
		if self._mode == self.MODE_SCRIPT:
			globalCommands.commands.script_navigatorObject_next(gesture)
		elif self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._moveAndReportReviewLine(1, gesture)
		else:
			self._movePCcursor("downArrow")

	def script_previousWord(self, gesture):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._prepareJawsCursorMovement()
			globalCommands.commands.script_review_previousWord(gesture)
		elif self._mode == self.MODE_SCRIPT:
			# Object navigation has no word-sized step to take.
			self._reportUnavailableInThisCursor()
		else:
			self._movePCcursor("control+leftArrow")

	def script_currentWord(self, gesture):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			globalCommands.commands.script_review_currentWord(gesture)
		elif self._mode == self.MODE_SCRIPT:
			self._reportUnavailableInThisCursor()
		else:
			self._reportActiveCursorUnit(textInfos.UNIT_WORD)

	def script_nextWord(self, gesture):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._prepareJawsCursorMovement()
			globalCommands.commands.script_review_nextWord(gesture)
		elif self._mode == self.MODE_SCRIPT:
			# Object navigation has no word-sized step to take.
			self._reportUnavailableInThisCursor()
		else:
			self._movePCcursor("control+rightArrow")

	def _fallbackSentenceInfo(self, position, direction=0):
		"""Build a sentence range when an NVDA TextInfo lacks sentence units."""
		try:
			allInfo = position.obj.makeTextInfo(textInfos.POSITION_ALL)
			prefix = allInfo.copy()
			prefix.setEndPoint(position, "endToStart")
			offset = len(prefix.text)
			text = allInfo.text
			spans = [
				match.span()
				for match in re.finditer(
					r"\S(?:.*?\S)?(?:[.!?]+(?=\s|$)|(?=\Z))",
					text,
					flags=re.DOTALL,
				)
			]
			index = next(
				(
					index for index, (start, end) in enumerate(spans)
					if start <= offset <= end
				),
				0 if spans and offset < spans[0][0] else len(spans) - 1,
			)
			index += direction
			if index < 0 or index >= len(spans):
				return None
			startOffset, endOffset = spans[index]
			target = allInfo.copy()
			target.collapse()
			target.move(textInfos.UNIT_CHARACTER, startOffset)
			end = target.copy()
			end.move(textInfos.UNIT_CHARACTER, endOffset - startOffset)
			target.setEndPoint(end, "endToEnd")
			return target
		except (AttributeError, LookupError, NotImplementedError, RuntimeError, TypeError):
			return None

	def _reportUnavailableInThisCursor(self):
		"""Say that the command has no meaning for the active cursor.

		A reading command that produces no output at all is indistinguishable
		from a dropped keystroke, so every dispatch path must end in speech.
		"""
		ui.message(_("Not available in this cursor"))

	def _reportCursorUnit(self, unit, unavailableMessage):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			info = api.getReviewPosition().copy()
		elif self._mode == self.MODE_PC:
			info = self._getPCcursorPosition()
		else:
			self._reportUnavailableInThisCursor()
			return
		try:
			info.expand(unit)
		except (LookupError, NotImplementedError, RuntimeError, TypeError):
			info = (
				self._fallbackSentenceInfo(info)
				if unit == textInfos.UNIT_SENTENCE
				else None
			)
			if info is None:
				ui.message(unavailableMessage)
				return
		_speechModule.speakTextInfo(
			info, unit=unit, reason=controlTypes.OutputReason.CARET,
		)

	def _moveAndReportCursorUnit(self, unit, direction, unavailableMessage):
		reviewCursor = self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE)
		if not reviewCursor and self._mode != self.MODE_PC:
			self._reportUnavailableInThisCursor()
			return
		if reviewCursor:
			self._prepareJawsCursorMovement()
			info = api.getReviewPosition().copy()
		else:
			info = self._getPCcursorPosition()
		try:
			info.expand(unit)
			info.collapse()
			while True:
				if info.move(unit, direction) == 0:
					ui.reviewMessage(_("Top") if direction < 0 else _("Bottom"))
					return
				target = info.copy()
				target.expand(unit)
				if unit != textInfos.UNIT_PARAGRAPH or target.text.strip():
					break
				info = target
				info.collapse()
			cursor = target.copy()
			cursor.collapse()
			if reviewCursor:
				api.setReviewPosition(cursor)
			else:
				cursor.updateCaret()
			info = target
		except (LookupError, NotImplementedError, RuntimeError, TypeError):
			if unit != textInfos.UNIT_SENTENCE:
				ui.message(unavailableMessage)
				return
			target = self._fallbackSentenceInfo(info, direction)
			if target is None:
				ui.reviewMessage(_("Top") if direction < 0 else _("Bottom"))
				return
			info = target.copy()
			info.collapse()
			if reviewCursor:
				api.setReviewPosition(info)
			else:
				info.updateCaret()
			info = target
		_speechModule.speakTextInfo(
			info, unit=unit, reason=controlTypes.OutputReason.CARET,
		)

	def script_currentParagraph(self, gesture):
		self._reportCursorUnit(textInfos.UNIT_PARAGRAPH, _("No paragraph"))

	def script_previousParagraph(self, gesture):
		self._moveAndReportCursorUnit(
			textInfos.UNIT_PARAGRAPH, -1, _("No paragraph"),
		)

	def script_nextParagraph(self, gesture):
		self._moveAndReportCursorUnit(
			textInfos.UNIT_PARAGRAPH, 1, _("No paragraph"),
		)

	def script_previousSentence(self, gesture):
		self._moveAndReportCursorUnit(
			textInfos.UNIT_SENTENCE, -1, _("No sentence"),
		)

	def script_currentSentence(self, gesture):
		self._reportCursorUnit(textInfos.UNIT_SENTENCE, _("No sentence"))

	def script_nextSentence(self, gesture):
		self._moveAndReportCursorUnit(
			textInfos.UNIT_SENTENCE, 1, _("No sentence"),
		)

	def script_previousCharacter(self, gesture):
		if self._mode == self.MODE_SCRIPT:
			globalCommands.commands.script_navigatorObject_parent(
				gesture,
			)
		elif self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._prepareJawsCursorMovement()
			globalCommands.commands.script_review_previousCharacter(
				gesture,
			)
		else:
			self._movePCcursor("leftArrow")

	def script_currentCharacter(self, gesture):
		if self._mode == self.MODE_SCRIPT:
			_speechModule.speakObject(api.getNavigatorObject())
		elif self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			globalCommands.commands.script_review_currentCharacter(
				gesture,
			)
		else:
			self._reportActiveCursorUnit(textInfos.UNIT_CHARACTER)

	def script_nextCharacter(self, gesture):
		if self._mode == self.MODE_SCRIPT:
			globalCommands.commands.script_navigatorObject_firstChild(
				gesture,
			)
		elif self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._prepareJawsCursorMovement()
			globalCommands.commands.script_review_nextCharacter(gesture)
		else:
			self._movePCcursor("rightArrow")

	def script_startOfLine(self, gesture):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._prepareJawsCursorMovement()
			globalCommands.commands.script_review_startOfLine(gesture)
		elif self._mode != self.MODE_SCRIPT:
			self._movePCcursor("home")
		else:
			self._reportUnavailableInThisCursor()

	def script_endOfLine(self, gesture):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._prepareJawsCursorMovement()
			globalCommands.commands.script_review_endOfLine(gesture)
		elif self._mode != self.MODE_SCRIPT:
			self._movePCcursor("end")
		else:
			self._reportUnavailableInThisCursor()

	def _speakReviewRange(self, startPosition, endPosition):
		cursor = self._getActiveCursorPosition()
		info = (
			cursor.copy()
			if startPosition == "cursor"
			else cursor.obj.makeTextInfo(startPosition)
		)
		if endPosition == "cursor":
			info.setEndPoint(cursor, "endToEnd")
		else:
			info.setEndPoint(
				cursor.obj.makeTextInfo(endPosition), "endToEnd",
			)
		repeatCount = scriptHandler.getLastScriptRepeatCount()
		if repeatCount:
			_speechModule.spellTextInfo(
				info, useCharacterDescriptions=repeatCount > 1,
			)
		else:
			_speechModule.speakTextInfo(
				info, reason=controlTypes.OutputReason.CARET,
			)

	def script_sayToCursor(self, gesture):
		self._speakReviewRange(textInfos.POSITION_FIRST, "cursor")

	def script_reportBatteryLevel(self, gesture):
		_powerTracking.reportCurrentBatteryStatus()

	def script_reportCurrentAccessKey(self, gesture):
		globalCommands.commands.script_reportFocusObjectAccelerator(gesture)

	def script_reportWindowPromptAndText(self, gesture):
		globalCommands.commands.script_reportCurrentFocus(gesture)

	def _getWindowCaption(self, hwnd):
		"""Return the caption of *hwnd*, as JAWS's GetWindowName reads it."""
		if not hwnd:
			return ""
		try:
			return (winUser.getWindowText(hwnd) or "").strip()
		except Exception as error:
			self._log(f"Unable to read the caption of {hwnd}: {error!r}")
			return ""

	def _resolveWindowTitle(self):
		"""Resolve a window title the way JAWS resolves one.

		JAWS never reads the foreground window directly. Its Say Window
		Title resolves the same three windows the JAWS Cursor restrictions
		already name here -- the application window, the real window owning
		the focused control, and the focused window itself -- reports the
		application's caption, and adds the real window's caption after it
		when that names something else, a document or a dialog the
		application owns. A caption the application title already contains
		is dropped rather than said twice.

		Starting from the application window is why JAWS has no "no title"
		outcome while a program is running, and why NVDA reaches one: a
		top-level window that is briefly nameless, as a browser's is while
		it starts, still resolves through the window that owns it and
		finally through the application's own name.
		"""
		foreground = api.getForegroundObject()
		focus = api.getFocusObject()
		current = (
			getattr(focus, "windowHandle", 0)
			or getattr(foreground, "windowHandle", 0)
		)
		application = (
			winUser.getAncestor(current, winUser.GA_ROOTOWNER) or current
		)
		real = winUser.getAncestor(current, winUser.GA_ROOT) or current
		title = self._getWindowCaption(application)
		subtitle = ""
		if real != application and real != current:
			subtitle = self._getWindowCaption(real)
		if subtitle and subtitle in title:
			# The application caption already names the document.
			subtitle = ""
		if not title:
			for candidate in (
				self._getWindowCaption(real),
				getattr(foreground, "name", None),
				getattr(
					getattr(foreground, "appModule", None), "appName", None,
				),
			):
				if isinstance(candidate, str) and candidate.strip():
					title = candidate.strip()
					break
		return " ".join(part for part in (title, subtitle) if part)

	def script_reportWindowTitle(self, gesture):
		if scriptHandler.getLastScriptRepeatCount():
			hwnd = api.getForegroundObject().windowHandle
			if ctypes.windll.user32.IsIconic(hwnd):
				ui.message(_("Minimized"))
			elif ctypes.windll.user32.IsZoomed(hwnd):
				ui.message(_("Maximized"))
			else:
				ui.message(_("Restored"))
			return
		ui.message(self._resolveWindowTitle() or _("No title"))

	def script_readBoxInTabOrder(self, gesture):
		focus = api.getFocusObject()
		hwnd = winUser.getAncestor(
			focus.windowHandle, winUser.GA_ROOT,
		) or focus.windowHandle
		getNextDlgTabItem = ctypes.windll.user32.GetNextDlgTabItem
		getNextDlgTabItem.argtypes = (
			ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool,
		)
		getNextDlgTabItem.restype = ctypes.c_void_p
		first = control = None
		controls = []
		# GetNextDlgTabItem returns the next enabled, visible tab-stop
		# control and wraps to the first one after the last control.
		for _ in range(100):
			control = getNextDlgTabItem(hwnd, control, False)
			if not control or control == first:
				break
			if first is None:
				first = control
			try:
				controls.append(getNVDAObjectFromEvent(
					control, winUser.OBJID_CLIENT, 0,
				))
			except Exception as error:
				self._log(f"Unable to retrieve tab-stop control: {error!r}")
		if not controls:
			ui.message(_("No controls in tab order"))
			return
		for control in controls:
			_speechModule.speakObject(
				control, reason=controlTypes.OutputReason.QUERY,
			)

	def _isWordInContextAvailable(self):
		"""Return whether focus is in a spell/find/replace dialog."""
		focus = api.getFocusObject()
		dialogActive = False
		obj = focus
		labels = []
		for _level in range(100):
			if obj is None:
				break
			if getattr(obj, "role", None) == controlTypes.Role.DIALOG:
				dialogActive = True
			for attribute in ("name", "description"):
				try:
					if value := getattr(obj, attribute, None):
						labels.append(str(value))
				except Exception:
					pass
			obj = getattr(obj, "simpleParent", None) or getattr(obj, "parent", None)
		try:
			treeInterceptor = self._getBrowseModeTreeInterceptor()
			kind, _root = self._virtualRestrictionCandidate(
				focus, treeInterceptor,
			)
			dialogActive = dialogActive or kind == "dialog"
		except Exception:
			pass
		try:
			foregroundWindow = winUser.getForegroundWindow()
			labels.append(winUser.getWindowText(foregroundWindow))
			dialogActive = dialogActive or (
				winUser.getClassName(foregroundWindow) == "#32770"
			)
		except Exception:
			pass
		if not dialogActive:
			return False
		context = " ".join(labels).casefold()
		return any(word in context for word in ("spell", "find", "replace"))

	def script_readWordInContext(self, gesture):
		if not self._isWordInContextAvailable():
			ui.message(_("Word in context not found"))
			return
		info = (
			api.getReviewPosition().copy()
			if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE)
			else self._getPCcursorPosition()
		)
		info.expand(textInfos.UNIT_WORD)
		start = info.copy()
		start.collapse()
		start.move(textInfos.UNIT_WORD, -1)
		end = info.copy()
		end.collapse(end=True)
		if end.move(textInfos.UNIT_WORD, 1):
			end.expand(textInfos.UNIT_WORD)
		info.setEndPoint(start, "startToStart")
		info.setEndPoint(end, "endToEnd")
		ui.message(_("Approximate word context"))
		_speechModule.speakTextInfo(
			info, reason=controlTypes.OutputReason.CARET,
		)

	def script_setTemporaryPlaceMarker(self, gesture):
		"""Set the session-only PlaceMarker at the Virtual Cursor."""
		treeInterceptor = self._getBrowseModeTreeInterceptor()
		if (
			treeInterceptor is None
			or getattr(treeInterceptor, "passThrough", False)
		):
			ui.message(_("Temporary PlaceMarker requires Browse Mode"))
			return
		try:
			self._temporaryPlaceMarker = treeInterceptor.makeTextInfo(
				textInfos.POSITION_CARET,
			).copy()
		except Exception:
			ui.message(_("Unable to set temporary PlaceMarker"))
			return
		self._temporaryPlaceMarkerTree = treeInterceptor
		ui.message(_("Temporary PlaceMarker set"))

	def script_moveToTemporaryPlaceMarker(self, gesture):
		"""Move to the session-only PlaceMarker in the current document."""
		treeInterceptor = self._getBrowseModeTreeInterceptor()
		if (
			self._virtualQuickKeysSuspended
			or treeInterceptor is None
			or getattr(treeInterceptor, "passThrough", False)
		):
			gesture.send()
			return
		if (
			self._temporaryPlaceMarker is None
			or treeInterceptor is not self._temporaryPlaceMarkerTree
		):
			ui.message(_("No temporary PlaceMarker in this document"))
			return
		try:
			position = self._temporaryPlaceMarker.copy()
			treeInterceptor._set_selection(position)
			line = position.copy()
			line.expand(textInfos.UNIT_LINE)
			_speechModule.speakTextInfo(
				line, reason=controlTypes.OutputReason.CARET,
			)
		except Exception:
			self._temporaryPlaceMarker = None
			self._temporaryPlaceMarkerTree = None
			ui.message(_("Temporary PlaceMarker is no longer available"))

	def script_toggleJawsVirtualQuickKeys(self, gesture):
		"""Suspend or resume optional JAWS Virtual Cursor quick keys."""
		if not config.conf["jvda"]["jawsVirtualQuickKeys"]:
			ui.message(_("JAWS Virtual Cursor quick keys are not enabled"))
			return
		self._virtualQuickKeysSuspended = not self._virtualQuickKeysSuspended
		ui.message(
			_("JAWS Virtual Cursor quick keys {}")
			.format(
				_("suspended")
				if self._virtualQuickKeysSuspended
				else _("resumed")
			),
		)

	def script_previousHeadingOnly(self, gesture):
		"""Move backward and report only the destination heading object."""
		treeInterceptor = self._getBrowseModeTreeInterceptor()
		if (
			treeInterceptor is None
			or getattr(treeInterceptor, "passThrough", False)
		):
			gesture.send()
			return
		try:
			item = next(treeInterceptor._iterNodesByType(
				"heading", "previous", treeInterceptor.selection,
			))
		except NotImplementedError:
			ui.message(_("Not supported in this document"))
			return
		except StopIteration:
			ui.message(_("No previous heading"))
			return
		if not gesture or not scriptHandler.willSayAllResume(gesture):
			try:
				obj = item.obj
			except Exception:
				obj = None
			if obj is not None:
				# Speak object properties only. speakObject also reads the object's
				# text line, which is the nested range that causes Discord to add
				# the ancestor heading in the first place.
				_speechModule.speakObjectProperties(
					obj,
					reason=controlTypes.OutputReason.QUICKNAV,
					name=True,
					role=True,
					positionInfo_level=True,
				)
			else:
				# UIA can provide a heading range without a backing object. Its
				# quick-nav label is still scoped to the destination heading.
				ui.message(item.label)
		item.moveTo()

	# NVDA gives its own quick navigation scripts this attribute so that
	# pressing the key during say all skim-reads to the new position and
	# keeps reading. Without the attribute, Shift+H would stop say all.
	script_previousHeadingOnly.resumeSayAllMode = sayAll.CURSOR.CARET

	def script_jawsVirtualQuickKey(self, gesture):
		"""Run an optional JAWS quick key in an active Virtual Cursor."""
		treeInterceptor = self._getBrowseModeTreeInterceptor()
		if (
			self._virtualQuickKeysSuspended
			or treeInterceptor is None
			or getattr(treeInterceptor, "passThrough", False)
		):
			gesture.send()
			return
		keyName = gesture.mainKeyName.lower()
		suffix = self._VIRTUAL_QUICK_SCRIPTS.get(keyName)
		if suffix is None:
			gesture.send()
			return
		direction = (
			"previous" if "shift" in gesture.modifierNames else "next"
		)
		script = getattr(
			treeInterceptor,
			f"script_{direction}{suffix}",
			None,
		)
		if script is None:
			gesture.send()
			return
		script(gesture)

	def _getTableNavigationTarget(self):
		focus = api.getFocusObject()
		treeInterceptor = getattr(focus, "treeInterceptor", None)
		if treeInterceptor and not getattr(treeInterceptor, "passThrough", False):
			return treeInterceptor
		return focus

	def _runTableCommands(self, gesture, *scriptNames):
		target = self._getTableNavigationTarget()
		for scriptName in scriptNames:
			script = getattr(target, f"script_{scriptName}", None)
			if script is None:
				ui.message(_("Not in a table"))
				return False
			script(gesture)
		return True

	def script_tableSpeakCell(self, gesture):
		"""Report the current table cell."""
		self._reportActiveCursorUnit(textInfos.UNIT_LINE)

	def script_tablePreviousRowAndRead(self, gesture):
		self._runTableCommands(gesture, "previousRow", "speakRow")

	def script_tableNextRowAndRead(self, gesture):
		self._runTableCommands(gesture, "nextRow", "speakRow")

	def script_tablePreviousColumnAndRead(self, gesture):
		self._runTableCommands(gesture, "previousColumn", "speakColumn")

	def script_tableNextColumnAndRead(self, gesture):
		self._runTableCommands(gesture, "nextColumn", "speakColumn")

	def script_tableSpeakRow(self, gesture):
		self._runTableCommands(gesture, "speakRow")

	def script_tableSpeakColumn(self, gesture):
		self._runTableCommands(gesture, "speakColumn")

	def script_tableFirstColumn(self, gesture):
		self._runTableCommands(gesture, "firstColumn")

	def script_tableLastColumn(self, gesture):
		self._runTableCommands(gesture, "lastColumn")

	def script_tableFirstRow(self, gesture):
		self._runTableCommands(gesture, "firstRow")

	def script_tableLastRow(self, gesture):
		self._runTableCommands(gesture, "lastRow")

	def script_tableFirstCell(self, gesture):
		self._runTableCommands(gesture, "firstRow", "firstColumn")

	def script_tableLastCell(self, gesture):
		self._runTableCommands(gesture, "lastRow", "lastColumn")

	def _getFindTarget(self):
		focus = api.getFocusObject()
		treeInterceptor = getattr(focus, "treeInterceptor", None)
		if treeInterceptor and hasattr(treeInterceptor, "script_find"):
			return treeInterceptor
		if hasattr(focus, "script_find"):
			return focus
		return None

	def _findInVirtualBuffer(self, gesture, scriptName):
		treeInterceptor = api.getFocusObject().treeInterceptor
		script = getattr(treeInterceptor, scriptName, None)
		if (
			isinstance(treeInterceptor, browseMode.BrowseModeTreeInterceptor)
			and script
		):
			script(gesture)
			return
		gesture.send()

	def _openElementsList(self, elementType, gesture):
		treeInterceptor = self._getBrowseModeTreeInterceptor()
		if treeInterceptor is None:
			ui.message(_("Elements list unavailable"))
			return
		dialogClass = treeInterceptor.ElementsListDialog
		for index, (identifier, _label) in enumerate(dialogClass.ELEMENT_TYPES):
			if identifier == elementType:
				dialogClass.lastSelectedElementType = index
				break
		else:
			ui.message(_("Elements list unavailable"))
			return
		treeInterceptor.script_elementsList(gesture)

	def script_listFormFields(self, gesture):
		"""List form fields in the current Virtual Cursor document."""
		self._openElementsList("formField", gesture)

	def script_listHeadings(self, gesture):
		"""List headings in the current Virtual Cursor document."""
		self._openElementsList("heading", gesture)

	def script_listLinks(self, gesture):
		"""List links in the current Virtual Cursor document."""
		self._openElementsList("link", gesture)

	def script_listButtons(self, gesture):
		"""List buttons in the current Virtual Cursor document."""
		self._openElementsList("button", gesture)

	def script_listLandmarks(self, gesture):
		"""List landmarks, the NVDA equivalent of JAWS regions."""
		self._openElementsList("landmark", gesture)

	def script_findInVirtualBuffer(self, gesture):
		self._findInVirtualBuffer(gesture, "script_find")

	def _findAgainInVirtualBuffer(self, gesture, reverse=False):
		treeInterceptor = api.getFocusObject().treeInterceptor
		if not isinstance(treeInterceptor, browseMode.BrowseModeTreeInterceptor):
			gesture.send()
			return
		text = treeInterceptor._lastFindText
		if not text:
			treeInterceptor.script_find(gesture, reverse=reverse)
			return
		info = treeInterceptor.makeTextInfo(textInfos.POSITION_CARET)
		if not info.find(
			text,
			reverse=reverse,
			caseSensitive=treeInterceptor._lastCaseSensitivity,
		):
			winsound.MessageBeep()
			return
		treeInterceptor.selection = info
		_speechCore.cancelSpeech()
		info.move(textInfos.UNIT_LINE, 1, endPoint="end")
		if not scriptHandler.willSayAllResume(gesture):
			_speechModule.speakTextInfo(
				info, reason=controlTypes.OutputReason.CARET,
			)

	def script_findNextInVirtualBuffer(self, gesture):
		self._findAgainInVirtualBuffer(gesture)

	def script_findPreviousInVirtualBuffer(self, gesture):
		self._findAgainInVirtualBuffer(gesture, reverse=True)

	def script_find(self, gesture):
		target = self._getFindTarget()
		if target is None:
			ui.message(_("Find unavailable"))
			return
		target.script_find(gesture)

	def script_findNext(self, gesture):
		target = self._getFindTarget()
		if target is None or not hasattr(target, "script_findNext"):
			ui.message(_("Find unavailable"))
			return
		target.script_findNext(gesture)

	def script_findPrevious(self, gesture):
		target = self._getFindTarget()
		if target is None or not hasattr(target, "script_findPrevious"):
			ui.message(_("Find unavailable"))
			return
		target.script_findPrevious(gesture)

	def script_reportFont(self, gesture):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			globalCommands.commands.script_reportFormattingAtReview(gesture)
		else:
			globalCommands.commands.script_reportFormattingAtCaret(gesture)

	def script_reportColor(self, gesture):
		info = (
			api.getReviewPosition().copy()
			if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE)
			else self._getPCcursorPosition()
		)
		info.expand(textInfos.UNIT_CHARACTER)
		formatConfig = {
			option: False for option in config.conf["documentFormatting"]
		}
		formatConfig["reportColor"] = True
		formatField = textInfos.FormatField()
		for field in info.getTextWithFields(formatConfig):
			if (
				isinstance(field, textInfos.FieldCommand)
				and isinstance(field.field, textInfos.FormatField)
			):
				formatField.update(field.field)
		if scriptHandler.getLastScriptRepeatCount():
			colors = []
			for label, key in (
				(_("Text"), "color"),
				(_("Background"), "background-color"),
			):
				color = formatField.get(key)
				if all(hasattr(color, component) for component in (
					"red", "green", "blue",
				)):
					colors.append(
						f"{label} {color.red}, {color.green}, {color.blue}",
					)
			ui.message("; ".join(colors) or _("No color information"))
			return
		sequence = info.getFormatFieldSpeech(
			formatField, formatConfig=formatConfig,
		)
		message = " ".join(
			item for item in sequence if isinstance(item, str)
		)
		ui.message(message or _("No color information"))

	def script_reportDefaultButton(self, gesture):
		# DM_GETDEFID returns the ID of a standard Win32 dialog's default
		# button in the low word, and DC_HASDEFID in the high word.
		DM_GETDEFID = 0x0400
		DC_HASDEFID = 0x534B
		focus = api.getFocusObject()
		hwnd = winUser.getAncestor(
			focus.windowHandle, winUser.GA_ROOT,
		) or focus.windowHandle
		result = winUser.sendMessage(hwnd, DM_GETDEFID, 0, 0)
		if result >> 16 != DC_HASDEFID:
			ui.message(_("No default button"))
			return
		buttonHwnd = ctypes.windll.user32.GetDlgItem(hwnd, result & 0xFFFF)
		if not buttonHwnd:
			ui.message(_("No default button"))
			return
		try:
			button = getNVDAObjectFromEvent(
				buttonHwnd, winUser.OBJID_CLIENT, 0,
			)
		except Exception as error:
			self._log(f"Unable to retrieve default button: {error!r}")
			ui.message(_("No default button"))
			return
		_speechModule.speakObject(
			button, reason=controlTypes.OutputReason.QUERY,
		)

	def script_reportFrameAtCursor(self, gesture):
		# Outside the JAWS cursors the review position is wherever it was
		# last left, possibly in another window, so it cannot answer for the
		# cursor the user is actually reading with.
		try:
			obj = self._getReadingPosition().obj
		except Exception as error:
			self._log(f"Unable to find the cursor for frame lookup: {error!r}")
			ui.message(_("No frame"))
			return
		while obj:
			if getattr(obj, "role", None) in (
				controlTypes.Role.FRAME,
				controlTypes.Role.TEXTFRAME,
				controlTypes.Role.INTERNALFRAME,
			):
				_speechModule.speakObject(
					obj, reason=controlTypes.OutputReason.QUERY,
				)
				return
			obj = getattr(obj, "parent", None)
		ui.message(_("No frame"))

	def script_sayFromCursor(self, gesture):
		self._speakReviewRange("cursor", textInfos.POSITION_LAST)

	def _sayReviewWindowLine(self, position):
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			info = api.getReviewPosition().obj.makeTextInfo(position)
		else:
			foreground = api.getForegroundObject()
			root = Window(windowHandle=foreground.windowHandle)
			info = DisplayModelTextInfo(root, position)
		info.expand(textInfos.UNIT_LINE)
		_speechModule.speakTextInfo(
			info,
			unit=textInfos.UNIT_LINE,
			reason=controlTypes.OutputReason.CARET,
		)

	def script_sayTopLineOfWindow(self, gesture):
		self._sayReviewWindowLine(textInfos.POSITION_FIRST)

	def script_sayBottomLineOfWindow(self, gesture):
		self._sayReviewWindowLine(textInfos.POSITION_LAST)

	def _moveMouseBy(self, xOffset, yOffset):
		if self._mode != self.MODE_JAWS:
			ui.message(_("Mouse movement requires JAWS cursor"))
			return
		x, y = winUser.getCursorPos()
		x += xOffset
		y += yOffset
		winUser.setCursorPos(x, y)
		mouseHandler.executeMouseMoveEvent(x, y)
		try:
			root = self._getRestrictionRoot()
			api.setReviewPosition(
				DisplayModelTextInfo(root, Point(x, y)),
				clearNavigatorObject=False,
			)
		except Exception as error:
			self._log(f"Unable to follow mouse with JAWS cursor: {error!r}")

	def _mouseMovementIncrement(self):
		return config.conf["jvda"]["mouseMovementIncrement"]

	def script_moveMouseUp(self, gesture):
		self._moveMouseBy(0, -self._mouseMovementIncrement())

	def script_moveMouseDown(self, gesture):
		self._moveMouseBy(0, self._mouseMovementIncrement())

	def script_moveMouseLeft(self, gesture):
		self._moveMouseBy(-self._mouseMovementIncrement(), 0)

	def script_moveMouseRight(self, gesture):
		self._moveMouseBy(self._mouseMovementIncrement(), 0)

	def _moveMouseToJawsCursor(self):
		"""Park the mouse on the JAWS Cursor, refusing in other modes.

		Every caller physically clicks, drags or locks a mouse button here.
		Outside JAWS and Invisible Cursor mode the review position is
		wherever it was last left -- possibly in another window -- so acting
		on it would activate whatever happens to be under a stale point.
		JAWSKey+4 in particular stays bound in every mode.
		"""
		if self._mode not in (self.MODE_JAWS, self.MODE_INVISIBLE):
			ui.message(_("Mouse commands require JAWS cursor"))
			return False
		try:
			point = api.getReviewPosition().pointAtStart
			winUser.setCursorPos(point.x, point.y)
			mouseHandler.executeMouseMoveEvent(point.x, point.y)
		except Exception as error:
			self._log(f"Unable to move mouse to JAWS cursor: {error!r}")
			ui.message(_("No mouse location"))
			return False
		return True

	def script_leftMouseClickAtJawsCursor(self, gesture):
		if not self._moveMouseToJawsCursor():
			return
		mouseHandler.executeMouseEvent(winUser.MOUSEEVENTF_LEFTDOWN, 0, 0)
		mouseHandler.executeMouseEvent(winUser.MOUSEEVENTF_LEFTUP, 0, 0)
		ui.message(_("Left click"))

	def script_rightMouseClickAtJawsCursor(self, gesture):
		if not self._moveMouseToJawsCursor():
			return
		mouseHandler.executeMouseEvent(winUser.MOUSEEVENTF_RIGHTDOWN, 0, 0)
		mouseHandler.executeMouseEvent(winUser.MOUSEEVENTF_RIGHTUP, 0, 0)
		ui.message(_("Right click"))

	def script_toggleLeftMouseButtonAtJawsCursor(self, gesture):
		if self._moveMouseToJawsCursor():
			if mouseHandler.isLeftMouseButtonLocked():
				mouseHandler.unlockLeftMouseButton()
				self._leftButtonLockedByJvda = False
			else:
				mouseHandler.lockLeftMouseButton()
				self._leftButtonLockedByJvda = True

	def script_toggleRightMouseButtonAtJawsCursor(self, gesture):
		if self._moveMouseToJawsCursor():
			if mouseHandler.isRightMouseButtonLocked():
				mouseHandler.unlockRightMouseButton()
				self._rightButtonLockedByJvda = False
			else:
				mouseHandler.lockRightMouseButton()
				self._rightButtonLockedByJvda = True

	def _releaseLockedMouseButtons(self):
		if self._leftButtonLockedByJvda:
			try:
				mouseHandler.unlockLeftMouseButton()
			except Exception as error:
				self._log(f"Unable to release left mouse button: {error!r}")
			finally:
				self._leftButtonLockedByJvda = False
		if self._rightButtonLockedByJvda:
			try:
				mouseHandler.unlockRightMouseButton()
			except Exception as error:
				self._log(f"Unable to release right mouse button: {error!r}")
			finally:
				self._rightButtonLockedByJvda = False
		self._dragSource = None

	@staticmethod
	def _windowAtPoint(x, y):
		windowFromPoint = ctypes.windll.user32.WindowFromPoint
		windowFromPoint.argtypes = (ctypes.wintypes.POINT,)
		windowFromPoint.restype = ctypes.c_void_p
		return windowFromPoint(ctypes.wintypes.POINT(x, y))

	def script_dragAndDropAtJawsCursor(self, gesture):
		if not self._moveMouseToJawsCursor():
			return
		x, y = winUser.getCursorPos()
		if self._dragSource is None:
			self._dragSource = (x, y, self._windowAtPoint(x, y))
			ui.message(_("Drag source marked"))
			return
		sourceX, sourceY, sourceWindow = self._dragSource
		self._dragSource = None
		if sourceWindow != self._windowAtPoint(sourceX, sourceY):
			ui.message(_("Drag source is no longer available"))
			return
		if (sourceX, sourceY) == (x, y):
			ui.message(_("Drag destination is unchanged"))
			return
		if mouseHandler.isLeftMouseButtonLocked():
			mouseHandler.unlockLeftMouseButton()
			self._leftButtonLockedByJvda = False
		try:
			winUser.setCursorPos(sourceX, sourceY)
			mouseHandler.executeMouseMoveEvent(sourceX, sourceY)
			mouseHandler.lockLeftMouseButton()
			self._leftButtonLockedByJvda = True
			winUser.setCursorPos(x, y)
			mouseHandler.executeMouseMoveEvent(x, y)
			ui.message(_("Drag complete"))
		finally:
			if self._leftButtonLockedByJvda:
				mouseHandler.unlockLeftMouseButton()
				self._leftButtonLockedByJvda = False

	def script_topOfWindow(self, gesture):
		"""Ctrl+Home in a review cursor: move to the top of the window."""
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._prepareJawsCursorMovement()
			globalCommands.commands.script_review_top(gesture)
		elif self._mode != self.MODE_SCRIPT:
			self._movePCcursor("control+home")
		else:
			self._reportUnavailableInThisCursor()

	def script_bottomOfWindow(self, gesture):
		"""Ctrl+End in a review cursor: move to the bottom of the window."""
		if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
			self._prepareJawsCursorMovement()
			globalCommands.commands.script_review_bottom(gesture)
		elif self._mode != self.MODE_SCRIPT:
			self._movePCcursor("control+end")
		else:
			self._reportUnavailableInThisCursor()

	# ------------------------------------------------------------------
	# Window list (NVDA+F10)
	# ------------------------------------------------------------------

	def _topLevelWindows(self):
		"""Return (hwnd, name) pairs for all visible top-level windows."""
		pairs = []

		@winUser._WNDENUMPROC
		def collectWindow(hwnd, _lParam):
			if winUser.isWindowVisible(hwnd) and (
				name := winUser.getWindowText(hwnd).strip()
			):
				pairs.append((hwnd, name))
			return True

		winUser._user32.EnumWindows(collectWindow, 0)
		self._log(f"EnumWindows raw count: {len(pairs)}")
		# Window identity is its handle, not its title. Keep duplicate titles
		# so two documents or dialogs with the same caption remain reachable.
		windows = sorted(pairs, key=lambda pair: str.casefold(pair[1]))
		names = [name for _hwnd, name in windows]
		self._log(f"Top-level windows ({len(windows)}): {names}")
		return windows

	_SHELL_PROCESS_NAMES = frozenset(
		name.casefold()
		for name in (
			"SearchHost.exe",
			"SearchApp.exe",
			"StartMenuExperienceHost.exe",
			"ShellExperienceHost.exe",
			"SystemSettings.exe",
			"TextInputHost.exe",
			"WindowsInternal.ComposableShell.Experiences."
			"TextInput.InputApp.exe",
		)
	)

	@staticmethod
	def _getProcessName(pid):
		import ctypes

		TH32CS_SNAPPROCESS = 2
		try:
			snapshot = winBindings.kernel32.CreateToolhelp32Snapshot(
				TH32CS_SNAPPROCESS, 0,
			)
			if snapshot == -1:
				return ""
		except Exception:
			return ""
		try:
			entry = winBindings.kernel32.PROCESSENTRY32W()
			entry.dwSize = ctypes.sizeof(entry)
			if not winBindings.kernel32.Process32First(
				snapshot, ctypes.byref(entry),
			):
				return ""
			while True:
				if entry.th32ProcessID == pid:
					return entry.szExeFile
				if not winBindings.kernel32.Process32Next(
					snapshot, ctypes.byref(entry),
				):
					break
			return ""
		finally:
			winBindings.kernel32.CloseHandle(snapshot)

	def _isSystemWindow(self, hwnd):
		"""Return (isSystem, reason) for *hwnd*."""
		import ctypes

		name = winUser.getWindowText(hwnd).strip()
		exStyle = winUser.getExtendedWindowStyle(hwnd)
		if (
			exStyle & winUser.WS_EX_TOOLWINDOW
			and not exStyle & winUser.WS_EX_APPWINDOW
		):
			return True, "tool-window"
		if exStyle & winUser.WS_EX_NOACTIVATE:
			return True, "no-activate"
		if not winUser.isWindowEnabled(hwnd):
			return True, "disabled"
		rect = ctypes.wintypes.RECT()
		if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
			if (
				rect.right - rect.left <= 0
				or rect.bottom - rect.top <= 0
			):
				return True, "zero-size"
		try:
			if winUser.getWindow(hwnd, winUser.GW_OWNER):
				return True, "owned"
		except Exception:
			pass
		_pid, _tid = winUser.getWindowThreadProcessID(hwnd)
		procName = self._getProcessName(_pid) if _pid else ""
		self._log(
			f"_isSystemWindow {name!r} pid={_pid} proc={procName!r} "
			f"exStyle=0x{exStyle:08X} "
			f"enabled={winUser.isWindowEnabled(hwnd)}",
		)
		if _pid and procName.casefold() in self._SHELL_PROCESS_NAMES:
			return True, f"shell-process({procName})"
		return False, ""

	def _showWindowsListDialog(self):
		allWindows = self._topLevelWindows()

		def show():
			dialog = _WindowsListDialog(
				gui.mainFrame, _("Open windows"), allWindows, self,
			)
			gui.mainFrame.prePopup()
			try:
				if dialog.ShowModal() == wx.ID_OK:
					dialog.activateSelected()
			finally:
				gui.mainFrame.postPopup()
				dialog.Destroy()

		wx.CallAfter(show)

	def _showTrayListDialog(self, title, entries, actionLocations=None):
		"""*entries* is a list of ``(name, obj)`` pairs."""
		def show():
			dialog = _TrayListDialog(
				gui.mainFrame, title, entries, actionLocations,
			)
			gui.mainFrame.prePopup()
			try:
				dialog.ShowModal()
			finally:
				gui.mainFrame.postPopup()
				dialog.Destroy()

		wx.CallAfter(show)

	def script_openWindowsList(self, gesture):
		if not self._topLevelWindows():
			ui.message(_("No open windows"))
			return
		self._showWindowsListDialog()

	# ------------------------------------------------------------------
	# System tray icons (NVDA+F11)
	# ------------------------------------------------------------------

	def _trayNVDAObjects(self):
		roots = []
		for hwnd in self._topLevelWindowHandles():
			className = winUser.getClassName(hwnd)
			if className in (
				"Shell_TrayWnd",
				"NotifyIconOverflowWindow",
				"TopLevelWindowForOverflowXamlIsland",
			):
				try:
					roots.append(
						getNVDAObjectFromEvent(
							hwnd, winUser.OBJID_CLIENT, 0,
						),
					)
					self._log(f"Tray root: {className}")
				except Exception as exc:
					self._log(f"Tray root {className} failed: {exc!r}")
		# Windows 11 may expose an empty top-level XAML island while the
		# focused flyout object has the actual icon children. Include that
		# accessibility ancestor when the overflow is open.
		try:
			focus = api.getFocusObject()
			obj = focus
			for _depth in range(12):
				name = (getattr(obj, "name", "") or "").casefold()
				if "system tray overflow window" in name:
					if all(id(root) != id(obj) for root in roots):
						roots.append(obj)
					# The XAML parent can report no children. Its focused icon is
					# still a reliable named leaf and can be listed directly.
					if all(id(root) != id(focus) for root in roots):
						roots.append(focus)
					break
				obj = getattr(obj, "parent", None)
				if obj is None:
					break
		except Exception as error:
			self._log(f"Focused tray overflow root failed: {error!r}")
		self._log(f"Tray roots count: {len(roots)}")
		return roots

	def _topLevelWindowHandles(self):
		handles = []

		@winUser._WNDENUMPROC
		def collectWindow(hwnd, _lParam):
			handles.append(hwnd)
			return True

		winUser._user32.EnumWindows(collectWindow, 0)
		return handles

	def _openTrayOverflow(self, roots):
		"""Open the hidden-icons flyout through its real accessibility action."""
		overflowRoots = [
			root for root in roots
			if getattr(root, "windowClassName", "") in (
				"NotifyIconOverflowWindow",
				"TopLevelWindowForOverflowXamlIsland",
			)
		]
		if overflowRoots and self._leafNames(overflowRoots):
			return True
		seen = set()
		overflowTarget = [None]

		def visit(obj):
			if id(obj) in seen:
				return False
			seen.add(id(obj))
			try:
				name = (obj.name or "").casefold()
			except Exception:
				name = ""
			if "hidden icon" in name or "notification overflow" in name:
				overflowTarget[0] = obj
				return True
			try:
				children = obj.children
			except Exception:
				children = ()
			return any(visit(child) for child in children)

		def waitForOverflow():
			for _attempt in range(10):
				time.sleep(0.1)
				api.processPendingEvents()
				overflowRoots = [
					root for root in self._trayNVDAObjects()
					if getattr(root, "windowClassName", "") in (
						"NotifyIconOverflowWindow",
						"TopLevelWindowForOverflowXamlIsland",
					)
				]
				if overflowRoots and self._leafNames(overflowRoots):
					return True
			return False

		opened = any(visit(root) for root in roots)
		if opened and overflowTarget[0] is not None:
			try:
				left, top, width, height = overflowTarget[0].location
				x, y = left + width // 2, top + height // 2
				winUser.setCursorPos(x, y)
				ctypes.windll.user32.mouse_event(
					winUser.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0,
				)
				ctypes.windll.user32.mouse_event(
					winUser.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0,
				)
				waitForOverflow()
			except Exception as error:
				self._log(f"Unable to click tray overflow: {error!r}")
		return opened

	def _leafNames(self, roots):
		"""Return sorted ``(name, obj)`` pairs for tray icon buttons.

		We collect the deepest-named object whose role suggests it is a
		clickable toolbar button — not leaf text/graphic children
		whose ``location`` may be wrong."""
		pairs = {}  # name → obj (dedup by name)
		seen = set()

		def visit(obj, depth=0):
			objectId = id(obj)
			if objectId in seen:
				return
			seen.add(objectId)
			try:
				objName = obj.name or ""
			except Exception:
				objName = ""
			try:
				objClass = obj.windowClassName
			except Exception:
				objClass = ""
			try:
				objRole = obj.role
			except Exception:
				objRole = None
			try:
				children = obj.children
			except Exception:
				return
			if children:
				for child in children:
					visit(child, depth + 1)
			elif isinstance(objName, str) and objName.strip():
				# We are at a named leaf.  Walk up to the nearest
				# clickable ancestor.
				btn = obj
				for _ in range(6):
					try:
						role = btn.role
					except Exception:
						break
					if role in (
						controlTypes.Role.BUTTON,
						controlTypes.Role.TOGGLEBUTTON,
						controlTypes.Role.CHECKBOX,
						controlTypes.Role.RADIOBUTTON,
						controlTypes.Role.LISTITEM,
					):
						break
					try:
						parent = btn.parent
					except Exception:
						break
					if parent is None:
						break
					btn = parent
				name = objName.strip()
				if name not in pairs:
					pairs[name] = btn

		for root in roots:
			try:
				rootClass = root.windowClassName
			except Exception:
				rootClass = "?"
			self._log(
				f"LeafNames root: {type(root).__name__} "
				f"class={rootClass!r}",
			)
			visit(root)
		_skip = frozenset(
			n.casefold() for n in ("DesktopWindowXamlSource", "Start")
		)
		filtered = [
			(name, obj)
			for name, obj in pairs.items()
			if "running window" not in name.casefold()
			and name.casefold().split("\n")[0].strip().casefold() not in _skip
			and "hidden icon" not in name.casefold()
		]
		result = sorted(filtered, key=lambda p: str.casefold(p[0]))
		self._log(f"Leaf names ({len(result)}): {[n for n, _ in result]}")
		return result

	def _showTrayIcons(self):
		roots = self._trayNVDAObjects()
		if self._openTrayOverflow(roots):
			roots = self._trayNVDAObjects()
		icons = self._leafNames(roots)
		if not icons:
			ui.message(_("No system tray icons"))
			return
		actionLocations = {}
		try:
			focusName = api.getFocusObject().name
			import UIAHandler
			rect = UIAHandler.handler.clientObject.GetFocusedElement().CurrentBoundingRectangle
			if rect.right > rect.left and rect.bottom > rect.top:
				actionLocations[focusName] = (
					rect.left, rect.top, rect.right - rect.left,
					rect.bottom - rect.top,
				)
		except Exception as error:
			self._log(f"Focused tray action location unavailable: {error!r}")
		self._showTrayListDialog(
			_("System tray icons"), icons, actionLocations,
		)

	def script_openSystemTrayIconsList(self, gesture):
		self._showTrayIcons()

	# ------------------------------------------------------------------
	# Debug: dump current control info
	# ------------------------------------------------------------------

	def _diagnosticState(self):
		"""Return cursor and object types without exposing document text."""
		def describeObject(obj):
			if obj is None:
				return "None"
			role = getattr(obj, "role", None)
			return f"{type(obj).__name__} role={role}"

		focus = api.getFocusObject()
		try:
			caret = api.getCaretObject()
		except Exception:
			caret = None
		try:
			reviewPosition = api.getReviewPosition()
			reviewObject = reviewPosition.obj
		except Exception:
			reviewObject = None
		treeInterceptor = getattr(focus, "treeInterceptor", None)
		return {
			"mode": self._mode,
			"restriction": self._RESTRICTIONS[self._restrictionIndex],
			"virtualRestriction": self._virtualRestriction,
			"reviewMode": review.getCurrentMode(),
			"focus": describeObject(focus),
			"navigator": describeObject(api.getNavigatorObject()),
			"caret": describeObject(caret),
			"review": describeObject(reviewObject),
			"treeInterceptor": (
				type(treeInterceptor).__name__ if treeInterceptor else "None"
			),
			"passThrough": getattr(treeInterceptor, "passThrough", None),
			"leftMouseLocked": self._leftButtonLockedByJvda,
			"rightMouseLocked": self._rightButtonLockedByJvda,
		}

	def script_reportDiagnostics(self, gesture):
		"""Show non-sensitive JVDA cursor diagnostics."""
		state = self._diagnosticState()
		message = "\n".join(
			f"{name}: {value}" for name, value in state.items()
		)
		ui.browseableMessage(message, _("JVDA diagnostics"))

	def script_debugCurrentControl(self, gesture):
		obj = api.getFocusObject()
		lines = []
		for attr in (
			"name",
			"role",
			"windowClassName",
			"windowControlID",
			"UIAElement",
			"UIAElement.cachedClassName",
			"UIAElement.cachedControlType",
			"UIAElement.cachedLocalizedControlType",
		):
			try:
				val = obj
				for part in attr.split("."):
					val = getattr(val, part)
				lines.append(f"{attr}: {val!r}")
			except Exception:
				pass
		lines.append(
			"MRO: " + " -> ".join(t.__name__ for t in type(obj).__mro__),
		)
		self._log("Control debug:\n" + "\n".join(lines))
		ui.message(type(obj).__name__)

	# ------------------------------------------------------------------
	# Virtualize current window (NVDA+Alt+W)
	# ------------------------------------------------------------------

	def script_virtualizeCurrentControl(self, gesture):
		VirtualWindow.showDialog(api.getFocusObject(), preferNative=True)

	def script_virtualizeCurrentWindow(self, gesture):
		VirtualWindow.showDialog(api.getForegroundObject())

	def script_virtualizeCurrentWindowRaw(self, gesture):
		VirtualWindow.showDialog(
			api.getForegroundObject(), rawXml=True,
		)

	# Translators: description for the virtualize current window command.
	script_virtualizeCurrentControl.__doc__ = _(
		"Shows all text from the current control in a read-only dialog",
	)
	script_virtualizeCurrentWindow.__doc__ = _(
		"Shows all text from the current window in a read-only dialog",
	)
	script_virtualizeCurrentWindowRaw.__doc__ = _(
		"Shows the raw display-model XML from the current window",
	)

	# Input Help only reports a script's docstring. Ensure every mapped
	# JAWS command identifies itself instead of speaking just the key.
	_jawsInputHelpDescriptions = {
		"previousLine": _("Moves to the previous line"),
		"currentLine": _("Reports the current line"),
		"nextLine": _("Moves to the next line"),
		"previousWord": _("Moves to the previous word"),
		"currentWord": _("Reports the current word"),
		"nextWord": _("Moves to the next word"),
		"previousCharacter": _("Moves to the previous character"),
		"currentCharacter": _("Reports the current character"),
		"nextCharacter": _("Moves to the next character"),
		"sayAll": _("Reads from the active cursor"),
		"cycleRestriction": _("Cycles active cursor restriction"),
		"reportActiveCursor": _("Reports the active cursor"),
		"toggleVirtualPCcursor": _("Toggles Virtual PC Cursor"),
		"routePCcursorToJawsCursor": _("Routes PC cursor to JAWS cursor"),
		"moveJawsCursorToPCcursor": _("Moves JAWS cursor to PC cursor"),
		"toggleJawsToPcTether": _(
			"Toggles whether JAWS Cursor follows PC Cursor",
		),
		"find": _("Finds text"),
		"findNext": _("Finds next occurrence"),
		"findPrevious": _("Finds previous occurrence"),
		"reportApplicationFileName": _("Reports the application file name"),
	}
	for _script in (
		tuple(__gestures.values())
		+ tuple(_JAWS_GESTURES.values())
		+ tuple(_SPACE_LAYER_GESTURES.values())
	):
		_method = locals().get(f"script_{_script}")
		if _method is not None and not _method.__doc__:
			_description = _jawsInputHelpDescriptions.get(_script)
			if _description is None:
				commandName = re.sub(r"(?<!^)(?=[A-Z])", " ", _script).lower()
				_description = _("JAWS command: {}").format(commandName)
			_method.__doc__ = _description
	del _script, _method, _description, _jawsInputHelpDescriptions
