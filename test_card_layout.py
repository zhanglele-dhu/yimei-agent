import io
import unittest

from PIL import Image, ImageChops

from studio import rendering
from studio.card_layout import split_production_notes


class CardLayoutTests(unittest.TestCase):
    def test_production_notes_excluded_without_changing_public_copy(self):
        text = '先了解门店流程。\n\n实拍建议：拍摄前台。\n避免出现顾客信息。\n\n保留你的咨询问题。'
        public, notes = split_production_notes(text)
        self.assertEqual(public, '先了解门店流程。\n\n保留你的咨询问题。')
        self.assertEqual(len(notes), 1)
        image, meta = rendering.render_themed('咨询前', text, 'minimal', 1, 3)
        clean_image, _ = rendering.render_themed('咨询前', public, 'minimal', 1, 3)
        self.assertEqual(image, clean_image)
        self.assertEqual(meta['production_notes'], notes)
        self.assertIn('实拍建议', text)

    def test_ordinary_advice_is_preserved(self):
        text = '到店建议：提前整理问题。\n拍摄是了解流程的一种方式。\n\n医生建议以面诊结果为准。'
        self.assertEqual(split_production_notes(text), (text, []))

    def test_seven_step_photo_card_fits_and_preserves_photo(self):
        source = Image.new('RGB', (413, 169), '#AB3456')
        source.putpixel((12, 13), (1, 2, 3))
        stream = io.BytesIO(); source.save(stream, format='PNG')
        text = ('咨询流程通常是：线上初步咨询 → 到店登记 → 皮肤检测 → 医生面诊评估 → 讲解适合的滤光片与方案 → 说明价格与套餐 → 预约治疗。'
                '\n\n到店时逐项核对信息，具体安排以门店资料与面诊评估为准。\n\n实拍建议：拍摄咨询区域。')
        raw, meta = rendering.render('到店后，流程一般怎么走', text, photo=stream.getvalue(), page=2, total_pages=3)
        self.assertEqual((meta['width'], meta['height']), (1080, 1440))
        self.assertLessEqual(meta['content_bottom'], meta['content_limit'])
        self.assertGreaterEqual(meta['body_font_size'], 32)
        x, y = meta['photo_offset_x'], meta['photo_offset_y']
        actual = Image.open(io.BytesIO(raw)).crop((x, y, x+413, y+169))
        self.assertIsNone(ImageChops.difference(source, actual).getbbox())
        self.assertNotIn('实拍建议', meta['public_text'])

    def test_long_title_dense_content_and_all_themes(self):
        for theme in ('minimal', 'soft', 'duotone'):
            raw, meta = rendering.render_themed('需要逐项确认的咨询信息' * 3,
                '把自己的疑问写下来。' * 50, theme, 1, 3)
            self.assertEqual(Image.open(io.BytesIO(raw)).size, (1080, 1440))
            self.assertLessEqual(meta['content_bottom'], meta['content_limit'])
        with self.assertRaisesRegex(ValueError, '文字过多'):
            rendering.render_themed('信息', '字' * 2000, 'minimal', 1, 3)

    def test_notes_only_cannot_become_empty_published_card(self):
        with self.assertRaisesRegex(ValueError, '没有可发布文字'):
            rendering.render_themed('', '制作说明：调整排版。', 'minimal')
