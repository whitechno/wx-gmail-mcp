"""Filter tools, registered only with WX_GMAIL_ALLOW_SETTINGS=true.

Every tool checks that the account granted ``gmail.settings.basic``: the
settings endpoints accept no other scope, the full mail scope included.
"""

from __future__ import annotations

from collections.abc import Sequence

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import auth, bulk, filters, gmail
from wx_gmail_mcp.config import GATE_DELETE, SCOPE_FULL, SCOPE_SETTINGS_BASIC
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.filters import FilterRequest, FilterSpec
from wx_gmail_mcp.gmail import GmailService, Runtime
from wx_gmail_mcp.labels import LabelMap
from wx_gmail_mcp.safety import describe_error, register_tool, require_ids
from wx_gmail_mcp.tools.organize import describe_changes

# After a filter exists, a re-run of create_filter would make a second one,
# so the apply is finished another way. A delete filter trashes, which
# modify_by_query refuses: that needs the trash tools.
FINISH_RELABEL = (
    "relabel existing mail with modify_by_query on the query above (it has its "
    "own limit)",
    "Finish with modify_by_query on the query above",
)
FINISH_TRASH = (
    "trash existing matches separately (search the query above, then a trash "
    "tool, which needs WX_GMAIL_ALLOW_DELETE=true)",
    "Finish with a trash tool on the remaining matches",
)
# filters.delete has no batch form: one get and one delete per id.
MAX_FILTER_IDS = 100


def _plural(n: int) -> str:
    return f"{n} filter" if n == 1 else f"{n} filters"


def register(mcp: MCPServer, rt: Runtime) -> None:
    def service(account: str) -> GmailService:
        auth.require_scope(
            rt.settings, account, rt.credentials(account), SCOPE_SETTINGS_BASIC
        )
        return rt.service(account)

    def list_filters(account: str) -> str:
        """List the account's mail filters: id, what each matches (and the
        equivalent Gmail search), and what it does, with label names."""
        svc = service(account)
        found = gmail.list_filters(svc)
        if not found:
            return "No filters."
        labels = LabelMap.fetch(svc)
        head = f"{len(found)} filter{'' if len(found) == 1 else 's'}:"
        return "\n".join([head, *(filters.filter_text(f, labels) for f in found)])

    def get_filter(account: str, filter_id: str) -> str:
        """Show one filter by id: criteria, the equivalent Gmail search and
        the action, with label names."""
        filter_id = filter_id.strip()
        if not filter_id:
            raise WxGmailError("filter_id is required.")
        svc = service(account)
        flt = gmail.get_filter(svc, filter_id)
        return filters.filter_text(flt, LabelMap.fetch(svc))

    def check_delete(account: str, req: FilterRequest) -> None:
        """``delete`` is a trash action: it needs the DELETE gate and scope."""
        if not req.delete:
            return
        if not rt.settings.gates.delete:
            raise WxGmailError(
                "delete=true adds TRASH, which makes mail disappear; it is "
                f"available only when the server runs with {GATE_DELETE.env}=true."
            )
        auth.require_scope(rt.settings, account, rt.credentials(account), SCOPE_FULL)

    def apply_spec(
        svc: GmailService, spec: FilterSpec, limit: int, dry_run: bool
    ) -> bulk.RelabelReport:
        return bulk.relabel_by_query(
            svc,
            spec.search(),
            spec.add,
            spec.remove,
            limit=limit,
            dry_run=dry_run,
            limit_name="apply_limit",
        )

    def preview(
        svc: GmailService,
        labels: LabelMap,
        spec: FilterSpec,
        apply: bool,
        apply_limit: int,
        what: str,
        head: list[str] | None = None,
    ) -> str:
        """The dry-run text: the filter, labels it would create, the matches."""
        lines = [f"Dry run: {what}.", *(head or []), *filters.spec_text(spec, labels)]
        if spec.missing:
            lines.append(f"Labels to create: {', '.join(spec.missing)}.")
        tail = f"Run again with dry_run=false to {what}"
        if apply:
            report = apply_spec(svc, spec, apply_limit, True)
            if report.matched:
                n = report.matched
                lines.append(
                    f"Existing mail: {n} message{'' if n == 1 else 's'} "
                    f"match{'es' if n == 1 else ''} '{report.query}'."
                )
                lines.extend(["Sample:", *(f"  {x}" for x in report.sample)])
                tail += f" and apply it to {'that message' if n == 1 else 'them'}"
            else:
                lines.append(f"Existing mail: nothing matches '{report.query}'.")
        lines.append(tail + ".")
        return "\n".join(lines)

    def create(
        svc: GmailService, labels: LabelMap, spec: FilterSpec
    ) -> tuple[str, list[str]]:
        """Create missing labels, then the filter.

        Returns the new filter id and the lines describing it. The caller
        applies afterwards, so the filter exists before the apply starts
        and mail arriving meanwhile is still caught.
        """
        spec, note = filters.create_missing(svc, spec)
        if note:
            labels = LabelMap.fetch(svc)
        try:
            created = gmail.create_filter(svc, spec.body())
        except Exception as e:
            if not note:
                raise
            raise WxGmailError(
                f"Creating the filter failed ({describe_error(e)}), after labels "
                f"were made for it. {note} They remain; reuse or delete_label them."
            ) from e
        filter_id = str(created.get("id", ""))
        lines = filters.spec_text(spec, labels)
        if note:
            lines.append(note)
        return filter_id, lines

    def apply_text(
        svc: GmailService, labels: LabelMap, spec: FilterSpec, apply_limit: int
    ) -> str:
        """Apply after the filter exists; a failure must not hide that fact."""
        on_error, on_partial = FINISH_TRASH if "TRASH" in spec.add else FINISH_RELABEL
        try:
            report = apply_spec(svc, spec, apply_limit, False)
        except Exception as e:
            reason = str(e) if isinstance(e, WxGmailError) else describe_error(e)
            return (
                f"Existing mail was not changed: {reason} The filter exists, so do "
                f"not create it again; {on_error}."
            )
        change = describe_changes(labels, spec.add, spec.remove)
        return "Existing mail: " + report.text(change, retry=on_partial)

    def create_filter(
        account: str,
        from_: str = "",
        to: str = "",
        subject: str = "",
        query: str = "",
        negated_query: str = "",
        has_attachment: bool = False,
        exclude_chats: bool = False,
        size: int = 0,
        size_comparison: str = "larger",
        add_labels: Sequence[str] = (),
        remove_labels: Sequence[str] = (),
        create_missing_labels: bool = False,
        skip_inbox: bool = False,
        mark_read: bool = False,
        star: bool = False,
        always_important: bool = False,
        never_important: bool = False,
        never_spam: bool = False,
        category: str = "",
        delete: bool = False,
        apply: bool = False,
        apply_limit: int = bulk.DEFAULT_LIMIT,
        dry_run: bool = True,
    ) -> str:
        """Create a mail filter. Criteria (at least one): `from_`, `to`,
        `subject`, `query` (Gmail search), `negated_query`, `has_attachment`,
        `exclude_chats`, `size` in bytes with `size_comparison` larger|smaller.
        Actions (at least one): `add_labels`/`remove_labels` by name or id
        (`create_missing_labels=true` creates unknown names), and the
        shortcuts `skip_inbox`, `mark_read`, `star`, `always_important`,
        `never_important`, `never_spam`, `category`
        (personal|social|promotions|updates|forums) and `delete` (to Trash;
        only with WX_GMAIL_ALLOW_DELETE). A filter affects future mail;
        `apply=true` also relabels existing matches, message by message,
        Spam and Trash excluded, failing above `apply_limit` (default 5000).
        `dry_run=true` (the default) shows the filter and the matches and
        changes nothing."""
        req = FilterRequest(
            from_=from_,
            to=to,
            subject=subject,
            query=query,
            negated_query=negated_query,
            has_attachment=has_attachment,
            exclude_chats=exclude_chats,
            size=size,
            size_comparison=size_comparison,
            add_labels=add_labels,
            remove_labels=remove_labels,
            skip_inbox=skip_inbox,
            mark_read=mark_read,
            star=star,
            always_important=always_important,
            never_important=never_important,
            never_spam=never_spam,
            category=category,
            delete=delete,
        )
        if apply:
            bulk.check_limit(apply_limit, "apply_limit")
        svc = service(account)
        check_delete(account, req)
        labels = LabelMap.fetch(svc)
        spec = filters.plan_filter(req, labels, create_missing_labels)
        if dry_run:
            return preview(svc, labels, spec, apply, apply_limit, "create the filter")
        filter_id, lines = create(svc, labels, spec)
        lines.insert(0, f"Created filter {filter_id}.")
        if apply:
            lines.append(apply_text(svc, labels, spec, apply_limit))
        return "\n".join(lines)

    def delete_filter(account: str, filter_ids: Sequence[str]) -> str:
        """Delete filters by id (up to 100). Each is shown as it was before
        deletion; the mail it labelled is untouched."""
        ids = require_ids(list(filter_ids), "filter_ids", cap=MAX_FILTER_IDS)
        svc = service(account)
        labels = LabelMap.fetch(svc)
        lines: list[str] = []
        done = 0
        try:
            for filter_id in ids:
                flt = gmail.get_filter(svc, filter_id)
                gmail.delete_filter(svc, filter_id)
                done += 1
                lines.append(filters.filter_text(flt, labels))
        except Exception as e:
            head = (
                f"Deleted {done} of {_plural(len(ids))} before an error on filter "
                f"{ids[done]}: {describe_error(e)}"
            )
            return "\n".join([head, *lines])
        return "\n".join([f"Deleted {_plural(done)}:", *lines])

    def replace_filter(
        account: str,
        filter_id: str,
        from_: str = "",
        to: str = "",
        subject: str = "",
        query: str = "",
        negated_query: str = "",
        has_attachment: bool = False,
        exclude_chats: bool = False,
        size: int = 0,
        size_comparison: str = "larger",
        add_labels: Sequence[str] = (),
        remove_labels: Sequence[str] = (),
        create_missing_labels: bool = False,
        skip_inbox: bool = False,
        mark_read: bool = False,
        star: bool = False,
        always_important: bool = False,
        never_important: bool = False,
        never_spam: bool = False,
        category: str = "",
        delete: bool = False,
        apply: bool = False,
        apply_limit: int = bulk.DEFAULT_LIMIT,
        dry_run: bool = True,
    ) -> str:
        """Replace filter `filter_id` with a new one described in full by the
        same flags as create_filter (nothing is inherited from the old
        filter). Gmail has no filter update, so the new filter is created,
        then the old one deleted, then `apply` runs if asked. `dry_run=true`
        (the default) shows both filters and changes nothing."""
        req = FilterRequest(
            from_=from_,
            to=to,
            subject=subject,
            query=query,
            negated_query=negated_query,
            has_attachment=has_attachment,
            exclude_chats=exclude_chats,
            size=size,
            size_comparison=size_comparison,
            add_labels=add_labels,
            remove_labels=remove_labels,
            skip_inbox=skip_inbox,
            mark_read=mark_read,
            star=star,
            always_important=always_important,
            never_important=never_important,
            never_spam=never_spam,
            category=category,
            delete=delete,
        )
        filter_id = filter_id.strip()
        if not filter_id:
            raise WxGmailError("filter_id is required.")
        if apply:
            bulk.check_limit(apply_limit, "apply_limit")
        svc = service(account)
        check_delete(account, req)
        labels = LabelMap.fetch(svc)
        spec = filters.plan_filter(req, labels, create_missing_labels)
        old = gmail.get_filter(svc, filter_id)
        current = [
            "Current:",
            *filters.filter_text(old, labels).split("\n")[1:],
            "New:",
        ]
        if dry_run:
            return preview(
                svc, labels, spec, apply, apply_limit, "replace the filter", current
            )
        new_id, lines = create(svc, labels, spec)
        try:
            gmail.delete_filter(svc, filter_id)
        except Exception as e:
            lines.insert(
                0,
                f"Created filter {new_id}, but deleting filter {filter_id} failed: "
                f"{describe_error(e)} Both exist; delete_filter the old one.",
            )
        else:
            lines.insert(0, f"Replaced filter {filter_id} with {new_id}.")
        if apply:
            lines.append(apply_text(svc, labels, spec, apply_limit))
        return "\n".join(lines)

    register_tool(mcp, list_filters)
    register_tool(mcp, get_filter)
    register_tool(mcp, create_filter)
    register_tool(mcp, delete_filter)
    register_tool(mcp, replace_filter)
