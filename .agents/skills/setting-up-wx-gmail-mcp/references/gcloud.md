# Google Cloud: gcloud and console steps

wx-gmail-mcp needs its own Google Cloud project with the Gmail API on,
an OAuth consent screen and one Desktop app OAuth client. The project
and the API can be done with `gcloud`; the consent screen and the client
are console only (Google offers no API for OAuth clients). Every
command below names the project explicitly, so the user's default
project is never touched.

## With gcloud

```bash
gcloud auth list                              # an ACTIVE account is needed
gcloud projects describe <project-id>         # exists?
gcloud projects create <project-id> --name=<project-id>
gcloud services enable gmail.googleapis.com --project=<project-id>
gcloud services list --enabled --project=<project-id> \
  --filter=config.name:gmail.googleapis.com
```

`scripts/gcloud_project.py <project-id> --create --enable` runs exactly
these, idempotently, and prints the console URLs for the rest. Project
ids are global and permanent: if `wx-gmail-mcp` is taken, use a suffix
such as `wx-gmail-mcp-<name>`. The script sets the display name to the
id: two projects both named "wx-gmail-mcp" are indistinguishable in
the console header. The Gmail API needs no billing account.

Not logged in: `gcloud auth login` opens a browser (**[you]**).
Not installed: skip to the console; nothing below needs gcloud.

## Console steps

All pages take `?project=<project-id>`; `scripts/gcloud_project.py
<project-id> --urls` prints them filled in. The user must be signed in
as the Google account that owns the project; the console may show a
different `authuser=` index in the URL, so check the account shown on
the page, not the index.

### Project (without gcloud)

https://console.cloud.google.com/projectcreate: name `wx-gmail-mcp`,
no organization, Create. Then enable the API from
`https://console.cloud.google.com/apis/library/gmail.googleapis.com?project=<project-id>`
(Enable).

### Consent screen (Google Auth Platform)

A new project shows a "Get started" wizard at
`https://console.cloud.google.com/auth/overview?project=<project-id>`:

1. App information: app name `WX Gmail MCP` (any name; it need not be
   unique across projects, but a distinct name tells two consent
   screens apart), user support email: picked from a dropdown of the
   signed-in account's addresses.
2. Audience: **External**.
3. Contact information: the user's address, typed.
4. Finish: a checkbox to agree to the Google API Services User Data
   Policy. **[you]**: the user ticks it and clicks Continue, then
   Create. The wizard keeps nothing until Create: a reload empties
   every field.

Then, at `https://console.cloud.google.com/auth/audience?project=<project-id>`,
under **Test users**, Add users: every Gmail address that will be
authorized. The first Save may only turn the typed address into a chip;
click Save again until the list shows it. The app stays in **Testing**.

Scopes (Data Access page): none. The server requests its scopes at
runtime, and Google shows them on the consent screen.

### Desktop client

`https://console.cloud.google.com/auth/clients?project=<project-id>`,
Create client:

- Application type: **Desktop app**.
- Name: `wx-gmail-mcp-desktop`.
- "This client will be used by an AI-powered agent": tick it. See the
  note below.
- Create. The confirmation dialog shows the client id and, once only,
  the secret. **[you]**: **Download JSON** (a download is the user's
  action) and OK. The file is `client_secret_<id>.json`, about 400
  bytes, in the browser's download folder, which may be a per-site
  subfolder rather than `~/Downloads` (Chrome put it under
  `~/Downloads/Chrome/<profile>/<site>/` in testing). Give
  `scripts/install_client_json.py` that path. The JSON can be
  downloaded again later from the client's row on the Clients page.

The client JSON holds the client id and secret. It goes to
`<home>/oauth_client.json` (step 4 of the skill) and nowhere else.

### The "AI-powered agent" option

The client form has a checkbox "This client will be used by an
AI-powered agent". Its help text in the console (2026-10-05) reads:
"Designates this client for AI agents that take actions on behalf of
users. If your application supports both AI agent workflows and
standard user features, use separate OAuth clients for each." Google's
public OAuth documentation does not describe the option.

That is what wx-gmail-mcp is, so tick it. It is a declaration to
Google, not a switch: with it ticked, the Desktop client type, the
loopback redirect, the consent screens and the granted scopes were
identical to an unticked client in a side-by-side test (Testing
status, a test user, base scopes). A client created without it works
the same today. Whatever Google ties to the flag later (review,
policy, consent wording) will apply to clients that declared it.

## Publishing status

- **Testing** (default): only test users can authorize; refresh tokens
  expire after 7 days, so each account needs `--auth` again weekly. Fine
  for a trial.
- **In production**: tokens persist. The app is unverified, so the
  consent screen shows a warning ("Google hasn't verified this app";
  Advanced > Go to WX Gmail MCP). Verification is not needed for
  personal use; the 100-user cap does not matter here. Switch at
  `https://console.cloud.google.com/auth/audience?project=<project-id>`,
  Publish app.

Gmail scopes are classed *restricted* and *sensitive*; an unverified app
can still use them for its own test users and, in production, for any
user who passes the warning screen.

## Deleting a project

`gcloud projects delete <project-id>` schedules the deletion (30-day
grace). Only for a scratch project; it revokes every token issued by
its OAuth client.
