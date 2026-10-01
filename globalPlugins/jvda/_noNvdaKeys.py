"""JVDA's JAWS-only keyboard: block NVDA's own commands.

A JAWS user who presses JAWSKey+S expects "set screen echo", not NVDA's speech
mode cycle. JVDA already rebinds every JAWS gesture it implements, but NVDA
keeps answering the NVDA-modified keys JVDA has left alone, and those answers
have nothing to do with JAWS. When the ``noNvdaKeys`` setting is on, this
module blocks them and reports that the JAWS command is unavailable.

The setting is off by default, because blocking NVDA's commands is a large
change for anyone who uses both.

Only gestures involving an NVDA modifier are considered. Plain typing, and
Control, Alt, Shift and Windows gestures, are never touched: they belong to
the application.

Like ``_spaceLayer``, this module runs inside NVDA's low-level keyboard hook
thread, so it decides synchronously and queues its speech onto
``queueHandler.eventQueue``. See the ``_spaceLayer`` module docstring for why.
"""

# No NVDA imports at module scope: the tests read this file without an NVDA
# runtime, and NVDA's subsystem initialisation must not be disturbed at import.


#: Spoken when a JAWS command exists for the pressed key but JVDA cannot
#: provide it, and when NVDA's own command for that key has been blocked.
#: Translators: reported when the pressed key has a JAWS command which JVDA
#: cannot provide.
UNAVAILABLE_JAWS_COMMAND_MESSAGE = "unavailable jaws command"

#: Gestures that must keep working in JAWS-only keyboard mode, so that the
#: user can always reach NVDA again.
#:
#: A gesture JVDA itself binds is already allowed, because the handler lets
#: every JVDA-owned gesture through. That covers JAWSKey+grave, which toggles
#: JVDA's keyboard interception and is the universal way out, and JAWSKey+F4,
#: which opens NVDA's exit dialog.
#:
#: These two are NVDA's own. JVDA deliberately does not bind them: NVDA+Q is
#: already JVDA's JAWS "script file name" command, and binding NVDA+1 or
#: NVDA+N would take a key away from a JAWS command on one layout or the
#: other. Allow-listing keeps both the JAWS command and the escape hatch.
ALLOWED_GESTURES = (
	"NVDA+1",  # NVDA's Input Help.
	"NVDA+n",  # NVDA's menu. JVDA binds the menu to JAWSKey+J on desktop
	# layout only, so NVDA+N is the only way to reach it on laptop layout.
)


def _normalize(gestureName):
	"""Return *gestureName* the way NVDA's normalizedIdentifiers spell it."""
	return "+".join(sorted(gestureName.lower().split("+")))


_ALLOWED_LOOKUPS = frozenset(_normalize(name) for name in ALLOWED_GESTURES)


class _NoNvdaKeysMixin:
	"""The raw keyboard handler behind the JAWS-only keyboard setting.

	``GlobalPlugin`` inherits this mixin alongside ``_SpaceLayerMixin``, and
	this mixin uses that one's ``_queueLayerEffect`` to move its speech onto
	NVDA's main thread. Both handlers face the same threading problem, so the
	helper is shared rather than written twice."""

	def _patchNoNvdaKeys(self):
		"""Register the JAWS-only keyboard's raw keyboard handler.

		This must be registered after the JAWSKey+Space layer's handler.
		``inputCore.decide_handleRawKey`` calls its handlers in registration
		order and stops at the first one that returns False, so registering
		second lets the layer consume its own keys first."""
		import inputCore

		inputCore.decide_handleRawKey.register(self._onNoNvdaKeysRawKey)

	def _unpatchNoNvdaKeys(self):
		import inputCore

		self._noNvdaKeysSwallowed.clear()
		try:
			inputCore.decide_handleRawKey.unregister(self._onNoNvdaKeysRawKey)
		except Exception:
			pass

	def _noNvdaKeysActive(self):
		import config

		return bool(
			self._keyboardInterceptionEnabled
			and config.conf["jvda"]["noNvdaKeys"],
		)

	def _onNoNvdaKeysRawKey(self, vkCode, scanCode, extended, pressed):
		"""Decide whether NVDA's own command for this key should be blocked."""
		key = (vkCode, extended)
		if not pressed:
			# Every blocked key-down must have its key-up blocked too, or the
			# application receives half a keystroke.
			if key in self._noNvdaKeysSwallowed:
				self._noNvdaKeysSwallowed.discard(key)
				return False
			return True
		if key in self._noNvdaKeysSwallowed:
			# An auto-repeat of a key already blocked: block it silently.
			return False
		if not self._noNvdaKeysActive():
			return True
		try:
			return self._decideNoNvdaKey(vkCode, scanCode, extended, key)
		except Exception as error:
			self._log(f"JAWS-only keyboard decision failed: {error!r}")
			return True

	def _decideNoNvdaKey(self, vkCode, scanCode, extended, key):
		import inputCore
		import keyboardHandler

		if inputCore.manager.isInputHelpActive:
			# Input Help must keep describing every key, including NVDA's own.
			return True
		if getattr(keyboardHandler, "ignoreInjected", False):
			return True
		if getattr(self, "_capslockToggleInProgress", False):
			return True
		if not self._involvesNvdaModifier(vkCode, extended):
			return True
		gesture = keyboardHandler.KeyboardInputGesture(
			keyboardHandler.currentModifiers, vkCode, scanCode, extended,
		)
		if gesture.isModifier:
			# The NVDA modifier itself is never blocked. Blocking it would
			# stop NVDA from recording the key as held, and every JVDA command
			# and every escape hatch would become unreachable.
			return True
		identifier = gesture.normalizedIdentifiers[-1].split(":", 1)[1]
		if identifier in _ALLOWED_LOOKUPS:
			return True
		if self.getScript(gesture) is not None:
			# JVDA owns this gesture, so NVDA is not the one answering it.
			return True
		self._noNvdaKeysSwallowed.add(key)
		self._queueLayerEffect(self._reportUnavailableJawsCommand)
		return False

	def _involvesNvdaModifier(self, vkCode, extended):
		"""Return whether this key-down is part of an NVDA-modified gesture.

		``currentModifiers`` has not yet been updated for this key-down, so a
		key-down which is itself an NVDA modifier is tested separately."""
		import keyboardHandler

		if keyboardHandler.isNVDAModifierKey(vkCode, extended):
			return True
		held = set(keyboardHandler.currentModifiers)
		return bool(held & set(keyboardHandler.getNVDAModifierKeys()))

	def _reportUnavailableJawsCommand(self):
		import ui

		ui.message(_(UNAVAILABLE_JAWS_COMMAND_MESSAGE))
