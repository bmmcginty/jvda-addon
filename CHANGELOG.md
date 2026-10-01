# JVDA release notes

## 0.1.2

Initial public release.

### Added

- JAWS-style PC, JAWS, Invisible, Touch, and Object Navigation cursor commands.
- Desktop and Laptop keyboard layouts, cursor routing and restrictions, mouse commands, window and system-tray lists, table navigation, and web navigation equivalents.
- JAWS-oriented Input Help, context help, command compatibility search, and a first-run welcome message.
- Configurable presentation fixes for repeated symbols, blank lines, table coordinates, autocomplete announcements, status positions, Alt+Tab, and list-view columns.
- A default-on option that prevents Shift+H from speaking ancestor heading text in applications such as Discord.
- Default-on suppression of NVDA's bare modifier-key double-tap pass-through, with an immediately applied setting to restore it.
- JAWS-compatible classic Winamp reports for track title and details, elapsed and remaining time, and total length.
- Layered JAWSKey+Space commands, on by default: a basic layer for the clipboard, audio ducking, the screen shade, speech muting, speech on demand, the command search and JVDA's keyboard toggle; a volume layer for the synthesizer volume, the sound balance and the audio output device; and a table layer that stays open while moving through cells. Question mark lists the open layer's keys, and keys JVDA cannot provide report "command invalid". Only the sublayers JVDA can run are offered; a JAWS layer with no NVDA equivalent reports "command invalid" instead of opening. Two falling tones mean the layer closed with nothing else to say, and a command that speaks its result plays no tone.
- An optional JAWS-only keyboard, off by default, which blocks every NVDA-modified key JVDA has not given a JAWS command to and reports "unavailable jaws command". JAWSKey+`, JAWSKey+F4, JAWSKey+N and JAWSKey+1 always keep working.

### Changed

- NVDA+Space opens the JAWSKey+Space layer instead of toggling browse and focus mode. JAWSKey+Z still toggles browse and focus mode, and switching the layer off in JVDA settings gives NVDA+Space back to NVDA at once.

### Fixed

- Empty screen-review ranges now return no display fields instead of raising an index error or returning the rest of the window. This prevents application-restricted JAWS Cursor movement in terminals such as PuTTY from intermittently skipping lines in Git, Nano, and other console applications.

### Compatibility

- Requires NVDA 2026.1 or later.
- Tested through NVDA 2026.2.0.
- Windows only, matching NVDA's supported platform.

### Known limitations

- Application accessibility providers determine which text, objects, headings, and tables JVDA can navigate.
- JVDA provides NVDA equivalents for many JAWS commands; it is not a JAWS scripting runtime and does not implement every JAWS command.
- Settings labelled "requires restart" take effect only after NVDA restarts.
- NVDA's Input Help cannot describe the keys inside a JAWSKey+Space layer, because JVDA dispatches them itself; the question mark help inside the layer lists them.
- The speech history, notification history, system volume, braille and text viewer, OCR, mouse echo, Picture Smart, Face in View, Skype and factory-default commands and layers are not implemented and report "command invalid".
