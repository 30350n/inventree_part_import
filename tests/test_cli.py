from pathlib import Path
from shutil import rmtree

from click.testing import CliRunner
from inventree.api import InvenTreeAPI

from inventree_part_import.cli import inventree_part_import
from inventree_part_import.config import (CATEGORIES_CONFIG, CONFIG, INVENTREE_CONFIG,
                                          PARAMETERS_CONFIG, SUPPLIERS_CONFIG)

HOST = "http://localhost:55555"
USERNAME = "testuser"
PASSWORD = "testpassword"

TEST_CONFIG_DIR = Path(__file__).parent / "test_config"

def test_config_dir_override():
    rmtree(TEST_CONFIG_DIR, ignore_errors=True)
    result = CliRunner().invoke(
        inventree_part_import, ("-c", str(TEST_CONFIG_DIR), "--show-config-dir"),
        input="\n",
    )
    assert result.exit_code == 0
    assert str(TEST_CONFIG_DIR.resolve()) in result.output
    assert TEST_CONFIG_DIR.exists()

class TestCli:
    def setup_class(self):
        rmtree(TEST_CONFIG_DIR, ignore_errors=True)
        TEST_CONFIG_DIR.mkdir(parents=True)

        api = InvenTreeAPI(HOST, username=USERNAME, password=PASSWORD, use_token_auth=True)
        (TEST_CONFIG_DIR / CONFIG).write_text(
            "currency: EUR\nlanguage: EN\nlocation: DE\nscraping: true\n")
        (TEST_CONFIG_DIR / INVENTREE_CONFIG).write_text(f"host: {HOST}\ntoken: {api.token}\n")
        (TEST_CONFIG_DIR / SUPPLIERS_CONFIG).write_text("lcsc:\n    ignore_duplicates: true\n")
        (TEST_CONFIG_DIR / CATEGORIES_CONFIG).touch()
        (TEST_CONFIG_DIR / PARAMETERS_CONFIG).touch()

    def test_setup_categories(self):
        result = CliRunner().invoke(
            inventree_part_import,
            ("-c", str(TEST_CONFIG_DIR), "TL072", "-v", "-i", "false"),
            catch_exceptions=False,
        )
        assert "skipping import" in result.output
        assert "TL072" in result.output
