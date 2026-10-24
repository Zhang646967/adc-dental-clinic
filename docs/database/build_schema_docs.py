"""Build current ER views and searchable dictionaries from schema metadata.

No database connection or business data is needed. The snapshot was collected
with a read-only transaction from the identified application version.
"""
from pathlib import Path
import hashlib, html, json, re

ROOT = Path(__file__).resolve().parent

# Selected columns keep the printed views legible; schema_snapshot.json and
# FIELD_CATALOG.md retain every ORM column and every actual SQL constraint.
VIEWS = {
    'er_professional_authority': {
        'title':'专业资质来源与限定操作授权',
        'tables': {
            'adc_clinic':['id','clinic_code'],
            'adc_user':['id','username'],
            'adc_booking_service':['id'],
            'adc_clinical_reviewer':['id','user_id','clinic_id','valid_until','is_active'],
            'adc_professional_authorization':['id','user_id','clinic_id','service_id','state','valid_until'],
            'adc_clinical_authority_event':['id','authorization_id','reviewer_id','operation_id'],
            'adc_clinical_authority_policy':['id','clinic_id','activated_by_id'],
        },
        'note':'审核职责按账号与诊所唯一；机构委任不等于病历访问。专业申请分别引用账号、诊所和可空服务；空服务仅指无服务旧记录，不是全服务通配。决定历史及诊所启用事实不可改写。图中仅展开关键外键，来源证据、有效期及查阅／记录／转诊动作见完整目录与命令核验。',
    },
    'er_clinical_referral': {
        'title':'限定跨店转诊与敏感查阅留痕',
        'tables': {
            'adc_patient':['id','patient_no'],
            'adc_clinic':['id','clinic_code'],
            'adc_user':['id','username'],
            'adc_visit':['id','patient_id'],
            'adc_visit_record_version':['id','visit_id','revision_no'],
            'adc_clinical_referral':['id','patient_id','source_visit_id','source_record_id','source_clinic_id','destination_clinic_id','receiver_id','state'],
            'adc_clinical_referral_event':['id','referral_id','actor_id','operation_id'],
            'adc_sensitive_read_event':['id','actor_id','object_kind','object_id','outcome'],
        },
        'note':'转诊保留原患者、原就诊、可选已发布版本、转出／接收诊所及指定医师；身份核对、临床披露同意和医师接收分别办理。不合并档案，不把转诊作为预约或实际诊疗。查阅事件的object_kind/object_id为受控类型与对象编号，不是虚构的患者或转诊外键。其余服务、来源人和有效期在完整目录保留。',
    },
    'er_patient_relationship': {
        'title': '患者关系核验与预约代办授权',
        'tables': {
            'adc_patient': ['id', 'patient_no'],
            'adc_clinic': ['id', 'clinic_code'],
            'adc_user': ['id', 'username'],
            'adc_patient_relationship': ['id','clinic_id','patient_id','delegate_user_id','kind','state','revision'],
            'adc_patient_appointment_grant': ['id','relationship_id','valid_from','valid_until','is_active','revision'],
            'adc_patient_relationship_event': ['id','relationship_id','actor_id','operation_id','action'],
            'adc_workspace_context': ['id','user_id','patient_grant_id','revision'],
        },
        'note': '关系属于患者及核验诊所，账号可在待核验阶段补充。每项关系至多一项预约授权；联系人和普通亲属关系不生成授权。决定事件仅追加，operation_id唯一。上下文可选一个授权，本人入口保持空；有效期、当前账号与本店范围由事务核验，不从外键连线推断病历、资金或临床同意权限。',
    },
    'er_portal_reschedule': {
        'title': '患者授权与预约改期来源',
        'tables': {
            'adc_user': ['id', 'username'],
            'adc_patient_access': ['id', 'user_id', 'patient_id', 'is_active'],
            'adc_patient': ['id', 'patient_no'],
            'adc_portal_booking_receipt': ['id', 'nonce', 'access_id', 'appointment_grant_id', 'visit_id'],
            'adc_patient_appointment_grant': ['id','relationship_id','revision'],
            'adc_visit': ['id', 'patient_id', 'replaces_visit_id', 'status'],
            'adc_wait_offer': ['id', 'visit_id', 'state'],
            'adc_cancellation_followup': ['id', 'visit_id', 'replacement_visit_id', 'state'],
        },
        'note': '本人绑定保留；预约确认回执必须且只能引用本人绑定或预约代办授权之一，nonce唯一，visit_id唯一。预约自引用可空且唯一，构成原约与后继。邀约和取消跟进保留各自原关联，不因后续改期改写；当前患者、本店代约范围和活动状态由事务命令核验，不能从外键推定权限。',
    },
    'er_schedule_coordination': {
        'title': '前台排班与调班责任',
        'tables': {
            'adc_clinic': ['id', 'clinic_code'],
            'adc_dentist': ['id', 'employee_no'],
            'adc_availability_slot': ['id', 'clinic_id', 'dentist_id', 'starts_at', 'ends_at', 'booking_paused'],
            'adc_visit': ['id', 'availability_slot_id', 'status'],
            'adc_wait_offer': ['id', 'slot_id', 'state', 'expires_at'],
            'adc_coordination_task': ['id', 'slot_id', 'assignee_id', 'due_at', 'state'],
            'adc_user': ['id', 'username'],
        },
        'note': '出诊是医师供给，预约与有效邀约是承诺；协调任务经slot_id归店，assignee_id可空，due_at历史可空。每个出诊至多一个活动任务；独立复核与具体预约变更另行办理。',
    },
    'er_booking': {
        'title': '预约与电话接待',
        'tables': {
            'adc_clinic': ['id', 'clinic_code'],
            'adc_dentist': ['id', 'employee_no'],
            'adc_patient': ['id', 'patient_no'],
            'adc_availability_slot': ['id', 'clinic_id', 'dentist_id', 'starts_at', 'ends_at'],
            'adc_visit': ['id', 'patient_id', 'availability_slot_id', 'status'],
            'adc_reception_case': ['id', 'clinic_id', 'patient_id', 'visit_id', 'state'],
            'adc_reception_communication': ['id', 'case_id', 'sequence'],
        },
        'note': '接待可以尚未建档；visit_id唯一且可空，沟通按case_id与sequence保留历史。诊所与医师等未展开外键见字段目录。',
    },
    'er_catalogue': {
        'title': '排班服务与医师适配',
        'tables': {
            'adc_clinic': ['id', 'clinic_code'],
            'adc_department': ['id', 'clinic_id', 'code'],
            'adc_department_hours': ['id', 'department_id', 'weekday', 'opens_at', 'closes_at'],
            'adc_treatment_room': ['id', 'department_id', 'code'],
            'adc_booking_service': ['id', 'department_id', 'duration_minutes'],
            'adc_service_presentation': ['id', 'service_id', 'category', 'fee_mode', 'fee_amount', 'is_published'],
            'adc_service_requirement': ['id', 'service_id', 'category', 'quantity'],
            'adc_booking_service_dentists': ['id', 'bookingservice_id', 'dentist_id'],
            'adc_dentist': ['id', 'employee_no'],
        },
        'note': '服务与医师的多对多关系通过真实连接表实现；科室开放与医师出诊分别保存。每项预约服务至多一份患者说明，未建立、草稿或不完整说明均不公开；费用说明不生成账单。',
    },
    'er_resource_claims': {
        'title': '设备位置与资源占用',
        'tables': {
            'adc_visit': ['id'],
            'adc_wait_offer': ['id', 'visit_id'],
            'adc_booking_service': ['id'],
            'adc_treatment_room': ['id'],
            'adc_resource_plan': ['id', 'visit_id', 'offer_id', 'service_id', 'room_id', 'version', 'is_current'],
            'adc_resource_claim': ['id', 'plan_id', 'asset_id', 'starts_at', 'ends_at', 'active'],
            'adc_equipment_asset': ['id', 'asset_code', 'state'],
            'adc_resource_binding': ['id', 'asset_id', 'room_id', 'shared'],
        },
        'note': '方案必须引用预约或邀约，接受邀约后允许两者同时存在；每个来源至多一个当前方案。牙椅使用设备资产，每项有效占用受时间排斥约束保护。',
    },
    'er_finance': {
        'title': '诊疗结算与资金凭据',
        'tables': {
            'adc_visit': ['id'],
            'adc_visit_record_version': ['id', 'visit_id', 'revision_no'],
            'adc_treatment_record': ['id', 'record_version_id', 'line_no'],
            'adc_invoice': ['id', 'visit_id', 'current_record_version_id'],
            'adc_cash_entry': ['id', 'invoice_id', 'amount', 'state'],
            'adc_cash_evidence': ['id', 'cash_entry_id', 'account_id', 'version'],
            'adc_payment_account': ['id'],
            'adc_statement_line': ['id', 'account_id', 'transaction_id'],
            'adc_reconciliation_match': ['id', 'cash_entry_id', 'evidence_id', 'line_id', 'state'],
        },
        'note': '每次就诊至多一个逻辑账单；账单另有复合外键保证当前记录版本属于同一次就诊。凭据与匹配保留多次历史，活动匹配的唯一性由条件约束限定。',
    },
}


def sql_foreign_key(item):
    m = re.match(r'FOREIGN KEY \(([^)]+)\) REFERENCES ([^ (]+)\(([^)]+)\)', item['definition'])
    assert m, item
    return item['table'], [s.strip() for s in m[1].split(',')], m[2], [s.strip() for s in m[3].split(',')]


def build():
    data = json.loads((ROOT/'schema_snapshot.json').read_text())
    models = {m['table']: m for m in data['models']}
    assert set(data['tables']) == set(models) | {'django_migrations'}
    normalize_type=lambda s: re.sub(r'\s+','',s.replace('character varying','varchar').replace('time without time zone','time'))
    actual_columns={(c['table'],c['column']):c for c in data['columns']}
    checked_columns=0
    type_differences=[]
    for table,model in models.items():
        assert {f['column'] for f in model['fields']}=={c['column'] for c in data['columns'] if c['table']==table}
        for f in model['fields']:
            column=actual_columns[table,f['column']]
            assert f['null']==column['null'], (table,f['column'],'nullability')
            if normalize_type(f['db_type'])!=normalize_type(column['db_type']):
                type_differences.append(dict(table=table,column=f['column'],model_type=f['db_type'],database_type=column['db_type']))
            if f['unique']:
                key='PRIMARY KEY' if f['pk'] else 'UNIQUE'
                assert any(c['table']==table and c['definition']==key+' ('+f['column']+')' for c in data['constraints']), (table,f['column'],'single-column key')
            checked_columns+=1
    sql_fks = [sql_foreign_key(c) for c in data['constraints'] if c['kind']=='f']
    expected = {(t, (f['column'],), f['target_table'], (f['target_column'],))
                for t,m in models.items() for f in m['fields'] if f['target_table']}
    actual = {(t, tuple(cols), parent, tuple(targets)) for t,cols,parent,targets in sql_fks}
    assert expected <= actual, 'ORM relation missing from actual SQL constraints'
    assert actual-expected == {('adc_invoice', ('current_record_version_id', 'visit_id'),
                               'adc_visit_record_version', ('id', 'visit_id'))}, 'Review additional SQL-only relations before publishing'
    # Preserve actual SQL semantics, including the invoice composite foreign key.
    dbml = ['// Current database ER source; selected view diagrams are projections.',
            f'// All {len(models)} ORM tables; django_migrations is a framework migration journal.',
            '// Partial uniqueness, exclusions and triggers are documented separately.', '']
    catalog = ['# 当前数据库字段目录', '',
        '结构基线日期：'+data['observed_on']+f'。本目录列出{len(models)}张ORM业务／框架表；另1张django_migrations为框架迁移日志。', '',
        '字段类型、可空、SQL约束及索引来自数据库只读结构核对；模型映射来自同版本已运行应用。没有读取任何业务行、密码、配置值或字段默认值。', '',
        'PK=主键；UK=单列唯一；FK=外键；NULL=可空。复合唯一、条件唯一和排斥约束另列，不用单列UK代替。', '']
    for name,m in models.items():
        catalog += ['## '+name, '', '模型：`'+m['model']+'`'+('；ORM生成的连接表。' if m['auto_created'] else '。'), '',
                    '| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |', '|---|---|---|---|---|']
        dbml += ['Table '+name+' {']
        for f in m['fields']:
            actual_type=actual_columns[name,f['column']]['db_type']
            flags = [v for k,v in [('pk','PK'),('unique','UK'),('target_table','FK')] if f.get(k) and not (k=='unique' and f['pk'])]
            target = f"`{f['target_table']}.{f['target_column']}`" if f['target_table'] else '—'
            catalog += [f"| {f['column']} | {actual_type} | {' / '.join(flags) or '—'} | {'是' if f['null'] else '否'} | {target} |"]
            dbflags = (['pk'] if f['pk'] else ['unique'] if f['unique'] else []) + (['null'] if f['null'] else ['not null'])
            dbml += ['  '+f['column']+' '+json.dumps(actual_type)+' ['+', '.join(dbflags)+']']
        for diff in type_differences:
            if diff['table']==name:
                catalog += ['', '兼容性记录：`'+diff['column']+'`的模型类型为`'+diff['model_type']+'`，实际数据库类型为`'+diff['database_type']+'`。本目录按实际类型记录；未执行缩窄字段或改写历史。']
        catalog += ['', '数据库约束：', '']
        catalog += ['- `'+c['name']+'`：`'+c['definition'].replace('|','\\|')+'`。'
                    for c in data['constraints'] if c['table']==name]
        catalog += ['', '索引（含条件唯一索引）：', '']
        catalog += ['- `'+i['name']+'`：`'+i['definition'].replace('|','\\|')+'`。'
                    for i in data['indexes'] if i['table']==name]
        catalog += ['', '跨表及历史触发器：', '']
        catalog += ['- `'+t['name']+'`：`'+t['definition'].replace('|','\\|')+'`。'
                    for t in data.get('triggers',[]) if t['table']==name]
        catalog += ['']
        composite=[]
        for c in data['constraints']:
            if c['table']!=name or c['kind']!='u':continue
            match=re.fullmatch(r'UNIQUE \(([^)]+)\)',c['definition'])
            if match and ',' in match[1]:composite.append((match[1],c['name']))
        if composite:
            dbml += ['  indexes {']
            dbml += ["    ("+cols+") [unique, name: '"+constraint+"']" for cols,constraint in composite]
            dbml += ['  }']
        dbml += ['}', '']
    for t,cols,parent,targets in sql_fks:
        side=lambda table,columns: table+'.'+(columns[0] if len(columns)==1 else '('+', '.join(columns)+')')
        unique=any(f['column'] in cols and f['unique'] for f in models[t]['fields'])
        dbml += ['Ref: '+side(t,cols)+(' - ' if unique else ' > ')+side(parent,targets)]
    (ROOT/'schema.dbml').write_text('\n'.join(dbml).rstrip()+'\n')
    (ROOT/'FIELD_CATALOG.md').write_text('\n'.join(catalog).rstrip()+'\n')
    relation_lines=['# 当前数据库外键关系', '',
        f'{len(sql_fks)}条实际SQL外键，其中{len(expected)}条对应ORM单列关系，1条为账单同次就诊复合外键。', '',
        '| 子表 | 外键列 | 父表 | 被引用列 |', '|---|---|---|---|']
    relation_lines += ['| '+t+' | '+', '.join(cols)+' | '+parent+' | '+', '.join(targets)+' |' for t,cols,parent,targets in sql_fks]
    (ROOT/'RELATIONSHIPS.md').write_text('\n'.join(relation_lines)+'\n')
    result = {}
    for name,view in VIEWS.items():
        parts=['digraph schema {', 'graph [rankdir=TB, bgcolor="white", pad="0.2", nodesep="0.40", ranksep="0.48", splines=polyline, outputorder=edgesfirst];',
               'node [shape=plain, fontname="Arial", fontsize=14];',
               'edge [color="#505965", arrowsize=0.8, dir=both];']
        edges=[]
        for table,columns in view['tables'].items():
            fields={f['column']:f for f in models[table]['fields']}
            assert set(columns)<=set(fields), (table,set(columns)-set(fields))
            rows=['<TR><TD COLSPAN="2" BGCOLOR="#e8edf2" BORDER="1"><B>'+table+'</B></TD></TR>']
            for col in columns:
                f=fields[col]
                key='PK' if f['pk'] else ('FK/UK' if f['unique'] else 'FK') if f['target_table'] else 'UK' if f['unique'] else ''
                rows += ['<TR><TD ALIGN="LEFT">'+key+'</TD><TD ALIGN="LEFT" PORT="'+col+'">'+html.escape(col)+(' ?' if f['null'] else '')+'</TD></TR>']
                if f['target_table'] in view['tables']:
                    assert f['target_column'] in view['tables'][f['target_table']]
                    edges.append((table,col,f['target_table'],f['target_column'], '0..1' if f['unique'] else '0..*', '0..1' if f['null'] else '1'))
            parts += ['"'+table+'" [label=<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4">'+''.join(rows)+'</TABLE>>];']
        for t,col,parent,pcol,child_mult,parent_mult in edges:
            parent_symbol='teeodot' if parent_mult=='0..1' else 'teetee'
            child_symbol='teeodot' if child_mult=='0..1' else 'crowodot'
            layout=', constraint=false' if (t,col)==('adc_reception_case','visit_id') else ''
            parts += ['"'+parent+'" -> "'+t+'" [arrowtail="'+parent_symbol+'", arrowhead="'+child_symbol+'"'+layout+', tooltip="'+t+'.'+col+' references '+parent+'.'+pcol+'; '+child_mult+':'+parent_mult+'"];']
        parts += ['}']
        (ROOT/(name+'.dot')).write_text('\n'.join(parts)+'\n')
        result[name]=dict(title=view['title'],tables=len(view['tables']),relationships=len(edges),note=view['note'],columns=view['tables'])
    result['validation'] = dict(passed=True,tables=len(data['tables']),orm_tables=len(models),columns_types_and_nullability_checked=checked_columns,model_database_type_differences=type_differences,orm_foreign_keys=len(expected),sql_foreign_keys=len(sql_fks),
        sql_only_composite_foreign_keys=1, snapshot_sha256=hashlib.sha256((ROOT/'schema_snapshot.json').read_bytes()).hexdigest(),
        scope='Structure documentation only; this is not a new business or capacity acceptance result.')
    (ROOT/'view_manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:({i:v[i] for i in ('tables','relationships')} if k!='validation' else v) for k,v in result.items()},ensure_ascii=False))


if __name__=='__main__':
    build()
