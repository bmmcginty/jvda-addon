"""JVDA's layered JAWSKey+Space command.

JAWS reserves ``JAWSKey+Space`` as a prefix: the next key selects a command
from a layer, and some keys open a sublayer whose own keys select further
commands.  NVDA's gesture system has no layered gestures, so JVDA binds only
the prefix as a script and dispatches every key inside the layer through
``inputCore.decide_handleRawKey``.  The raw hook is required rather than
convenient: a key with no JAWS command must be reported and must end the
layer, which a gesture binding cannot do, and the raw hook cannot leave a
stale binding behind if JVDA is unloaded while a layer is open.

Two implementation facts are worth stating, because they differ from what
NVDA's own commands do.

First, ``inputCore.decide_handleRawKey`` runs on NVDA's low-level keyboard
hook thread, not on NVDA's main thread
(``nvda2/source/winInputHook.py`` installs the hook on its own thread, and
``keyboardHandler.internal_keyDownEvent`` calls the decider directly).
Speaking, beeping and especially ``ui.browseableMessage`` must not run there.
``_onSpaceLayerRawKey`` therefore does only the decision -- which layer, which
key, consume or pass through -- and updates the layer state synchronously, and
queues every effect onto ``queueHandler.eventQueue`` so the effect runs on
NVDA's main thread.

Second, ``inputCore.decide_handleRawKey`` is not given the injected flag that
``keyboardHandler.internal_keyDownEvent`` receives, so the layer cannot test a
key for injection directly.  ``_onSpaceLayerRawKey`` instead honours the two
flags JVDA and NVDA set while injecting: ``keyboardHandler.ignoreInjected``
and JVDA's own ``_capslockToggleInProgress``.
"""

# This module deliberately imports nothing from NVDA at module scope.  Every
# NVDA import is deferred into the method that needs it, so that the tests can
# read the tables below without an NVDA runtime and so that NVDA's subsystem
# initialisation order is not disturbed while the add-on is imported.


#: How long a layer stays open without a key press, in milliseconds.
#: [verify] against live JAWS; JAWS's own value is not documented.
LAYER_TIMEOUT_MS = 2000

#: Beeps played when a layer opens: two rising tones, do then so.
ENTER_TONES = ((523, 60), (784, 60))

#: Beeps played when a layer closes: two falling tones, so then do.
EXIT_TONES = ((784, 60), (523, 60))

#: Keys that end the layer wherever they are pressed, matching JAWS.
LAYER_EXIT_KEYS = ("escape", "space", "tab", "enter", "numpadEnter")

#: The key that shows the open layer's own help.
LAYER_HELP_KEY = "shift+/"

#: Layer commands which open a window.  The layer must close before one of
#: these runs, or the still-open layer swallows the keys used to read that
#: window.  Basic-layer commands close the layer anyway; this set is what
#: makes the sublayer help behave the same way.
LAYER_CLOSING_COMMANDS = frozenset({
	"layerHelp",
	"layerViewClipboardText",
	"layerCommandsSearch",
})

#: Spoken when the pressed key has no JAWS command in the shipped keymap.
#: Translators: spoken in a JAWSKey+Space layer when the pressed key has no
#: JAWS command at all.
LAYER_UNASSIGNED_MESSAGE = "command unassigned"

#: Spoken when the pressed key has a JAWS command that JVDA cannot support.
#: Translators: spoken in a JAWSKey+Space layer when the pressed key has a
#: JAWS command which JVDA does not implement.
LAYER_INVALID_MESSAGE = "command invalid"

#: Titles used by the per-layer help, keyed by layer name.
LAYER_TITLES = {
	"basic": "JAWSKey+Space layer",
	"volume": "JAWSKey+Space volume layer",
	"volumeJaws": "JAWSKey+Space JAWS volume layer",
	"volumeSystem": "JAWSKey+Space system volume layer",
	"volumeBalance": "JAWSKey+Space sound balance layer",
	"volumeSoundCard": "JAWSKey+Space sound card layer",
	"table": "JAWSKey+Space table layer",
	"viewer": "JAWSKey+Space braille and text viewer layer",
	"echo": "JAWSKey+Space mouse echo layer",
	"ocr": "JAWSKey+Space OCR layer",
	"picture": "JAWSKey+Space Picture Smart layer",
	"skype": "JAWSKey+Space Skype layer",
	"face": "JAWSKey+Space Face in View layer",
	"faceCamera": "JAWSKey+Space Face in View camera layer",
}

#: The key in each layer that opens a sublayer JVDA implements, mapped to the
#: sublayer name. A sublayer entry is a layer transition rather than a command,
#: so these keys are deliberately absent from LAYER_INVENTORY.
#:
#: Only sublayers with commands behind them appear here. A sublayer JVDA cannot
#: support is not offered at all: see UNSUPPORTED_SUBLAYERS.
LAYER_SUBLAYERS = {
	"basic": {
		"t": "table",
		"v": "volume",
	},
	"volume": {
		"b": "volumeBalance",
		"c": "volumeSoundCard",
		"j": "volumeJaws",
	},
}

#: Keys that open a JAWS sublayer JVDA cannot support, mapped to the JAWS name
#: of that sublayer.
#:
#: These are deliberately not layers in JVDA. Opening one would put the user
#: inside a layer where every single key reports "command invalid", with no way
#: to tell that the whole sublayer is unavailable. The entry key reports
#: "command invalid" itself and ends the layer, which answers the question in
#: one keystroke.
UNSUPPORTED_SUBLAYERS = {
	"basic": {
		# Translators: the JAWS braille and text viewer layer, which JVDA
		# does not implement.
		"b": "braille and text viewer layer",
		# Translators: the JAWS mouse echo layer, which JVDA does not
		# implement.
		"e": "mouse echo layer",
		# Translators: the JAWS Face in View layer, which JVDA does not
		# implement.
		"f": "Face in View layer",
		# Translators: the JAWS OCR layer, which JVDA does not implement.
		"o": "OCR layer",
		# Translators: the JAWS Picture Smart layer, which JVDA does not
		# implement.
		"p": "Picture Smart layer",
		# Translators: the JAWS Skype layer, which JVDA does not implement.
		"y": "Skype layer",
	},
	"volume": {
		# Translators: the JAWS system volume layer, which JVDA does not
		# implement.
		"s": "system volume layer",
	},
}

#: Every key JAWS 2026 assigns inside a JAWSKey+Space layer, mapped to the
#: JAWS command name, keyed by NVDA gesture spelling.  Generated from
#: ``reference/default.jkm`` and checked against it by
#: ``tests/test_space_layer.py``.  A key present here but absent from the
#: layer's JVDA command table reports "command invalid"; a key absent here
#: reports "command unassigned".
LAYER_INVENTORY = {
	"basic": {
		"`": "VolumeControlNotifications",
		"a": "ToggleTextAnalyzer",
		"c": "ViewClipboardText",
		"d": "ToggleAudioDucking",
		"f1": "LaunchFSCompanion",
		"f11": "ScreenShadeToggle",
		"f2": "LaunchFusionAI",
		"f4": "RestartWithoutDump",
		"h": "ShowSpeechHistory",
		"j": "LaunchCommandsSearch",
		"l": "LockKeyboard",
		"m": "SelectTextBetweenMarkedPlaceAndCurrentPosition",
		"n": "ShowNotificationHistory",
		"printScreen": "ScreenShadeToggle",
		"q": "OpenQuickAccessBar",
		"r": "ResearchItByEnteringTerm",
		"s": "MuteSynthesizer",
		"x": "DoFlexibleWebDialog",
		"z": "ToggleDefaultUserMode",
		"alt+l": "ShowLabelManager",
		"control+h": "CopySpeechHistoryToClipboard",
		"control+n": "ToggleToastNotificationAnnouncement",
		"shift+/": "BasicLayerHelp",
		"shift+=": "ShowMathEditor",
		"shift+h": "ClearSpeechHistory",
		"shift+m": "MessageCenter",
		"shift+n": "RepeatLastNotification",
		"shift+r": "RepeatLastSkypeNotification",
		"shift+s": "SpeechOnDemandToggle",
	},
	"volume": {
		"escape": "ExitVolumeLayer",
		"shift+/": "VolumesLayerHelp",
	},
	"volumeJaws": {
		"downArrow": "JAWSVolumeDownSmall",
		"escape": "ExitVolumeLayer",
		"leftArrow": "JAWSVolumeDownSmall",
		"numpad2": "JAWSVolumeDownSmall",
		"numpad3": "JAWSVolumeDownLarge",
		"numpad4": "JAWSVolumeDownSmall",
		"numpad6": "JAWSVolumeUpSmall",
		"numpad8": "JAWSVolumeUpSmall",
		"numpad9": "JAWSVolumeUpLarge",
		"pageDown": "JAWSVolumeDownLarge",
		"pageUp": "JAWSVolumeUpLarge",
		"rightArrow": "JAWSVolumeUpSmall",
		"upArrow": "JAWSVolumeUpSmall",
		"shift+/": "JAWSVolumeLayerHelp",
	},
	"volumeSystem": {
		"downArrow": "SystemVolumeDownSmall",
		"escape": "ExitVolumeLayer",
		"leftArrow": "SystemVolumeDownSmall",
		"numpad2": "SystemVolumeDownSmall",
		"numpad3": "SystemVolumeDownLarge",
		"numpad4": "SystemVolumeDownSmall",
		"numpad6": "SystemVolumeUpSmall",
		"numpad8": "SystemVolumeUpSmall",
		"numpad9": "SystemVolumeUpLarge",
		"pageDown": "SystemVolumeDownLarge",
		"pageUp": "SystemVolumeUpLarge",
		"rightArrow": "SystemVolumeUpSmall",
		"upArrow": "SystemVolumeUpSmall",
		"shift+/": "SystemVolumeLayerHelp",
	},
	"volumeBalance": {
		"escape": "ExitVolumeLayer",
		"leftArrow": "RouteJAWSSoundLeft",
		"numpad4": "RouteJAWSSoundLeft",
		"numpad6": "RouteJAWSSoundRight",
		"numpad8": "RestoreSoundBalance",
		"rightArrow": "RouteJAWSSoundRight",
		"upArrow": "RestoreSoundBalance",
		"shift+/": "SoundBalanceHelp",
	},
	"volumeSoundCard": {
		"downArrow": "SelectNextSoundCard",
		"escape": "ExitVolumeLayer",
		"numpad2": "SelectNextSoundCard",
		"numpad8": "SelectPreviousSoundCard",
		"upArrow": "SelectPreviousSoundCard",
		"shift+/": "SoundCardsHelp",
	},
	"table": {
		",": "SayCell",
		".": "NextCell",
		"downArrow": "DownCell",
		"end": "MoveToEndOfRow",
		"escape": "ExitTableLayer",
		"home": "MoveToStartOfRow",
		"leftArrow": "PriorCell",
		"m": "PriorCell",
		"n": "DownCell",
		"numpad1": "MoveToEndOfRow",
		"numpad2": "DownCell",
		"numpad4": "PriorCell",
		"numpad5": "SayCell",
		"numpad6": "NextCell",
		"numpad7": "MoveToStartOfRow",
		"numpad8": "UpCell",
		"rightArrow": "NextCell",
		"t": "MoveToNextTable",
		"upArrow": "UpCell",
		"y": "UpCell",
		"alt+,": "SayCell",
		"control+,": "FSReaderRewind",
		"control+.": "FSReaderFastForward",
		"control+downArrow": "MoveToBottomOfColumn",
		"control+end": "LastCellInTable",
		"control+enter": "MoveToNextTable",
		"control+home": "FirstCellInTable",
		"control+leftArrow": "MoveToStartOfRow",
		"control+numpad1": "LastCellInTable",
		"control+numpad2": "MoveToBottomOfColumn",
		"control+numpad4": "MoveToStartOfRow",
		"control+numpad6": "MoveToEndOfRow",
		"control+numpad7": "FirstCellInTable",
		"control+numpad8": "MoveToTopOfColumn",
		"control+numpadEnter": "MoveToNextTable",
		"control+p": "FSReaderPlay",
		"control+rightArrow": "MoveToEndOfRow",
		"control+upArrow": "MoveToTopOfColumn",
		"NVDA+,": "SayCell",
		"shift+,": "ReadCurrentColumn",
		"shift+/": "TableLayerHelp",
		"shift+end": "ReadFromTopOfColumn",
		"shift+home": "ReadToCurrentCell",
		"shift+numpad1": "ReadFromTopOfColumn",
		"shift+numpad3": "ReadToBottomOfColumn",
		"shift+numpad5": "ReadCurrentColumn",
		"shift+numpad7": "ReadToCurrentCell",
		"shift+numpad8": "ReadCurrentRow",
		"shift+numpad9": "ReadFromCurrentCell",
		"shift+pageDown": "ReadToBottomOfColumn",
		"shift+pageUp": "ReadFromCurrentCell",
		"shift+t": "MoveToPriorTable",
		"shift+upArrow": "ReadCurrentRow",
		"windows+,": "ReadCurrentRow",
		"windows+.": "ReadCurrentColumn",
		"windows+j": "JumpReturnFromTableCell",
		"alt+control+downArrow": "DownCell",
		"alt+control+end": "LastCellInTable",
		"alt+control+enter": "MoveToNextTable",
		"alt+control+home": "FirstCellInTable",
		"alt+control+leftArrow": "PriorCell",
		"alt+control+numpad1": "LastCellInTable",
		"alt+control+numpad2": "DownCell",
		"alt+control+numpad4": "PriorCell",
		"alt+control+numpad5": "SayCell",
		"alt+control+numpad6": "NextCell",
		"alt+control+numpad7": "FirstCellInTable",
		"alt+control+numpad8": "UpCell",
		"alt+control+numpadEnter": "MoveToNextTable",
		"alt+control+rightArrow": "NextCell",
		"alt+control+upArrow": "UpCell",
		"alt+shift+,": "SayCell",
		"alt+shift+.": "NextCell",
		"alt+shift+m": "PriorCell",
		"alt+shift+n": "DownCell",
		"alt+shift+y": "UpCell",
		"control+shift+enter": "MoveToPriorTable",
		"control+shift+numpadEnter": "MoveToPriorTable",
		"shift+NVDA+end": "ReadFromTopOfColumn",
		"shift+NVDA+home": "ReadToCurrentCell",
		"shift+NVDA+numpad1": "ReadFromTopOfColumn",
		"shift+NVDA+numpad3": "ReadToBottomOfColumn",
		"shift+NVDA+numpad5": "ReadCurrentColumn",
		"shift+NVDA+numpad7": "ReadToCurrentCell",
		"shift+NVDA+numpad8": "ReadCurrentRow",
		"shift+NVDA+numpad9": "ReadFromCurrentCell",
		"shift+NVDA+pageDown": "ReadToBottomOfColumn",
		"shift+NVDA+pageUp": "ReadFromCurrentCell",
		"shift+NVDA+upArrow": "ReadCurrentRow",
		"alt+control+shift+downArrow": "MoveToBottomOfColumn",
		"alt+control+shift+enter": "MoveToPriorTable",
		"alt+control+shift+leftArrow": "MoveToStartOfRow",
		"alt+control+shift+numpad2": "MoveToBottomOfColumn",
		"alt+control+shift+numpad4": "MoveToStartOfRow",
		"alt+control+shift+numpad6": "MoveToEndOfRow",
		"alt+control+shift+numpad8": "MoveToTopOfColumn",
		"alt+control+shift+numpadEnter": "MoveToPriorTable",
		"alt+control+shift+rightArrow": "MoveToEndOfRow",
		"alt+control+shift+upArrow": "MoveToTopOfColumn",
		"control+shift+windows+j": "JumpReturnFromTableCell",
	},
	"viewer": {
		"b": "ToggleBrailleViewerEnable",
		"downArrow": "BrailleViewerNextLine",
		"leftArrow": "PanBrailleViewerLeft",
		"numpad2": "BrailleViewerNextLine",
		"numpad4": "PanBrailleViewerLeft",
		"numpad6": "PanBrailleViewerRight",
		"numpad8": "BrailleViewerPriorLine",
		"rightArrow": "PanBrailleViewerRight",
		"t": "ToggleTextViewerEnable",
		"upArrow": "BrailleViewerPriorLine",
		"control+leftArrow": "PanTextViewerLeft",
		"control+numpad4": "PanTextViewerLeft",
		"control+numpad6": "PanTextViewerRight",
		"control+rightArrow": "PanTextViewerRight",
		"shift+/": "BrailleAndTextViewerLayerHelp",
		"shift+leftArrow": "PanBrailleViewerLeftLine2",
		"shift+numpad4": "PanBrailleViewerLeftLine2",
		"shift+numpad6": "PanBrailleViewerRightLine2",
		"shift+rightArrow": "PanBrailleViewerRightLine2",
	},
	"echo": {
		"c": "SetMouseEchoToCharacter",
		"d": "ToggleMouseEchoItemDescriptionException",
		"l": "SetMouseEchoToLine",
		"o": "ToggleMouseEchoFromLayer",
		"p": "SetMouseEchoToParagraph",
		"w": "SetMouseEchoToWord",
		"shift+/": "EchoLayerHelp",
	},
	"ocr": {
		"a": "RecognizeCamera",
		"b": "StartBackgroundRecognition",
		"c": "RecognizeControl",
		"d": "OCRDocument",
		"enter": "OCRAllInOne",
		"f": "OCRSelectedFile",
		"m": "OCRMouseMode",
		"numpadEnter": "OCRAllInOne",
		"q": "CancelRecognition",
		"r": "OCRSelectedFileToWord",
		"s": "RecognizeScreen",
		"w": "RecognizeRealWindow",
		"control+b": "StartBackgroundRecognitionWithSound",
		"control+enter": "OCRAllInOneWithSound",
		"control+numpadEnter": "OCRAllInOneWithSound",
		"shift+/": "OCRLayerHelp",
	},
	"picture": {
		"a": "PictureSmartWithCamera",
		"c": "PictureSmartWithControl",
		"enter": "PictureSmartAllInOne",
		"f": "PictureSmartWithSelectedFile",
		"m": "PictureSmartMouseMode",
		"numpadEnter": "PictureSmartAllInOne",
		"s": "PictureSmartWithScreen",
		"w": "PictureSmartWithWindow",
		"alt+a": "PictureSmartWithCameraAskPrelim",
		"alt+c": "PictureSmartWithControlAskPrelim",
		"alt+enter": "PictureSmartAllInOneAskPrelim",
		"alt+f": "PictureSmartWithSelectedFileAskPrelim",
		"alt+numpadEnter": "PictureSmartAllInOneAskPrelim",
		"alt+s": "PictureSmartWithScreenAskPrelim",
		"alt+w": "PictureSmartWithWindowAskPrelim",
		"control+a": "PictureSmartWithCamera(4)",
		"control+c": "PictureSmartWithControl(4)",
		"control+enter": "PictureSmartAllInOne(4)",
		"control+f": "PictureSmartWithSelectedFile(4)",
		"control+numpadEnter": "PictureSmartAllInOne(4)",
		"control+s": "PictureSmartWithScreen(4)",
		"control+w": "PictureSmartWithWindow(4)",
		"shift+/": "PictureSmartLayerHelp",
		"shift+a": "PictureSmartWithCameraMultiService",
		"shift+c": "PictureSmartWithControlMultiService",
		"shift+enter": "PictureSmartAllInOneMultiService",
		"shift+f": "PictureSmartWithSelectedFileMultiService",
		"shift+numpadEnter": "PictureSmartAllInOneMultiService",
		"shift+s": "PictureSmartWithScreenMultiService",
		"shift+w": "PictureSmartWithWindowMultiService",
		"shift+alt+a": "PictureSmartWithCameraMultiServiceAskPrelim",
		"shift+alt+c": "PictureSmartWithControlMultiServiceAskPrelim",
		"shift+alt+enter": "PictureSmartAllInOneMultiServiceAskPrelim",
		"shift+alt+f": "PictureSmartWithSelectedFileMultiServiceAskPrelim",
		"shift+alt+numpadEnter": "PictureSmartAllInOneMultiServiceAskPrelim",
		"shift+alt+s": "PictureSmartWithScreenMultiServiceAskPrelim",
		"shift+alt+w": "PictureSmartWithWindowMultiServiceAskPrelim",
		"shift+control+a": "PictureSmartWithCameraMultiService(4)",
		"shift+control+c": "PictureSmartWithControlMultiService(4)",
		"shift+control+enter": "PictureSmartAllInOneMultiService(4)",
		"shift+control+f": "PictureSmartWithSelectedFileMultiService(4)",
		"shift+control+numpadEnter": "PictureSmartAllInOneMultiService(4)",
		"shift+control+s": "PictureSmartWithScreenMultiService(4)",
		"shift+control+w": "PictureSmartWithWindowMultiService(4)",
	},
	"skype": {
		"a": "SkypeDesktopAnswerCall",
		"d": "SkypeDesktopDisconnectCall",
		"downArrow": "SkypeDesktopDisconnectCall",
		"numpad2": "SkypeDesktopDisconnectCall",
		"numpad8": "SkypeDesktopAnswerCall",
		"s": "SkypeDesktopFocusSkypeWindow",
		"upArrow": "SkypeDesktopAnswerCall",
		"shift+/": "SkypeDesktopLayerHelp",
	},
	"face": {
		"d": "SayFaceInViewDescription",
		"l": "SayFaceInViewBrightness",
		"o": "ToggleFaceInView",
		"p": "FaceInViewPictureSmart",
		"u": "FaceInViewChangeConfidenceThreshold",
		"shift+/": "FaceInViewLayerHelp",
	},
	"faceCamera": {
		"downArrow": "FaceInViewNextCamera",
		"numpad2": "FaceInViewNextCamera",
		"numpad8": "FaceInViewPreviousCamera",
		"upArrow": "FaceInViewPreviousCamera",
		"shift+/": "FaceInViewCameraLayerHelp",
	},
}


def normalizeLayerKey(nvdaKey):
	"""Return *nvdaKey* in the form NVDA's ``normalizedIdentifiers`` produces.

	``inputCore.normalizeGestureIdentifier`` lower-cases the identifier and
	sorts the ``+``-separated parts, so ``kb:shift+alt+downArrow`` and
	``kb:alt+shift+downarrow`` are one gesture.  JVDA's layer tables are
	written in the readable NVDA spelling and reduced through this function,
	so that a table lookup and NVDA's own identifier always agree.
	"""
	return "+".join(sorted(nvdaKey.lower().split("+")))


def normalizeLayerTable(table):
	"""Return *table* with every key reduced by :func:`normalizeLayerKey`."""
	return {normalizeLayerKey(key): value for key, value in table.items()}


#: LAYER_INVENTORY, LAYER_SUBLAYERS and the exit keys in lookup form.
_NORMALIZED_INVENTORY = {
	layerName: normalizeLayerTable(keys)
	for layerName, keys in LAYER_INVENTORY.items()
}
_NORMALIZED_SUBLAYERS = {
	layerName: normalizeLayerTable(keys)
	for layerName, keys in LAYER_SUBLAYERS.items()
}
_NORMALIZED_UNSUPPORTED_SUBLAYERS = {
	layerName: normalizeLayerTable(keys)
	for layerName, keys in UNSUPPORTED_SUBLAYERS.items()
}
_NORMALIZED_EXIT_KEYS = frozenset(
	normalizeLayerKey(key) for key in LAYER_EXIT_KEYS
)


class _SpaceLayerMixin:
	"""The JAWSKey+Space prefix script, the layer state machine and the raw
	keyboard hook that dispatches the keys pressed inside a layer."""

	# ------------------------------------------------------------------
	# Registration
	# ------------------------------------------------------------------

	def _patchSpaceLayer(self):
		"""Register the layer's raw keyboard handler."""
		import inputCore

		inputCore.decide_handleRawKey.register(self._onSpaceLayerRawKey)

	def _unpatchSpaceLayer(self):
		"""Close any open layer and unregister the raw keyboard handler."""
		import inputCore

		self._closeLayer(silent=True)
		try:
			inputCore.decide_handleRawKey.unregister(self._onSpaceLayerRawKey)
		except Exception:
			pass

	def _spaceLayerAvailable(self):
		"""Return whether the layer may open at all right now."""
		import config

		return bool(
			self._keyboardInterceptionEnabled
			and config.conf["jvda"]["spaceLayerEnabled"],
		)

	# ------------------------------------------------------------------
	# The prefix
	# ------------------------------------------------------------------

	def script_spaceLayer(self, gesture):
		"""Open the JAWSKey+Space layered commands."""
		import inputCore

		if inputCore.manager.isInputHelpActive:
			return
		if not self._spaceLayerAvailable():
			return
		if self._layerStack:
			# JAWSKey+Space inside a layer closes the layer.
			self._closeLayer()
			return
		self._enterLayer("basic")

	# ------------------------------------------------------------------
	# State machine
	# ------------------------------------------------------------------

	def _enterLayer(self, layerName):
		"""Open *layerName*, playing the entry tones for the outermost layer."""
		wasClosed = not self._layerStack
		self._layerStack.append(layerName)
		# The audio output devices are re-read on every layer transition, so
		# that a device plugged in since the last visit is offered.
		self._layerSoundCardDevices = None
		if wasClosed:
			self._queueLayerEffect(self._playLayerEnterTones)
		self._restartLayerTimeout()

	def _closeLayer(self, silent=False):
		"""Close every open layer.

		The swallowed-key set is deliberately not cleared: the key that closed
		the layer has not been released yet, and its key-up must still be
		swallowed or the application receives half a keystroke.
		"""
		wasOpen = bool(self._layerStack)
		self._layerStack = []
		self._layerDeadline = None
		self._layerSoundCardDevices = None
		if wasOpen and not silent:
			self._queueLayerEffect(self._playLayerExitTones)

	def _restartLayerTimeout(self):
		"""Restart the inactivity timer that closes the layer.

		A single pending ``core.callLater`` call is reused rather than
		cancelled and rescheduled, because the raw keyboard hook runs off
		NVDA's main thread, where ``core.callLater`` returns a
		``wx.CallAfter`` result with no ``Stop`` method.  The pending call
		compares the current time against ``_layerDeadline`` and reschedules
		itself when a later key press has pushed the deadline out.
		"""
		import time

		self._layerDeadline = time.time() + LAYER_TIMEOUT_MS / 1000.0
		if self._layerTimeoutPending:
			return
		self._layerTimeoutPending = True
		self._queueLayerEffect(self._scheduleLayerTimeout, LAYER_TIMEOUT_MS)

	def _scheduleLayerTimeout(self, delayMs):
		import core

		try:
			core.callLater(delayMs, self._onLayerTimeout)
		except Exception as error:
			self._layerTimeoutPending = False
			self._log(f"Unable to schedule the layer timeout: {error!r}")

	def _onLayerTimeout(self):
		"""Close the layer when no key has been pressed for the timeout."""
		import time

		self._layerTimeoutPending = False
		if not self._layerStack or self._layerDeadline is None:
			return
		remaining = self._layerDeadline - time.time()
		if remaining > 0:
			self._layerTimeoutPending = True
			self._scheduleLayerTimeout(int(remaining * 1000) + 1)
			return
		self._closeLayer()

	# ------------------------------------------------------------------
	# Tones and messages
	# ------------------------------------------------------------------

	def _playLayerTones(self, tones_):
		import tones

		for hz, length in tones_:
			tones.beep(hz, length)

	def _playLayerEnterTones(self):
		self._playLayerTones(ENTER_TONES)

	def _playLayerExitTones(self):
		self._playLayerTones(EXIT_TONES)

	def _reportLayerUnassigned(self):
		import ui

		ui.message(_(LAYER_UNASSIGNED_MESSAGE))

	def _reportLayerInvalid(self):
		import ui

		ui.message(_(LAYER_INVALID_MESSAGE))

	# ------------------------------------------------------------------
	# Raw keyboard dispatch
	# ------------------------------------------------------------------

	def _queueLayerEffect(self, function, *args):
		"""Run *function* on NVDA's main thread.

		Every visible effect of a layer key goes through here, because the raw
		keyboard hook runs on the low-level hook thread where speech, beeps and
		browseable messages are not safe.
		"""
		import queueHandler

		queueHandler.queueFunction(
			queueHandler.eventQueue, function, *args, _immediate=True,
		)

	def _onSpaceLayerRawKey(self, vkCode, scanCode, extended, pressed):
		"""Decide whether the open layer consumes this raw key event."""
		key = (vkCode, extended)
		if not pressed:
			if key in self._layerSwallowedKeys:
				self._layerSwallowedKeys.discard(key)
				return False
			return True
		if key in self._layerSwallowedKeys:
			# An auto-repeat of a key the layer already consumed.
			return False
		if not self._layerStack:
			return True
		if not self._spaceLayerAvailable():
			return True
		try:
			return self._dispatchLayerKey(vkCode, scanCode, extended, key)
		except Exception as error:
			self._log(f"Layer key dispatch failed: {error!r}")
			self._closeLayer(silent=True)
			return True

	def _dispatchLayerKey(self, vkCode, scanCode, extended, key):
		import inputCore
		import keyboardHandler

		if inputCore.manager.isInputHelpActive:
			return True
		if getattr(keyboardHandler, "ignoreInjected", False):
			return True
		if getattr(self, "_capslockToggleInProgress", False):
			return True
		gesture = keyboardHandler.KeyboardInputGesture(
			keyboardHandler.currentModifiers, vkCode, scanCode, extended,
		)
		if gesture.isModifier:
			# Holding JAWSKey, Shift, Control or Alt is how the layer's own
			# modified keys are typed; a modifier never selects a command.
			return True
		# normalizedIdentifiers[-1] is the layout-independent "kb:" identifier,
		# already lower-cased with its parts sorted.
		keyName = gesture.normalizedIdentifiers[-1].split(":", 1)[1]
		self._layerSwallowedKeys.add(key)
		self._handleLayerKey(self._layerStack[-1], keyName)
		return False

	def _handleLayerKey(self, layerName, keyName):
		"""Run, report or redirect one key pressed inside *layerName*."""
		self._layerHelpTarget = layerName
		if keyName in _NORMALIZED_EXIT_KEYS:
			self._closeLayer()
			return
		sublayer = _NORMALIZED_SUBLAYERS.get(layerName, {}).get(keyName)
		if sublayer is not None:
			self._enterLayer(sublayer)
			return
		methodName = self._layerCommandTable(layerName).get(keyName)
		if methodName is not None:
			if layerName == "basic" or methodName in LAYER_CLOSING_COMMANDS:
				# JAWS's basic layer ends after one command; a sublayer stays
				# open until Escape, a timeout or an unusable key.  A command
				# which opens a window ends the layer wherever it is run.
				#
				# The exit tones are not played: every one of these commands
				# either speaks its result or opens a window, and that answer
				# already tells the user the layer has ended.  A tone on top
				# of it says the same thing twice.
				self._closeLayer(silent=True)
			else:
				self._restartLayerTimeout()
			self._queueLayerEffect(self._runLayerCommand, methodName)
			return
		# No command runs, but a message is spoken, and that message is itself
		# the confirmation that the layer has ended.  No exit tones here either.
		self._closeLayer(silent=True)
		if (
			keyName in _NORMALIZED_INVENTORY.get(layerName, {})
			or keyName in _NORMALIZED_UNSUPPORTED_SUBLAYERS.get(layerName, {})
		):
			self._queueLayerEffect(self._reportLayerInvalid)
		else:
			self._queueLayerEffect(self._reportLayerUnassigned)

	#: The class-body dictionaries in GlobalPlugin which name the JVDA method
	#: implementing each layer key.  Each dictionary is keyed by layer name so
	#: that one key can mean different things in different sublayers.
	_LAYER_COMMAND_SOURCES = (
		"_LAYER_COMMANDS", "_LAYER_VOLUME_COMMANDS", "_LAYER_TABLE_COMMANDS",
	)

	def _layerCommandTable(self, layerName):
		"""Return the JVDA commands implemented for *layerName*."""
		tables = getattr(self, "_normalizedLayerCommands", None)
		if tables is None:
			tables = {}
			for sourceName in self._LAYER_COMMAND_SOURCES:
				for name, commands in getattr(self, sourceName, {}).items():
					tables.setdefault(name, {}).update(
						normalizeLayerTable(commands),
					)
			self._normalizedLayerCommands = tables
		return tables.get(layerName, {})

	def _runLayerCommand(self, methodName):
		import speech

		method = getattr(self, methodName, None)
		if method is None:
			self._log(f"Layer command {methodName} is not implemented")
			self._reportLayerInvalid()
			return
		# Every NVDA keyboard command cancels speech before its script runs:
		# inputCore.InputManager.executeGesture queues speech.cancelSpeech for
		# a gesture whose speechEffectWhenExecuted is SPEECHEFFECT_CANCEL,
		# which every keyboard gesture's is. A layer key never reaches
		# executeGesture, so the cancel has to happen here. Without it a
		# command that reads through sayAll -- the table layer's row and
		# column readers -- is cut off after its first utterance, because the
		# speech state left by the still-held modifier is never cleared.
		speech.cancelSpeech()
		try:
			method()
		except Exception as error:
			# The command runs from the event queue, where an escaping
			# exception is logged without naming what failed.
			self._log(f"Layer command {methodName} failed: {error!r}")

	# ------------------------------------------------------------------
	# Layer help
	# ------------------------------------------------------------------

	def layerHelp(self):
		"""Show every key of the JAWSKey+Space layer that was last open."""
		self._showLayerHelp(getattr(self, "_layerHelpTarget", "basic"))

	def _layerHelpRows(self, layerName):
		"""Return one (key, JAWS command, JVDA command) row per layer key."""
		commands = self._layerCommandTable(layerName)
		# Translators: shown in the JAWSKey+Space layer help for a JAWS command
		# JVDA does not implement.
		notSupported = _("not supported")
		rows = []
		for key, jawsCommand in LAYER_INVENTORY.get(layerName, {}).items():
			lookup = normalizeLayerKey(key)
			if lookup in commands:
				jvdaCommand = _describeLayerCommand(commands[lookup])
			else:
				jvdaCommand = notSupported
			rows.append((key, jawsCommand, jvdaCommand))
		for key, sublayerName in LAYER_SUBLAYERS.get(layerName, {}).items():
			rows.append((
				key,
				LAYER_TITLES.get(sublayerName, sublayerName),
				# Translators: shown in the JAWSKey+Space layer help for a key
				# which opens a further layer rather than running a command.
				_("opens a further layer"),
			))
		for key, jawsName in UNSUPPORTED_SUBLAYERS.get(layerName, {}).items():
			rows.append((key, jawsName, notSupported))
		return sorted(rows, key=lambda row: (row[0].count("+"), row[0].lower()))

	def _showLayerHelp(self, layerName):
		import ui

		lines = [
			f"{key}\t{jawsCommand}\t{jvdaCommand}"
			for key, jawsCommand, jvdaCommand in self._layerHelpRows(layerName)
		]
		ui.browseableMessage(
			"\n".join(lines),
			_(LAYER_TITLES.get(layerName, "JAWSKey+Space layer")),
		)

	def script_layerHelp(self, gesture):
		"""Show the commands of the JAWSKey+Space layer.

		The layer's own help key is dispatched by the raw keyboard hook, so
		this script exists only so that the command can also be given an
		ordinary NVDA gesture by a user who wants one."""
		self._closeLayer()
		self.layerHelp()


def _describeLayerCommand(methodName):
	"""Return a readable name for a JVDA layer command method."""
	import re

	name = re.sub(r"^layer", "", methodName)
	name = re.sub(r"(?<!^)(?=[A-Z])", " ", name)
	return name[:1].upper() + name[1:]
