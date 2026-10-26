"""Offline regression for the one deployed-service verification entrypoint."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from checks.serving import verify_service as verifier


class ServiceVerificationChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.release=root/'release.json'
        self.release.write_text(json.dumps({'bundles':{'phishing':{'model_version':'phishing-test'}}}))
        self.fixtures=root/'fixtures';self.fixtures.mkdir()
        self.packet={'task_id':'phishing','sample_id':'sample','target':'0x'+'11'*20,'cutoff':42,
                     'model_version':'phishing-test','scaler_sha256':'test-scaler','graph_sample':{}}
        self.result={**{k:self.packet[k] for k in ('task_id','sample_id','target','cutoff','model_version','scaler_sha256')},
            'status':'ok','score':.42,'result_origin':'model','label':'High Risk','risk_band':'high',
            'risk_band_policy_version':'test-policy','decision':'screen_positive'}
        expected={k:self.result[k] for k in ('task_id','model_version','score','decision','label','risk_band','risk_band_policy_version')}
        (self.fixtures/'one.json').write_text(json.dumps({'packet':self.packet,'expected':expected}))
        self.calls=[];self.changes={};self.ready=True;self.available=True

    def request(self,url,method='GET',body=None,headers=None,*,timeout=180):
        self.calls.append((url,method,body,headers,timeout))
        if url.endswith('/health/live'):return 200,{'status':'ok'}
        if url.endswith('/health/ready'):return 200,{'status':'ready','loaded_tasks':['phishing'] if self.ready else []}
        if url.endswith('/models'):return 200,{'status':'ready','tasks':[{'task_id':'phishing',
            'model_version':'phishing-test','model_available':self.available}]}
        if not headers or headers.get('X-Inference-Key')!='test-key':return 401,{}
        return 200,{**self.result,**self.changes}

    def verify(self,**options):
        with patch.object(verifier,'call',side_effect=self.request),redirect_stdout(io.StringIO()) as output:
            verifier.verify('https://model.example',release=self.release,fixtures=self.fixtures,
                            headers={'X-Inference-Key':'test-key'},timeout=17,**options)
        return output.getvalue()

    def test_merges_health_catalog_authentication_and_saved_packet_checks(self):
        payload=Path(self.temp.name)/'input.json';payload.write_text(json.dumps(self.packet))
        output=self.verify(payload=payload)
        self.assertIn('PASS:',output);self.assertNotIn('test-key',output)
        self.assertTrue(any(url.endswith('/health/ready') for url,*_ in self.calls))
        predictions=[row for row in self.calls if row[0].endswith('/predict')]
        self.assertEqual(len(predictions),3)  # Missing-key probe, fixed fixture, optional packet.
        self.assertTrue(all(row[4]==17 for row in predictions))

    def test_not_ready_or_unavailable_model_fails_before_prediction(self):
        for attribute in ('ready','available'):
            with self.subTest(attribute=attribute):
                self.calls=[];setattr(self,attribute,False)
                with self.assertRaises(SystemExit):self.verify()
                self.assertFalse(any(row[0].endswith('/predict') for row in self.calls))
                setattr(self,attribute,True)

    def test_rejects_wrong_binding_nonfinite_scores_and_missing_labels(self):
        for changes in ({'sample_id':'wrong'},{'model_version':'wrong'},{'scaler_sha256':'wrong'},
                        {'score':float('nan')},{'score':True},{'label':None},{'result_origin':'synthetic'},
                        {'score':.41},{'decision':'screen_negative'},
                        {'risk_band':'low','label':'Low Risk'},{'risk_band_policy_version':'wrong'}):
            with self.subTest(changes=changes),self.assertRaises(SystemExit):
                self.changes=changes;self.verify()

    def test_hugging_face_token_never_goes_to_modal_or_unrelated_hosts(self):
        with patch.dict(os.environ,{'HF_TOKEN':'hf-private','INFERENCE_API_KEY':'test-key'},clear=True):
            for url in ('https://app.modal.run','http://localhost:7860','https://hf.space.example.com'):
                self.assertEqual(verifier.request_headers(url),{'X-Inference-Key':'test-key'})
            for url in ('https://owner-service.hf.space','https://huggingface.co'):
                self.assertEqual(verifier.request_headers(url)['Authorization'],'Bearer hf-private')

    def test_cli_rejects_invalid_timeout_before_network_access(self):
        with patch('sys.argv',['verify_service','https://model.example','--timeout','-1']),patch.object(verifier,'call') as call:
            with redirect_stdout(io.StringIO()),patch('sys.stderr',io.StringIO()),self.assertRaises(SystemExit):
                verifier.main()
            call.assert_not_called()
