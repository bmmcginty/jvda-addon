# appModules/putty.py — JVDA override for IA2-capable PuTTY builds.
# Replaces the scratchpad version that checks for Role.TERMINAL (82),
# which never matches PuTTY's ROLE_SYSTEM_CLIENT (10).

import oleacc
from NVDAObjects.behaviors import Terminal
from NVDAObjects.window import DisplayModelEditableText, DisplayModelLiveText
import appModuleHandler
from NVDAObjects.IAccessible import IAccessible
from NVDAObjects import NVDAObject
import controlTypes
from NVDAObjects.IAccessible import IA2TextTextInfo
import textInfos

from ._timing import timedClass


@timedClass
class CustomTextInfo(IA2TextTextInfo):
	def _get_clipboardText(self):
		text = self.text.rstrip()
		text = [line.rstrip() for line in text.split("\n")]
		return "\r\n".join(text)


@timedClass
class CustomTerminal(NVDAObject):
	"""Terminal overlay that prefers IA2 text when available."""
	TextInfo = CustomTextInfo


@timedClass
class AppModule(appModuleHandler.AppModule):
	TERMINAL_WINDOW_CLASS = "PuTTY"

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		if (
			obj.windowClassName == self.TERMINAL_WINDOW_CLASS
			and isinstance(obj, IAccessible)
			and obj.IAccessibleRole == oleacc.ROLE_SYSTEM_CLIENT
		):
			# Remove display-model text so NVDA falls through to
			# IA2 (CustomTextInfo) when the custom PuTTY build
			# exposes IAccessibleText2.
			try:
				clsList.remove(DisplayModelEditableText)
			except ValueError:
				pass
			clsList[0:0] = (CustomTerminal,)
