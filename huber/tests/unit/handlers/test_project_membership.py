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

from unittest import mock

from huber.handlers import project_membership as pm
from huber.notification import event as event_mod
from huber.tests.unit import base as test_base


TM_ROLE_ID = "role-tm"
MEMBER_ROLE_ID = "role-mem"
READER_ROLE_ID = "role-reader"
OTHER_ROLE_ID = "role-other"


def _stub(**attrs):
    """Build an object that looks like a keystoneclient resource."""
    obj = mock.Mock(spec=list(attrs.keys()))
    for name, value in attrs.items():
        setattr(obj, name, value)
    return obj


def _user(uid, email, name=None, enabled=True):
    return _stub(id=uid, email=email, name=name or uid, enabled=enabled)


def _assignment(user_id, role_id):
    return _stub(user={"id": user_id}, role={"id": role_id})


def _event(event_type, traits, message_id="mid"):
    return event_mod.Event(
        event_type=event_type,
        traits=traits,
        message_id=message_id,
        generated="2026-05-18T00:00:00",
        raw_payload={},
    )


class TestProjectMembershipHandler(test_base.TestCase):
    def setUp(self):
        super().setUp()
        self.handler = pm.ProjectMembershipHandler()
        self.ks = mock.Mock()
        self.taynac = mock.Mock()
        # Taynac echoes the recipients it resolved from the project.
        self.taynac.messages.send.return_value = _stub(
            backend_id="42",
            recipient="tm@example.com",
            cc=["m@example.com"],
        )
        self.handler._ks = self.ks
        self.handler._taynac = self.taynac

        self.ks.projects.get.return_value = _stub(id="p-1", name="my-project")

        # Default: the event was about adding role-mem.
        self._roles = {
            TM_ROLE_ID: _stub(id=TM_ROLE_ID, name="TenantManager"),
            MEMBER_ROLE_ID: _stub(id=MEMBER_ROLE_ID, name="Member"),
            READER_ROLE_ID: _stub(id=READER_ROLE_ID, name="Reader"),
            OTHER_ROLE_ID: _stub(id=OTHER_ROLE_ID, name="heat_stack_owner"),
        }
        self.ks.roles.get.side_effect = lambda rid: self._roles[rid]

    def _wire_users(self, users):
        by_id = {u.id: u for u in users}
        self.ks.users.get.side_effect = lambda uid: by_id[uid]

    def test_sends_one_message_with_project_id(self):
        tm = _user("u-tm", "tm@example.com", "TM")
        member = _user("u-m", "m@example.com", "Mem")
        target = _user("u-new", "new@example.com", "New")
        self._wire_users([tm, member, target])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
            _assignment("u-m", MEMBER_ROLE_ID),
            _assignment("u-new", MEMBER_ROLE_ID),
        ]

        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-new", "role": MEMBER_ROLE_ID},
            )
        )

        self.taynac.messages.send.assert_called_once()
        call = self.taynac.messages.send.call_args
        # Recipient resolution is delegated to taynac via project_id.
        self.assertEqual("p-1", call.kwargs["project_id"])
        self.assertNotIn("recipient", call.kwargs)
        self.assertNotIn("cc", call.kwargs)
        # Subject carries the configured prefix plus the project name.
        self.assertEqual(
            "Nectar project role change: my-project",
            call.kwargs["subject"],
        )
        body = call.kwargs["body"]
        self.assertIn("granted", body)
        self.assertIn("my-project", body)
        self.assertIn("Member", body)
        self.assertIn("New", body)

    def test_sends_even_without_tenantmanager(self):
        # Taynac owns recipient resolution (including the no-manager
        # fallback), so huber sends regardless of who holds which role.
        member = _user("u-m", "m@example.com")
        member2 = _user("u-m2", "m2@example.com")
        self._wire_users([member, member2])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-m", MEMBER_ROLE_ID),
            _assignment("u-m2", MEMBER_ROLE_ID),
        ]

        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-m", "role": MEMBER_ROLE_ID},
            )
        )

        self.taynac.messages.send.assert_called_once()
        call = self.taynac.messages.send.call_args
        self.assertEqual("p-1", call.kwargs["project_id"])

    def test_single_recipient_skips_send(self):
        # The tenant manager is the only enabled user with a recipient
        # role, so nobody else would be notified — no message is sent.
        tm = _user("u-tm", "tm@example.com")
        target = _user("u-gone", "gone@example.com")
        self._wire_users([tm, target])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
        ]

        self.handler.handle(
            _event(
                pm.DELETED_EVENT,
                {"project": "p-1", "user": "u-gone", "role": MEMBER_ROLE_ID},
            )
        )
        self.taynac.messages.send.assert_not_called()

    def test_reader_only_users_do_not_count_as_recipients(self):
        # Readers appear in the members table but are not notified by
        # taynac, so a TM plus a reader is still a single recipient.
        tm = _user("u-tm", "tm@example.com")
        reader = _user("u-r", "r@example.com")
        self._wire_users([tm, reader])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
            _assignment("u-r", READER_ROLE_ID),
        ]

        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-r", "role": READER_ROLE_ID},
            )
        )
        self.taynac.messages.send.assert_not_called()

    def test_recipients_without_email_do_not_count(self):
        tm = _user("u-tm", "tm@example.com")
        no_email = _user("u-x", "")
        self._wire_users([tm, no_email])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
            _assignment("u-x", MEMBER_ROLE_ID),
        ]

        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-x", "role": MEMBER_ROLE_ID},
            )
        )
        self.taynac.messages.send.assert_not_called()

    def test_disabled_recipients_do_not_count(self):
        tm = _user("u-tm", "tm@example.com")
        disabled = _user("u-off", "off@example.com", enabled=False)
        self._wire_users([tm, disabled])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
            _assignment("u-off", MEMBER_ROLE_ID),
        ]

        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-off", "role": MEMBER_ROLE_ID},
            )
        )
        self.taynac.messages.send.assert_not_called()

    def test_role_name_match_is_case_insensitive(self):
        # Keystone calls the role "tenantmanager" (no caps) in some
        # deployments; we should still recognise it.
        self._roles[TM_ROLE_ID] = _stub(id=TM_ROLE_ID, name="tenantmanager")
        self._roles[MEMBER_ROLE_ID] = _stub(id=MEMBER_ROLE_ID, name="MEMBER")

        tm = _user("u-tm", "tm@example.com")
        member = _user("u-m", "m@example.com")
        self._wire_users([tm, member])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
            _assignment("u-m", MEMBER_ROLE_ID),
        ]

        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-m", "role": MEMBER_ROLE_ID},
            )
        )

        self.taynac.messages.send.assert_called_once()
        call = self.taynac.messages.send.call_args
        self.assertEqual("p-1", call.kwargs["project_id"])

    def test_deleted_event_uses_removed_template(self):
        tm = _user("u-tm", "tm@example.com")
        member = _user("u-m", "m@example.com")
        # The removed user is no longer in role_assignments.
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
            _assignment("u-m", MEMBER_ROLE_ID),
        ]
        target = _user("u-gone", "gone@example.com", "Gone")
        self._wire_users([tm, member, target])

        self.handler.handle(
            _event(
                pm.DELETED_EVENT,
                {"project": "p-1", "user": "u-gone", "role": MEMBER_ROLE_ID},
            )
        )

        call = self.taynac.messages.send.call_args
        self.assertEqual("p-1", call.kwargs["project_id"])
        body = call.kwargs["body"]
        self.assertIn("revoked", body)
        self.assertIn("Gone", body)
        # Removed user is NOT in the members table — they no longer hold
        # the role.
        self.assertNotIn("gone@example.com", body)

    def test_group_assignment_uses_group_label(self):
        tm = _user("u-tm", "tm@example.com")
        member = _user("u-m", "m@example.com")
        self._wire_users([tm, member])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
            _assignment("u-m", MEMBER_ROLE_ID),
        ]
        group = _stub(id="g-1", name="science-team")
        self.ks.groups.get.return_value = group

        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "group": "g-1", "role": MEMBER_ROLE_ID},
            )
        )

        call = self.taynac.messages.send.call_args
        self.assertIn("science-team", call.kwargs["body"])
        self.assertIn("group", call.kwargs["body"])

    def test_reader_role_triggers_notification(self):
        tm = _user("u-tm", "tm@example.com")
        member = _user("u-m", "m@example.com")
        target = _user("u-new", "new@example.com")
        self._wire_users([tm, member, target])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
            _assignment("u-m", MEMBER_ROLE_ID),
            _assignment("u-new", READER_ROLE_ID),
        ]

        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-new", "role": READER_ROLE_ID},
            )
        )

        self.taynac.messages.send.assert_called_once()
        body = self.taynac.messages.send.call_args.kwargs["body"]
        self.assertIn("Reader", body)

    def test_non_notifiable_role_skips_send(self):
        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-new", "role": OTHER_ROLE_ID},
            )
        )
        # Skipped before any membership lookup.
        self.ks.role_assignments.list.assert_not_called()
        self.taynac.messages.send.assert_not_called()

    def test_missing_role_trait_skips_send(self):
        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-new"},
            )
        )
        self.ks.role_assignments.list.assert_not_called()
        self.taynac.messages.send.assert_not_called()

    def test_missing_project_trait_is_a_noop(self):
        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"domain": "d-1", "user": "u-new", "role": MEMBER_ROLE_ID},
            )
        )
        self.ks.projects.get.assert_not_called()
        self.taynac.messages.send.assert_not_called()

    def test_missing_user_and_group_is_a_noop(self):
        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "role": MEMBER_ROLE_ID},
            )
        )
        self.ks.projects.get.assert_not_called()
        self.taynac.messages.send.assert_not_called()

    def test_taynac_failure_is_logged_not_raised(self):
        tm = _user("u-tm", "tm@example.com")
        target = _user("u-new", "new@example.com")
        self._wire_users([tm, target])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
            _assignment("u-new", MEMBER_ROLE_ID),
        ]
        self.taynac.messages.send.side_effect = RuntimeError("smtp down")

        # Must not propagate.
        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-new", "role": MEMBER_ROLE_ID},
            )
        )
        self.taynac.messages.send.assert_called_once()

    def test_body_includes_members_table(self):
        tm = _user("u-tm", "tm@example.com", "Alice TM")
        member = _user("u-m", "m@example.com", "Bob Member")
        reader = _user("u-r", "r@example.com", "Carol Reader")
        self._wire_users([tm, member, reader])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
            _assignment("u-m", MEMBER_ROLE_ID),
            # User holding two roles — should appear once with both roles.
            _assignment("u-r", MEMBER_ROLE_ID),
            _assignment("u-r", READER_ROLE_ID),
        ]

        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-m", "role": MEMBER_ROLE_ID},
            )
        )

        body = self.taynac.messages.send.call_args.kwargs["body"]
        # Table headings.
        self.assertIn("<table", body)
        self.assertIn("<th align=\"left\">User</th>", body)
        self.assertIn("<th align=\"left\">Email</th>", body)
        self.assertIn("<th align=\"left\">Roles</th>", body)
        # Each user appears in a row.
        self.assertIn("Alice TM", body)
        self.assertIn("tm@example.com", body)
        self.assertIn("Bob Member", body)
        self.assertIn("Carol Reader", body)
        # Carol has both roles, comma-joined and sorted.
        self.assertIn("Member, Reader", body)
        # Rows sorted by name — Alice should appear before Bob. Scope to
        # the table: the target's name also appears in the paragraph above.
        table = body[body.index("<table") :]
        self.assertLess(table.index("Alice TM"), table.index("Bob Member"))

    def test_disabled_user_is_not_in_members_table(self):
        tm = _user("u-tm", "tm@example.com", "Alice TM")
        member = _user("u-m", "m@example.com", "Bob Member")
        disabled = _user(
            "u-off", "off@example.com", "Carol Off", enabled=False
        )
        self._wire_users([tm, member, disabled])
        self.ks.role_assignments.list.return_value = [
            _assignment("u-tm", TM_ROLE_ID),
            _assignment("u-m", MEMBER_ROLE_ID),
            _assignment("u-off", MEMBER_ROLE_ID),
        ]

        self.handler.handle(
            _event(
                pm.CREATED_EVENT,
                {"project": "p-1", "user": "u-m", "role": MEMBER_ROLE_ID},
            )
        )

        body = self.taynac.messages.send.call_args.kwargs["body"]
        self.assertIn("Alice TM", body)
        self.assertIn("Bob Member", body)
        self.assertNotIn("Carol Off", body)
        self.assertNotIn("off@example.com", body)

    def test_matches_only_role_assignment_events(self):
        self.assertTrue(self.handler.matches(pm.CREATED_EVENT))
        self.assertTrue(self.handler.matches(pm.DELETED_EVENT))
        self.assertFalse(self.handler.matches("identity.user.created"))
        self.assertFalse(self.handler.matches("compute.instance.create.end"))
