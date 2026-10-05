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
gcloud projects create <project-id> --name=wx-gmail-mcp
gcloud services enable gmail.googleapis.com --project=<project-id>
gcloud services list --enabled --project=<project-id> \
  --filter=config.name:gmail.googleapis.com
```

`scripts/gcloud_project.py <project-id> --create --enable` runs exactly
these, idempotently, and prints the console URLs for the rest. Project
ids are global and permanent: if `wx-gmail-mcp` is taken, use a suffix
such as `wx-gmail-mcp-<name>`. The Gmail API needs no billing account.

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

1. App information: app name `WX Gmail MCP`, user support email: the
   user's address.
2. Audience: **External**.
3. Contact information: the user's address.
4. Finish: a checkbox to agree to the Google API Services User Data
   Policy. **[you]**: the user ticks it and clicks Continue, then
   Create.

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
- "This client will be used by an AI-powered agent": leave it
  **unchecked**. See the note below.
- Create. On the confirmation dialog, **Download JSON**; the file is
  `client_secret_<id>.json` in the browser's download folder. If the
  browser asks where to save or whether to keep the download, that is
  **[you]**. A browser tool may leave only a temporary file in the
  download folder; `scripts/install_client_json.py <path>` takes any
  path. The JSON can be downloaded again later from the client's row.

The client JSON holds the client id and secret. It goes to
`<home>/oauth_client.json` (step 4 of the skill) and nowhere else.

### The "AI-powered agent" option

The console's client form has a checkbox "This client will be used by
an AI-powered agent". It is a declaration for Google's app review; it
changes nothing in how the OAuth flow works for this server. Leave it
unchecked: wx-gmail-mcp is an ordinary installed application that the
user runs and authorizes in person, and its scopes are requested at
runtime from a consent screen the user sees. Revisit this if the app is
ever published and submitted for verification. (Checked 2026-10-05 in
the console; Google's OAuth docs do not describe the option.)

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
