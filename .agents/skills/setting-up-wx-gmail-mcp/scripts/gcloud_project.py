#!/usr/bin/env python3
"""Google Cloud project for wx-gmail-mcp, through gcloud. Idempotent.

    gcloud_project.py PROJECT_ID            report; never creates
    gcloud_project.py PROJECT_ID --create   create the project if missing
    gcloud_project.py PROJECT_ID --enable   also enable the Gmail API
    gcloud_project.py PROJECT_ID --urls     print the console URLs only

Every call names the project (positional or ``--project``); the user's
default project is never read or changed. The consent screen and the
OAuth client cannot be created with gcloud: the script prints the console
URLs for them. Exit 1 when gcloud is missing or not logged in, when a step
fails, and in report mode when the project or the API is still missing.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

GMAIL_API = "gmail.googleapis.com"
CONSOLE = "https://console.cloud.google.com"


def console_urls(project: str) -> dict[str, str]:
    q = f"?project={project}"
    return {
        "branding (app name, emails)": f"{CONSOLE}/auth/branding{q}",
        "audience (user type, test users)": f"{CONSOLE}/auth/audience{q}",
        "clients (create the Desktop app client)": f"{CONSOLE}/auth/clients{q}",
        "Gmail API": f"{CONSOLE}/apis/library/{GMAIL_API}{q}",
    }


def gcloud(gcloud_path: str, *args: str) -> tuple[int, str, str]:
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [gcloud_path, *args, "--quiet"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return 1, "", "gcloud timed out after 120 s"
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("project", help="globally unique project id")
    parser.add_argument("--create", action="store_true", help="create if missing")
    parser.add_argument("--enable", action="store_true", help="enable the Gmail API")
    parser.add_argument("--urls", action="store_true", help="print console URLs only")
    args = parser.parse_args(argv)
    project: str = args.project

    if args.urls:
        for label, url in console_urls(project).items():
            print(f"{label}: {url}")
        return 0

    path = shutil.which("gcloud")
    if not path:
        print("FAIL gcloud: not installed; follow the console steps instead")
        return 1
    code, account, _ = gcloud(
        path, "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"
    )
    if code != 0 or not account:
        print("FAIL gcloud: no active account; run: gcloud auth login")
        return 1
    print(f"ok   gcloud: logged in as {account}")

    code, _, err = gcloud(
        path, "projects", "describe", project, "--format=value(projectId)"
    )
    if code == 0:
        print(f"ok   project: {project} exists")
    elif not args.create:
        print(
            f"info project: {project} not found (or no access); add --create to make it"
        )
        return 1
    else:
        code, _, err = gcloud(path, "projects", "create", project, f"--name={project}")
        if code != 0:
            print(
                f"FAIL project: create failed: {err.splitlines()[-1] if err else code}"
            )
            print("     (a taken id? project ids are global; add a suffix)")
            return 1
        print(f"ok   project: {project} created")

    code, out, err = gcloud(
        path,
        "services",
        "list",
        "--enabled",
        f"--project={project}",
        f"--filter=config.name:{GMAIL_API}",
        "--format=value(config.name)",
    )
    if code == 0 and GMAIL_API in out:
        print(f"ok   gmail api: enabled on {project}")
    elif not args.enable:
        print(f"info gmail api: not enabled on {project}; add --enable")
        return 1
    else:
        code, _, err = gcloud(
            path, "services", "enable", GMAIL_API, f"--project={project}"
        )
        if code != 0:
            reason = err.splitlines()[-1] if err else str(code)
            print(f"FAIL gmail api: enable failed: {reason}")
            return 1
        print(f"ok   gmail api: enabled on {project}")

    print("next, in the console (gcloud cannot do these):")
    for label, url in console_urls(project).items():
        print(f"  {label}: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
