import tempfile
import unittest
from pathlib import Path

import api.fuel as fuel


class HistoryDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.csv_path = Path(self.tempdir.name) / "fuel_history.csv"
        fuel.HISTORY_CSV = self.csv_path
        fuel.HISTORY_FILE = Path(self.tempdir.name) / "fuel_history.json"
        fuel._ensure_history_csv()

    def test_save_and_load_history_roundtrip(self):
        record = {
            "source_date": "01 Jan 2024",
            "exchange_rate": {"usd_ngn": 1500.0, "date": "2024-01-01"},
            "rows": [{"country": "Nigeria", "price_ngn_per_litre": 700.0}],
            "recorded_at": "2024-01-01T00:00:00Z",
        }

        fuel._save_history([record])
        saved = fuel._load_history()

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["source_date"], "01 Jan 2024")
        self.assertEqual(saved[0]["rows"][0]["country"], "Nigeria")

    def test_update_history_does_not_duplicate_existing_week(self):
        payload = {
            "source_date": "08 Jan 2024",
            "exchange_rate": {"usd_ngn": 1505.0, "date": "2024-01-08"},
            "rows": [{"country": "Nigeria", "price_ngn_per_litre": 710.0}],
        }

        first = fuel._update_history(payload)
        second = fuel._update_history(payload)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)

    def test_extract_fuely_average_from_summary_html(self):
        html = """
        <html>
          <body>
            <h2>Fuel Price Summary</h2>
            <div>Petrol</div>
            <div>Lowest</div>
            <div>₦1,249.00</div>
            <div>Highest</div>
            <div>₦1,350.00</div>
          </body>
        </html>
        """

        self.assertAlmostEqual(fuel._extract_fuely_average(html), 1299.5, places=2)


if __name__ == "__main__":
    unittest.main()
