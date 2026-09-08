"""Bounds and source/output separation for the offline cold-DAT preparation."""
import struct
import tempfile
from pathlib import Path
import unittest
from prepare_graphics import expected_size, prepare


class PrepareGraphicsTests(unittest.TestCase):
    def test_header_bounds_and_raw_passthrough(self):
        self.assertEqual(expected_size(b'original raw bytes'),18)
        for method in (1,2):
            header=b'RNC'+bytes([method])+struct.pack('>II',307200,3)+b'\0'*6
            self.assertEqual(expected_size(header+b'abc'),307200)
        for data in (b'RNC',b'RNC\3'+b'\0'*14,
                     b'RNC\1'+struct.pack('>II',0,0)+b'\0'*6,
                     b'RNC\1'+struct.pack('>II',0x1000000,0)+b'\0'*6,
                     b'RNC\1'+struct.pack('>II',640,4)+b'\0'*6):
            with self.assertRaises(ValueError):expected_size(data)

    def test_reject_source_output_overlap_before_tool_or_file_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);game=root/'game'
            for stage,cache in ((game,root/'cache'),(game/'inside',root/'cache'),
                                (root,root/'cache'),(root/'stage',game/'cache')):
                with self.assertRaises(ValueError):prepare(game,stage,cache,root/'upstream')
            self.assertEqual(list(root.iterdir()),[])


if __name__=='__main__':unittest.main()
