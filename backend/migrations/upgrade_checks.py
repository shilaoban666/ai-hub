"""Read-only checks for the 044-063 upgrade, without importing the application."""

# Columns absent from baseline b663a72. All other current columns of these
# tables must already exist before the incremental upgrade can run.
ADDED_COLUMNS = {
    'platform_global_settings': {'runtime_environment'},
    'agent_message_feedback': {'processing_remark', 'processing_images'},
    'skills': {'conversation_examples', 'development_mode'},
    'user_workspaces': {'agent_id', 'scope_agent_id'},
    'runtime_cells': {'agent_id', 'scope_agent_id'},
    'skill_installations': {'scope_agent_id'},
    'mcp_connections': {'scope_agent_id'},
    'credential_references': {'scope_agent_id'},
    'expert_mcp_bindings': {'status'},
    'platform_agent_settings': {'thinking_level', 'reasoning_visibility'},
    'agent_runs': {'idempotency_key', 'idempotency_fingerprint'},
    'agents': {'noun_highlight_enabled', 'noun_explanation_url'},
    'prompt_templates': set(),
    'expert_skill_bindings': set(),
    'mcp_revisions': set(),
}
NEW_TABLES = ('agent_prompt_templates', 'user_execution_gates', 'workbench_settings',
              'workspace_prompt_references', 'model_gateway_requests',
              'agent_open_calls', 'agent_open_requests',
              'knowledge_settings', 'knowledge_dingtalk_identities', 'knowledge_uploads',
              'knowledge_call_logs', 'knowledge_call_hits', 'knowledge_doc_links')
INDEXES = {
    'user_workspaces': {
        'uq_user_workspaces_user_agent': (True, ['user_id', 'agent_id']),
        'uq_user_workspaces_user_scope': (True, ['user_id', 'scope_agent_id']),
    },
    'runtime_cells': {
        'uq_runtime_cells_user_agent': (True, ['user_id', 'agent_id']),
        'uq_runtime_cells_user_scope': (True, ['user_id', 'scope_agent_id']),
    },
    'skill_installations': {'uq_skill_installations_user_scope_skill': (True, ['user_id', 'scope_agent_id', 'skill_id'])},
    'mcp_connections': {'uq_mcp_connections_user_scope_name': (True, ['user_id', 'scope_agent_id', 'name'])},
    'credential_references': {'uq_credential_references_user_scope_name': (True, ['user_id', 'scope_agent_id', 'name'])},
    'agent_runs': {
        'uq_agent_runs_user_idempotency': (True, ['user_id', 'idempotency_key']),
        'ix_agent_runs_queue_admission': (False, ['user_id', 'source', 'status']),
    },
}


def schema_problems(connection, *, baseline=False):
    from sqlalchemy import inspect
    from models import Base
    import knowledge_models  # noqa: F401  registers knowledge tables on Base.metadata

    inspector = inspect(connection)
    problems = []
    tables = list(ADDED_COLUMNS) + ([] if baseline else list(NEW_TABLES))
    for table in tables:
        if not inspector.has_table(table):
            problems.append(f'{table}: table missing')
            continue
        columns = {column['name']: column for column in inspector.get_columns(table)}
        expected = set(Base.metadata.tables[table].columns.keys())
        if baseline:
            expected -= ADDED_COLUMNS[table]
        missing = expected - columns.keys()
        if missing:
            problems.append(f'{table}: missing columns {", ".join(sorted(missing))}')
        if baseline:
            continue
        if table in ('user_workspaces', 'runtime_cells'):
            computed = columns.get('scope_agent_id', {}).get('computed', {})
            expression = ''.join(str(computed.get('sqltext', '')).lower().replace('`', '').split())
            while expression.startswith('(') and expression.endswith(')'):
                expression = expression[1:-1]
            if expression != 'coalesce(agent_id,0)' or not computed.get('persisted'):
                problems.append(f'{table}.scope_agent_id: expected stored COALESCE(agent_id, 0)')
        indexes = inspector.get_indexes(table)
        actual = {item['name']: (bool(item.get('unique')), item['column_names']) for item in indexes}
        for name, definition in INDEXES.get(table, {}).items():
            if actual.get(name) != definition:
                problems.append(f'{table}: missing or mismatched index {name}')
        legacy_keys = ([['user_id']] if table in ('user_workspaces', 'runtime_cells') else
                       [['user_id', 'skill_id']] if table == 'skill_installations' else
                       [['user_id', 'name']] if table in ('mcp_connections', 'credential_references') else [])
        if any(item.get('unique') and item['column_names'] in legacy_keys for item in indexes):
            problems.append(f'{table}: legacy uniqueness still blocks independent agent resources')
    return problems


DATA_CHECKS = {
    '049: skill bindings not isolated': '''SELECT COUNT(*) FROM expert_skill_bindings b
        LEFT JOIN skill_installations s ON s.id=b.installation_id
        WHERE s.id IS NULL OR s.scope_agent_id<>b.agent_id''',
    '049: MCP bindings not isolated': '''SELECT COUNT(*) FROM expert_mcp_bindings b
        LEFT JOIN mcp_connections c ON c.id=b.connection_id
        WHERE c.id IS NULL OR c.scope_agent_id<>b.agent_id''',
    '052: workbench settings not seeded': '''SELECT COUNT(*) FROM platform_agent_settings
        WHERE status IN ('published','draft') AND NOT EXISTS (SELECT 1 FROM workbench_settings)''',
    '056: agent runtime not migrated': "SELECT COUNT(*) FROM agents WHERE runtime_type='openclaw'",
    '056: session runtime not migrated': "SELECT COUNT(*) FROM agent_sessions WHERE runtime_type='openclaw'",
    '056: policy runtime not migrated': "SELECT COUNT(*) FROM platform_agent_settings WHERE runtime_type='openclaw'",
    '056: cell runtime not migrated': "SELECT COUNT(*) FROM runtime_cells WHERE runtime_type='openclaw'",
    '056: instance not retired': "SELECT COUNT(*) FROM runtime_instances WHERE runtime_type='openclaw' AND status<>'retired'",
    '056: legacy file import pending': '''SELECT COUNT(DISTINCT w.id)
        FROM user_workspaces w JOIN agents a ON (w.agent_id=a.id OR w.id=a.workspace_id)
        JOIN runtime_instances i ON i.agent_id=a.id
        WHERE w.migration_status='pending' AND i.runtime_type='openclaw'
        AND a.runtime_type='claude_code' AND a.is_deleted=0''',
}


def data_problems(connection):
    problems = []
    for label, sql in DATA_CHECKS.items():
        count = connection.exec_driver_sql(sql).scalar()
        if count:
            problems.append(f'{label}: {count}')
    return problems
