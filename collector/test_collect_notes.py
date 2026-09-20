import json
import tempfile
import unittest
from pathlib import Path
from collect_notes import parse_count, safe_cell, export, read_note


class Tests(unittest.IsolatedAsyncioTestCase):
    def test_counts(self):
        self.assertEqual(parse_count('1.2万'), 12000)
        self.assertEqual(parse_count('2k'), 2000)
        self.assertEqual(parse_count('0'), 0)
        self.assertIsNone(parse_count('点赞'))
        self.assertIsNone(parse_count(None))

    def test_export(self):
        with tempfile.TemporaryDirectory() as folder:
            stem = Path(folder) / 'result'
            export([{'title': '=1+1', 'likes': None}], [], 'M22', stem, 'test')
            self.assertIsNone(json.loads(stem.with_suffix('.json').read_text(encoding='utf-8'))['items'][0]['likes'])
            self.assertIn("'=1+1", stem.with_suffix('.csv').read_text(encoding='utf-8-sig'))
        self.assertEqual(safe_cell(0), '0')

    async def test_note(self):
        class Page:
            async def evaluate(self, script):
                return {'type': 'normal', 'title': '测试', 'desc': '正文',
                        'interactInfo': {'likedCount': '1.2万', 'commentCount': '0'},
                        'imageList': [{'urlDefault': 'https://example.com/image.jpg'}]}
        row = await read_note(Page(), 'https://example.com/note')
        self.assertEqual(row['likes'], 12000)
        self.assertEqual(row['comments'], 0)
        self.assertIsNone(row['favorites'])
        self.assertIn('favorites', row['missing_fields'])

    async def test_video_skipped(self):
        class Page:
            async def evaluate(self, script):
                return {'type': 'video'}
        self.assertIsNone(await read_note(Page(), 'test'))


if __name__ == '__main__':
    unittest.main()
