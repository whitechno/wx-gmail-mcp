# Tool catalogue

Every tool wx-gmail-mcp registers, with its gate, scope, parameters,
defaults, worked examples and the behaviors found in live use. The
docstrings the server sends to the model stay short; this page holds the
long form. A test keeps the tool list and every parameter table here equal
to the server's catalogue.

Conventions used below:

- **Gate** is the `WX_GMAIL_ALLOW_*` variable that registers the group,
  or *none* for the always-on tools. **Scope** is the OAuth scope the
  account must have granted; a tool refuses an account that lacks it and
  names the re-auth command. The base scopes (`gmail.readonly` and
  `gmail.modify`) are requested for every account.
- Examples show a call as `tool(param=value, ...)` and the plain text it
  returns. Ids, addresses and labels are placeholders. `work` is an
  account alias.
- Every mailbox tool takes `account`, an alias from `list_accounts`.
  Labels are accepted by name or id everywhere. Results are plain text.
- A `string` parameter whose default is `""` is optional. A `list of
  strings` with default `[]` is optional too.

| Group | Tools | Gate |
|---|---|---|
| [Accounts](#accounts) | `list_accounts`, `add_account`, `remove_account`, `get_profile` | none |
| [Read and search](#read-and-search) | `search`, `search_threads`, `read_message`, `read_thread`, `list_attachments`, `download_attachment` | none |
| [Labels](#labels) | `list_labels`, `create_label`, `update_label`, `delete_label` | none |
| [Organize](#organize) | `modify_labels`, `mark_read`, `mark_unread`, `archive`, `modify_thread_labels`, `modify_by_query` | none |
| [Trash and delete](#trash-and-delete) | `trash`, `untrash`, `delete_permanently` | `WX_GMAIL_ALLOW_DELETE` |
| [Drafts](#drafts) | `create_draft`, `list_drafts`, `get_draft`, `update_draft`, `delete_draft` | none |
| [Send](#send) | `send_message`, `send_draft`, `reply`, `forward` | `WX_GMAIL_ALLOW_SENDING` |
| [Filters](#filters) | `list_filters`, `get_filter`, `create_filter`, `delete_filter`, `replace_filter` | `WX_GMAIL_ALLOW_SETTINGS` |
| [Settings](#settings) | `get_vacation`, `set_vacation`, `list_send_as`, `set_signature` | `WX_GMAIL_ALLOW_SETTINGS` |

## Accounts

Gate: none. Scope: base. These tools manage the server's own account
list under `~/.wx-gmail-mcp/`; `get_profile` is the only one that calls
Gmail.

### `list_accounts`

One line per configured account: alias, address, token health, the
scopes Google granted, and a warning for each gate that is on in the
server but not granted by that account. The same text as
`wx-gmail-mcp --list`. Call it first in a session to learn the aliases.

| Parameter | Type | Default | Meaning |
|---|---|---|---|

```
list_accounts()
```

```
- work: you@example.com [healthy] scopes: full, modify, readonly, send, settings.basic
- home: other@example.com [healthy] scopes: modify, readonly
    warning: WX_GMAIL_ALLOW_SENDING is on but the send scope is not granted; re-run: WX_GMAIL_ALLOW_SENDING=true wx-gmail-mcp --auth home --email other@example.com
```

An account authorized with fewer gates than the server runs with is a
valid setup: the warning is informational, and that account refuses the
gated tools with the same hint. Several unmet gates share one warning
line (`... WX_GMAIL_ALLOW_SETTINGS and WX_GMAIL_ALLOW_DELETE are on but
the settings.basic and full scopes are not granted; re-run: ...`). A
token that cannot be refreshed shows `[needs re-auth: ...]` with the
command to run.

### `add_account`

Runs the OAuth consent flow in a browser on the machine the server runs
on and stores the token under `alias`. The scopes requested are the base
scopes plus one per gate that is on in the server's environment. Prefer
the terminal command `wx-gmail-mcp --auth <alias> --email <address>`:
some clients sandbox the server and block the loopback browser flow.
Re-running with an existing alias replaces its token.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `alias` | string | required | Letters, digits, `-` and `_` only; becomes the token file name |
| `email` | string | required | The address to sign in with (pre-selected on Google's screen) |

```
add_account(alias="work", email="you@example.com")
```

```
Authorized 'work' -> you@example.com. Token saved. Scopes: modify, readonly, settings.basic.
```

If the user signs in as a different address, the result says so and the
token is stored for that address. If the user unticks a scope on Google's
consent screen, the result warns which gate's tools will fail. Re-using
an alias replaces its token, and the result notes the address it held.

### `remove_account`

Deletes the local token and the alias. With `revoke=true` the grant is
also revoked at Google, which cuts off every alias that points at the
same address; without it the grant stays until the user removes it at
<https://myaccount.google.com/permissions>. If the revoke fails, nothing
is removed.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `alias` | string | required | The alias to forget |
| `revoke` | boolean | false | Also revoke the grant at Google |

```
remove_account(alias="old", revoke=true)
```

```
Removed account 'old' (local token deleted). Google grant for 'old' revoked.
```

### `get_profile`

The mailbox's address, message and thread totals and current history id,
from `users.getProfile`. A cheap way to confirm which mailbox an alias
points at.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |

```
get_profile(account="work")
```

```
Email: you@example.com
Messages: 68912
Threads: 51204
History id: 1234567
```

## Read and search

Gate: none. Scope: base. Bodies are decoded to text; HTML is returned as
is when a message has no plain-text part. Bodies longer than the server's
cap (20000 characters) end with `...[truncated]`. Snippets have their
HTML entities unescaped.

### `search`

Messages matching a Gmail search, newest first, with the ids every other
tool needs. Spam and Trash are searched only with `include_spam_trash` or
when the query names them (`in:trash`). Results are paged: a
`next_page_token` line appears when more exist; pass it back as
`page_token` with the same query.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `query` | string | required | Gmail search syntax, as typed in the web UI search box |
| `max_results` | integer | 10 | Hits per page, 1 to 100 |
| `page_token` | string | "" | The `next_page_token` of the previous page |
| `include_spam_trash` | boolean | false | Also search Spam and Trash |

```
search(account="work", query="from:billing@example.com newer_than:30d is:unread", max_results=2)
```

```
[18f3a2b4c5d6e7f8] Mon, 05 Oct 2026 09:12:33 +0000 | thread 18f3a2b4c5d6e7f8
  From: Billing <billing@example.com>
  Subj: Your October invoice
  Labels: UNREAD, CATEGORY_UPDATES, INBOX
  Invoice #4821 is ready. Amount due: ...

[18f29c1d0e2f3a4b] Thu, 01 Oct 2026 16:40:02 +0000 | thread 18f29c1d0e2f3a4b
  From: Billing <billing@example.com>
  Subj: Payment received
  Labels: UNREAD, CATEGORY_UPDATES, INBOX
  Thanks, we received your payment of ...

next_page_token: 09876543210987654321
```

Useful queries: `newer_than:7d`, `older_than:1y`, `has:attachment`,
`label:wx-test/phase3`, `subject:(quarterly report)`, `-in:chats`,
`larger:10M`. A message id is the first field in brackets; the thread id
follows the date.

### `search_threads`

Conversations instead of messages, with the same query syntax. Each hit
shows the thread id, the message count, the last message's date, sender
and subject, the union of labels across the thread, and a snippet.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `query` | string | required | Gmail search syntax |
| `max_results` | integer | 10 | Threads per page, 1 to 100 |
| `page_token` | string | "" | The `next_page_token` of the previous page |
| `include_spam_trash` | boolean | false | Also search Spam and Trash |

```
search_threads(account="work", query="label:wx-test", max_results=1)
```

```
[thread 18f3a2b4c5d6e7f8] 4 messages | last Mon, 05 Oct 2026 11:02:10 +0000
  From: you@example.com
  Subj: Re: wx-test: self with attachment
  Labels: SENT, INBOX, wx-test
  Here is the file you asked for ...
```

### `read_message`

One message in full: ids, headers (Cc when present), labels, the
attachment list and the body. The body is the first plain-text part, or
the HTML part when there is none, cut at the server's cap.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `message_id` | string | required | From `search`, `search_threads` or `read_thread` |

```
read_message(account="work", message_id="18f3a2b4c5d6e7f8")
```

```
Message id: 18f3a2b4c5d6e7f8
Thread id: 18f3a2b4c5d6e7f8
Date: Mon, 05 Oct 2026 09:12:33 +0000
From: Billing <billing@example.com>
To: you@example.com
Subject: Your October invoice
Labels: UNREAD, CATEGORY_UPDATES, INBOX
Attachments:
  - part 1: invoice-4821.pdf (application/pdf, 48213 bytes) id=ANGjdJ8...

Hello,

Invoice #4821 is ready. Amount due: ...
```

### `read_thread`

Every message of a conversation, oldest first, each with its id, date,
sender, subject, labels and body. `max_body` caps each body for long
threads; `0` means the server default.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `thread_id` | string | required | From `search` or `search_threads` |
| `max_body` | integer | 0 | Characters per body; 0 = server default (20000) |

```
read_thread(account="work", thread_id="18f3a2b4c5d6e7f8", max_body=200)
```

```
--- [18f3a2b4c5d6e7f8] Mon, 05 Oct 2026 09:12:33 +0000 | Billing <billing@example.com>
Subject: Your October invoice
Labels: CATEGORY_UPDATES, INBOX
Hello,

Invoice #4821 is ready. Amount due: ...
...[truncated]

--- [18f3a2c9d0e1f2a3] Mon, 05 Oct 2026 10:01:12 +0000 | you@example.com
Subject: Re: Your October invoice
Labels: SENT
Paid today, thanks.
```

### `list_attachments`

A message's attachments: part number, file name, MIME type, size and
Gmail's attachment id.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `message_id` | string | required | The message to inspect |

```
list_attachments(account="work", message_id="18f3a2b4c5d6e7f8")
```

```
part 1: invoice-4821.pdf (application/pdf, 48213 bytes) id=ANGjdJ8...
part 2: terms.txt (text/plain, 1204 bytes) id=ANGjdJ9...
```

**Attachment ids rotate.** Gmail returns a different `attachmentId` for
the same part on every read, so an id copied from `read_message` may not
match the one `list_attachments` shows a moment later. The part number is
stable: pass it (or the file name) to `download_attachment`. An older id
still downloads; the server falls back to it when nothing else matches.

### `download_attachment`

Saves one attachment under the server's downloads directory
(`~/.wx-gmail-mcp/downloads/`, created with mode 700; files get mode
600) and returns the path. Nothing outside that directory can be written:
`filename` is relative, may use subfolders and may not escape it.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `message_id` | string | required | The message holding the attachment |
| `attachment` | string | "" | Part number, file name or attachment id; optional when the message has exactly one |
| `filename` | string | "" | Save under this relative name instead of the attachment's own |
| `overwrite` | boolean | false | Replace an existing file of that name |

```
download_attachment(account="work", message_id="18f3a2b4c5d6e7f8", attachment="1")
```

```
Saved ~/.wx-gmail-mcp/downloads/invoice-4821.pdf (48213 bytes, application/pdf).
```

An existing file is an error unless `overwrite=true`. File names are
sanitized (`:` becomes `_`, path separators are dropped).

## Labels

Gate: none. Scope: base. System labels (`INBOX`, `UNREAD`, `STARRED`,
`IMPORTANT`, `SENT`, `TRASH`, `SPAM`, the `CATEGORY_*` set and so on)
can be used in every tool but never created, renamed or deleted. Gmail
nests labels by name alone: `Parent/Child` is nested under `Parent`.

### `list_labels`

All labels as `id: name [type]`, system labels first. Counts are opt-in
because they cost one API call per label.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `include_counts` | boolean | false | Add message, unread and thread counts per label |

```
list_labels(account="work")
```

```
CATEGORY_UPDATES: CATEGORY_UPDATES [system]
INBOX: INBOX [system]
SENT: SENT [system]
UNREAD: UNREAD [system]
Label_12: wx-test [user]
Label_13: wx-test/phase3 [user]
```

### `create_label`

Creates a user label. A nested name creates missing parents after the
label itself, so a rejected name leaves nothing behind. Colors are a pair
of `#rrggbb` values from Gmail's label palette (Gmail refuses others);
visibility values are Gmail's own.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `name` | string | required | The label name; `Parent/Child` nests |
| `color_background` | string | "" | Hex color; give both colors or neither |
| `color_text` | string | "" | Hex color |
| `label_list_visibility` | string | "" | `labelShow`, `labelShowIfUnread` or `labelHide` |
| `message_list_visibility` | string | "" | `show` or `hide` |

```
create_label(account="work", name="wx-test/phase3", color_background="#16a765", color_text="#ffffff")
```

```
Created label 'wx-test/phase3' (id Label_13). Also created parent wx-test.
```

A name that already exists (case-insensitive) is refused with the
existing id.

### `update_label`

Renames a user label, moves it (renaming `A/B` to `C/B`), or changes its
colors or visibility. Empty fields keep their value. After a rename the
result says what happened to labels nested under the old name: Gmail
moves them with the parent in most cases, and the tool reports from a
fresh listing rather than assuming.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `label` | string | required | Name or id of the label to change |
| `new_name` | string | "" | The new name |
| `color_background` | string | "" | Hex color; give both colors or neither |
| `color_text` | string | "" | Hex color |
| `label_list_visibility` | string | "" | `labelShow`, `labelShowIfUnread` or `labelHide` |
| `message_list_visibility` | string | "" | `show` or `hide` |

```
update_label(account="work", label="wx-test/phase3", new_name="wx-test/phase3b")
```

```
Updated label 'wx-test/phase3' (id Label_13): name 'wx-test/phase3b'.
```

### `delete_label`

Deletes a user label. Its messages stay in the mailbox with their other
labels; nothing is trashed. The tool is always on because it needs only
the base scope and removes no message, but it does strip the label from
every message in one call with no dry run, so check with `search
label:...` first when that matters.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `label` | string | required | Name or id of the user label |

```
delete_label(account="work", label="wx-test")
```

```
Deleted label 'wx-test' (id Label_12); no messages were removed. Its nested labels were deleted with it.
```

## Organize

Gate: none. Scope: base. These tools relabel mail. None of them adds
`TRASH` or `SPAM`: making mail disappear is the trash tools' job, behind
`WX_GMAIL_ALLOW_DELETE`. Removing those labels is allowed. Id-list tools
run `messages.batchModify` in chunks of 1000.

### `modify_labels`

Adds and removes labels on a list of messages in one batch. Give at least
one label to add or remove.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `message_ids` | list of strings | required | Up to 1000 message ids |
| `add` | list of strings | [] | Labels to add, by name or id |
| `remove` | list of strings | [] | Labels to remove, by name or id |

```
modify_labels(account="work", message_ids=["18f3a2b4c5d6e7f8", "18f29c1d0e2f3a4b"], add=["wx-test/phase3"], remove=["INBOX", "UNREAD"])
```

```
Updated 2 messages: added wx-test/phase3; removed INBOX, UNREAD.
```

```
modify_labels(account="work", message_ids=["18f3a2b4c5d6e7f8"], add=["TRASH"])
```

```
Error: modify_labels does not add TRASH: that makes mail disappear. Use the trash tools, which register only with WX_GMAIL_ALLOW_DELETE=true.
```

### `mark_read`

Removes `UNREAD` from up to 1000 messages.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `message_ids` | list of strings | required | Up to 1000 message ids |

```
mark_read(account="work", message_ids=["18f3a2b4c5d6e7f8"])
```

```
Marked 1 message read.
```

### `mark_unread`

Adds `UNREAD` to up to 1000 messages.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `message_ids` | list of strings | required | Up to 1000 message ids |

```
mark_unread(account="work", message_ids=["18f3a2b4c5d6e7f8", "18f29c1d0e2f3a4b"])
```

```
Marked 2 messages unread.
```

### `archive`

Removes `INBOX` from up to 1000 messages. Nothing is deleted; the mail
stays under All Mail and its other labels.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `message_ids` | list of strings | required | Up to 1000 message ids |

```
archive(account="work", message_ids=["18f3a2b4c5d6e7f8"])
```

```
Archived 1 message.
```

### `modify_thread_labels`

Adds and removes labels on whole conversations, every message included,
through `threads.modify`. There is no batch form, so each thread is one
API call and the cap is 100. A failure midway reports how many threads
were done.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `thread_ids` | list of strings | required | Up to 100 thread ids |
| `add` | list of strings | [] | Labels to add, by name or id |
| `remove` | list of strings | [] | Labels to remove, by name or id |

```
modify_thread_labels(account="work", thread_ids=["18f3a2b4c5d6e7f8"], add=["wx-test"], remove=["UNREAD"])
```

```
Updated 1 thread: added wx-test; removed UNREAD.
```

### `modify_by_query`

Relabels every message matching a Gmail search. The dry run is the
default: it counts the matches and shows a five-message sample, and
nothing changes until the same call runs with `dry_run=false`. More than
`limit` matches is an error, so a typo in the query cannot relabel the
whole mailbox; raise `limit` (at most 100000) on purpose. Spam and Trash
are searched only when the query names them (`in:trash`). The engine is
the same one `create_filter(apply=true)` uses.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `query` | string | required | Gmail search syntax |
| `add` | list of strings | [] | Labels to add, by name or id |
| `remove` | list of strings | [] | Labels to remove, by name or id |
| `dry_run` | boolean | true | Count and sample only |
| `limit` | integer | 5000 | Fail when more messages match |

```
modify_by_query(account="work", query="from:no-reply@accounts.example.com newer_than:365d", add=["wx-test/phase3"], remove=["INBOX"])
```

```
Dry run: 2 messages match 'from:no-reply@accounts.example.com newer_than:365d'. Would have added wx-test/phase3; removed INBOX.
Sample:
  [18f3a2b4c5d6e7f8] Mon, 05 Oct 2026 09:12:33 +0000 | Accounts <no-reply@accounts.example.com> | Security alert
  [18f29c1d0e2f3a4b] Thu, 01 Oct 2026 16:40:02 +0000 | Accounts <no-reply@accounts.example.com> | New sign-in
Run again with dry_run=false to apply.
```

```
modify_by_query(account="work", query="from:no-reply@accounts.example.com newer_than:365d", add=["wx-test/phase3"], remove=["INBOX"], dry_run=false)
```

```
Modified 2 messages matching 'from:no-reply@accounts.example.com newer_than:365d': added wx-test/phase3; removed INBOX.
Sample:
  [18f3a2b4c5d6e7f8] Mon, 05 Oct 2026 09:12:33 +0000 | Accounts <no-reply@accounts.example.com> | Security alert
  [18f29c1d0e2f3a4b] Thu, 01 Oct 2026 16:40:02 +0000 | Accounts <no-reply@accounts.example.com> | New sign-in
```

A failure partway through the batches reports how many messages were
modified; a re-run finishes the rest (messages already modified are
unaffected).

## Trash and delete

Gate: `WX_GMAIL_ALLOW_DELETE`. Scope: `https://mail.google.com/` (the
full mail scope). Trash and untrash would work with the base scope, but
every tool that makes mail disappear sits behind this one gate on
purpose, so an account opts in explicitly. Messages or whole threads are
chosen with `kind`; each id is one API call and the cap is 100 per call.
There is no empty-trash tool and no query form for permanent deletion.

### `trash`

Moves messages or threads to Trash, where Gmail purges them after 30
days. Reversible with `untrash`. Trash removes `INBOX` and adds `TRASH`.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `ids` | list of strings | required | Up to 100 message or thread ids |
| `kind` | string | "message" | `message` or `thread` |

```
trash(account="work", ids=["18f3a2b4c5d6e7f8", "18f29c1d0e2f3a4b"])
```

```
Trashed 2 messages.
```

### `untrash`

Moves messages or threads out of Trash. **Untrash does not restore
INBOX.** Gmail removes `TRASH` and the message goes back to its other
labels only, so a trashed inbox message reappears under All Mail, not in
the inbox. Add `INBOX` with `modify_labels` afterwards if wanted.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `ids` | list of strings | required | Up to 100 message or thread ids |
| `kind` | string | "message" | `message` or `thread` |

```
untrash(account="work", ids=["18f3a2b4c5d6e7f8"])
modify_labels(account="work", message_ids=["18f3a2b4c5d6e7f8"], add=["INBOX"])
```

```
Untrashed 1 message.
Updated 1 message: added INBOX.
```

### `delete_permanently`

Deletes messages or threads for good. Guardrails, all server-side:

- explicit ids only, at most 100 per call, no query form;
- only mail already in Trash is accepted unless `require_trashed=false`
  (a thread must be entirely in Trash);
- every item's date, sender and subject are fetched first and returned
  as the **audit trail**, and exactly those audited messages are deleted
  in one `messages.batchDelete`, for threads too (a reply that arrives
  between the audit and the delete is not swept away);
- the dry run is the default and shows the trail without deleting.

With `require_trashed=false`, a thread that holds no messages is skipped
and the result says so (`... 2 threads (1 empty thread skipped)`).

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `ids` | list of strings | required | Up to 100 message or thread ids |
| `kind` | string | "message" | `message` or `thread` |
| `require_trashed` | boolean | true | Refuse anything not in Trash |
| `dry_run` | boolean | true | Show the audit trail only |

```
delete_permanently(account="work", ids=["18f3a2b4c5d6e7f8"], kind="thread")
```

```
Dry run: 1 thread would be permanently deleted. Run again with dry_run=false to delete; there is no undo.
[thread 18f3a2b4c5d6e7f8] 2 messages
  [18f3a2b4c5d6e7f8] Mon, 05 Oct 2026 09:12:33 +0000 | From: you@example.com | Subj: wx-test: plain message
  [18f3a2c9d0e1f2a3] Mon, 05 Oct 2026 10:01:12 +0000 | From: you@example.com | Subj: Re: wx-test: plain message
```

```
delete_permanently(account="work", ids=["18f3a2b4c5d6e7f8"], kind="thread", dry_run=false)
```

```
Permanently deleted 1 thread:
[thread 18f3a2b4c5d6e7f8] 2 messages
  [18f3a2b4c5d6e7f8] Mon, 05 Oct 2026 09:12:33 +0000 | From: you@example.com | Subj: wx-test: plain message
  [18f3a2c9d0e1f2a3] Mon, 05 Oct 2026 10:01:12 +0000 | From: you@example.com | Subj: Re: wx-test: plain message
```

An item outside Trash is refused before anything happens:

```
Error: 2 messages are not in Trash: 18f3a2b4c5d6e7f8, 18f29c1d0e2f3a4b. Trash them first, or pass require_trashed=false to delete them anyway. Nothing was deleted.
```

If the `batchDelete` call itself fails, the result says the items may or
may not be gone and lists the trail; a retry re-audits and reports a 404
for anything already deleted. The hint for a bad id arrives from the
audit fetch (`HTTP 400: Invalid id value`) before any delete.

## Drafts

Gate: none. Scope: base. Drafts need only the base scope; sending one is
`send_draft`, behind the sending gate. Recipients take any RFC 5322 form
(`Name <addr@example.com>, other@example.com`); a field that does not
parse is an error rather than dropped. Attachments are file names inside
`~/.wx-gmail-mcp/outbox/` (subfolders allowed, nothing outside it) and
may total up to 25 MB per message.

### `create_draft`

Creates a draft; nothing is sent. `html` is an alternative to the plain
`body`, or the whole body when `body` is empty (then the message is a
single `text/html` part).

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `to` | string | required | Recipients |
| `subject` | string | required | Subject |
| `body` | string | required | Plain-text body (may be empty when `html` is given) |
| `cc` | string | "" | Cc recipients |
| `bcc` | string | "" | Bcc recipients |
| `html` | string | "" | HTML body or alternative |
| `attachments` | list of strings | [] | File names in the outbox directory |
| `reply_to` | string | "" | Reply-To header |

```
create_draft(account="work", to="someone@example.com", subject="wx-test: report", body="See attached.", attachments=["report.pdf"])
```

```
Draft created. draft id=r-1234567890123456789 message id=18f3a2d5e6f7a8b9
```

Draft ids are `r` followed by a signed number (`r-4556...` or `r8914...`);
the draft's message has its own id.

### `list_drafts`

Drafts newest first, with ids, date, recipient and subject; paged.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `query` | string | "" | Gmail search syntax, matched against the drafts |
| `max_results` | integer | 20 | Drafts per page, 1 to 100 |
| `page_token` | string | "" | The `next_page_token` of the previous page |

```
list_drafts(account="work")
```

```
[draft r-1234567890123456789] message 18f3a2d5e6f7a8b9 | thread 18f3a2d5e6f7a8b9 | Mon, 05 Oct 2026 12:00:00 +0000
  To: someone@example.com
  Subj: wx-test: report
```

A draft deleted between the listing and the detail fetch shows as
`(gone)`.

### `get_draft`

One draft: ids, headers (Cc, Bcc, Reply-To and In-Reply-To when
present), attachments and body.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `draft_id` | string | required | From `create_draft` or `list_drafts` |
| `max_body` | integer | 0 | Characters of body; 0 = server default |

```
get_draft(account="work", draft_id="r-1234567890123456789")
```

```
Draft id: r-1234567890123456789
Message id: 18f3a2d5e6f7a8b9
Thread id: 18f3a2d5e6f7a8b9
Date: Mon, 05 Oct 2026 12:00:00 +0000
To: someone@example.com
Subject: wx-test: report
Attachments:
  - part 1: report.pdf (application/pdf, 10240 bytes) id=ANGjdJ8...

See attached.
```

### `update_draft`

Replaces a draft's content with the given fields, the same ones as
`create_draft`. Anything not given is dropped, attachments included. A
reply draft keeps its thread id, `In-Reply-To` and `References`, so it
stays in its conversation as long as the subject still matches. The
draft gets a new message id; the draft id and thread id stay.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `draft_id` | string | required | The draft to replace |
| `to` | string | required | Recipients |
| `subject` | string | required | Subject |
| `body` | string | required | Plain-text body |
| `cc` | string | "" | Cc recipients |
| `bcc` | string | "" | Bcc recipients |
| `html` | string | "" | HTML body or alternative |
| `attachments` | list of strings | [] | File names in the outbox directory |
| `reply_to` | string | "" | Reply-To header |

```
update_draft(account="work", draft_id="r-1234567890123456789", to="someone@example.com", subject="wx-test: report (v2)", body="Second version attached.", attachments=["report-v2.pdf"])
```

```
Draft updated. draft id=r-1234567890123456789 message id=18f3a2e1f2a3b4c5
```

### `delete_draft`

Deletes unsent drafts by id, one API call each, up to 100. Permanent:
Gmail has no Trash for drafts. The tool is always on because it needs
only the base scope and never touches sent or received mail.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `draft_ids` | list of strings | required | Up to 100 draft ids |

```
delete_draft(account="work", draft_ids=["r-1234567890123456789"])
```

```
Deleted 1 draft.
```

## Send

Gate: `WX_GMAIL_ALLOW_SENDING`. Scope: `gmail.send`. Every tool here
sends immediately with no confirmation step: the model should confirm
with the user before calling. Recipients and attachments follow the
rules in [Drafts](#drafts). Messages are uploaded as `message/rfc822`
media, so attachments may total 25 MB.

### `send_message`

Sends a new message from the account.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `to` | string | required | Recipients |
| `subject` | string | required | Subject |
| `body` | string | required | Plain-text body (may be empty when `html` is given) |
| `cc` | string | "" | Cc recipients |
| `bcc` | string | "" | Bcc recipients |
| `html` | string | "" | HTML body or alternative |
| `attachments` | list of strings | [] | File names in the outbox directory |
| `reply_to` | string | "" | Reply-To header |

```
send_message(account="work", to="you@example.com", subject="wx-test: hello", body="A test from the server.")
```

```
Sent. message id=18f3a2f0a1b2c3d4 thread id=18f3a2f0a1b2c3d4
```

### `send_draft`

Sends a draft exactly as stored; the draft disappears on success. The
result repeats the recipient and subject it had, so the model can show
what went out.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `draft_id` | string | required | The draft to send |

```
send_draft(account="work", draft_id="r-1234567890123456789")
```

```
Sent draft r-1234567890123456789 (To: someone@example.com | Subj: wx-test: report). message id=18f3a2f9b0c1d2e3 thread id=18f3a2d5e6f7a8b9
```

### `reply`

Replies in the original's conversation: Gmail's thread id plus
`In-Reply-To` and `References`, subject prefixed with `Re:` unless it
already is. Recipients follow the web UI: the original's `Reply-To`, else
its `From`; when the account itself sent the original, its original
recipients. `reply_all` adds the other `To` and `Cc` addresses, minus the
account and anyone already in `To`, each once. The original text is
quoted under the reply by default, HTML rendered as text. Plain text
only; outbox attachments are allowed.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `message_id` | string | required | The message to answer |
| `body` | string | required | The reply text |
| `reply_all` | boolean | false | Copy the other recipients |
| `quote` | boolean | true | Append the original as a quoted block |
| `cc` | string | "" | Extra Cc recipients |
| `bcc` | string | "" | Bcc recipients |
| `attachments` | list of strings | [] | File names in the outbox directory |

```
reply(account="work", message_id="18f3a2b4c5d6e7f8", body="Paid today, thanks.", quote=false)
```

```
Replied to 18f3a2b4c5d6e7f8 (To: Billing <billing@example.com> | Subj: Re: Your October invoice). message id=18f3a2c9d0e1f2a3 thread id=18f3a2b4c5d6e7f8.
```

An original longer than 200000 characters is quoted cut, and the result
says so; forward it with `as_attachment=true` to pass on the whole
message.

### `forward`

Forwards a message in its conversation on the sender's side (the
recipient sees a new thread), subject prefixed with `Fwd:`. By default
the original text follows `body` under a forwarded-message header and
the original's attachments are re-attached. `as_attachment=true` sends
the complete original as a `message/rfc822` file named after its subject
instead, with any `Bcc` header of a sent original stripped. Plain text
only.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `message_id` | string | required | The message to forward |
| `to` | string | required | Recipients |
| `body` | string | "" | Text above the forwarded message |
| `cc` | string | "" | Cc recipients |
| `bcc` | string | "" | Bcc recipients |
| `as_attachment` | boolean | false | Attach the original as an `.eml` file instead of quoting |
| `include_attachments` | boolean | true | Re-attach the original's attachments when quoting |
| `attachments` | list of strings | [] | Extra files from the outbox directory |

```
forward(account="work", message_id="18f3a2b4c5d6e7f8", to="someone@example.com", body="FYI, invoice below.")
```

```
Forwarded 18f3a2b4c5d6e7f8 (To: someone@example.com | Subj: Fwd: Your October invoice). message id=18f3a301a2b3c4d5 thread id=18f3a2b4c5d6e7f8.
```

The original's declared sizes are checked before anything is fetched:
attachments over 25 MB in total are refused with a hint to use
`include_attachments=false`, and an original too large to attach whole is
refused with a hint to forward it quoted.

## Filters

Gate: `WX_GMAIL_ALLOW_SETTINGS`. Scope: `gmail.settings.basic`. The
settings endpoints accept only this scope: an account that granted the
full mail scope but not this one is still refused. Filters are rendered
with label names and with the Gmail search equivalent to their criteria,
the same translation the web UI uses for "also apply filter to matching
conversations". There is no forward action: it needs the sharing scope,
which the server never requests.

### `list_filters`

Every filter: id, what it matches, the equivalent search, what it does.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |

```
list_filters(account="work")
```

```
2 filters:
ANe1BmgExampleFilterId00000000000000001
  match: from "news@example.com"
  query: from:(news@example.com)
  do: add Newsletters; remove INBOX
ANe1BmgExampleFilterId00000000000000002
  match: has words "unsubscribe", has attachment
  query: unsubscribe has:attachment
  do: remove IMPORTANT
```

### `get_filter`

One filter by id, in the same form.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `filter_id` | string | required | From `list_filters` or `create_filter` |

```
get_filter(account="work", filter_id="ANe1BmgExampleFilterId00000000000000001")
```

```
ANe1BmgExampleFilterId00000000000000001
  match: from "news@example.com"
  query: from:(news@example.com)
  do: add Newsletters; remove INBOX
```

### `create_filter`

Creates a filter from flat flags. At least one criterion and one action
are required. Criteria map to Gmail's `FilterCriteria`; the shortcut
flags map to the web UI's checkboxes:

| Shortcut | Does |
|---|---|
| `skip_inbox` | removes `INBOX` (Archive it) |
| `mark_read` | removes `UNREAD` |
| `star` | adds `STARRED` |
| `always_important` | adds `IMPORTANT` |
| `never_important` | removes `IMPORTANT` |
| `never_spam` | removes `SPAM` |
| `category` | adds the matching `CATEGORY_*` label |
| `delete` | adds `TRASH`; needs `WX_GMAIL_ALLOW_DELETE` and the full scope on the account |

A filter catches future mail only. `apply=true` also relabels existing
matches the way the web UI's checkbox does: the criteria are translated
to a search, the matches are listed (Spam and Trash excluded, up to
`apply_limit`) and relabeled in batches. The filter is created first and
applied second, so mail arriving in between is caught. The API works per
message where the UI works per conversation. The dry run is the default:
it shows the filter, the labels it would create and the matching mail,
and changes nothing.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `from_` | string | "" | Sender matches (Gmail `from:` semantics) |
| `to` | string | "" | Recipient matches |
| `subject` | string | "" | Subject contains |
| `query` | string | "" | Has the words (Gmail search syntax) |
| `negated_query` | string | "" | Doesn't have the words |
| `has_attachment` | boolean | false | Only mail with attachments |
| `exclude_chats` | boolean | false | Skip chat messages |
| `size` | integer | 0 | Size in bytes; 0 = no size criterion |
| `size_comparison` | string | "larger" | `larger` or `smaller` |
| `add_labels` | list of strings | [] | Labels to add, by name or id |
| `remove_labels` | list of strings | [] | Labels to remove, by name or id |
| `create_missing_labels` | boolean | false | Create unknown names in `add_labels` |
| `skip_inbox` | boolean | false | Shortcut, see above |
| `mark_read` | boolean | false | Shortcut |
| `star` | boolean | false | Shortcut |
| `always_important` | boolean | false | Shortcut |
| `never_important` | boolean | false | Shortcut |
| `never_spam` | boolean | false | Shortcut |
| `category` | string | "" | `personal`, `social`, `promotions`, `updates` or `forums` |
| `delete` | boolean | false | Shortcut; only with the delete gate |
| `apply` | boolean | false | Also relabel existing matches |
| `apply_limit` | integer | 5000 | Fail the apply above this many matches (at most 100000) |
| `dry_run` | boolean | true | Show the filter and matches, change nothing |

```
create_filter(account="work", from_="news@example.com", add_labels=["Newsletters"], create_missing_labels=true, skip_inbox=true, apply=true)
```

```
Dry run: create the filter.
  match: from "news@example.com"
  query: from:(news@example.com)
  do: add Newsletters; remove INBOX
Labels to create: Newsletters.
Existing mail: 14 messages match 'from:(news@example.com)'.
Sample:
  [18f3a2b4c5d6e7f8] Mon, 05 Oct 2026 09:12:33 +0000 | News <news@example.com> | This week
  [18f29c1d0e2f3a4b] Mon, 28 Sep 2026 09:10:51 +0000 | News <news@example.com> | Last week
  ...
Run again with dry_run=false to create the filter and apply it to them.
```

```
create_filter(account="work", from_="news@example.com", add_labels=["Newsletters"], create_missing_labels=true, skip_inbox=true, apply=true, dry_run=false)
```

```
Created filter ANe1BmgExampleFilterId00000000000000001.
  match: from "news@example.com"
  query: from:(news@example.com)
  do: add Newsletters; remove INBOX
Created labels: Newsletters (Label_14).
Existing mail: Modified 14 messages matching 'from:(news@example.com)': added Newsletters; removed INBOX.
Sample:
  [18f3a2b4c5d6e7f8] Mon, 05 Oct 2026 09:12:33 +0000 | News <news@example.com> | This week
  ...
```

Behaviors worth knowing:

- `add_labels=["TRASH"]` is refused with a pointer to `delete`; a filter
  never adds `SPAM` (Gmail has no such action).
- Without `WX_GMAIL_ALLOW_DELETE` on the server, `delete=true` is refused
  before anything is created; with it, the account must also have
  granted the full scope.
- If the apply fails after the filter exists, the result still starts
  with `Created filter ...` so the call is not repeated (that would make
  a duplicate), and names how to finish: `modify_by_query` on the shown
  query, or the trash tools for a `delete` filter.
- With `apply=true` and `category`, existing mail gains the new
  `CATEGORY_*` label without losing its current category; the web UI may
  differ.
- Gmail refuses a filter identical to an existing one (`Filter already
  exists`).

### `delete_filter`

Deletes filters by id, up to 100, each shown as it was before deletion.
The mail a filter labelled is untouched. A failure midway reports how
many were deleted.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `filter_ids` | list of strings | required | Up to 100 filter ids |

```
delete_filter(account="work", filter_ids=["ANe1BmgExampleFilterId00000000000000001"])
```

```
Deleted 1 filter:
ANe1BmgExampleFilterId00000000000000001
  match: from "news@example.com"
  query: from:(news@example.com)
  do: add Newsletters; remove INBOX
```

### `replace_filter`

Gmail has no filter update, so this creates a new filter from the flags,
then deletes the old one, then applies if asked. The new filter is
described in full by the same flags as `create_filter`; nothing is
inherited from the old one. The dry run (default) shows the current and
the new filter side by side and changes nothing.

**An identical replacement is refused by Gmail** (`Filter already
exists`) before anything is deleted, so re-running a replace with the
same flags is safe. If the new filter is created but deleting the old one
fails, the result says both exist and names the old id for
`delete_filter`.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `filter_id` | string | required | The filter to replace |
| `from_` | string | "" | As in `create_filter` |
| `to` | string | "" | As in `create_filter` |
| `subject` | string | "" | As in `create_filter` |
| `query` | string | "" | As in `create_filter` |
| `negated_query` | string | "" | As in `create_filter` |
| `has_attachment` | boolean | false | As in `create_filter` |
| `exclude_chats` | boolean | false | As in `create_filter` |
| `size` | integer | 0 | As in `create_filter` |
| `size_comparison` | string | "larger" | As in `create_filter` |
| `add_labels` | list of strings | [] | As in `create_filter` |
| `remove_labels` | list of strings | [] | As in `create_filter` |
| `create_missing_labels` | boolean | false | As in `create_filter` |
| `skip_inbox` | boolean | false | As in `create_filter` |
| `mark_read` | boolean | false | As in `create_filter` |
| `star` | boolean | false | As in `create_filter` |
| `always_important` | boolean | false | As in `create_filter` |
| `never_important` | boolean | false | As in `create_filter` |
| `never_spam` | boolean | false | As in `create_filter` |
| `category` | string | "" | As in `create_filter` |
| `delete` | boolean | false | As in `create_filter` |
| `apply` | boolean | false | As in `create_filter` |
| `apply_limit` | integer | 5000 | As in `create_filter` |
| `dry_run` | boolean | true | Show both filters, change nothing |

```
replace_filter(account="work", filter_id="ANe1BmgExampleFilterId00000000000000001", from_="news@example.com", add_labels=["Newsletters"], skip_inbox=true, mark_read=true)
```

```
Dry run: replace the filter.
Current:
  match: from "news@example.com"
  query: from:(news@example.com)
  do: add Newsletters; remove INBOX
New:
  match: from "news@example.com"
  query: from:(news@example.com)
  do: add Newsletters; remove INBOX, UNREAD
Run again with dry_run=false to replace the filter.
```

```
replace_filter(account="work", filter_id="ANe1BmgExampleFilterId00000000000000001", from_="news@example.com", add_labels=["Newsletters"], skip_inbox=true, mark_read=true, dry_run=false)
```

```
Replaced filter ANe1BmgExampleFilterId00000000000000001 with ANe1BmgExampleFilterId00000000000000003.
  match: from "news@example.com"
  query: from:(news@example.com)
  do: add Newsletters; remove INBOX, UNREAD
```

## Settings

Gate: `WX_GMAIL_ALLOW_SETTINGS`. Scope: `gmail.settings.basic` (the full
mail scope does not cover it). Forwarding addresses, auto-forwarding,
delegates and alias creation are deliberately absent: they need the
sharing scope, which the server never requests.

### `get_vacation`

The vacation (out of office) responder as stored: on or off, subject,
message, period and who gets replies. Gmail stores the period as
instants; a midnight reads as a first or last day, anything else with
its time and zone. Days are shown in the machine's zone unless an IANA
`timezone` is given.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `timezone` | string | "" | IANA zone for the dates shown, like `Europe/Paris` |

```
get_vacation(account="work")
```

```
Vacation responder: on
  subject: Out of office
  html: <div>Back on Thursday.</div>
  first day: 2026-10-05
  last day: 2026-10-07
  time zone: PDT (local)
  only to: contacts
```

A responder that was never configured reads
`Vacation responder: off (nothing saved)`.

### `set_vacation`

**Replaces the whole responder.** Gmail's `updateVacation` is a PUT with
no partial form: every field left out is cleared, including the dates.
Call `get_vacation` first and pass back what must stay. An enabled
responder needs a message. **Gmail keeps only the HTML:** when both
`body` and `html` are given, the plain text is dropped silently, so
`get_vacation` afterwards shows `html` only.

`start_date` and `end_date` are the first and last day inclusive,
`YYYY-MM-DD`, converted to midnight instants in the machine's zone or
the IANA `timezone`. Without dates the responder runs until turned off.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `enabled` | boolean | required | Turn replies on or off |
| `subject` | string | "" | Reply subject |
| `body` | string | "" | Plain-text reply (dropped when `html` is given) |
| `html` | string | "" | HTML reply |
| `start_date` | string | "" | First day, `YYYY-MM-DD` |
| `end_date` | string | "" | Last day, `YYYY-MM-DD` |
| `contacts_only` | boolean | false | Reply only to contacts |
| `domain_only` | boolean | false | Reply only within the Workspace domain |
| `timezone` | string | "" | IANA zone for the dates |

```
set_vacation(account="work", enabled=true, subject="Out of office", html="<div>Back on Thursday.</div>", start_date="2026-10-05", end_date="2026-10-07", contacts_only=true, timezone="Europe/Paris")
```

```
Updated the vacation responder.
Vacation responder: on
  subject: Out of office
  html: <div>Back on Thursday.</div>
  first day: 2026-10-05
  last day: 2026-10-07
  time zone: Europe/Paris
  only to: contacts
```

To turn it off and clear everything, as the web UI's "off" does:

```
set_vacation(account="work", enabled=false)
```

```
Updated the vacation responder.
Vacation responder: off
```

Validation happens before any call: reversed dates, an enabled responder
without a message, an unknown zone.

### `list_send_as`

The account's send-as identities: the primary address and any aliases,
each with display name, reply-to, `primary`/`default`/`alias` flags,
verification status (aliases) and the signature exactly as stored, HTML
included, so it can be restored byte for byte.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |

```
list_send_as(account="work")
```

```
1 send-as identity:
you@example.com (primary, default)
  name: You Example
  signature: <div>You Example</div><div>Example Co</div>
```

### `set_signature`

Sets the signature of one identity through `sendAs.patch`, touching
nothing else. `signature` is HTML (Gmail sanitizes it); an empty or
whitespace-only string removes it. The primary identity is the default
target.

**Aliases on a personal account are refused.** Google allows
`sendAs.patch` on an alias only for Workspace service accounts with
domain-wide delegation; with `send_as_email` naming an alias of a
personal Gmail account, expect a refusal from Gmail.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `account` | string | required | Account alias |
| `signature` | string | required | HTML signature; empty removes it |
| `send_as_email` | string | "" | An alias address from `list_send_as`; default: the primary |

```
set_signature(account="work", signature="<div>You Example</div><div>Example Co</div>")
```

```
Set the signature of you@example.com.
you@example.com (primary, default)
  name: You Example
  signature: <div>You Example</div><div>Example Co</div>
```

```
set_signature(account="work", signature="")
```

```
Cleared the signature of you@example.com.
you@example.com (primary, default)
  name: You Example
  signature: (none)
```

## Errors

Every tool returns errors as text rather than raising, so the model can
read them:

- `Error: Account 'home' has not granted the send scope. Set
  WX_GMAIL_ALLOW_SENDING=true and re-authorize with: ...` when a gated
  tool is called for an account that lacks the scope.
- `Error: No token for account 'x'. Known accounts: work, home. ...` for
  an unknown alias.
- `Gmail API error: HTTP 400: Invalid id value` for a bad id; `HTTP 404`
  for something gone.
- `Error: ...` with the validation message for bad parameters, before
  any API call.
