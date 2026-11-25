import unittest
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import Session

from database import Base
from auth import CurrentUser
from enterprise_schemas import WorkbenchSettingsDraft
from enterprise_routes import save_workbench_settings_draft, public_assistant_appearance


class AssistantCharactersTests(unittest.TestCase):
    def test_defaults_and_independent_choices(self):
        self.assertEqual(WorkbenchSettingsDraft().assistant_icon, 'H')
        self.assertEqual(WorkbenchSettingsDraft().assistant_mascot, '@cow')
        value = WorkbenchSettingsDraft(assistant_icon='@cow', assistant_mascot='@sprout')
        self.assertEqual(value.assistant_mascot, '@sprout')
        path = '/uploads/images/20260915_12345678.svg'
        self.assertEqual(WorkbenchSettingsDraft(assistant_icon=path).assistant_icon, path)
        for invalid in ['https://other.test/icon.svg', '/uploads/images/../x.svg', 'data:image/svg+xml,x', '@unknown']:
            with self.assertRaises(ValidationError):
                WorkbenchSettingsDraft(assistant_mascot=invalid)

    def test_saved_choices_and_public_payload_only_use_published_mascot(self):
        engine = create_engine('sqlite://')
        try:
            with patch.object(SQLiteTypeCompiler, 'visit_BIGINT', return_value='INTEGER'):
                Base.metadata.create_all(engine)
            with Session(engine) as db:
                self.assertEqual(public_assistant_appearance(db), {'mascot': '@cow'})
                draft = save_workbench_settings_draft(WorkbenchSettingsDraft(
                    assistant_icon='/uploads/images/chat.svg', assistant_mascot='@sprout', system_prompt='private',
                ), db, CurrentUser(user_id=7, is_superuser=True))
                db.commit()
                db.refresh(draft)
                self.assertEqual(draft.assistant_icon, '/uploads/images/chat.svg')
                self.assertEqual(public_assistant_appearance(db), {'mascot': '@cow'})
                draft.status = 'published'
                db.commit()
                self.assertEqual(public_assistant_appearance(db), {'mascot': '@sprout'})
                next_draft = save_workbench_settings_draft(WorkbenchSettingsDraft(
                    assistant_icon='H', assistant_mascot='/uploads/images/custom.png',
                ), db, CurrentUser(user_id=7, is_superuser=True))
                db.commit()
                self.assertNotEqual(next_draft.id, draft.id)
                self.assertEqual(public_assistant_appearance(db), {'mascot': '@sprout'})
        finally:
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
