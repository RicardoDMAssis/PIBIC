import gzip
import json
import tempfile
import unittest
from pathlib import Path

from bpc_ingestion.bronze import BronzeWriter


class BronzeWriterTest(unittest.TestCase):
    def test_writes_recoverable_gzip_ndjson(self):
        with tempfile.TemporaryDirectory() as directory:
            with BronzeWriter(directory, "datajud", "TRF1", "run-1") as writer:
                writer.write({"_id": "one", "texto": "beneficio"})
                path = writer.path
            self.assertTrue(path.exists())
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                self.assertEqual(
                    json.loads(stream.readline()),
                    {"_id": "one", "texto": "beneficio"},
                )


if __name__ == "__main__":
    unittest.main()
