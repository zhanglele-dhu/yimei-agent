import tempfile,unittest
from pathlib import Path
from studio import writing_style,tones

class WritingStyleTests(unittest.TestCase):
 def test_verified_source_snippets_exclude_templates(self):
  cases=[{'id':'test'+str(i),'title':'表达示例','url':'https://example.org/'+str(i),'body':q} for i,q in enumerate(['这一点怎么理解？我们先看它的作用。','名字很多，我们按用途慢慢梳理。','看起来复杂，其实可以先分两步。'])]
  cases.append({'id':'row045','title':'M22体验','url':'https://www.xiaohongshu.com/explore/row045','body':'以上文案仅供参考，今天给大家分享'})
  with tempfile.TemporaryDirectory() as temp:
   manifest={'bundle_id':'fixture','cases':[{**c,'pages':[{'ocr':''}]} for c in cases]}
   labels={c['id']:{'case_id':c['id'],'status':'classified','voice_id':'friend-sharing','confidence':.9,
      'evidence':[{'quote':c['body']}],'reason':'平等口语分享','matched_rules':['friend-sharing.1']} for c in cases[:3]}
   tones.save(Path(temp),manifest,{'version':tones.VERSION,'bundle_id':'fixture','labels':labels,'updated_at':None})
   result=writing_style.profile(Path(temp),manifest)
   self.assertEqual(len(result['source_examples']),3)
   self.assertIn('row045',result['excluded_template_ids'])
   for example in result['source_examples']:
    self.assertIn(example['quote'],next(c['body'] for c in cases if c['id']==example['case_id']))
   self.assertTrue((Path(temp)/'style_library/friend-sharing.json').exists())
 def test_lecture_chain_is_not_mistaken_for_friend_voice(self):
  draft={'pages':[{'number':1,'text':'换滤片，本质是换波段，不是按功能按钮，也不是叠加效果。先理解这一点，再看具体分工。'}]}
  issues=writing_style.voice_issues(draft)
  self.assertEqual(len(issues),2)
  self.assertEqual(writing_style.voice_issues({'pages':[{'number':1,'text':'滤片名字看着多，按分工来认就清楚多了。'}]}),[])
 def test_no_fake_examples_when_imported_bundle_lacks_them(self):
  with tempfile.TemporaryDirectory() as temp:
   result=writing_style.profile(Path(temp),{'bundle_id':'empty','cases':[]})
   self.assertEqual(result['source_examples'],[])
   self.assertIn('编辑编写',result['guide'])
   self.assertNotIn('source_examples',writing_style.context({'writing_style':result}))

if __name__=='__main__':unittest.main()
