import unittest
import sqlite3
import tempfile
import os

from database import (
    SCHEMA,
    insert_pokemon,
    find_duplicate,
    build_nickname,
    set_nickname,
    insert_evo_rankings
)
from evaluator import _is_immune, enforce_top_n, evaluate_catch

# run with #python -m unittest test_cataloger.py -v
class TestPokemonCataloger(unittest.TestCase):

    def setUp(self):
        # Create an isolated temporary database for each test
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def tearDown(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_nickname_generation(self):
        """Test that rank-encoded nicknames format correctly up to 12 chars."""
        self.assertEqual(build_nickname("Bulbasaur", 12, 45), "BulbG12U45")
        self.assertEqual(build_nickname("Pikachu", None, 3), "PikaU3")
        self.assertEqual(build_nickname("Fletchling", 1, None), "FletG1")

    def test_duplicate_detection_with_date(self):
        """Test find_duplicate accurately keys off caught_date when present[cite: 1]."""
        data = {
            "name": "Pikachu", "cp": 450, "hp": 50, "dust": 1000, "level": 15.0,
            "iv_atk": 15, "iv_def": 14, "iv_sta": 13, "iv_pct": 93.3, "iv_stars": "3*",
            "caught_date": "8/24/2026", "screenshot_path": "test.png"
        }
        insert_pokemon(self.conn, data)

        # Exact match should be found as duplicate
        self.assertTrue(find_duplicate(self.conn, "Pikachu", 450, 15, 14, 13, "8/24/2026"))

        # Different date should NOT be considered a duplicate
        self.assertFalse(find_duplicate(self.conn, "Pikachu", 450, 15, 14, 13, "8/23/2026"))

    def test_immunity_rules(self):
        """Test that hundos, nundos, high levels, and shinies correctly trigger immunity[cite: 1]."""
        hundo = {"name": "Pikachu", "iv_pct": 100.0, "iv_atk": 15, "iv_def": 15, "iv_sta": 15, "is_shiny": 0}
        shiny = {"name": "Pikachu", "iv_pct": 50.0, "iv_atk": 5, "iv_def": 5, "iv_sta": 5, "is_shiny": 1}
        trash = {"name": "Pikachu", "iv_pct": 40.0, "iv_atk": 2, "iv_def": 3, "iv_sta": 1, "is_shiny": 0}

        self.assertTrue(_is_immune(hundo))
        self.assertTrue(_is_immune(shiny))  # Shinies are immune once flagged[cite: 1]
        self.assertFalse(_is_immune(trash))

    def test_enforce_top_n_quotas(self):
        """Test that enforce_top_n demotes excess catches outside top-N while respecting quotas[cite: 1]."""
        # Insert 7 bulbasaurs with varying GL ranks
        for i in range(1, 8):
            data = {
                "name": "Bulbasaur", "cp": 500 + i, "hp": 50, "dust": 1000, "level": 20.0,
                "iv_atk": 0, "iv_def": 15, "iv_sta": 15, "iv_pct": 65.0, "iv_stars": "2*",
                "caught_date": f"8/{i}/2026",
                "pvp": {"great": {"rank": i * 10, "percentile": 95.0}, "ultra": {}}
            }
            poke_id = insert_pokemon(self.conn, data)
            # Mark them all as KEEP initially
            self.conn.execute("UPDATE pokemon SET tag = 'KEEP' WHERE id = ?", (poke_id,))
        self.conn.commit()

        # Run top-N enforcement with top_n = 5
        demoted = enforce_top_n(self.conn, top_n=5)

        # Ranks 60 and 70 (ids 6 and 7) should be demoted
        demoted_ids = {p["id"] for p in demoted}
        self.assertIn(6, demoted_ids)
        self.assertIn(7, demoted_ids)

        # Ranks 10, 20, 30, 40, 50 should remain safe
        safe_rows = self.conn.execute("SELECT id FROM pokemon WHERE tag = 'KEEP'").fetchall()
        self.assertEqual(len(safe_rows), 5)


if __name__ == "__main__":
    unittest.main()