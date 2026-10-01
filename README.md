# JVDA

A collection of features for NVDA users familiar with JAWS.

## Features

- **JAWS, Invisible, PC, Touch, and Object Navigation modes** — press Numpad Minus for the JAWS Cursor and repeat it for an independent Invisible Cursor; Shift+Numpad Plus activates flat Touch Cursor traversal; Numpad Plus returns to the PC Cursor.
- **Desktop and laptop profiles** — JAWS gestures follow NVDA's configured keyboard layout, with separate mappings for layout conflicts such as JAWSKey+H, JAWSKey+J, and JAWSKey+8.
- **Navigation keys** — arrow keys, numpad arrows, and NVDA+letter combos for line/word/character movement, with mode-aware behavior.
- **JAWS Cursor mouse control** — Alt+Shift+Arrow moves the mouse and JAWS Cursor together using a configurable 1–100 pixel increment; Invisible Cursor never moves the mouse.
- **Optional JAWS-to-PC tethering** — matching JAWS defaults, the JAWS Cursor remains independent of PC caret and focus changes unless tethering is enabled. Toggle it with Ctrl+JAWSKey+Numpad Minus (Ctrl+JAWSKey+Left Bracket on laptop layouts) or in JVDA settings.
- **Separate cursor restrictions** — JAWSKey+R cycles the six JAWS/Invisible Cursor window scopes. In NVDA browse or focus mode, it instead restricts the Virtual Cursor to the current nested web dialog or document; repeat it to unrestrict.
- **CapsLock double-tap to toggle** — tap CapsLock twice quickly to turn it on or off, without interfering with NVDA+CapsLock commands.
- **Safe NVDA modifier keys** — by default, a rapid double-tap of CapsLock or either Insert key is prevented from passing the bare key to the focused application. This can be changed immediately in JVDA settings.
- **Repeated symbol capping** — limits how many times a repeated symbol (like `----`) is spoken.
- **Column separator fix** — uses spaces instead of semicolons when reading list-view columns and browse-mode labels, matching JAWS.
- **Window list (NVDA+F10)** — list and switch to any open window, with a checkbox to show or hide system windows.
- **System tray icons (NVDA+F11)** — list and explore notification-area icons, with right-click (default), left-click, and double-click actions.
- **Skip blank lines in browse mode** — pressing `n` (skip past links) or arrowing up/down skips over blank and whitespace-only lines, landing on actual text.
- **JAWS table navigation** — table-reading aliases include current cell, T/Shift+T for next/prior table, row/column movement and extents, and Ctrl+Alt+Home/End for the first/last cell. Normal arrowing remains quiet while Ctrl+Alt+arrows report coordinates.
- **Suppress "has auto complete"** — stops NVDA from announcing "has auto complete" on edit fields.
- **Heading navigation backward** — Shift+H in browse mode speaks only the destination heading object, avoiding ancestor heading text exposed by applications such as Discord. This is enabled by default and can be disabled in JVDA settings.
- **Quiet Alt+Tab** — suppresses position info ("3 of 5") and table coordinates during Alt+Tab, so you hear only the window name.
- **Temporary speech rate** — Ctrl+Alt+PageUp and Ctrl+Alt+PageDown increase or decrease speech rate by 5%. The configured rate is restored when you switch windows, and the temporary rate is never saved.
- **Classic Winamp support** — JAWS-compatible commands report the current track title and information, elapsed and remaining time, and total track length while preserving NVDA's playlist, shuffle, and repeat support.
- **JAWS-oriented help** — JAWSKey+1 opens NVDA Input Help with JAWS command descriptions; desktop JAWSKey+H opens Hot Key Help, JAWSKey+F1 reports focused-control guidance, and Ctrl+Shift+JAWSKey+F2 opens the searchable command compatibility list.
- **Welcome message** — the first time NVDA starts with JVDA installed, a dialog explains how to switch JVDA's keyboard commands off and back on with JAWSKey+`, what the numpad now does, and where the settings and command list live. The JVDA settings panel has a button which shows it again.
- **Layered JAWSKey+Space commands** — press JAWSKey+Space, then one more key, the way JAWS layers work. Two rising tones open the layer; two falling tones mean it closed with nothing else to say, and a command that speaks its result plays no tone because the answer is itself the signal. The basic layer covers the clipboard, audio ducking, the screen shade, speech muting and speech on demand, the command search and JVDA's keyboard toggle; V opens a volume layer for the synthesizer volume, the sound balance and the audio output device; T opens a table layer that stays open while you move through cells. Question mark lists the open layer's keys. Only the sublayers JVDA can actually run are offered: a JAWS layer with no NVDA equivalent reports "command invalid" rather than opening. The layer takes NVDA+Space from NVDA's browse and focus mode toggle, which JAWSKey+Z also does; switch the layer off in JVDA settings to give NVDA+Space back.
- **JAWS-only keyboard (optional)** — "Ignore NVDA's own key commands" blocks every NVDA-modified key JVDA has not given a JAWS command to, and says "unavailable jaws command" instead. It is off by default. Ordinary typing and Control, Alt, Shift and Windows commands are untouched, and JAWSKey+`, JAWSKey+F4, JAWSKey+N and JAWSKey+1 always keep working.
- **NVDA menu and keyboard toggle** — Insert+J opens the NVDA menu, while CapsLock+J moves to the previous word. JAWSKey+` toggles all JVDA keyboard commands, leaving only that toggle available while commands are off.

Keyboard and presentation features can be configured in the JVDA settings panel under NVDA Preferences → Settings. JAWSKey+V opens NVDA Configuration Profiles as the practical application-specific Quick Settings equivalent, while JAWSKey+6 opens the global NVDA Settings dialog. Options that install or remove presentation patches and the optional web quick-key map are labeled “requires restart”; all other JVDA settings apply immediately, including the JAWSKey+Space layer and the JAWS-only keyboard.

## Web browsing: JAWS and NVDA terminology

On web pages, HTML help, HTML email, and supported PDFs, NVDA's Browse Mode is
the equivalent of the JAWS Virtual Cursor. NVDA's Focus Mode is the equivalent
of the JAWS PC Cursor or Forms Mode: keystrokes go to the focused control or web
application instead of moving through the document.

- Press JAWSKey+Z (NVDA+Z) to switch between Browse Mode and Focus Mode.
- In Browse Mode, NVDA's one-letter quick-navigation keys provide the familiar
  JAWS behavior: H/Shift+H for headings, T/Shift+T for tables, F/Shift+F for
  form controls, K/Shift+K for links, and 1 through 6 (with Shift for reverse)
  for heading levels. NVDA uses K for links rather than the JAWS L; L moves by
  list in both screen readers. The optional JAWS Virtual Cursor quick-key
  overrides make A/Shift+A move by radio button, O/Shift+O move by article, and
  Z/Shift+Z move by division/grouping. They also make K/Shift+K return to the
  temporary PlaceMarker set with Ctrl+Windows+K. Temporary markers last for the
  NVDA session and are not written to disk. Enable the overrides in JVDA
  settings and restart NVDA.
- Press Enter or Space on a control when it should receive input. Press Escape
  or JAWSKey+Z to return to Browse Mode when NVDA enters Focus Mode.
- For ARIA applications that need unmodified letters, enter Focus Mode before
  using the application. JAWSKey+3 passes the next keystroke through without
  changing modes. When the optional JAWS quick-key overrides are enabled,
  Ctrl+JAWSKey+N suspends or resumes them for the rest of the NVDA session so
  their letters can reach an application while Browse Mode remains active.
- JAWSKey+F5, JAWSKey+F6, and JAWSKey+F7 open NVDA's form-field, heading, and
  link lists. Ctrl+JAWSKey+B lists buttons, and Ctrl+JAWSKey+R lists NVDA
  landmarks as the practical equivalent of JAWS regions. These use NVDA's
  Elements List rather than the proprietary JAWS dialogs.

Quick-navigation availability depends on the document provider. In particular,
some PDF controls and dynamic web applications expose fewer element types than
ordinary browser documents.

## Command compatibility reference

The add-on includes `commands.md` with complete Desktop and Laptop gesture
tables and `user-guide.md` with task-oriented cursor, routing, web, table, and
mouse instructions. Ctrl+Shift+JAWSKey+F2 provides a searchable dialog for the
explicitly mapped commands.

## Help and support

Open JVDA's installed guide with the **Open JVDA help** button in NVDA
Preferences → Settings → JVDA, or use the Help action for JVDA in NVDA's
Add-on Store. The guide includes troubleshooting, known limitations, and
instructions for safely disabling or removing the add-on.

For support, email **help@effortlessvi.com**. Include the JVDA, NVDA, and
Windows versions; the affected application; the exact keystrokes; and what you
expected and heard. Ctrl+Shift+JAWSKey+F1 displays non-sensitive JVDA cursor
diagnostics. Review any diagnostic information or logs before sharing them.

JVDA is licensed under the GNU General Public License version 2 or later. JAWS
is a trademark of Freedom Scientific. JVDA is an independent project and is
not affiliated with or endorsed by Freedom Scientific.
