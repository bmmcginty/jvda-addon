# JVDA task guide

## Choose and leave a cursor

- Press Numpad Minus once for the JAWS Cursor. Press it again quickly for the
  independent Invisible Cursor.
- Press Shift+Numpad Plus for the Touch Cursor. Press Windows+JAWSKey+Minus for
  Object Navigation.
- Press Numpad Plus to return safely to the PC Cursor from any JVDA cursor.
- On a laptop layout, use JAWSKey+P for the JAWS Cursor, JAWSKey+Semicolon for
  the PC Cursor, and Shift+JAWSKey+Semicolon for the Touch Cursor.

The JAWS Cursor remains independent of PC focus and caret changes by default,
matching JAWS. The Invisible Cursor is always independent and never moves the
system caret or physical mouse. Toggle optional JAWS-to-PC tethering with
Ctrl+JAWSKey+Numpad Minus on Desktop or Ctrl+JAWSKey+Left Bracket on Laptop.

## Route between cursors

Routing moves one cursor to the other cursor's location; it is different from
switching cursors.

- JAWSKey+Numpad Minus moves the JAWS or Invisible Cursor to the PC Cursor.
- JAWSKey+Numpad Plus routes the PC Cursor to the JAWS or Invisible Cursor and
  returns to PC mode.
- JAWSKey+Delete routes the Virtual Cursor to the PC Cursor.
- Ctrl+JAWSKey+Delete routes the PC Cursor to the Virtual Cursor.

On Laptop, use JAWSKey+Left Bracket to move JAWS to PC and JAWSKey+Apostrophe
to route PC to JAWS.

## Restrict review to a window

In JAWS or Invisible Cursor mode, JAWSKey+R cycles Unrestricted, Application
Window, Real Window, Current Window, Focus Window, and Frame. The review
position does not move when the restriction changes; the new boundary applies
on the next navigation command.

In a nested web dialog or document, the same command restricts the Virtual
Cursor to that web scope. Press it again to remove the web restriction.

## Browse and interact with the web

NVDA Browse Mode is the JAWS Virtual Cursor equivalent. NVDA Focus Mode is the
JAWS PC Cursor or Forms Mode equivalent.

1. Use H/Shift+H for headings, T/Shift+T for tables, F/Shift+F for form
   controls, and K/Shift+K for links in standard NVDA Browse Mode. By default,
   JVDA makes Shift+H speak only the destination heading instead of also
   speaking an ancestor heading. This can be disabled in JVDA settings and
   requires an NVDA restart when changed.
2. Press Enter or Space on an interactive control. Press Escape or JAWSKey+Z
   to return to Browse Mode.
3. For an ARIA application, switch to Focus Mode so unmodified letters reach
   the application. JAWSKey+3 passes only the next key through.
4. If optional JAWS quick-key overrides are enabled, Ctrl+JAWSKey+N suspends
   or resumes them for the current NVDA session.
5. Use JAWSKey+F5, F6, or F7 for form-field, heading, or link lists.
   Ctrl+JAWSKey+B lists buttons and Ctrl+JAWSKey+R lists landmarks.

Optional JAWS quick-key overrides change A to radio buttons, O to articles, Z
to divisions/groupings, and K to the session-only temporary PlaceMarker. Set
that marker with Ctrl+Windows+K. These overrides require an NVDA restart after
enabling or disabling them.

## Use classic Winamp

JVDA adds the following JAWS reporting commands when focus is in classic
Winamp. They query Winamp directly, so the visible time-display mode does not
change what is reported.

- Alt+Shift+T reports elapsed time.
- Ctrl+Shift+T reports remaining time.
- Ctrl+JAWSKey+T reports total track length.
- Alt+Ctrl+T reports the current track title.
- Shift+JAWSKey+T reports the title, length, sample rate, bit rate, and channel
  count.

Live streams may not provide a total length, so length and remaining time can
be unavailable. This support targets Winamp's classic `Winamp v1.x` window and
retains NVDA's existing playlist, shuffle, and repeat behavior.

## Navigate tables

Use Ctrl+Alt+Arrow for ordinary cell movement. Ctrl+Alt+Home and Ctrl+Alt+End
move to the first and last cell. Alt+Ctrl+Numpad5 reports the current cell.
Windows+Alt+Arrow moves and reads rows or columns. The complete aliases are in
`commands.md`.

## Use layered commands (JAWSKey+Space)

Press JAWSKey+Space, then one more key, the way JAWS layers work. Two rising
tones mean the layer is open.

The layer closes after one command. Some keys open a sublayer instead, and a
sublayer stays open so that you can press its keys repeatedly. Escape, Space,
Tab, Enter or two seconds without a key press close the layer, as does moving
the mouse or changing window.

Two falling tones mean the layer has closed with nothing else to say, after
Escape or a timeout. A command that speaks its result, or opens a window,
plays no tone: hearing "Audio ducking on" already tells you the layer has
ended, and a tone on top of it would say the same thing twice.

Press question mark (Shift+Slash) inside any layer to list that layer's keys.
If a key has a JAWS command JVDA cannot provide, JVDA speaks "command invalid".
If a key has no JAWS command at all, JVDA speaks "command unassigned". Both
end the layer.

JVDA offers only the sublayers it can actually run: the volume layer and the
table layer. JAWS's braille and text viewer, mouse echo, Face in View, OCR,
Picture Smart and Skype layers, and the volume layer's system volume sublayer,
report "command invalid" when you press their key. They do not open, because a
layer in which every key answered "command invalid" would tell you nothing.

Layer keys are dispatched by JVDA rather than by NVDA, so NVDA's Input Help
cannot describe them. Use the question mark help, or the table in
`commands.md`.

### Basic layer keys

- C shows the clipboard text.
- D turns audio ducking on or off.
- F11 or Print Screen turns the screen shade on or off.
- J opens the searchable command compatibility list.
- L turns JVDA's keyboard commands off or on.
- S mutes or unmutes speech; Shift+S switches speech on demand on or off.
- T opens the table layer; V opens the volume layer.
- B, E, F, O, P and Y are JAWS layers JVDA cannot support and report
  "command invalid".

### Volume layer keys

Press JAWSKey+Space, then V, then one of:

- J for the JAWS volume: Up or Right Arrow raises the synthesizer volume by 5
  percent, Down or Left Arrow lowers it, Page Up and Page Down move by 20.
- B for the sound balance: Left Arrow puts NVDA's speech on the left and
  applications on the right, Right Arrow does the reverse, Up Arrow restores
  both to the centre.
- C for the sound card: Up and Down Arrow move through the audio output
  devices and switch to the one they announce.

S is JAWS's system volume sublayer, which NVDA has no interface for; it
reports "command invalid".

### Table layer keys

Press JAWSKey+Space, then T. The arrow keys move a cell at a time, Home and End
move to the start and end of the row, Ctrl+Up and Ctrl+Down move to the top and
bottom of the column, and Ctrl+Home and Ctrl+End move to the first and last
cell of the table. Comma reports the current cell, Shift+Up Arrow reads the
row, and Shift+Comma reads the column. The table layer stays open until you
close it.

### JAWSKey+Space and browse mode

The layer takes NVDA+Space, which is NVDA's own browse and focus mode toggle.
JAWSKey+Z does the same job and is the JAWS command for it. To give NVDA+Space
back, uncheck "JAWSKey+Space layer commands" in the JVDA settings panel; the
change applies at once, without restarting NVDA.

## Ignore NVDA's own key commands

The JVDA settings panel has an option called "Ignore NVDA's own key commands
(JAWS-only keyboard)". It is off by default. When it is on, an NVDA-modified
key that JVDA has not given a JAWS command to is blocked, and JVDA speaks
"unavailable jaws command" instead of letting NVDA answer it.

Ordinary typing is untouched, and so are Control, Alt, Shift and Windows
commands: only keys pressed with the NVDA modifier are affected.

Four commands keep working whatever this option is set to, so that you can
always reach NVDA again:

- JAWSKey+` turns every JVDA keyboard command off, including this option.
- JAWSKey+F4 opens NVDA's exit dialog.
- JAWSKey+N opens the NVDA menu.
- JAWSKey+1 turns Input Help on and off.

## Use the mouse safely

In JAWS Cursor mode, Numpad Divide left-clicks and Numpad Multiply right-clicks
at the review position. JAWSKey with those keys locks or unlocks the matching
button. JVDA releases its locks when leaving the cursor, reloading, or
unloading. On Laptop, Shift+JAWSKey+8 marks a drag source; move the JAWS Cursor
and press it again to complete the drag.

## Find commands and compatibility

- JAWSKey+1 opens JAWS-oriented Input Help.
- Desktop JAWSKey+H opens Hot Key Help.
- JAWSKey+F1 shows context help for the focused control.
- Ctrl+Shift+JAWSKey+F2 opens the searchable compatibility list.
- `commands.md` contains Desktop and Laptop tables. The searchable compatibility
  list identifies exact, equivalent, approximate, and unavailable mappings.
- The JVDA settings panel button "Show welcome message" reopens the
  first-run message, which covers switching JVDA's keyboard commands off
  with JAWSKey+` and the basics of the JAWS keypad.
- Use "Open JVDA help" in the settings panel or the Help action for JVDA in
  NVDA's Add-on Store to open the complete installed guide.

## Configure NVDA modifier double-taps

By default, JVDA prevents a rapid double-tap of a configured NVDA modifier key
(CapsLock, Numpad Insert, or the dedicated Insert key) from sending that bare
key to the focused application. This avoids accidental Insert commands and
terminal keypad input. The separate "CapsLock double-tap to toggle" setting
continues to provide JAWS-style CapsLock toggling.

Uncheck "Prevent NVDA modifier keys from passing through on double-tap" in the
JVDA settings panel to restore NVDA's native pass-through behavior. The change
applies immediately. Temporarily disabling JVDA keyboard commands with
JAWSKey+` also restores NVDA's native behavior until interception is enabled
again.

## Troubleshoot JVDA

- If JVDA keystrokes interfere with an application, press JAWSKey+` to disable
  all JVDA keyboard commands. Press it again to restore them.
- Press Numpad Plus to return to the PC Cursor. On Laptop layout, press
  JAWSKey+Semicolon.
- If letters type into a web application instead of navigating, press Escape
  or JAWSKey+Z to return to Browse Mode. If navigation letters interfere with
  the application, use Focus Mode instead.
- If a JAWSKey+Space layer seems stuck and keys are being swallowed, press
  Escape. If that does not help, press JAWSKey+` to turn JVDA's keyboard
  commands off, which also closes any open layer, then press it again.
- Confirm that NVDA's Desktop or Laptop keyboard layout matches the commands
  you are using. Numpad commands require a physical or emulated numpad.
- Settings labelled "requires restart" take effect after NVDA restarts.
- To check for an add-on conflict, restart NVDA with add-ons disabled, then
  enable JVDA alone. JVDA can be disabled or removed from NVDA's Add-on Store.

## Known limitations

- Results depend on what an application's accessibility provider exposes.
  Browser documents, PDFs, Discord, terminals, and custom controls can expose
  different text, heading, table, or object boundaries.
- JVDA provides practical NVDA equivalents for many JAWS commands, not a JAWS
  scripting runtime or exact implementation of every JAWS feature.
- Some commands remain native NVDA commands, and unsupported mappings are
  identified in the searchable compatibility list.
- Options marked "requires restart" cannot be changed for the running session.
- NVDA's Input Help cannot describe the keys inside a JAWSKey+Space layer,
  because JVDA dispatches them itself. Use the question mark help inside the
  layer instead.
- The JAWSKey+Space commands and layers JVDA does not implement report
  "command invalid": speech history, notification history, the system volume,
  the braille and text viewers, OCR, mouse echo, Picture Smart, Face in View,
  Skype, and the factory-default mode.

## Get support

Email **help@effortlessvi.com** and include:

- JVDA, NVDA, and Windows versions;
- the application and, for web problems, the browser;
- exact keystrokes and steps to reproduce the problem;
- what you expected and what NVDA spoke; and
- whether the problem occurs with other add-ons disabled.

Ctrl+Shift+JAWSKey+F1 shows JVDA cursor diagnostics without document text.
Review diagnostics and NVDA logs before sharing them because environmental or
third-party information may still be present. JVDA never sends a support
request, diagnostic report, or log automatically.

## Accessibility

JVDA's dialogs and settings use standard keyboard-accessible NVDA and wxPython
controls. Dialogs have labelled controls, keyboard focus, and standard Escape
or Close behavior. Report an inaccessible workflow to help@effortlessvi.com.
