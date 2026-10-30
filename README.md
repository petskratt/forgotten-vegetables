# Forgotten vegetables soup (soupe aux légumes oubliés) *

Archive your Mattermost chats, private messages, and attachments to a folder, then open `archive/index.html` in a browser. No web server.

---
`*` Comfort food for when techies have decided your Mattermost is out of fashion, but the users still have their work history in it.

## Setup

Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` from a logged-in browser session (token, user id, CSRF, host, user agent). `MMHOST` can include a subdirectory. Uncomment `PROXY` if you need one (`127.0.0.1:8080` is fine; the scheme is optional). If that proxy intercepts TLS, set `SSL_VERIFY=false` or point it at your CA bundle.

## Run

```bash
./archive.py
```

The first run writes `archive/channels.yaml` and stops. Each chat is one line. Comment out any you do not want. Set `since` to a UTC date (`2024-01-01`) or leave `all`, and set `delay_seconds` if you want a longer pause between API calls.

```bash
./archive.py
```

The second run downloads posts and files, then builds the viewer. Open `archive/index.html` from that folder.

- `./archive.py discover` refreshes the chat list. New chats are appended. Commented lines are left alone.
- `./archive.py fetch` downloads only.
- `./archive.py viewer` rebuilds the HTML from JSON already on disk.
- `--env` and `--out` override `.env` and `archive/`.

Posts are saved under `archive/data/`. Attachments go in `archive/media/<channel_id>/<file_id>/`. Deleted posts are included only for a system admin. Mattermost rejects that request for everyone else.

`show_system` includes join, leave, and other system posts in the viewer and in search. Leave it false to hide them. `avatar_letter` is `first` or `last` (default `last`): the circle uses the first letter of that word of the username, split on anything that is not a letter. `title` is the browser tab text (default `MM Archive`). `open_at` is `start` or `end` (default `end`): where a chat opens the first time. After you scroll, switching chats keeps your place. Start and End in the channel header jump there. A message time links to that post (`#channel/post`); hover it for the full timestamp. Run `./archive.py viewer` after changing any of these.

## Resume

A rate limit, auth failure, server error, or network error stops the run immediately. There is no retry. `archive/state.json` remembers the cursor. Run the same command to continue. Files already on disk are not downloaded again.

## Viewer

Search has two scopes and one text box. **This chat** highlights matches in the open conversation, including attachment filenames. **Everything** searches every saved chat and filename. Previous and next step through the matches. There are no from, in, or date operators.

The page loads each chat with a normal script tag, because a `file://` page cannot fetch JSON. Message text uses Mattermost's CommonMark (tables, lists, emphasis, links). The tab icon is the Mattermost mark. Keep `index.html`, `commonmark.js`, `markdown.js`, the favicon pngs, `chats/`, `search.js`, and `media/` together.
