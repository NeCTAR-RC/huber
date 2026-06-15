#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_config import cfg
from oslo_log import log as logging

from huber.handlers import common


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


project_membership_opts = [
    cfg.StrOpt(
        "subject",
        default="Nectar project role change",
        help=(
            "Subject prefix for taynac messages sent by this handler. The "
            "affected project's name is appended, giving a subject like "
            "'Nectar project role change: my-project'."
        ),
    ),
    cfg.StrOpt(
        "tenantmanager_role",
        default="tenantmanager",
        help=(
            "Name of the keystone role that identifies a project's "
            "tenant managers. The first user holding this role is used "
            "as the message's primary recipient. Compared case-"
            "insensitively against role names from keystone."
        ),
    ),
    cfg.StrOpt(
        "member_role",
        default="member",
        help=(
            "Name of the keystone role that identifies ordinary project "
            "members. Users with this role (and tenantmanagers) are CC'd "
            "on the notification. Compared case-insensitively."
        ),
    ),
    cfg.StrOpt(
        "reader_role",
        default="reader",
        help=(
            "Name of the keystone role that identifies read-only project "
            "members. Compared case-insensitively against role names "
            "from keystone."
        ),
    ),
]
cfg.CONF.register_opts(project_membership_opts, group="project_membership")


CREATED_EVENT = "identity.role_assignment.created"
DELETED_EVENT = "identity.role_assignment.deleted"


class ProjectMembershipHandler(common.TaynacHandlerBase):
    """Notify a project's tenant manager when membership changes.

    Triggered by keystone's ``identity.role_assignment.created`` and
    ``identity.role_assignment.deleted`` notifications. For each event we:

    1. Resolve the affected user/group, project, and role via keystone.
       Only the tenantmanager, member, and reader roles are notifiable;
       events for any other role are ignored.
    2. Find the project's tenant managers and ordinary members (effective
       assignments — group memberships are expanded to users).
    3. Send **one** taynac message:
        * ``recipient`` = first tenant manager (by keystone API order)
        * ``cc`` = every other user holding the tenantmanager or member
          role on the project

    If nobody would be CC'd (the tenant manager is the only recipient),
    no message is sent.
    """

    event_types = [CREATED_EVENT, DELETED_EVENT]

    def handle(self, event):
        action = "added" if event.event_type == CREATED_EVENT else "removed"

        project_id = event.traits.get("project")
        if not project_id:
            LOG.debug(
                "Skipping %s (message_id=%s): no project trait "
                "(domain-scoped assignment?)",
                event.event_type,
                event.message_id,
            )
            return

        target_user_id = event.traits.get("user")
        target_group_id = event.traits.get("group")
        if not target_user_id and not target_group_id:
            LOG.debug(
                "Skipping %s (message_id=%s): no user or group trait",
                event.event_type,
                event.message_id,
            )
            return

        role_id = event.traits.get("role")

        ks, taynac = self._clients()
        role = ks.roles.get(role_id) if role_id else None
        role_name = getattr(role, "name", None) if role else None
        notifiable_roles = (
            CONF.project_membership.tenantmanager_role.lower(),
            CONF.project_membership.member_role.lower(),
            CONF.project_membership.reader_role.lower(),
        )
        if not role_name or role_name.lower() not in notifiable_roles:
            LOG.debug(
                "Skipping %s (message_id=%s): role %s is not a "
                "notifiable role",
                event.event_type,
                event.message_id,
                role_name or role_id,
            )
            return

        project = ks.projects.get(project_id)

        if target_user_id:
            target = ks.users.get(target_user_id)
            target_kind = "user"
        else:
            target = ks.groups.get(target_group_id)
            target_kind = "group"

        tenantmanagers, cc_users, members_table = (
            self._collect_project_membership(ks, project_id)
        )
        if not tenantmanagers:
            LOG.warning(
                "No %s on project %s; skipping %s notification "
                "(message_id=%s)",
                CONF.project_membership.tenantmanager_role,
                project_id,
                event.event_type,
                event.message_id,
            )
            return

        primary = tenantmanagers[0]
        primary_email = getattr(primary, "email", None)
        if not primary_email:
            LOG.warning(
                "Primary tenant manager %s has no email; skipping %s "
                "notification (message_id=%s)",
                primary.id,
                event.event_type,
                event.message_id,
            )
            return

        cc_emails = sorted(
            {
                u.email
                for u in cc_users
                if getattr(u, "email", None) and u.id != primary.id
            }
        )
        if not cc_emails:
            LOG.debug(
                "Skipping %s (message_id=%s): only one user would be notified",
                event.event_type,
                event.message_id,
            )
            return

        project_name = getattr(project, "name", project_id)

        body = self.render(
            f"project_membership/{action}.html",
            recipient_name=common.display_name(primary),
            target_name=common.display_name(target),
            target_kind=target_kind,
            project_name=project_name,
            role_name=role_name,
            members_table=members_table,
        )

        subject = f"{CONF.project_membership.subject}: {project_name}"

        try:
            msg = taynac.messages.send(
                subject=subject,
                body=body,
                recipient=primary_email,
                cc=cc_emails,
            )
        except Exception:
            LOG.exception(
                "Failed sending taynac message for %s (project=%s, target=%s)",
                event.event_type,
                project_id,
                target.id,
            )
            return

        LOG.info(
            "Sent project-membership %s message: to=%s cc=%d "
            "(backend_id=%s, project=%s, target=%s)",
            action,
            primary_email,
            len(cc_emails),
            getattr(msg, "backend_id", None),
            project_id,
            target.id,
        )

    @staticmethod
    def _collect_project_membership(ks, project_id):
        """Single pass over the project's effective role assignments.

        Returns ``(tenantmanagers, cc_users, members_table)``:

        * ``tenantmanagers`` — User objects in keystone API order so
          ``[0]`` is deterministic.
        * ``cc_users`` — every user with the tenantmanager or member role,
          deduplicated by id.
        * ``members_table`` — list of ``{"name", "email", "roles"}`` dicts
          covering every user holding any role on the project, sorted by
          display name. ``roles`` is the deduped list of role names.
        """
        tm_name = CONF.project_membership.tenantmanager_role.lower()
        member_name = CONF.project_membership.member_role.lower()

        role_names = {}  # role_id -> role.name (original case)
        user_to_role_ids = {}  # user_id -> set of role_ids
        tenantmanager_ids = []  # order-preserving

        for a in ks.role_assignments.list(project=project_id, effective=True):
            role_ref = getattr(a, "role", None)
            user_ref = getattr(a, "user", None)
            if not role_ref or not user_ref:
                continue
            role_id = common.ref_id(role_ref)
            user_id = common.ref_id(user_ref)
            if not role_id or not user_id:
                continue

            if role_id not in role_names:
                role_names[role_id] = ks.roles.get(role_id).name
            normalized = role_names[role_id].lower()

            user_to_role_ids.setdefault(user_id, set()).add(role_id)

            if normalized == tm_name and user_id not in tenantmanager_ids:
                tenantmanager_ids.append(user_id)

        # Fetch each user once.
        user_cache = {uid: ks.users.get(uid) for uid in user_to_role_ids}

        # Disabled keystone users can't read email and shouldn't be on the
        # to/cc lists. Default to enabled when the attribute is missing.
        def _enabled(uid):
            return bool(getattr(user_cache[uid], "enabled", True))

        tenantmanagers = [
            user_cache[uid] for uid in tenantmanager_ids if _enabled(uid)
        ]

        cc_user_ids = {
            uid
            for uid, rids in user_to_role_ids.items()
            if _enabled(uid)
            and any(
                role_names[rid].lower() in (tm_name, member_name)
                for rid in rids
            )
        }
        cc_users = [user_cache[uid] for uid in cc_user_ids]

        members_table = []
        for uid, rids in user_to_role_ids.items():
            if not _enabled(uid):
                continue
            user = user_cache[uid]
            members_table.append(
                {
                    "name": common.display_name(user),
                    "email": getattr(user, "email", "") or "",
                    "roles": sorted({role_names[rid] for rid in rids}),
                }
            )
        members_table.sort(key=lambda row: row["name"].lower())

        return tenantmanagers, cc_users, members_table
