from pathlib import Path
import shutil

from cutie import prompt_yes_or_no, secure_input
from inventree.api import InvenTreeAPI
from platformdirs import user_config_path
import yaml
from yaml.error import MarkedYAMLError

from ..error_helper import *
from .. import __package__ as parent_package

CONFIG_DIR = user_config_path(parent_package, ensure_exists=True)
TEMPLATE_DIR = Path(__file__).parent

# if someone decides to create a git repository in the CONFIG_DIR,
# stop them from leaking their InvenTree host configuration
_gitignore = CONFIG_DIR / ".gitignore"
if not _gitignore.exists():
    _gitignore.write_text("inventree.yaml\n", encoding="utf-8")

INVENTREE_CONFIG = CONFIG_DIR / "inventree.yaml"
def setup_inventree_api():
    info("setting up InvenTree API ...")
    if INVENTREE_CONFIG.is_file():
        info(f"loading api configuration from '{INVENTREE_CONFIG.name}' ...")
        with INVENTREE_CONFIG.open(encoding="utf-8") as file:
            try:
                config = yaml.safe_load(file)
                return InvenTreeAPI(host=config.get("host"), token=config.get("token"))
            except MarkedYAMLError as e:
                error(e, prefix="")
            except (ConnectionError, TimeoutError) as e:
                error(f"failed to connect to '{host}' with '{e}'")
                if not prompt_yes_or_no("do you want to enter your connection details again?"):
                    return None
    else:
        print()

    inventree_api = None
    while not inventree_api:
        host = input("inventree host: ")
        username = input("username: ")
        password = secure_input("password:")
        try:
            inventree_api = InvenTreeAPI(
                host, username=username, password=password, use_token_auth=True,
            )
        except (ConnectionError, TimeoutError) as e:
            error(f"failed to connect to '{host}' with '{e}'")

    with INVENTREE_CONFIG.open("w", encoding="utf-8") as file:
        yaml.safe_dump({"host": host, "token": inventree_api.token}, file, sort_keys=False)
    success(f"wrote API configuration to '{INVENTREE_CONFIG}'")

    return inventree_api

CATEGORIES_CONFIG = CONFIG_DIR / "categories.yaml"
def get_categories_config():
    return _get_config_file(CATEGORIES_CONFIG)

PARAMETERS_CONFIG = CONFIG_DIR / "parameters.yaml"
def get_parameters_config():
    return _get_config_file(PARAMETERS_CONFIG)

def _get_config_file(config_path):
    if not config_path.is_file():
        info(f"failed to find {config_path.name} config file", end="\n")
        hint("this is normal if you're using this for the first time")
        if prompt_yes_or_no("copy the default configuration file?", default_is_yes=True):
            shutil.copy(TEMPLATE_DIR / config_path.name, config_path)
        else:
            return None

    with config_path.open(encoding="utf-8") as file:
        try:
            return yaml.safe_load(file)
        except MarkedYAMLError as e:
            error(e, prefix="")
            return None

def get_pre_creation_hooks():
    return []
