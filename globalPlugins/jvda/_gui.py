# JVDA GUI: Windows-list and tray-icon dialogs, plus the NVDA
# settings panel.  Uses wx.ListCtrl (listview) so that consecutive
# keystrokes perform incremental search (e.g. "no" for "Notepad").

import addonHandler
import config
from pathlib import Path
import wx
import winUser

from ._config import setUserValue
from ._timing import timedClass


_settingsPanelClass = None


@timedClass
class _WindowsListDialog(wx.Dialog):
	"""A dialog listing top-level windows in a listview."""

	def __init__(self, parent, title, allWindows, plugin):
		self._allWindows = allWindows  # list of (hwnd, name)
		self._plugin = plugin
		super().__init__(parent, title=title)

		self._checkBox = wx.CheckBox(self, label=_("Show system &windows"))
		self._checkBox.SetValue(False)
		self._checkBox.Bind(wx.EVT_CHECKBOX, self._onCheckChanged)

		self._list = wx.ListCtrl(
			self,
			style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER,
		)
		self._list.AppendColumn("", width=wx.LIST_AUTOSIZE)
		self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onActivate)
		self.Bind(wx.EVT_CHAR_HOOK, self._onListChar)
		self._populateList()

		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(
			self._list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10,
		)
		sizer.Add(
			self._checkBox,
			flag=wx.LEFT | wx.RIGHT | wx.BOTTOM,
			border=10,
		)
		buttonSizer = wx.StdDialogButtonSizer()
		buttonSizer.AddButton(wx.Button(self, wx.ID_OK))
		buttonSizer.AddButton(wx.Button(self, wx.ID_CANCEL))
		buttonSizer.Realize()
		sizer.Add(buttonSizer, flag=wx.EXPAND | wx.ALL, border=10)
		self.SetSizer(sizer)
		sizer.Fit(self)
		self.CenterOnScreen()
		self._list.SetFocus()

	def _shownWindows(self):
		showSystem = self._checkBox.GetValue()
		if showSystem:
			return self._allWindows
		result = []
		for hwnd, name in self._allWindows:
			isSys, reason = self._plugin._isSystemWindow(hwnd)
			if isSys:
				self._plugin._log(
					f"System window filtered: {name!r} reason={reason}",
				)
			else:
				result.append((hwnd, name))
		return result

	def _populateList(self):
		index = self._list.GetFirstSelected()
		selectedName = None
		if index != -1:
			selectedName = self._list.GetItemText(index)
		self._list.DeleteAllItems()
		for idx, (hwnd, name) in enumerate(self._shownWindows()):
			self._list.InsertItem(idx, name)
			self._list.SetItemData(idx, hwnd)
		if selectedName is not None:
			item = self._list.FindItem(-1, selectedName)
			if item != -1:
				self._list.Select(item)
				self._list.Focus(item)
		if self._list.GetFirstSelected() == -1 and self._list.GetItemCount():
			self._list.Select(0)
			self._list.Focus(0)

	def _onCheckChanged(self, event):
		self._populateList()
		event.Skip()

	def _onActivate(self, event):
		self.EndModal(wx.ID_OK)

	def _onListChar(self, event):
		if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
			self.EndModal(wx.ID_OK)
		else:
			event.Skip()

	def activateSelected(self):
		index = self._list.GetFirstSelected()
		if index == -1:
			return
		hwnd = self._list.GetItemData(index)
		if hwnd:
			self._bringWindowToFront(hwnd)

	@staticmethod
	def _bringWindowToFront(hwnd):
		import ctypes

		if ctypes.windll.user32.IsIconic(hwnd):
			ctypes.windll.user32.ShowWindow(hwnd, winUser.SW_SHOWNORMAL)
		winUser.setForegroundWindow(hwnd)


@timedClass
class _TrayListDialog(wx.Dialog):
	"""Dialog listing system-tray icons with Right/Left/Double Click."""

	def __init__(self, parent, title, entries, actionLocations=None):
		"""*entries* is a list of ``(name, obj)`` pairs."""
		self._entries = entries  # (name, obj)
		self._actionLocations = actionLocations or {}
		super().__init__(parent, title=title)

		self._list = wx.ListCtrl(
			self,
			style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER,
		)
		self._list.AppendColumn("", width=wx.LIST_AUTOSIZE)
		self.Bind(wx.EVT_CHAR_HOOK, self._onListChar)
		for idx, (name, _obj) in enumerate(entries):
			self._list.InsertItem(idx, name)
		if self._list.GetItemCount():
			self._list.Select(0)
			self._list.Focus(0)

		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(
			self._list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10,
		)

		# Three action buttons — Right Click is the default.
		buttonSizer = wx.BoxSizer(wx.HORIZONTAL)
		rightBtn = wx.Button(self, label=_("&Right Click"))
		rightBtn.SetDefault()
		rightBtn.Bind(wx.EVT_BUTTON, self._onRightClick)
		buttonSizer.Add(rightBtn, flag=wx.RIGHT, border=5)

		leftBtn = wx.Button(self, label=_("&Left Click"))
		leftBtn.Bind(wx.EVT_BUTTON, self._onLeftClick)
		buttonSizer.Add(leftBtn, flag=wx.RIGHT, border=5)

		doubleBtn = wx.Button(self, label=_("&Double Click"))
		doubleBtn.Bind(wx.EVT_BUTTON, self._onDoubleClick)
		buttonSizer.Add(doubleBtn, flag=wx.RIGHT, border=5)

		closeBtn = wx.Button(self, wx.ID_CANCEL, label=_("&Close"))
		buttonSizer.Add(closeBtn)

		sizer.Add(buttonSizer, flag=wx.EXPAND | wx.ALL, border=10)
		self.SetSizer(sizer)
		sizer.Fit(self)
		self.CenterOnScreen()
		self._list.SetFocus()

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------

	def _getSelectedObj(self):
		index = self._list.GetFirstSelected()
		if index == -1:
			return None
		_name, obj = self._entries[index]
		return obj

	@staticmethod
	def _clickLocation(location, button="right", double=False):
		"""Click a captured screen location after the dialog closes."""
		import ctypes

		left, top, width, height = location
		x = left + width // 2
		y = top + height // 2
		winUser.setCursorPos(x, y)
		if button == "left":
			down = winUser.MOUSEEVENTF_LEFTDOWN
			up = winUser.MOUSEEVENTF_LEFTUP
		else:
			down = winUser.MOUSEEVENTF_RIGHTDOWN
			up = winUser.MOUSEEVENTF_RIGHTUP
		ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
		ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)
		if double:
			wx.MilliSleep(50)
			ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
			ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)

	def _scheduleClick(self, button="right", double=False):
		"""Close the dialog and then click the selected icon."""
		obj = self._getSelectedObj()
		if obj is None:
			return
		# Capture coordinates before closing: a tray accessibility object can
		# become invalid as soon as its flyout loses focus.
		name, _obj = self._entries[self._list.GetFirstSelected()]
		location = self._actionLocations.get(name)
		if location is None:
			try:
				location = obj.location
			except Exception:
				return
		self._clickLocation(location, button, double)
		self.EndModal(wx.ID_OK)

	# ------------------------------------------------------------------
	# Event handlers
	# ------------------------------------------------------------------

	def _onListChar(self, event):
		"""Enter → right-click; Space → normal selection (skip)."""
		key = event.GetKeyCode()
		if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
			self._scheduleClick(button="right")
		elif event.AltDown() and key in (ord("R"), ord("r")):
			self._scheduleClick(button="right")
		elif event.AltDown() and key in (ord("L"), ord("l")):
			self._scheduleClick(button="left")
		elif event.AltDown() and key in (ord("D"), ord("d")):
			self._scheduleClick(button="left", double=True)
		else:
			event.Skip()

	def _onRightClick(self, event):
		self._scheduleClick(button="right")

	def _onLeftClick(self, event):
		self._scheduleClick(button="left")

	def _onDoubleClick(self, event):
		self._scheduleClick(button="left", double=True)


@timedClass
class _CommandCompatibilityDialog(wx.Dialog):
	"""Searchable JAWS command and JVDA compatibility list."""

	def __init__(self, parent, title, entries):
		super().__init__(parent, title=title, size=(850, 500))
		self._entries = entries
		self._search = wx.TextCtrl(self)
		self._search.SetHint(_("Search commands, gestures, or compatibility"))
		self._search.Bind(wx.EVT_TEXT, self._onSearch)
		self._search.Bind(wx.EVT_KEY_UP, self._onSearchKeyUp)
		self._list = wx.ListCtrl(
			self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
		)
		for label, width in (
			(_("JAWS gesture"), 180), (_("Command"), 260),
			(_("Compatibility"), 120), (_("JVDA gesture"), 220),
		):
			self._list.AppendColumn(label, width=width)

		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(self._search, flag=wx.EXPAND | wx.ALL, border=10)
		sizer.Add(
			self._list, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT,
			border=10,
		)
		closeButton = wx.Button(self, wx.ID_CANCEL, label=_("&Close"))
		sizer.Add(closeButton, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)
		self.SetSizer(sizer)
		self.CenterOnScreen()
		self._populate("")
		self._search.SetFocus()
		wx.CallAfter(self._search.SetFocus)

	def _matchingEntries(self, query):
		words = query.casefold().split()
		if not words:
			return self._entries
		return [
			entry for entry in self._entries
			if all(word in " ".join(str(value) for value in entry.values()).casefold()
				for word in words)
		]

	def _populate(self, query):
		self._list.DeleteAllItems()
		for entry in self._matchingEntries(query):
			row = self._list.InsertItem(
				self._list.GetItemCount(), entry["jawsGesture"],
			)
			if row == -1:
				continue
			self._list.SetItem(row, 1, entry["jawsCommand"])
			self._list.SetItem(row, 2, entry["status"])
			self._list.SetItem(row, 3, entry["jvdaGesture"])
		if self._list.GetItemCount():
			self._list.Select(0)

	def _onSearch(self, event):
		wx.CallAfter(self._populate, event.GetString())
		event.Skip()

	def _onSearchKeyUp(self, event):
		self._populate(self._search.GetValue())
		event.Skip()


@timedClass
class _VirtualWindowViewer(wx.Dialog):
	"""A read-only multi-line dialog showing all text from a window."""

	def __init__(self, parent, title, text):
		super().__init__(parent, title=title, size=(600, 500))

		textCtrl = wx.TextCtrl(
			self,
			style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
		)
		textCtrl.SetValue(text)

		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(
			textCtrl, proportion=1, flag=wx.EXPAND | wx.ALL, border=10,
		)
		closeBtn = wx.Button(self, wx.ID_CANCEL, label=_("&Close"))
		closeBtn.Bind(wx.EVT_BUTTON, lambda evt: self.Destroy())
		sizer.Add(closeBtn, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)
		self.SetSizer(sizer)
		self.CenterOnScreen()
		textCtrl.SetFocus()


WELCOME_TITLE = _("Welcome to JVDA")
SUPPORT_EMAIL = "help@effortlessvi.com"


def openInstalledHelp():
	"""Open the localized guide registered with NVDA's Add-on Store."""
	addon = addonHandler.getCodeAddon()
	helpPath = addon.getDocFilePath() if addon else None
	if helpPath and wx.LaunchDefaultBrowser(Path(helpPath).as_uri()):
		return
	wx.MessageBox(
		_("The installed JVDA help file could not be opened."),
		_("JVDA Help"),
		wx.OK | wx.ICON_ERROR,
	)


def contactSupport():
	"""Open a new support message in the user's default mail application."""
	url = "mailto:help@effortlessvi.com?subject=JVDA%20support%20request"
	if wx.LaunchDefaultBrowser(url):
		return
	wx.MessageBox(
		_("Email JVDA support at help@effortlessvi.com."),
		_("JVDA Support"),
		wx.OK | wx.ICON_INFORMATION,
	)


def _applySettingsToRunningPlugin():
	"""Ask the running JVDA plugin to re-apply settings that bind gestures.

	The JAWSKey+Space layer and the JAWS-only keyboard are bound or unbound by
	``GlobalPlugin._bindBaseGestures``, so a changed setting only takes effect
	once the running plugin rebinds. The plugin is found through NVDA's
	registry of running global plugins rather than held as a reference, so the
	settings panel never keeps a dead plugin alive."""
	try:
		import globalPluginHandler
	except Exception:
		return
	for plugin in getattr(globalPluginHandler, "runningPlugins", ()):
		apply = getattr(plugin, "_applySettingsChange", None)
		if apply is not None:
			try:
				apply()
			except Exception:
				pass


def _welcomeText():
	"""The text of the first-run message, as one reviewable block."""
	return "\n".join((
		_("JVDA adds JAWS-style commands to NVDA. Five things are worth "
			"knowing before you start."),
		"",
		_("1. Switching JVDA's keyboard commands off and back on"),
		_("Press NVDA+` (the NVDA key with the grave accent or backtick "
			"key above Tab) to switch every JVDA keyboard command off. "
			"NVDA at once behaves exactly as it does without JVDA. Press "
			"NVDA+` again to switch the commands back on."),
		_("That one toggle keeps working while the rest are off, so it is "
			"always the way back. Use it if a JVDA command gets in your "
			"way, or before opening the NVDA menu with NVDA+N to reach "
			"Tools, Add-on Store, where JVDA can be disabled or removed. "
			"If NVDA itself becomes unusable, choose NVDA menu, Tools, "
			"Restart with add-ons disabled."),
		"",
		_("2. The numpad becomes a JAWS keypad"),
		_("Numpad Minus turns on the JAWS Cursor, and pressing it twice "
			"gives the Invisible Cursor. Numpad Plus always returns to "
			"the PC Cursor."),
		_("While a JAWS or Invisible Cursor is reading, speech is pitched "
			"slightly lower and the arrow keys review the screen instead "
			"of moving the caret. Numpad Plus brings normal typing and "
			"arrowing back. On a laptop keyboard layout, use NVDA+P for "
			"the JAWS Cursor and NVDA+Semicolon for the PC Cursor."),
		"",
		_("3. Other things that change straight away"),
		_("Tapping CapsLock twice quickly toggles CapsLock. NVDA+Z "
			"switches between browse mode, the JAWS Virtual Cursor "
			"equivalent, and focus mode, the Forms Mode equivalent. "
			"NVDA+F10 lists open windows and NVDA+F11 lists system tray "
			"icons."),
		"",
		_("4. JAWSKey+Space opens a layer of commands"),
		_("Press NVDA+Space, then one more key, the way JAWS layers work. "
			"Two rising tones mean the layer is open. Press question mark "
			"to hear the layer's own keys, or Escape to leave. NVDA+Space "
			"no longer switches between browse and focus mode; NVDA+Z "
			"does that. The settings panel can switch the layer off."),
		"",
		_("5. Finding commands and settings"),
		_("Ctrl+Shift+NVDA+F2 opens a searchable list of JAWS commands "
			"and their JVDA equivalents. NVDA+1 starts input help with "
			"JAWS-oriented descriptions: press keys to hear what they do, "
			"and press NVDA+1 again to leave. Every JVDA option lives in "
			"NVDA menu, Preferences, Settings, JVDA; options labelled "
			"\"requires restart\" take effect after NVDA restarts."),
		"",
		_("The settings panel also has an option called \"Ignore NVDA's own "
			"key commands\", which is off unless you switch it on. While it "
			"is on, NVDA's own commands answer with \"unavailable jaws "
			"command\", and NVDA+`, NVDA+F4, NVDA+N and NVDA+1 are the "
			"commands that always keep working."),
		"",
		_("This message is shown only once. The JVDA settings panel has a "
			"button that shows it again."),
		_("For help, open the installed JVDA guide or email "
			"help@effortlessvi.com."),
	))


@timedClass
class _WelcomeDialog(wx.Dialog):
	"""First-run message: how to leave JVDA's key mode, and the basics."""

	def __init__(self, parent):
		super().__init__(parent, title=WELCOME_TITLE, size=(650, 500))

		text = wx.TextCtrl(
			self,
			value=_welcomeText(),
			style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
		)

		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(text, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
		buttonSizer = wx.StdDialogButtonSizer()
		okButton = wx.Button(self, wx.ID_OK)
		okButton.SetDefault()
		buttonSizer.AddButton(okButton)
		buttonSizer.Realize()
		sizer.Add(buttonSizer, flag=wx.EXPAND | wx.ALL, border=10)
		self.SetSizer(sizer)
		self.CenterOnScreen()
		self.SetEscapeId(wx.ID_OK)
		text.SetInsertionPoint(0)
		text.SetFocus()


def showWelcomeDialog(parent=None):
	"""Show the JVDA welcome message modally."""
	import gui

	parent = parent or gui.mainFrame
	usingMainFrame = parent is gui.mainFrame
	if usingMainFrame:
		gui.mainFrame.prePopup()
	dialog = _WelcomeDialog(parent)
	try:
		dialog.ShowModal()
	finally:
		dialog.Destroy()
		if usingMainFrame:
			gui.mainFrame.postPopup()


def _unregisterSettingsPanel():
	"""Remove current and stale JVDA settings panels by module and title."""
	global _settingsPanelClass
	try:
		from gui import settingsDialogs
		settingsDialogs.NVDASettingsDialog.categoryClasses[:] = [
			panel for panel in settingsDialogs.NVDASettingsDialog.categoryClasses
			if not (
				getattr(panel, "__module__", None) == __name__
				and getattr(panel, "title", None) == "JVDA"
			)
		]
	except Exception:
		pass
	_settingsPanelClass = None


def _tryRegisterSettingsPanel():
	"""Create and register the JVDA settings panel.

	All GUI imports are deferred so a missing or partially-initialised
	``gui.settingsDialogs`` cannot prevent the add-on from loading."""
	try:
		from gui import settingsDialogs
		from gui import guiHelper
	except Exception:
		return

	@timedClass
	class _Panel(settingsDialogs.SettingsPanel):
		title = "JVDA"

		def makeSettings(self, settingsSizer):
			sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
			self._repeatedSymbolLimit = sHelper.addLabeledControl(
				# Translators: label for repeated-symbol limit spin
				# control.
				_("Repeated &symbol limit"),
				wx.SpinCtrl,
				min=1,
				max=20,
			)
			self._repeatedSymbolLimit.SetValue(
				config.conf["jvda"]["repeatedSymbolLimit"],
			)
			self._mouseMovementIncrement = sHelper.addLabeledControl(
				# Translators: label for the JAWS Cursor mouse movement step.
				_("Mouse movement &increment in pixels"),
				wx.SpinCtrl,
				min=1,
				max=100,
			)
			self._mouseMovementIncrement.SetValue(
				config.conf["jvda"]["mouseMovementIncrement"],
			)
			self._tetherJawsToPc = sHelper.addItem(
				# Translators: label for following the PC caret with JAWS Cursor.
				wx.CheckBox(
					self, label=_("&Tether JAWS Cursor to PC Cursor"),
				),
			)
			self._tetherJawsToPc.SetValue(
				config.conf["jvda"]["tetherJawsToPc"],
			)
			self._capsLockFix = sHelper.addItem(
				# Translators: label for the CapsLock double-tap
				# checkbox.
				wx.CheckBox(
					self, label=_("CapsLock double-tap to &toggle"),
				),
			)
			self._capsLockFix.SetValue(config.conf["jvda"]["capsLockFix"])
			self._suppressModifierDoubleTap = sHelper.addItem(
				# Translators: checkbox preventing a bare NVDA modifier key from
				# reaching the focused application when pressed twice quickly.
				wx.CheckBox(
					self,
					label=_(
						"Prevent NVDA modifier keys from passing through on "
						"&double-tap",
					),
				),
			)
			self._suppressModifierDoubleTap.SetValue(
				config.conf["jvda"]["suppressModifierDoubleTap"],
			)
			self._skipBlankNotLinkBlock = sHelper.addItem(
				# Translators: label for the skip-blank-lines in
				# non-link blocks checkbox.
				wx.CheckBox(
					self,
					label=_(
						"Skip blank lines in non-link text &blocks "
						"(requires restart)",
					),
				),
			)
			self._skipBlankNotLinkBlock.SetValue(
				config.conf["jvda"]["skipBlankLinesNotLinkBlock"],
			)
			self._skipBlankBrowseMode = sHelper.addItem(
				# Translators: label for the skip-blank-lines in
				# browse mode checkbox.
				wx.CheckBox(
					self,
					label=_(
						"Skip blank lines when moving by line "
						"in browse &mode (requires restart)",
					),
				),
			)
			self._skipBlankBrowseMode.SetValue(
				config.conf["jvda"]["skipBlankLinesBrowseMode"],
			)
			self._suppressTableCoords = sHelper.addItem(
				# Translators: label for the suppress-table-coords
				# checkbox.
				wx.CheckBox(
					self,
					label=_(
						"Suppress table row/column &announcements "
						"while arrowing (requires restart)",
					),
				),
			)
			self._suppressTableCoords.SetValue(
				config.conf["jvda"]["suppressTableCoordsArrowing"],
			)
			self._suppressAutocomplete = sHelper.addItem(
				# Translators: label for the suppress-autocomplete
				# checkbox.
				wx.CheckBox(
					self,
					label=_(
						'Suppress "has auto &complete" announcements '
						"(requires restart)",
					),
				),
			)
			self._suppressAutocomplete.SetValue(
				config.conf["jvda"]["suppressAutocomplete"],
			)
			self._suppressStatusAndProgressPositions = sHelper.addItem(
				# Translators: label for the status and media progress
				# position announcement checkbox.
				wx.CheckBox(
					self,
					label=_(
						"Suppress &status and media progress positions "
						"(requires restart)",
					),
				),
			)
			self._suppressStatusAndProgressPositions.SetValue(
				config.conf["jvda"]["suppressStatusAndProgressPositions"],
			)
			self._suppressAltTabPos = sHelper.addItem(
				# Translators: label for the suppress-alt-tab-position checkbox.
				wx.CheckBox(
					self,
					label=_(
						'Suppress position info ("3 of 5"&) '
						"during Alt+Tab",
					),
				),
			)
			self._suppressAltTabPos.SetValue(
				config.conf["jvda"]["suppressAltTabPositionInfo"],
			)
			self._columnSepFix = sHelper.addItem(
				# Translators: label for the column-separator-fix checkbox.
				wx.CheckBox(
					self,
					label=_(
						"Use spaces instead of semicolons in "
						"list-view &columns (requires restart)",
					),
				),
			)
			self._columnSepFix.SetValue(
				config.conf["jvda"]["columnSeparatorFix"],
			)
			self._limitPreviousHeadingSpeech = sHelper.addItem(
				# Translators: checkbox limiting reverse heading navigation speech.
				wx.CheckBox(
					self,
					label=_(
						"Speak only the destination heading with Shift+&H "
						"(requires restart)"
					),
				),
			)
			self._limitPreviousHeadingSpeech.SetValue(
				config.conf["jvda"]["limitPreviousHeadingSpeech"],
			)
			self._jawsVirtualQuickKeys = sHelper.addItem(
				# Translators: optional JAWS web quick-key overrides checkbox.
				wx.CheckBox(
					self,
					label=_(
						"Use &JAWS Virtual Cursor quick-key overrides "
						"(requires restart)"
					),
				),
			)
			self._jawsVirtualQuickKeys.SetValue(
				config.conf["jvda"]["jawsVirtualQuickKeys"],
			)
			self._spaceLayerEnabled = sHelper.addItem(
				# Translators: checkbox enabling the layered JAWSKey+Space
				# commands, which take NVDA+Space from NVDA's own browse and
				# focus mode toggle.
				wx.CheckBox(
					self,
					label=_("JAWSKey+Space &layer commands"),
				),
			)
			self._spaceLayerEnabled.SetValue(
				config.conf["jvda"]["spaceLayerEnabled"],
			)
			self._noNvdaKeys = sHelper.addItem(
				# Translators: checkbox blocking NVDA's own keyboard commands
				# so that only JVDA's JAWS commands answer.
				wx.CheckBox(
					self,
					label=_(
						"Ignore NVDA's own key commands "
						"(&JAWS-only keyboard)",
					),
				),
			)
			self._noNvdaKeys.SetValue(config.conf["jvda"]["noNvdaKeys"])
			self._debugLog = sHelper.addItem(
				# Translators: label for the debug-log checkbox.
				wx.CheckBox(
					self,
					label=_("Enable &debug logging"),
				),
			)
			self._debugLog.SetValue(
				config.conf["jvda"]["debugLogEnabled"],
			)
			self._helpButton = sHelper.addItem(
				# Translators: button which opens the installed JVDA user guide.
				wx.Button(self, label=_("Open JVDA &help")),
			)
			self._helpButton.Bind(wx.EVT_BUTTON, self._onOpenHelp)
			self._supportButton = sHelper.addItem(
				# Translators: button which starts an email to JVDA support.
				wx.Button(
					self, label=_("Email &support at help@effortlessvi.com"),
				),
			)
			self._supportButton.Bind(wx.EVT_BUTTON, self._onContactSupport)
			self._welcomeButton = sHelper.addItem(
				# Translators: button which re-opens the JVDA welcome message.
				wx.Button(self, label=_("Show welcome &message")),
			)
			self._welcomeButton.Bind(wx.EVT_BUTTON, self._onShowWelcome)

		def _onOpenHelp(self, event):
			openInstalledHelp()

		def _onContactSupport(self, event):
			contactSupport()

		def _onShowWelcome(self, event):
			showWelcomeDialog(self)

		def onSave(self):
			conf = config.conf["jvda"]
			values = {
				"repeatedSymbolLimit": self._repeatedSymbolLimit.GetValue(),
				"mouseMovementIncrement": self._mouseMovementIncrement.GetValue(),
				"tetherJawsToPc": self._tetherJawsToPc.GetValue(),
				"capsLockFix": self._capsLockFix.GetValue(),
				"suppressModifierDoubleTap": (
					self._suppressModifierDoubleTap.GetValue()
				),
				"skipBlankLinesNotLinkBlock": (
					self._skipBlankNotLinkBlock.GetValue()
				),
				"skipBlankLinesBrowseMode": (
					self._skipBlankBrowseMode.GetValue()
				),
				"suppressTableCoordsArrowing": (
					self._suppressTableCoords.GetValue()
				),
				"suppressAutocomplete": self._suppressAutocomplete.GetValue(),
				"suppressStatusAndProgressPositions": (
					self._suppressStatusAndProgressPositions.GetValue()
				),
				"suppressAltTabPositionInfo": self._suppressAltTabPos.GetValue(),
				"columnSeparatorFix": self._columnSepFix.GetValue(),
				"debugLogEnabled": self._debugLog.GetValue(),
				"jawsVirtualQuickKeys": self._jawsVirtualQuickKeys.GetValue(),
				"limitPreviousHeadingSpeech": (
					self._limitPreviousHeadingSpeech.GetValue()
				),
				"spaceLayerEnabled": self._spaceLayerEnabled.GetValue(),
				"noNvdaKeys": self._noNvdaKeys.GetValue(),
			}
			changed = False
			for name, value in values.items():
				if value != conf[name]:
					setUserValue(conf, name, value)
					changed = True
			if changed:
				_applySettingsToRunningPlugin()

	global _settingsPanelClass
	_unregisterSettingsPanel()
	try:
		settingsDialogs.NVDASettingsDialog.categoryClasses.append(_Panel)
		_settingsPanelClass = _Panel
	except Exception:
		pass
