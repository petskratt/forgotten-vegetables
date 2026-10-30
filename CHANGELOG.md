# Changelog

## 0.1.1 - 2026-10-29

- Fetch channel posts without `include_deleted` unless the session user is a system admin. Mattermost returns 403 for that flag before it checks channel membership. The web client never sends it.
- Use the Mattermost navy sidebar and a compact search header. Messages sit in one column, with the time beside the name and a colored initial instead of a photo.
- Hide system posts unless `show_system` is true. `avatar_letter` picks the first or last word of the username.
- Store attachments in `media/<channel>/<file_id>/<name>`. Older prefixed files are moved the next time you fetch or rebuild the viewer.
- Sidebar rows are the chat name only. The open chat is a square row with a left bar. Message text is 14px on a 20px line, and thread replies line up with the message body.
- Read file responses whose status line says `HTTP/2` but whose body is still HTTP/1.1. urllib aborted those downloads even after the handshake asked for HTTP/1.1.
- `./archive.py` is the command. If the virtualenv, packages, or `.env` are missing, it prints the setup commands that are still left.
- The viewer tab uses the Mattermost icon. `title` in `channels.yaml` sets the tab text (default `MM Archive`).
- Chats open at the end unless `open_at` is `start`. Start and End jump there, and switching chats keeps the place you had scrolled to. A message time is a link to `#channel/post`, with the full timestamp on hover.
- Message text is rendered with Mattermost's CommonMark instead of a handful of regular expressions. Tables render, and an unclosed `*` or `**` no longer paints the rest of the chat.

## 0.1.0 - 2026-10-28

- Discover teams, channels, direct messages, and group messages into an editable `channels.yaml`.
- Download posts and attachments with a delay, and stop on errors or an empty rate-limit window so the same command can resume.
- Build a static viewer that opens from the archive folder, with this-chat and archive-wide text search over messages and filenames.
