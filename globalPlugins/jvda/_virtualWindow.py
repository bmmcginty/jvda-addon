# JVDA virtual window viewer — captures and displays all text
# from the foreground window using NVDA's display model.

import ctypes
import controlTypes
from xml.etree import ElementTree

from ._timing import timedClass


@timedClass
class VirtualWindow:
	"""Extracts and displays text from the current foreground window."""

	@staticmethod
	def _extractDisplayModelText(rawXml):
		"""Parse display-model XML and return the text content
		with newlines inserted where the baseline (Y position)
		changes between consecutive ``<text>`` elements."""
		if not rawXml:
			return ""
		try:
			root = ElementTree.fromstring(
				f"<root>{rawXml}</root>",
			)
		except ElementTree.ParseError:
			return ""
		lines = []
		prevBaseline = None
		for elem in root.findall("text"):
			baseline = elem.get("baseline", "")
			if (
				prevBaseline is not None
				and baseline != prevBaseline
			):
				lines.append("\n")
			prevBaseline = baseline
			if elem.text:
				lines.append(elem.text)
		return VirtualWindow._trimLineEnds("".join(lines))

	@staticmethod
	def _trimLineEnds(text):
		"""Remove display-cell padding and bottom blank lines.

		The display model and some accessible text providers retain unused
		terminal cells as spaces. Virtualization presents logical lines, so
		that padding and empty terminal rows should not become part of the
		viewer text.
		"""
		return "\n".join(
			line.rstrip(" \t") for line in text.split("\n")
		).rstrip("\n")

	@staticmethod
	def _collectNativeText(obj):
		"""Return accessible text exposed directly by *obj*, if any."""
		import textInfos

		try:
			return obj.makeTextInfo(textInfos.POSITION_ALL).text or ""
		except Exception:
			return ""

	@classmethod
	def collectText(cls, obj, rawXml=False, preferNative=False):
		"""Try every available method to extract text from *obj*.

		When *preferNative* is true, prefer the control's accessible TextInfo
		over screen text. This preserves logical text (including terminal
		scrollback) where a control, such as current PuTTY, exposes IA2 text.
		When *preferNative* is false (whole-window capture), the focused
		control's native text is still checked first — if it provides richer
		text (e.g. IA2 terminal scrollback), it wins over the display model.
		If *rawXml* is true, return raw display-model XML when available."""
		text = ""
		nativeTextTried = False

		# A current control can expose richer logical text than its rendered
		# area. Do not use this for a whole-window capture, which must include
		# static and otherwise inaccessible screen text.
		if preferNative and not rawXml:
			text = cls._collectNativeText(obj)
			nativeTextTried = True

		# Whole-window capture: try the focused control's native text
		# first.  When it is available (IA2 terminal, rich edit, etc.) it
		# is cleaner and includes scrollback that the display model misses.
		if not preferNative and not rawXml:
			try:
				import api
				focusNative = cls._collectNativeText(
					api.getFocusObject(),
				)
				if focusNative.strip():
					text = focusNative
					nativeTextTried = True
			except Exception:
				pass

		# Display model via getWindowTextInRect (terminals, PuTTY).
		if not text.strip():
			try:
				import displayModel

				hwnd = obj.windowHandle
				rect = ctypes.wintypes.RECT()
				ctypes.windll.user32.GetWindowRect(
					hwnd, ctypes.byref(rect),
				)
				bindingHandle = obj.appModule.helperLocalBindingHandle
				if bindingHandle:
					raw, _locs = displayModel.getWindowTextInRect(
						bindingHandle,
						hwnd,
						rect.left,
						rect.top,
						rect.right,
						rect.bottom,
						0,
						0,
						False,
					)
					if rawXml:
						text = raw
					else:
						text = cls._extractDisplayModelText(raw)
			except Exception:
				pass

		# Native TextInfo is the fallback for whole-window virtualization.
		if not text.strip() and not nativeTextTried:
			text = cls._collectNativeText(obj)

		# Accessibility tree.
		if not text.strip():
			text = cls._collectTreeText(obj)

		# Do not alter the diagnostic raw XML view. All regular extraction
		# paths receive the same logical-line cleanup, regardless of app.
		return text if rawXml else cls._trimLineEnds(text)

	@staticmethod
	def _collectTreeText(obj, depth=0):
		"""Recursively collect visible text from the accessibility tree."""
		if depth > 20:
			return ""
		parts = []
		try:
			role = obj.role
		except Exception:
			role = None
		try:
			name = obj.name or ""
		except Exception:
			name = ""
		if name.strip() and role not in (
			controlTypes.Role.WINDOW,
			controlTypes.Role.PANE,
			controlTypes.Role.PROPERTYPAGE,
			controlTypes.Role.DIALOG,
			controlTypes.Role.TOOLBAR,
			controlTypes.Role.MENUBAR,
		):
			parts.append(name.strip())
		try:
			children = obj.children
		except Exception:
			children = []
		for child in children:
			parts.append(cls._collectTreeText(child, depth + 1))
		return "\n".join(p for p in parts if p)

	@classmethod
	def showDialog(cls, obj, rawXml=False, preferNative=False):
		"""Collect text from *obj* and show it in a read-only dialog."""
		import api
		import gui
		import ui
		import wx

		from ._gui import _VirtualWindowViewer

		text = cls.collectText(
			obj, rawXml=rawXml, preferNative=preferNative,
		)
		if not text.strip():
			# Translators: shown when no text can be extracted.
			ui.message(_("No text found"))
			return

		def _show():
			dialog = _VirtualWindowViewer(
				gui.mainFrame,
				# Translators: title for the virtual window viewer.
				_("Virtual Window Viewer"),
				text,
			)
			gui.mainFrame.prePopup()
			try:
				dialog.Show()
			finally:
				gui.mainFrame.postPopup()

		wx.CallAfter(_show)
