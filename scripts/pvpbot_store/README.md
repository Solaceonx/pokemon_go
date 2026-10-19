# The website's game store (Google Drive, through Apps Script)

Games played on solaceonx.github.io/pokemon_go_pvpbot are sent here as they finish, and again when notes are
added. Each is one JSON file in the owner's Google Drive, folder "pvpbot games". Free, nothing to keep running.
The page keeps every game in the browser too and resends any that did not get through, so a game is lost only if
the browser is wiped before it ever reaches the store.

## Set up (the owner, once, about 5 minutes)

1. Go to script.google.com, signed in to the Google account that should hold the games. New project.
2. Replace the editor's contents with `Code.gs` from this folder. Save.
3. Project Settings (gear) → Script Properties → Add: `READ_KEY` = a long random string you make up. Keep it to
   yourself; it is what lets the import script read the games back.
4. Deploy → New deployment → type "Web app". Execute as: Me. Who has access: Anyone. Deploy; allow the Drive
   access Google asks for. Copy the web app URL (ends in `/exec`).
5. Give the URL to the agent (it goes into the site; it is not secret, it only accepts games). Put both in
   `.pvpbot_store.json` at the project root (not tracked by git):
   `{"url": "https://script.google.com/macros/s/.../exec", "read_key": "the string from step 3"}`

Changing Code.gs later needs Deploy → Manage deployments → edit → new version, so the URL stays the same.

## Read the games back

    python3 scripts/import_played.py --store

fetches every game (the read key goes in the request body), writes new ones to games/played/ and updates the notes of games already there.
