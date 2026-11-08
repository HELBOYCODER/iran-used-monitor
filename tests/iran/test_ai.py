import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from iran_monitor.core import Store
from iran_monitor.engine import Engine


class AITests(unittest.TestCase):
    def test_ai_below_threshold_not_notified_and_duplicates_not_paid(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(str(Path(tmp)/'db'))
            watch=store.create_watch({'name':'test','query':'test','source':'divar'})
            def scanner(w): return [dict(source='divar',title='test',price=10,url='https://divar.ir/v/a',image='',city='tehran',description='',score=None,ai_evaluated=False,reason='local')]
            engine=Engine(store,scanner)
            store.set_settings({'ai_enabled':True})
            def model(score): return json.dumps({'choices':[{'message':{'content':json.dumps({'score':score,'reason':'evaluated'})}}]})
            with patch.dict('os.environ',{'OPENAI_API_KEY':'test-key','OPENAI_MODEL':'test-model'}):
                with patch('iran_monitor.engine.fetch',return_value=model(10)):
                    self.assertEqual(engine.scan(watch['id'])['new_items'],0)
                    self.assertEqual(store.notifications(),[])
                engine.last_source_call.clear()
                with patch('iran_monitor.engine.fetch',return_value=model(90)) as fetch:
                    self.assertEqual(engine.scan(watch['id'])['new_items'],1)
                    engine.last_source_call.clear()
                    engine.scan(watch['id'])
                    self.assertEqual(fetch.call_count,1)
                    self.assertTrue(store.list_items({})[0]['ai_evaluated'])

    def test_local_scores_are_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=Engine(Store(str(Path(tmp)/'db')))
            item=engine.ai_relevance({},dict(score=None,ai_evaluated=False,reason='local'))
            self.assertIsNone(item['score'])
            self.assertFalse(item['ai_evaluated'])
            self.assertEqual(engine.settings()['ai_budget_per_scan'],1)

if __name__=='__main__': unittest.main()
