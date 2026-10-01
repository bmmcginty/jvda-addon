# JVDA monkey-patches — each wrapped by a config-gated method on a
# mixin that the main GlobalPlugin inherits.

import browseMode
import config
import controlTypes
import ctypes
import textInfos
import time
import unicodedata

from ._textUtils import isMediaPosition
from ._timing import timedClass

# Most heavy imports (virtualBuffers, cursorManager, speech.speech, …)
# are deferred into the patch methods so that NVDA's subsystem init
# order is not disturbed during add-on import.


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _jawsInputHelpPresentation(gestureName, description):
	"""Return JAWS-oriented key and command text for JVDA Input Help."""
	gestureName = gestureName.replace("NVDA", "JAWSKey")
	if description and not description.casefold().startswith("jaws "):
		description = f"JAWS command: {description}"
	return gestureName, description


def _stripBlankLines(textInfo):
	"""Return a copy of *textInfo* with leading and trailing blank /
	whitespace-only lines removed.

	A line whose text is a single space (the virtual buffer's
	placeholder for an embedded object like a form field) is never
	considered blank.

	Internal blank lines are preserved since the TextInfo API provides
	no simple way to excise a mid-range line.  In practice this is
	invisible: ``n`` reads one line (the first non-blank one) and the
	cursor lands there.

	Returns None if every line is blank or whitespace.
	"""
	lines = (textInfo.text or "").split("\n")
	# Indices of non-blank lines: have visible text OR are a single
	# space (the VBuf placeholder for an embedded object).
	kept = [
		idx for idx, line in enumerate(lines)
		if line.strip() or line == " "
	]
	if not kept:
		return None

	first = kept[0]
	last = kept[-1]

	# Fast path: no blank lines at all.
	if first == 0 and last == len(lines) - 1:
		return textInfo.copy()

	endMark = textInfo.copy()
	result = textInfo.copy()

	# Strip leading blank lines: repeatedly collapse, advance one
	# line, then re-expand the end to the original block boundary.
	for _ in range(first):
		result.collapse()
		if result.move(textInfos.UNIT_LINE, 1) <= 0:
			break
		result.setEndPoint(endMark, "endToEnd")

	# Strip trailing blank lines: pull the end point back one line
	# at a time (endPoint="end" only moves the end, not the start).
	trailing = len(lines) - 1 - last
	for _ in range(trailing):
		result.move(textInfos.UNIT_LINE, -1, endPoint="end")

	return result


def _patchBytecodeSeparator(original):
	"""Return a copy of *original* with the ``"; "`` constant in
	its bytecode replaced by ``" "``.  If ``"; "`` is not found the
	original is returned unchanged.

	This surgically changes only the join separator — column
	values that themselves contain ``"; "`` are left alone."""
	import types

	code = original.__code__
	if "; " not in code.co_consts:
		return original
	newConsts = tuple(
		" " if c == "; " else c
		for c in code.co_consts
	)
	newCode = code.replace(co_consts=newConsts)
	return types.FunctionType(
		newCode,
		original.__globals__,
		original.__name__,
		original.__defaults__,
		original.__closure__,
	)


# ------------------------------------------------------------------
# Mixin class
# ------------------------------------------------------------------

@timedClass
class _PatchesMixin:
	"""Mixin that provides all ``_patch*`` / ``_unpatch*`` methods.

	Assumes the concrete class also provides ``self._log(message)``.
	"""

	# ------------------------------------------------------------------
	# Repeated-symbol patch
	# ------------------------------------------------------------------

	def _patchRepeatedSymbols(self):
		"""Wrap _regexpRepl so the 'repeated' branch respects the
		user-configured symbol limit.  All other branches delegate to
		the original function."""
		import characterProcessing

		original = characterProcessing.SpeechSymbolProcessor._regexpRepl
		self._origRegexpRepl = original

		def wrapper(self, m):
			if m.lastgroup != "repeated":
				return original(self, m)
			text = m.group()
			symbol = self.computedSymbols[text[0]]
			if self._level < symbol.level:
				return original(self, m)
			if symbol.preserve in (
				characterProcessing.SYMPRES_ALWAYS,
				characterProcessing.SYMPRES_NOREP,
			):
				return text
			if not symbol.replacement:
				return " "
			_limit = config.conf["jvda"]["repeatedSymbolLimit"]
			return " " + " ".join(
				[symbol.replacement] * min(len(text), _limit)
			) + " "

		self._repeatedSymbolsWrapper = wrapper
		characterProcessing.SpeechSymbolProcessor._regexpRepl = wrapper
		self._log("Repeated-symbol patch applied")

	def _unpatchRepeatedSymbols(self):
		import characterProcessing

		original = getattr(self, "_origRegexpRepl", None)
		wrapper = getattr(self, "_repeatedSymbolsWrapper", None)
		if (
			original is not None
			and characterProcessing.SpeechSymbolProcessor._regexpRepl is wrapper
		):
			characterProcessing.SpeechSymbolProcessor._regexpRepl = original
		self._origRegexpRepl = None
		self._repeatedSymbolsWrapper = None

	# ------------------------------------------------------------------
	# Display-model collapsed range patch
	# ------------------------------------------------------------------

	def _patchDisplayModelCollapsedRanges(self):
		"""Make an empty display-model range return no fields.

		``DisplayModelTextInfo._getFieldsInRange`` searches independently
		for the text chunks containing the start and end offsets. At the
		start of a chunk, a collapsed range finds its start but not its end
		because the end comparison is strict. Depending on the formatting
		field layout, NVDA then either returns the remainder of the screen or
		indexes a too-short slice and raises ``IndexError``.

		The JAWS cursor reads a collapsed range from the beginning of the
		line to its current position to preserve the horizontal column. A
		bogus remainder-of-screen result therefore moves review to the end of
		the next line, while an exception makes movement intermittent. Empty
		ranges have no fields by definition, so handle them before NVDA's
		private range slicer. This also protects native screen-review users
		inside terminal applications while JVDA is running.
		"""
		import displayModel

		if getattr(self, "_displayModelGetFieldsInRangeWrapper", None) is not None:
			return
		textInfoClass = displayModel.DisplayModelTextInfo
		original = textInfoClass._getFieldsInRange

		def wrapper(textInfo, start, end):
			if start >= end:
				return []
			return original(textInfo, start, end)

		self._origDisplayModelGetFieldsInRange = original
		self._displayModelGetFieldsInRangeWrapper = wrapper
		textInfoClass._getFieldsInRange = wrapper
		self._log("Display-model collapsed-range patch applied")

	def _unpatchDisplayModelCollapsedRanges(self):
		import displayModel

		original = getattr(self, "_origDisplayModelGetFieldsInRange", None)
		wrapper = getattr(self, "_displayModelGetFieldsInRangeWrapper", None)
		if (
			original is not None
			and displayModel.DisplayModelTextInfo._getFieldsInRange is wrapper
		):
			displayModel.DisplayModelTextInfo._getFieldsInRange = original
		self._origDisplayModelGetFieldsInRange = None
		self._displayModelGetFieldsInRangeWrapper = None

	# ------------------------------------------------------------------
	# Symbol pronunciation dialog labels
	# ------------------------------------------------------------------

	def _patchSpeechSymbolsDialog(self):
		"""Give symbol-list entries a stable spoken name.

		The list previously exposed a raw character as its name. NVDA then
		applied that character's user-defined replacement while announcing
		it, making an edited symbol impossible to identify on returning to
		the dialog.
		"""
		from gui import settingsDialogs

		dialogClass = settingsDialogs.SpeechSymbolsDialog
		original = dialogClass.getItemTextForList
		self._origSpeechSymbolsGetItemText = original

		def getOriginalSymbolName(dialog, symbol):
			# User symbols are deliberately excluded: their replacement is the
			# value being edited, not the identity of the symbol.
			for source in dialog.symbolProcessor.builtinSources:
				sourceSymbol = source.symbols.get(symbol.identifier)
				if sourceSymbol:
					name = sourceSymbol.displayName or sourceSymbol.replacement
					if name:
						return name
			return " ".join(
				unicodedata.name(character, character)
				for character in symbol.identifier
			)

		def replacement(dialog, item, column):
			if column != 0:
				return original(dialog, item, column)
			symbol = dialog.filteredSymbols[item]
			name = getOriginalSymbolName(dialog, symbol)
			# Keep the raw character visible while ensuring its name is spoken
			# before any symbol substitution can affect the parenthesized text.
			return f"{name} ({symbol.identifier})"

		self._speechSymbolsGetItemTextWrapper = replacement
		dialogClass.getItemTextForList = replacement
		self._log("Symbol-pronunciation dialog label patch applied")

	def _unpatchSpeechSymbolsDialog(self):
		original = getattr(self, "_origSpeechSymbolsGetItemText", None)
		if original is None:
			return
		from gui import settingsDialogs

		wrapper = getattr(self, "_speechSymbolsGetItemTextWrapper", None)
		if settingsDialogs.SpeechSymbolsDialog.getItemTextForList is wrapper:
			settingsDialogs.SpeechSymbolsDialog.getItemTextForList = original
		self._origSpeechSymbolsGetItemText = None
		self._speechSymbolsGetItemTextWrapper = None

	# ------------------------------------------------------------------
	# NVDA modifier and CapsLock double-tap handling
	# ------------------------------------------------------------------

	def _patchCapsLockFix(self):
		"""Register JVDA's raw NVDA-modifier key handler.

		The handler runs synchronously inside the low-level keyboard hook,
		before NVDA can turn a rapid second press of a configured NVDA modifier
		into the key's normal action.  When suppression is enabled, clearing
		NVDA's release timestamp on each modifier key-down prevents that native
		pass-through for CapsLock, Numpad Insert, and extended Insert.

		The existing, separately configurable CapsLock fix still implements
		JAWS-style CapsLock toggling itself on the second key-up.  Its injected
		key events bypass this handler."""
		import inputCore
		import keyboardHandler

		self._capslockState = self._CS_IDLE
		self._capslockFirstUpTime = 0.0
		self._capslockToggleInProgress = False
		inputCore.decide_handleRawKey.register(self._onCapsLockRawKey)

	def _unpatchCapsLockFix(self):
		import inputCore

		try:
			inputCore.decide_handleRawKey.unregister(self._onCapsLockRawKey)
		except Exception:
			pass

	def _onCapsLockRawKey(self, vkCode, scanCode, extended, pressed):
		"""Extension-point handler for every raw keyboard event."""
		import keyboardHandler
		import ui
		import winUser

		from keyLabels import localizedKeyLabels

		# While we are injecting our own CapsLock toggle, let the
		# injected events pass through without interference.
		if self._capslockToggleInProgress:
			return True

		# NVDA normally passes a configured NVDA modifier to the application
		# when it is pressed twice quickly.  Clear its state before internal
		# keyboard processing sees the second key-down.  Ask NVDA whether this
		# exact key is a modifier so NumLock-on Numpad 0 remains a normal digit.
		if (
			pressed
			and self._keyboardInterceptionEnabled
			and config.conf["jvda"]["suppressModifierDoubleTap"]
			and keyboardHandler.isNVDAModifierKey(vkCode, extended)
		):
			keyboardHandler.bypassNVDAModifier = False
			keyboardHandler.lastNVDAModifierReleaseTime = None

		# Not CapsLock: cancel any in-progress double-tap on key-down.
		if vkCode != winUser.VK_CAPITAL:
			if pressed:
				self._capslockState = self._CS_IDLE
			return True

		# Feature or add-on keyboard commands are off — don't interfere.
		if (
			not self._keyboardInterceptionEnabled
			or not config.conf["jvda"]["capsLockFix"]
		):
			return True

		if pressed:
			# ---- CapsLock key-down ----
			if self._capslockState == self._CS_IDLE:
				self._capslockState = self._CS_FIRST_DOWN
			elif self._capslockState == self._CS_FIRST_UP:
				timeout = config.conf["keyboard"]["multiPressTimeout"] / 1000.0
				if time.time() - self._capslockFirstUpTime <= timeout:
					self._capslockState = self._CS_SECOND_DOWN
				else:
					self._capslockState = self._CS_FIRST_DOWN
			if self._capslockState == self._CS_SECOND_DOWN:
				keyboardHandler.bypassNVDAModifier = False
				keyboardHandler.lastNVDAModifierReleaseTime = None
			else:
				keyboardHandler.lastNVDAModifierReleaseTime = None
		else:
			# ---- CapsLock key-up ----
			if self._capslockState == self._CS_FIRST_DOWN:
				self._capslockState = self._CS_FIRST_UP
				self._capslockFirstUpTime = time.time()
			elif self._capslockState == self._CS_SECOND_DOWN:
				self._capslockState = self._CS_IDLE
				self._log("CapsLock double-tap: toggling")
				self._capslockToggleInProgress = True
				try:
					with keyboardHandler.ignoreInjection():
						ctypes.windll.user32.keybd_event(
							winUser.VK_CAPITAL, 0, 0, 0,
						)
						ctypes.windll.user32.keybd_event(
							winUser.VK_CAPITAL, 0, 2, 0,
						)
				finally:
					self._capslockToggleInProgress = False
				key = localizedKeyLabels.get("capslock", "caps lock")
				state = (
					_("on")
					if winUser.getKeyState(winUser.VK_CAPITAL) & 1
					else _("off")
				)
				ui.message(f"{key} {state}")
			else:
				self._capslockState = self._CS_IDLE

		return True

	# ------------------------------------------------------------------
	# JAWS-cursor review-follow isolation
	# ------------------------------------------------------------------

	def _patchJawsCursorReviewFollow(self):
		"""Prevent NVDA review following while JAWS cursor is active.

		NVDA normally follows focus in ``api.setFocusObject`` and follows
		the caret in ``review.handleCaretMove``.  Previously JVDA changed
		the persistent review-cursor settings for the entire duration of
		JAWS mode.  Keep those preferences intact and suppress only the
		corresponding updates while this add-on owns JAWS cursor mode.
		"""
		import api
		import review

		self._origSetFocusObjectForJawsCursor = api.setFocusObject
		self._origHandleCaretMoveForJawsCursor = review.handleCaretMove

		def setFocusObject(obj):
			if self._mode not in (self.MODE_JAWS, self.MODE_INVISIBLE):
				return self._origSetFocusObjectForJawsCursor(obj)
			reviewCursorConfig = config.conf["reviewCursor"]
			followFocus = reviewCursorConfig["followFocus"]
			reviewCursorConfig["followFocus"] = False
			try:
				return self._origSetFocusObjectForJawsCursor(obj)
			finally:
				reviewCursorConfig["followFocus"] = followFocus

		def handleCaretMove(pos):
			if self._mode in (self.MODE_JAWS, self.MODE_INVISIBLE):
				return
			return self._origHandleCaretMoveForJawsCursor(pos)

		self._jawsCursorSetFocusObjectWrapper = setFocusObject
		self._jawsCursorHandleCaretMoveWrapper = handleCaretMove
		api.setFocusObject = setFocusObject
		review.handleCaretMove = handleCaretMove
		self._log("JAWS cursor review-follow isolation patch applied")

	def _unpatchJawsCursorReviewFollow(self):
		import api
		import review

		original = getattr(self, "_origSetFocusObjectForJawsCursor", None)
		wrapper = getattr(self, "_jawsCursorSetFocusObjectWrapper", None)
		if original is not None and api.setFocusObject is wrapper:
			api.setFocusObject = original
		self._origSetFocusObjectForJawsCursor = None
		self._jawsCursorSetFocusObjectWrapper = None

		original = getattr(self, "_origHandleCaretMoveForJawsCursor", None)
		wrapper = getattr(self, "_jawsCursorHandleCaretMoveWrapper", None)
		if original is not None and review.handleCaretMove is wrapper:
			review.handleCaretMove = original
		self._origHandleCaretMoveForJawsCursor = None
		self._jawsCursorHandleCaretMoveWrapper = None

	# ------------------------------------------------------------------
	# Column separator fix
	# ------------------------------------------------------------------

	def _patchColumnSeparator(self):
		"""Replace NVDA's ``"; "`` column/property separator with a
		space in SysListView32 items and browse-mode quick-nav labels,
		matching JAWS behaviour.

		Uses bytecode constant patching so only the join separator
		is affected -- column values are never touched.

		For SysListView32 we patch the auto-property descriptor's
		``fget`` directly because NVDA's metaclass wraps
		``_get_name`` in a ``CachingGetter`` at class-creation time.

		Gated on ``config.conf["jvda"]["columnSeparatorFix"]``."""
		if not config.conf["jvda"]["columnSeparatorFix"]:
			return

		import browseMode as _browseMode
		import NVDAObjects.IAccessible.sysListView32 as ia_slv32
		import NVDAObjects.UIA.sysListView32 as uia_slv32

		self._origBROWSEGetLabel = (
			_browseMode.TextInfoQuickNavItem._getLabelForProperties
		)
		self._origIANameFget = ia_slv32.ListItem.name.fget
		self._origUIANameFget = uia_slv32.SysListViewItem.name.fget

		self._patchedBROWSEGetLabel = _patchBytecodeSeparator(
			self._origBROWSEGetLabel,
		)
		self._patchedIANameFget = _patchBytecodeSeparator(
			self._origIANameFget,
		)
		self._patchedUIANameFget = _patchBytecodeSeparator(
			self._origUIANameFget,
		)
		_browseMode.TextInfoQuickNavItem._getLabelForProperties = (
			self._patchedBROWSEGetLabel
		)
		ia_slv32.ListItem.name.fget = self._patchedIANameFget
		uia_slv32.SysListViewItem.name.fget = self._patchedUIANameFget
		self._log("Column separator patch applied")

	def _unpatchColumnSeparator(self):
		import browseMode as _browseMode
		import NVDAObjects.IAccessible.sysListView32 as ia_slv32
		import NVDAObjects.UIA.sysListView32 as uia_slv32

		orig = getattr(self, "_origBROWSEGetLabel", None)
		patched = getattr(self, "_patchedBROWSEGetLabel", None)
		if (
			orig is not None
			and _browseMode.TextInfoQuickNavItem._getLabelForProperties is patched
		):
			_browseMode.TextInfoQuickNavItem._getLabelForProperties = orig
		self._origBROWSEGetLabel = None
		self._patchedBROWSEGetLabel = None
		orig = getattr(self, "_origIANameFget", None)
		patched = getattr(self, "_patchedIANameFget", None)
		if orig is not None and ia_slv32.ListItem.name.fget is patched:
			ia_slv32.ListItem.name.fget = orig
		self._origIANameFget = None
		self._patchedIANameFget = None
		orig = getattr(self, "_origUIANameFget", None)
		patched = getattr(self, "_patchedUIANameFget", None)
		if orig is not None and uia_slv32.SysListViewItem.name.fget is patched:
			uia_slv32.SysListViewItem.name.fget = orig
		self._origUIANameFget = None
		self._patchedUIANameFget = None

	# ------------------------------------------------------------------
	# Not-link-block blank-line skip patch
	# ------------------------------------------------------------------

	def _patchNotLinkBlockSkipBlankLines(self):
		"""Wrap ``_iterNotLinkBlock`` so leading / trailing blank /
		whitespace lines are trimmed from each text block before it
		is yielded.

		Gated on ``config.conf["jvda"]["skipBlankLinesNotLinkBlock"]``."""
		if not config.conf["jvda"]["skipBlankLinesNotLinkBlock"]:
			return
		import browseMode as _browseMode

		original = _browseMode.BrowseModeDocumentTreeInterceptor._iterNotLinkBlock
		self._origIterNotLinkBlock = original

		def wrapper(treeInt, direction="next", pos=None):
			for item in original(treeInt, direction, pos):
				stripped = _stripBlankLines(item.textInfo)
				if stripped is not None:
					item.textInfo = stripped
					yield item

		self._iterNotLinkBlockWrapper = wrapper
		_browseMode.BrowseModeDocumentTreeInterceptor._iterNotLinkBlock = wrapper
		self._log("Not-link-block blank-line strip patch applied")

	def _unpatchNotLinkBlockSkipBlankLines(self):
		import browseMode as _browseMode

		original = getattr(self, "_origIterNotLinkBlock", None)
		wrapper = getattr(self, "_iterNotLinkBlockWrapper", None)
		if (
			original is not None
			and _browseMode.BrowseModeDocumentTreeInterceptor._iterNotLinkBlock
			is wrapper
		):
			_browseMode.BrowseModeDocumentTreeInterceptor._iterNotLinkBlock = original
		self._origIterNotLinkBlock = None
		self._iterNotLinkBlockWrapper = None

	# ------------------------------------------------------------------
	# Browse-mode line-movement blank-line skip patch
	# ------------------------------------------------------------------

	def _patchLineMoveSkipBlankLines(self):
		"""Wrap ``VirtualBufferTextInfo.move`` so that moving by
		``UNIT_LINE`` keeps advancing until it lands on a non-blank
		(non-whitespace-only) line.

		Only intercepts cursor-movement calls (``endPoint`` is None).
		Reading / expanding calls (``endPoint="end"``) are left alone
		so that reporting a blank line is still possible.

		Gated on ``config.conf["jvda"]["skipBlankLinesBrowseMode"]``."""
		if not config.conf["jvda"]["skipBlankLinesBrowseMode"]:
			return
		import virtualBuffers

		original = virtualBuffers.VirtualBufferTextInfo.move
		self._origLineMove = original

		def wrapper(self_info, unit, direction, endPoint=None):
			if (
				unit != textInfos.UNIT_LINE
				or direction == 0
				or endPoint is not None
			):
				return original(self_info, unit, direction, endPoint)

			totalMoved = 0
			safety = 0
			while safety < 1000:
				result = original(self_info, unit, direction, endPoint)
				if result == 0:
					return totalMoved
				totalMoved += result

				info = self_info.copy()
				info.expand(textInfos.UNIT_LINE)
				lineText = info.text or ""
				if lineText.strip():
					return totalMoved
				# The text is whitespace-only.  Check whether the
				# line contains an embedded object (form field,
				# graphic, etc.) whose text is just a placeholder
				# space / empty string.
				try:
					focusObj = info.focusableNVDAObjectAtStart
					rootObj = info.obj.rootNVDAObject
					if focusObj is not rootObj:
						return totalMoved
				except Exception:
					pass

				safety += 1

			return totalMoved

		self._lineMoveWrapper = wrapper
		virtualBuffers.VirtualBufferTextInfo.move = wrapper
		self._log("Line-move blank-line skip patch applied")

	def _unpatchLineMoveSkipBlankLines(self):
		import virtualBuffers

		original = getattr(self, "_origLineMove", None)
		wrapper = getattr(self, "_lineMoveWrapper", None)
		if original is not None and virtualBuffers.VirtualBufferTextInfo.move is wrapper:
			virtualBuffers.VirtualBufferTextInfo.move = original
		self._origLineMove = None
		self._lineMoveWrapper = None

	# ------------------------------------------------------------------
	# Suppress table row/column announcements during normal arrow movement
	# ------------------------------------------------------------------

	def _patchSuppressTableCoords(self):
		"""Wrap ``CursorManager._caretMovementScriptHelper`` so that
		``reportTables`` is temporarily set to ``False`` while the
		original method runs.

		This suppresses table row / column announcements during normal
		arrow-key movement without affecting explicit table navigation
		(ctrl+alt+arrows), which already forces ``reportTables=True``
		via its own ``formatConfig``.

		Gated on
		``config.conf["jvda"]["suppressTableCoordsArrowing"]``."""
		if not config.conf["jvda"]["suppressTableCoordsArrowing"]:
			return
		import cursorManager

		original = cursorManager.CursorManager._caretMovementScriptHelper
		self._origCaretMovementHelper = original

		def wrapper(self_cm, gesture, unit, *args, **kwargs):
			oldReportTables = config.conf["documentFormatting"]["reportTables"]
			config.conf["documentFormatting"]["reportTables"] = False
			try:
				return original(self_cm, gesture, unit, *args, **kwargs)
			finally:
				config.conf["documentFormatting"]["reportTables"] = (
					oldReportTables
				)

		self._caretMovementHelperWrapper = wrapper
		cursorManager.CursorManager._caretMovementScriptHelper = wrapper
		self._log("Suppress-table-coords patch applied")

	def _unpatchSuppressTableCoords(self):
		import cursorManager

		original = getattr(self, "_origCaretMovementHelper", None)
		wrapper = getattr(self, "_caretMovementHelperWrapper", None)
		if (
			original is not None
			and cursorManager.CursorManager._caretMovementScriptHelper is wrapper
		):
			cursorManager.CursorManager._caretMovementScriptHelper = original
		self._origCaretMovementHelper = None
		self._caretMovementHelperWrapper = None

	# ------------------------------------------------------------------
	# Suppress "has auto complete" announcements
	# ------------------------------------------------------------------

	def _patchSuppressAutocomplete(self):
		"""Wrap ``speech.speech.getPropertiesSpeech`` to remove
		``controlTypes.State.AUTOCOMPLETE`` from the set of states
		before they are converted to speech, silencing the
		"has auto complete" announcement.

		Gated on ``config.conf["jvda"]["suppressAutocomplete"]``."""
		if not config.conf["jvda"]["suppressAutocomplete"]:
			return
		import speech.speech as sp

		original = sp.getPropertiesSpeech
		self._origGetPropertiesSpeech = original

		def wrapper(reason=controlTypes.OutputReason.QUERY, **propertyValues):
			states = propertyValues.get("states")
			if states is not None and controlTypes.State.AUTOCOMPLETE in states:
				states = states - {controlTypes.State.AUTOCOMPLETE}
				propertyValues = dict(propertyValues, states=states)
			return original(reason, **propertyValues)

		self._autocompleteSpeechWrapper = wrapper
		sp.getPropertiesSpeech = wrapper
		self._log("Suppress-autocomplete patch applied")

	def _unpatchSuppressAutocomplete(self):
		import speech.speech as sp

		original = getattr(self, "_origGetPropertiesSpeech", None)
		wrapper = getattr(self, "_autocompleteSpeechWrapper", None)
		if original is not None and sp.getPropertiesSpeech is wrapper:
			sp.getPropertiesSpeech = original
		self._origGetPropertiesSpeech = None
		self._autocompleteSpeechWrapper = None

	# ------------------------------------------------------------------
	# Suppress status and media-progress positions
	# ------------------------------------------------------------------

	def _patchSuppressStatusAndProgressPositions(self):
		"""Suppress values reported by status, progress, and seek controls.

		Browser media players commonly expose their elapsed/total time as a
		status bar, progress bar, or slider value. NVDA's progress-bar output
		setting controls unsolicited updates, not these focus announcements.
		"""
		if not config.conf["jvda"]["suppressStatusAndProgressPositions"]:
			return
		import speech.speech as sp

		original = sp.getPropertiesSpeech
		self._origGetPropertiesSpeechForProgress = original

		def wrapper(reason=controlTypes.OutputReason.QUERY, **propertyValues):
			role = propertyValues.get("role", propertyValues.get("_role"))
			try:
				role = controlTypes.Role(role)
			except (TypeError, ValueError):
				return original(reason, **propertyValues)
			name = propertyValues.get("name")
			value = propertyValues.get("value")
			description = propertyValues.get("description")
			if (
				role in (
					controlTypes.Role.STATUSBAR,
					controlTypes.Role.PROGRESSBAR,
					controlTypes.Role.SLIDER,
				)
				and isMediaPosition(name, value, description)
			):
				if role == controlTypes.Role.STATUSBAR:
					propertyValues = dict(
						propertyValues, name=None, value=None,
					)
				else:
					propertyValues = dict(propertyValues, value=None)
			return original(reason, **propertyValues)

		self._statusProgressSpeechWrapper = wrapper
		sp.getPropertiesSpeech = wrapper
		self._log("Suppress-status-and-progress-positions patch applied")

	def _unpatchSuppressStatusAndProgressPositions(self):
		import speech.speech as sp

		original = getattr(self, "_origGetPropertiesSpeechForProgress", None)
		wrapper = getattr(self, "_statusProgressSpeechWrapper", None)
		if original is not None and sp.getPropertiesSpeech is wrapper:
			sp.getPropertiesSpeech = original
		self._origGetPropertiesSpeechForProgress = None
		self._statusProgressSpeechWrapper = None

	# ------------------------------------------------------------------
	# Improved input help
	# ------------------------------------------------------------------

	def _patchImprovedInputHelp(self):
		"""Wrap ``_handleInputHelp`` so that when a key has a binding
		a brief pause is inserted between the gesture name and the
		description, making it easier to distinguish keys that do
		something from keys that do nothing."""
		import inputCore
		import scriptHandler
		from speech.commands import BreakCommand

		original = inputCore.InputManager._handleInputHelp
		self._origHandleInputHelp = original

		def wrapper(self_im, gesture, onlyLog=False):
			script = gesture.script
			# If the key does nothing, or we're only logging,
			# delegate entirely — the original already speaks just
			# the gesture name.
			if script is None or onlyLog:
				return original(self_im, gesture, onlyLog=onlyLog)

			# Must keep the toggleInputHelp escape hatch.
			scriptName = scriptHandler.getScriptName(script)
			if scriptName == "toggleInputHelp":
				return original(self_im, gesture, onlyLog=onlyLog)

			# Key has a binding: a brief silence, then the gesture
			# name, then the description.  The silence lets the user
			# quickly scan for shortcuts by listening for it.
			import braille
			import controlTypes
			import characterProcessing
			from speech import speak

			gestureName = gesture.displayName
			desc = script.__doc__
			if getattr(script, "__module__", "").startswith(
				"globalPlugins.jvda"
			):
				gestureName, desc = _jawsInputHelpPresentation(
					gestureName, desc,
				)
			textList = [gestureName]
			if desc:
				textList.append(desc)
			logMsg = "Input help: gesture %s" % gesture.identifiers[0]
			logMsg += ", bound to script %s" % scriptName
			import logHandler
			logHandler.log.info(logMsg)

			braille.handler.message("\t\t".join(textList))
			speechSeq = []
			if desc:
				speechSeq.append(BreakCommand(time=150))
			speechSeq.append(textList[0])
			if desc:
				speechSeq.append(textList[1])
			speak(
				speechSeq,
				symbolLevel=characterProcessing.SymbolLevel.ALL,
			)

		self._inputHelpWrapper = wrapper
		inputCore.InputManager._handleInputHelp = wrapper
		self._log("Improved-input-help patch applied")

	def _unpatchImprovedInputHelp(self):
		import inputCore

		original = getattr(self, "_origHandleInputHelp", None)
		wrapper = getattr(self, "_inputHelpWrapper", None)
		if original is not None and inputCore.InputManager._handleInputHelp is wrapper:
			inputCore.InputManager._handleInputHelp = original
		self._origHandleInputHelp = None
		self._inputHelpWrapper = None
