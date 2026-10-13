"""Executed without Django. HTTP adapters use mocks; no paid model calls."""
from datetime import datetime,timedelta,timezone
from dataclasses import replace
import ast
import hashlib
import io
import json
from pathlib import Path
import urllib.error
from unittest import TestCase
from unittest.mock import patch,MagicMock
from assistants.protocol import (validate_message,redact,local_intent,parse_decision,system_prompt,AIProtocolError,INTENTS)
from assistants.provider import ProviderConfig,ProviderError,endpoint,classify,NoRedirect
from portal.rules import validate_public_start
from adc_core.rules import RuleError
from scripts.configure_ai import merge_env

ROOT=Path(__file__).resolve().parents[1]

class ProtocolTests(TestCase):
    def test_message_rejects_wrong_types(self):
        for obj in (None,{},[],1,True):
            with self.subTest(obj=obj),self.assertRaises(AIProtocolError): validate_message(obj)
    def test_message_rejects_empty_and_long(self):
        for obj in ('','  ','x'*801,'\u200b'):
            with self.subTest(obj=obj[:5]),self.assertRaises(AIProtocolError): validate_message(obj)
    def test_secret_is_blocked(self):
        for msg in ('sk-abcdefgh12345678','这是sk-abcdefgh12345678','API_KEY=secret','Bearer dont-send-this'):
            with self.subTest(msg=msg),self.assertRaises(AIProtocolError): validate_message(msg)
    def test_control_and_bidi_removed(self):
        self.assertEqual(validate_message('我要\u202e预\u200b约'),'我要预约')
    def test_phone_redacted_next_to_chinese(self):
        self.assertNotIn('13800138000',redact('电话13800138000'))
    def test_email_redacted(self): self.assertNotIn('name@example.com',redact('mail name@example.com'))
    def test_id_redacted(self): self.assertNotIn('110101200001012345',redact('证件110101200001012345'))
    def test_names_are_not_claimed_anonymous(self): self.assertIn('张某',redact('张某想预约'))
    def test_medical_is_routed_to_human(self):
        for q in ('牙痛怎么办','阿莫西林怎么吃','is antibiotic dosage correct','肿胀怎么处理'):
            for audience in INTENTS:
                self.assertEqual(local_intent(q,audience),'clinical')
    def test_patient_common_intents(self):
        for q,intent in [('我想预约','book'),('我的预约几点','appointments'),('取消预约','cancel'),('账单费用怎么看','bill'),('字体太小','accessibility'),('家属能代办吗','human')]:
            self.assertEqual(local_intent(q,'patient'),intent)
    def test_staff_common_intents(self):
        for q,intent in [('今日工作概览','overview'),('改期规则','appointment_policy'),('接诊过敏怎么复核','care_help'),('结算流程','billing_policy')]:
            self.assertEqual(local_intent(q,'staff'),intent)
    def test_valid_contract(self): self.assertEqual(parse_decision('{"intent":"book","confidence":0.9}','patient'),'book')
    def test_low_confidence_is_help(self): self.assertEqual(parse_decision('{"intent":"book","confidence":0.3}','patient'),'help')
    def test_cross_audience_intent_rejected(self):
        with self.assertRaises(AIProtocolError): parse_decision('{"intent":"overview","confidence":1}','patient')
    def test_extra_commands_rejected(self):
        with self.assertRaises(AIProtocolError): parse_decision('{"intent":"book","confidence":1,"sql":"DROP TABLE x"}','patient')
    def test_free_text_and_markup_rejected(self):
        for raw in ('<script>alert(1)</script>','```json\n{}\n```','[]','null'):
            with self.assertRaises(AIProtocolError): parse_decision(raw,'patient')
    def test_invalid_confidence_rejected(self):
        for p in ('NaN','Infinity','true','-1','2','"0.9"'):
            with self.assertRaises(AIProtocolError): parse_decision('{"intent":"book","confidence":'+p+'}','patient')
    def test_classifier_prompt_contains_no_context(self):
        p=system_prompt('patient');self.assertIn('Do not answer',p);self.assertNotIn('patient_no',p)

class ProviderTests(TestCase):
    def setUp(self):
        self.cfg=ProviderConfig('https://api.openai.com/v1','synthetic-test-key','test-model',('api.openai.com',))
    def test_endpoint(self): self.assertEqual(endpoint(self.cfg),'https://api.openai.com/v1/chat/completions')
    def test_unapproved_host_rejected(self):
        with self.assertRaises(ProviderError): endpoint(replace(self.cfg,base_url='https://evil.example/v1'))
    def test_plain_http_rejected(self):
        with self.assertRaises(ProviderError): endpoint(replace(self.cfg,base_url='http://api.openai.com/v1'))
    def test_embedded_user_and_query_rejected(self):
        for url in ('https://user@api.openai.com/v1','https://api.openai.com/v1?key=a','https://api.openai.com:444/v1'):
            with self.assertRaises(ProviderError): endpoint(replace(self.cfg,base_url=url))
    def test_private_host_rejected_even_allowlisted(self):
        for host in ('127.0.0.1','localhost','169.254.169.254'):
            with self.assertRaises(ProviderError): endpoint(replace(self.cfg,base_url='https://'+host,allowed_hosts=(host,)))
    def test_missing_key_or_model_rejected(self):
        for cfg in (replace(self.cfg,api_key=''),replace(self.cfg,model='')):
            with self.assertRaises(ProviderError): endpoint(cfg)
    def test_redirect_blocked(self):
        with self.assertRaises(ProviderError): NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example')
    def transport(self,body):
        response=MagicMock();response.__enter__.return_value=response;response.read.return_value=body
        opener=MagicMock();opener.open.return_value=response
        return opener
    def body(self,content='{"intent":"book","confidence":0.99}',finish='stop'):
        return json.dumps({'choices':[{'finish_reason':finish,'message':{'content':content}}]}).encode()
    def test_classify_success_and_payload_minimisation(self):
        opener=self.transport(self.body())
        with patch('urllib.request.build_opener',return_value=opener): self.assertEqual(classify('我想预约','patient',self.cfg),'book')
        request=opener.open.call_args.args[0];payload=json.loads(request.data)
        self.assertEqual(set(payload),{'model','messages','response_format','max_completion_tokens','stream'})
        self.assertEqual(payload['messages'][1],{'role':'user','content':'我想预约'})
        self.assertEqual(payload['max_completion_tokens'],256)
        self.assertNotIn('tools',payload);self.assertFalse(payload['stream'])
    def test_compatible_token_parameter(self):
        opener=self.transport(self.body())
        with patch('urllib.request.build_opener',return_value=opener): classify('book','patient',replace(self.cfg,token_field='max_tokens'))
        self.assertEqual(json.loads(opener.open.call_args.args[0].data)['max_tokens'],256)
    def test_truncated_output_rejected(self):
        with patch('urllib.request.build_opener',return_value=self.transport(self.body(finish='length'))),self.assertRaises(ProviderError): classify('book','patient',self.cfg)
    def test_invalid_response_types(self):
        for body in (b'[]',b'{}',b'{"choices":["bad"]}',b'not-json'):
            with patch('urllib.request.build_opener',return_value=self.transport(body)),self.assertRaises(ProviderError): classify('book','patient',self.cfg)
    def test_oversize_response_rejected(self):
        with patch('urllib.request.build_opener',return_value=self.transport(b'x'*32769)),self.assertRaises(ProviderError): classify('book','patient',self.cfg)
    def test_auth_error_does_not_echo_body_or_key(self):
        opener=MagicMock();opener.open.side_effect=urllib.error.HTTPError('https://x',401,'secret-might-be-here',{},io.BytesIO(b'synthetic-test-key'))
        with patch('urllib.request.build_opener',return_value=opener):
            with self.assertRaises(ProviderError) as cm: classify('book','patient',self.cfg)
        self.assertEqual(str(cm.exception),'provider_auth')
    def test_timeout_not_retried(self):
        opener=MagicMock();opener.open.side_effect=TimeoutError()
        with patch('urllib.request.build_opener',return_value=opener),self.assertRaises(ProviderError): classify('book','patient',self.cfg)
        self.assertEqual(opener.open.call_count,1)

class PortalAndPackageTests(TestCase):
    def setUp(self): self.now=datetime(2026,9,22,8,tzinfo=timezone.utc);self.start=self.now+timedelta(days=1)
    def test_valid_30_min_booking(self): self.assertEqual(validate_public_start(self.start,self.start,self.start+timedelta(hours=4),self.now),self.start+timedelta(minutes=30))
    def test_off_grid_time_rejected(self):
        with self.assertRaises(RuleError): validate_public_start(self.start+timedelta(minutes=10),self.start,self.start+timedelta(hours=2),self.now)
    def test_outside_horizon_rejected(self):
        t=self.now+timedelta(days=15)
        with self.assertRaises(RuleError): validate_public_start(t,t,t+timedelta(hours=2),self.now)
    def test_past_booking_rejected(self):
        with self.assertRaises(RuleError): validate_public_start(self.now-timedelta(hours=1),self.now-timedelta(hours=1),self.start,self.now)
    def test_booking_end_must_fit(self):
        with self.assertRaises(RuleError): validate_public_start(self.start,self.start,self.start+timedelta(minutes=20),self.now)
    def test_naive_time_rejected(self):
        with self.assertRaises(RuleError): validate_public_start(self.start.replace(tzinfo=None),self.start,self.start+timedelta(hours=1),self.now)
    def test_env_update_preserves_database_secrets(self):
        before='DJANGO_SECRET_KEY=keep\nPOSTGRES_PASSWORD=stay\nAI_MODE=demo\n'
        after=merge_env(before,{'AI_MODE':'remote','AI_API_KEY':'private-example'})
        self.assertIn('DJANGO_SECRET_KEY=keep',after);self.assertIn('POSTGRES_PASSWORD=stay',after);self.assertEqual(after.count('AI_MODE='),1)
    def test_transcript_not_saved_in_browser(self):
        js=(ROOT/'static/assistant.js').read_text()
        self.assertNotIn('localStorage',js);self.assertNotIn('innerHTML',js);self.assertNotIn('eval(',js)
    def test_voice_is_local_only_and_opt_in(self):
        js=(ROOT/'static/assistant.js').read_text()
        self.assertIn('v.localService === true',js);self.assertNotIn('getUserMedia',js);self.assertNotIn('SpeechRecognition',js)
    def test_no_secret_in_static_or_templates(self):
        for folder in ('static','templates'):
            for p in (ROOT/folder).rglob('*'):
                if p.is_file():
                    text=p.read_text();self.assertNotIn('AI_API_KEY',text);self.assertNotIn('OPENAI_API_KEY',text)
    def test_all_original_migrations_unchanged(self):
        checks=json.loads((ROOT/'docs/original_migration_hashes.json').read_text())
        for path,digest in checks.items(): self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)
    def test_source_has_no_hidden_control_chars(self):
        for path in ROOT.rglob('*.py'):
            text=path.read_text()
            self.assertFalse(any(ord(c)<32 and c not in '\n\t\r' for c in text),str(path))
