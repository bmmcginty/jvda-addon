# JVDA support for classic Winamp.
# Playlist overlays are derived from NVDA's GPL-licensed Winamp app module.
# Copyright (C) 2006-2020 NV Access Limited and JVDA contributors.
# This file is licensed under the GNU General Public License version 2 or later.

import addonHandler
import api
import appModuleHandler
import braille
from ctypes import Structure, byref, c_char, c_int, sizeof
import controlTypes
from NVDAObjects.IAccessible import IAccessible
import re
from scriptHandler import isScriptWaiting
import speech
import textUtils
import ui
import watchdog
import winKernel
import winUser

addonHandler.initTranslation()

WM_WA_IPC = winUser.WM_USER
IPC_ISPLAYING = 104
IPC_GETOUTPUTTIME = 105
IPC_GETINFO = 126
IPC_GET_SHUFFLE = 250
IPC_GET_REPEAT = 251
IPC_PLAYLIST_GET_NEXT_SELECTED = 3029
IPC_PE_GETCURINDEX = 100
IPC_PE_GETINDEXTOTAL = 101
IPC_PE_GETINDEXTITLE = 200


class fileinfo2(Structure):
	_fields_ = [
		("fileindex", c_int),
		("filetitle", c_char * 256),
		("filelength", c_char * 16),
	]


def _mainWindow():
	return winUser.FindWindow("Winamp v1.x", None)


def _sendIpc(parameter, command):
	hwnd = _mainWindow()
	if not hwnd:
		return -1
	return watchdog.cancellableSendMessage(
		hwnd, WM_WA_IPC, parameter, command,
	)


def _playbackState():
	return _sendIpc(0, IPC_ISPLAYING)


def _elapsedSeconds():
	milliseconds = _sendIpc(0, IPC_GETOUTPUTTIME)
	return milliseconds // 1000 if milliseconds >= 0 else None


def _totalSeconds():
	seconds = _sendIpc(1, IPC_GETOUTPUTTIME)
	return seconds if seconds >= 0 else None


def _formatTime(seconds):
	"""Return Winamp time in the spoken form used by the JAWS scripts."""
	seconds = max(0, int(seconds))
	minutes, seconds = divmod(seconds, 60)
	minuteText = _("1 minute") if minutes == 1 else _("{} minutes").format(minutes)
	secondText = _("1 second") if seconds == 1 else _("{} seconds").format(seconds)
	return _("{} {}").format(minuteText, secondText)


def _trackTitle(windowTitle):
	"""Remove Winamp's playlist number, status, and application suffix."""
	title = (windowTitle or "").strip()
	title = re.sub(r"\s+-\s+Winamp(?:\s+\[[^]]+\])?\s*$", "", title, flags=re.I)
	title = re.sub(r"^\d+\.\s*", "", title)
	return title if title.casefold() != "winamp" else ""


def _currentTrackTitle():
	hwnd = _mainWindow()
	return _trackTitle(winUser.getWindowText(hwnd)) if hwnd else ""


def getShuffle():
	return _sendIpc(0, IPC_GET_SHUFFLE)


def getRepeat():
	return _sendIpc(0, IPC_GET_REPEAT)


class AppModule(appModuleHandler.AppModule):
	"""Retain NVDA's Winamp support and add JAWS reporting commands."""

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		windowClass = obj.windowClassName
		if windowClass == "Winamp PE":
			clsList.insert(0, WinampPlaylistEditor)
		elif windowClass == "Winamp v1.x":
			clsList.insert(0, WinampMainWindow)

	def _requireTrack(self):
		if _playbackState() <= 0:
			ui.message(_("No track is playing"))
			return False
		return True

	def script_reportElapsedTime(self, gesture):
		"""Report elapsed time for the current Winamp track."""
		if not self._requireTrack():
			return
		seconds = _elapsedSeconds()
		if seconds is None:
			ui.message(_("Elapsed time unavailable"))
		else:
			ui.message(_("{}").format(_formatTime(seconds)))

	def script_reportRemainingTime(self, gesture):
		"""Report remaining time for the current Winamp track."""
		if not self._requireTrack():
			return
		elapsed = _elapsedSeconds()
		total = _totalSeconds()
		if elapsed is None or total is None:
			ui.message(_("Remaining time unavailable"))
		else:
			ui.message(_("{}").format(
				_formatTime(max(0, total - elapsed)),
			))

	def script_reportTrackLength(self, gesture):
		"""Report the length of the current Winamp track."""
		if not self._requireTrack():
			return
		total = _totalSeconds()
		if total is None:
			ui.message(_("Track length unavailable"))
		else:
			ui.message(_("{}").format(_formatTime(total)))

	def script_reportTrackTitle(self, gesture):
		"""Report the current Winamp track title."""
		title = _currentTrackTitle()
		ui.message(
			_("{}").format(title)
			if title else _("Track title unavailable")
		)

	def script_reportTrackInformation(self, gesture):
		"""Report title, length, sample rate, bit rate, and channels."""
		if not self._requireTrack():
			return
		title = _currentTrackTitle() or _("Unknown track")
		total = _totalSeconds()
		sampleRate = _sendIpc(0, IPC_GETINFO)
		bitRate = _sendIpc(1, IPC_GETINFO)
		channels = _sendIpc(2, IPC_GETINFO)
		parts = [_("{}").format(title)]
		if total is not None:
			parts.append(_("length {}").format(_formatTime(total)))
		if sampleRate >= 0:
			parts.append(_("{} hertz").format(sampleRate))
		if bitRate >= 0:
			parts.append(_("{} kilobits per second").format(bitRate))
		if channels >= 0:
			parts.append(
				_("1 channel") if channels == 1
				else _("{} channels").format(channels)
			)
		ui.message(", ".join(parts))

	__gestures = {
		"kb:alt+shift+t": "reportElapsedTime",
		"kb:control+shift+t": "reportRemainingTime",
		"kb:control+NVDA+t": "reportTrackLength",
		"kb:alt+control+t": "reportTrackTitle",
		"kb:NVDA+shift+t": "reportTrackInformation",
	}


class WinampMainWindow(IAccessible):
	def event_nameChange(self):
		pass

	def script_shuffleToggle(self, gesture):
		gesture.send()
		if not isScriptWaiting():
			api.processPendingEvents()
			ui.message(pgettext("shuffle", "on") if getShuffle() else pgettext("shuffle", "off"))

	def script_repeatToggle(self, gesture):
		gesture.send()
		if not isScriptWaiting():
			api.processPendingEvents()
			ui.message(pgettext("repeat", "on") if getRepeat() else pgettext("repeat", "off"))

	__gestures = {
		"kb:s": "shuffleToggle",
		"kb:r": "repeatToggle",
	}


class WinampPlaylistEditor(WinampMainWindow):
	def _get_name(self):
		curIndex = _sendIpc(-1, IPC_PLAYLIST_GET_NEXT_SELECTED)
		if curIndex < 0:
			return None
		info = fileinfo2()
		info.fileindex = curIndex
		internalInfo = winKernel.virtualAllocEx(
			self.processHandle, None, sizeof(info),
			winKernel.MEM_COMMIT, winKernel.PAGE_READWRITE,
		)
		try:
			winKernel.writeProcessMemory(
				self.processHandle, internalInfo, byref(info), sizeof(info), None,
			)
			watchdog.cancellableSendMessage(
				self.windowHandle, WM_WA_IPC, IPC_PE_GETINDEXTITLE, internalInfo,
			)
			winKernel.readProcessMemory(
				self.processHandle, internalInfo, byref(info), sizeof(info), None,
			)
		finally:
			winKernel.virtualFreeEx(
				self.processHandle, internalInfo, 0, winKernel.MEM_RELEASE,
			)
		fileTitle = info.filetitle.decode(
			textUtils.USER_ANSI_CODE_PAGE, errors="replace",
		)
		return "%d.\t%s\t%s" % (
			curIndex + 1, fileTitle, info.filelength.decode(errors="replace"),
		)

	def _get_role(self):
		return controlTypes.Role.LISTITEM

	def script_changeItem(self, gesture):
		gesture.send()
		if not isScriptWaiting():
			api.processPendingEvents()
			speech.speakObject(self, reason=controlTypes.OutputReason.FOCUS)
			braille.handler.handleGainFocus(self)

	def event_nameChange(self):
		return super(WinampMainWindow, self).event_nameChange()

	__changeItemGestures = (
		"kb:upArrow", "kb:downArrow", "kb:pageUp", "kb:pageDown",
	)

	def initOverlayClass(self):
		for gesture in self.__changeItemGestures:
			self.bindGesture(gesture, "changeItem")
