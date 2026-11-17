import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from studio import tones,writing_style

class ToneLibraryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  def note(id,body):return {'id':id,'title':'同一M22内容','body':body,'url':'https://www.xiaohongshu.com/explore/'+id,'pages':[{'ocr':''}]}
  self.manifest={'bundle_id':'fixture','cases':[note('one','名字太多容易看晕，给你捋清楚。'),note('two','#M22'),note('bad','以上文案仅供参考')]}
 def fake(self,schema,instruction,sources):
  result=[]
  for case in instruction['cases']:
   if case['case_id']=='two':result.append({'case_id':'two','voice_id':'uncertain','confidence':.3,'reason':'只有话题标签'})
   else:result.append({'case_id':case['case_id'],'voice_id':'friend-sharing','confidence':.9,'reason':'平等口语介绍',
      'matched_rules':['friend-sharing.1'],'quote_ids':[case['quote_options'][0]['quote_id']]})
  return schema(items=result),{'provider':'mock','model':'test'}
 def test_semantic_batch_provenance_exclusion_and_resume(self):
  initial=tones.catalog(self.root,self.manifest);self.assertEqual(initial['summary']['pending'],2)
  with patch.object(tones.llm,'generate',side_effect=self.fake) as model:
   result=tones.analyze_batch(self.root,self.manifest);again=tones.analyze_batch(self.root,self.manifest)
  self.assertEqual(model.call_count,1);self.assertEqual(result['summary'],{'total':3,'classified':1,'uncertain':1,'excluded':1,'pending':0})
  self.assertEqual(again['summary'],result['summary'])
  self.assertEqual(result['items'][0]['evidence'][0]['quote'],self.manifest['cases'][0]['body'])
  self.assertEqual(len(model.call_args.args[1]['standards']),6)
  profile=writing_style.profile(self.root,self.manifest)
  self.assertEqual([x['case_id'] for x in profile['source_examples']],['one'])
  self.assertEqual(writing_style.profile(self.root,self.manifest,'neutral')['source_examples'],[])
 def test_invalid_rule_or_quote_does_not_publish_batch(self):
  def invalid(*args,**kwargs):
   result,trace=self.fake(*args,**kwargs);result.items[0].matched_rules=['neutral.1'];return result,trace
  with patch.object(tones.llm,'generate',side_effect=invalid):
   with self.assertRaises(ValueError):tones.analyze_batch(self.root,self.manifest)
  self.assertFalse(tones.path_for(self.root,self.manifest).exists())
 def test_each_tone_requires_exact_criteria_and_literal_draft_evidence(self):
  draft={'pages':[{'number':1,'text':'读者看到的当前正文。'}]}
  for preset in tones.PRESETS:
   check={'style_id':preset['id'],'passed':True,'criteria':[{'rule_id':r['id'],'passed':True,'quote':'当前正文','reason':'依据'} for r in preset['criteria']]}
   self.assertTrue(tones.validate_check(check,preset,draft))
   altered=copy.deepcopy(check);altered['criteria'][0]['passed']=False
   self.assertFalse(tones.validate_check(altered,preset,draft))
   altered=copy.deepcopy(check);altered['style_id']='wrong'
   with self.assertRaises(ValueError):tones.validate_check(altered,preset,draft)
   altered=copy.deepcopy(check);altered['criteria'].pop()
   with self.assertRaises(ValueError):tones.validate_check(altered,preset,draft)
   altered=copy.deepcopy(check);altered['criteria'][0]['quote']='原文没有的句子'
   with self.assertRaises(ValueError):tones.validate_check(altered,preset,draft)

if __name__=='__main__':unittest.main()
