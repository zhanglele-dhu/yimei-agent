import io,json,tempfile,unittest,zipfile
from pathlib import Path
from PIL import Image
from export_cases import build_bundle

class CaseExportTests(unittest.TestCase):
    def test_current_bundle_matches_ocr_and_originals(self):
        root=Path(__file__).parent/'data/m22_analysis'
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'cases.zip';m=build_bundle(root,out)
            self.assertEqual(len(m['cases']),87)
            self.assertEqual(sum(len(c['pages']) for c in m['cases']),233)
            self.assertEqual(sum(not p['ocr'].strip() for c in m['cases'] for p in c['pages']),13)
            self.assertEqual(m['cases'][0]['likes'],2122)
            self.assertEqual([p['number'] for p in m['cases'][0]['pages']],[1,2])
            self.assertEqual(m['cases'][75]['research']['source']['row_id'],'row075')
            self.assertEqual(len(m['cases'][75]['pages']),1)  # Body is not a second image.
            with zipfile.ZipFile(out) as z:
                self.assertEqual(len(z.namelist()),234)
                for c in m['cases']:
                    self.assertTrue(all(p['image'].startswith('images/') for p in c['pages']))
                    if c['research']:
                        self.assertNotIn('local_image', c['research']['ocr_evidence'])
                for c in m['cases']:
                    for p in c['pages']:Image.open(io.BytesIO(z.read(p['image']))).verify()

if __name__=='__main__':unittest.main()
