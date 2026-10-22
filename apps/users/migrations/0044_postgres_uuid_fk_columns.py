from django.db import migrations


# Project, Department and User switched from integer to UUID primary keys in
# 0007-0014. On PostgreSQL those AlterFields leave the existing FK columns
# (including admin's LogEntry.user) as
# bigint with no FK constraint, so inserts fail with "column ... is of type
# bigint but expression is of type uuid". SQLite never enforced the type, so
# this only repairs PostgreSQL schemas and is a no-op elsewhere.
COLUMNS = [
    # (table, column, referenced table, nullable)
    ('users_user', 'department_id', 'users_department', True),
    ('users_user', 'project_id', 'users_project', True),
    ('users_user_groups', 'user_id', 'users_user', False),
    ('users_user_user_permissions', 'user_id', 'users_user', False),
    ('django_admin_log', 'user_id', 'users_user', False),
]


def fix_fk_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        for table, column, ref_table, nullable in COLUMNS:
            cursor.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s",
                [table, column],
            )
            row = cursor.fetchone()
            if not row or row[0] == 'uuid':
                continue
            # Integer ids cannot point at UUID rows, so existing values are
            # unrecoverable: null them, or drop the rows of NOT NULL M2M tables.
            if not nullable:
                cursor.execute('DELETE FROM "%s"' % table)
            cursor.execute(
                'ALTER TABLE "%s" ALTER COLUMN "%s" TYPE uuid USING NULL::uuid' % (table, column)
            )
            cursor.execute(
                'ALTER TABLE "%s" ADD CONSTRAINT "%s_%s_fk_%s_uuid" FOREIGN KEY ("%s") '
                'REFERENCES "%s" ("uuid") DEFERRABLE INITIALLY DEFERRED'
                % (table, table[:20], column, ref_table, column, ref_table)
            )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0043_lead_pipeline'),
        ('admin', '0003_logentry_add_action_flag_choices'),
    ]

    operations = [
        migrations.RunPython(fix_fk_columns, migrations.RunPython.noop),
    ]
