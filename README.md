# Division 2 Keybinder (Linux Mint · Steam/Proton)

A small GTK app for editing Tom Clancy's The Division 2 keyboard and mouse bindings outside the game, including keys the in‑game menu won't let you change (the UI/menu keys).

## Install

```bash
tar xzf division2-keybinder.tar.gz
cd division2-keybinder
./install.sh
```

Then open **Division 2 Keybinder** from the Mint menu. Linux Mint already ships GTK3 for Python; the installer only calls `apt` if it's missing. Uninstall with `./install.sh --uninstall`.

You can also just run it without installing: `python3 division2_keybinder.py`

## First run

The game stores bindings in `user.bindings` inside Steam's Proton prefix:

```
~/.local/share/Steam/steamapps/compatdata/2221490/pfx/drive_c/users/steamuser/
    Documents/My Games/Tom Clancy's The Division 2/user.bindings
```

The app searches every Steam library (native, Flatpak and Snap Steam), so games on a second drive are found too. If nothing turns up, the game hasn't written the file yet: start the game, change any key in Settings → Keyboard/Mouse, quit, and press **Search again**.

## Choosing a profile at startup

Every time the program starts it opens **Choose key binding profile**. The profile currently in the game is marked **● in use now**.

- **Use this profile** writes the selected layout to the game straight away (a backup is made first). Double-click or Enter works too.
- **Edit keys** keeps the current layout and opens the editor.
- **Quit program** closes without changing anything.

Reopen it any time with **Switch profile…** (Ctrl+P). Untick "Show this window every time the program starts" if you'd rather go straight to the editor. Save new layouts from **More → Save current layout as profile…**.

## Using it

- **Rebind:** double‑click a Primary or Alternate cell, then press a key, click a mouse button or scroll. If that key is taken you choose **Move** (take it from the other action), **Swap**, or **Keep both**.
- **Swap:** select two actions and press Swap.
- **Move keys:** select a group (e.g. the four Move actions) and shift them with the arrows, e.g. WASD → ESDF. A preview shows the result before applying.
- **Conflicts** get a ⚠ icon; hover for details. Only clashes inside the same category are flagged, since menu keys and gameplay keys normally overlap (F is both Interact and the UI "F").
- **Add binding…** inserts an entry the file is missing, such as `KB_UI_R`.
- **Rename** an action by clicking its name. Names are generated from the game's internal names, so give them your own labels where they're cryptic.
- **Shortcuts:** Ctrl+S save, Ctrl+Z undo, Ctrl+O open, Ctrl+F search, Ctrl+P switch profile, Ctrl+Q close. Nothing touches the game file until you Save. The bind window has a **Close** button (or press Esc), and the main window has Close buttons at the top right and bottom right.

## Safety

- **Quit the game before saving.** It rewrites `user.bindings` when it exits. The app warns you if it sees the game running.
- Every save makes a timestamped backup (last 50 kept) in `~/.config/division2-keybinder/backups`. Use **Menu → Restore a backup**.
- The first time a file is opened, an **Original layout** profile is saved automatically.
- **Profiles** keep several layouts and can be exported/imported as JSON.
- **Reset to game defaults** backs up and removes the file so the game writes fresh defaults.
- If the game or Ubisoft Connect's cloud sync keeps reverting your changes, tick **Protect file (read‑only) after saving**. While on, changes you make inside the game won't stick.

## Key codes

Keyboard keys are DirectInput scan codes (W = 17, F = 33, Delete = 211, arrows 200/203/205/208). Mouse inputs start at 65536: Mouse 4 = 65540, wheel up = 65547, wheel down = 98315 are confirmed by players; left/right/middle (65537–65539) and Mouse 5 (65541) follow the same pattern. If a mouse button shows up wrong, check what your Fire/Aim entries contain and use **Enter code…** in the bind dialog. Key names follow your keyboard layout, so a Norwegian keyboard shows Ø, Æ and Å.

Players have reported that arrow keys, Page Up/Down and Home can misbehave as UI keys, and that two UI keys can't share the same key.

## Privacy and what the app touches

- **No network access.** It never connects to the internet and sends nothing anywhere.
- **Reads:** Steam's library list (`libraryfolders.vdf`, to find which drives have Steam games), the Division 2 folder inside Proton (app 2221490 only), the *names* of running programs (to warn you if the game is open), and your keyboard layout (to show the right key letters).
- **Writes:** only `user.bindings` (when you press Save, use a profile, restore or reset) and its own folder `~/.config/division2-keybinder` (settings, profiles, backups).
- **Starts:** only your file manager (Open file location) and Steam (Launch game), and only when you click those.
- **Exported profiles** contain just the profile name, date and key codes — no file paths, user name or computer details. Imported profiles are checked and anything that isn't a plain key code is dropped.
- **install.sh** asks for your password (sudo) only if GTK for Python is missing, which it normally isn't on Linux Mint.
