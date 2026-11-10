"""#111 unique WebP fixture safety and Graph-asset wiring tests."""
from pathlib import Path
import tempfile
import unittest

from ops.canvas_unique_media_111 import (
    apply_distinct_media, make_distinct_webp,
)

class UniqueMediaFixtureTests(unittest.TestCase):
    def test_small_derived_webps_have_distinct_bytes_and_bounded_size(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"qa111-unit"
            result=make_distinct_webp(target,count=4,size=(32,24))
            self.assertEqual(result["count"],4)
            self.assertEqual(result["uniqueSha256"],4)
            self.assertEqual(result["decodedPixelsExpected"],4*32*24)
            self.assertEqual(len(set(result["urls"])),4)
            self.assertEqual(len(list(target.glob("*.webp"))),4)
            self.assertFalse(result["isProductionMedia"])
            with self.assertRaises(ValueError):
                make_distinct_webp(target,count=4,size=(32,24))
            with self.assertRaises(ValueError):
                make_distinct_webp(Path(directory)/"too-big",count=121)

    def test_graph_rewrites_only_image_fields(self):
        graph={"nodes":[
            {"id":"a","type":"text_input","data":{"text":"never-touch"}},
            {"id":"b","type":"asset","data":{"items":[{"image":"/old.webp","name":"label"}]}},
            {"id":"c","type":"output_display","data":{"items":[{"imageUrl":"/old2.webp"}]}},
        ]}
        applied=apply_distinct_media(graph,["/starter/demo/a.webp","/starter/demo/b.webp"])
        self.assertEqual(applied,2)
        self.assertEqual(graph["nodes"][0]["data"]["text"],"never-touch")
        self.assertEqual(graph["nodes"][1]["data"]["items"][0]["name"],"label")
        self.assertEqual(graph["nodes"][1]["data"]["items"][0]["image"],"/starter/demo/a.webp")
        self.assertEqual(graph["nodes"][2]["data"]["items"][0]["imageUrl"],"/starter/demo/b.webp")
        with self.assertRaises(ValueError):
            apply_distinct_media(graph,["/starter/demo/a.webp"])

if __name__=="__main__":
    unittest.main()
