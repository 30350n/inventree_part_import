from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import shutil
import sys
from typing import TYPE_CHECKING

from cutie import prompt_yes_or_no, secure_input, select_multiple
from inventree.api import InvenTreeAPI
from isocodes import countries, languages, currencies
from platformdirs import user_config_path
import yaml
from yaml.error import MarkedYAMLError

if TYPE_CHECKING:
    from ..suppliers.base import Supplier
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
        try:
            config = yaml.safe_load(INVENTREE_CONFIG.read_text(encoding="utf-8"))
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
        print("setup your InvenTree API connection:")
        host = input("host: ").strip()
        username = input("username: ").strip()
        password = secure_input("password:").strip()
        try:
            inventree_api = InvenTreeAPI(
                host, username=username, password=password, use_token_auth=True,
            )
        except (ConnectionError, TimeoutError) as e:
            error(f"failed to connect to '{host}' with '{e}'")

    yaml_data = yaml.safe_dump({"host": host, "token": inventree_api.token}, sort_keys=False)
    INVENTREE_CONFIG.write_text(yaml_data, encoding="utf-8")
    success(f"wrote API configuration to '{INVENTREE_CONFIG}'")

    return inventree_api

CONFIG = CONFIG_DIR / "config.yaml"
_CONFIG_LOADED = None
def get_config():
    global _CONFIG_LOADED
    if _CONFIG_LOADED is not None:
        return _CONFIG_LOADED

    if CONFIG.is_file():
        try:
            _CONFIG_LOADED = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
            return _CONFIG_LOADED
        except MarkedYAMLError as e:
            error(e, prefix="")
            exit(-1)

    info(f"failed to find {CONFIG.name} config file", end="\n")
    print_new_configuration_hint()

    print("\nsetup your default configuration:")
    currency = input_currency()
    language = input_language()
    location = input_location()
    print("do you want to enable web scraping? (this is required to use some suppliers)")
    warning("enabling scraping can get you temporarily blocked sometimes")
    scraping = prompt_yes_or_no("enable scraping?", default_is_yes=True)

    _CONFIG_LOADED = {
        "currency": currency,
        "language": language,
        "location": location,
        "scraping": scraping
    }
    with CONFIG.open("w", encoding="utf-8") as file:
        yaml.safe_dump(_CONFIG_LOADED, file, sort_keys=False)
    success("setup default configuration!")
    return _CONFIG_LOADED

CATEGORIES_CONFIG = CONFIG_DIR / "categories.yaml"
def get_categories_config():
    return _get_config_file(CATEGORIES_CONFIG)

PARAMETERS_CONFIG = CONFIG_DIR / "parameters.yaml"
def get_parameters_config():
    return _get_config_file(PARAMETERS_CONFIG)

def _get_config_file(config_path: Path):
    if not config_path.is_file():
        info(f"failed to find {config_path.name} config file", end="\n")
        print_new_configuration_hint()
        if prompt_yes_or_no("copy the default configuration file?", default_is_yes=True):
            shutil.copy(TEMPLATE_DIR / config_path.name, config_path)
        else:
            return None

    try:
        return yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except MarkedYAMLError as e:
        error(e, prefix="")
        return None

@contextmanager
def update_config_file(config_path: Path):
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    try:
        yield config
    finally:
        backup_path = config_path.with_suffix(config_path.suffix + "_bak")
        shutil.copy(config_path, backup_path)
        yaml_data = yaml.safe_dump(config, sort_keys=False)
        config_path.write_text(yaml_data, encoding="utf-8")
        backup_path.unlink()

SUPPLIERS_CONFIG = CONFIG_DIR / "suppliers.yaml"
def load_suppliers_config(suppliers: dict[str, Supplier]):
    if not SUPPLIERS_CONFIG.is_file():
        info(f"failed to find {SUPPLIERS_CONFIG.name} config file", end="\n")
        print_new_configuration_hint()

        suppliers_config = {}
        print("\nselect the suppliers you want to setup: (SPACEBAR to toggle, ENTER to confirm)")
        selection = select_multiple(
            [supplier.name for supplier in suppliers.values()],
            ticked_indices=list(range(len(suppliers))),
            deselected_unticked_prefix = "  [ ] ",
            deselected_ticked_prefix   = "  [x] ",
            selected_unticked_prefix   = "> [ ] ",
            selected_ticked_prefix     = "> [x] ",
        )

        suppliers_out = {}
        supplier_ids = list(suppliers.keys())
        for id in (supplier_ids[index] for index in selection):
            suppliers_config[id] = update_supplier_config(suppliers[id], {})
            suppliers_out[id] = suppliers[id]

        yaml_data = yaml.safe_dump(suppliers_config, indent=4, sort_keys=False)
        SUPPLIERS_CONFIG.write_text(yaml_data, encoding="utf-8")

        return suppliers_out

    suppliers_out = {}
    try:
        with update_config_file(SUPPLIERS_CONFIG) as suppliers_config:
            for id, supplier_config in suppliers_config.items():
                if supplier := suppliers.get(id):
                    suppliers_config[id] = update_supplier_config(supplier, supplier_config)
                    suppliers_out[id] = supplier
                else:
                    warning(f"skipping unknown supplier '{id}' in '{SUPPLIERS_CONFIG.name}'")
    except MarkedYAMLError as e:
        error(e, prefix="")
        exit(-1)

    return suppliers_out

def update_supplier_config(supplier: Supplier, supplier_config: dict):
    global_config = get_config()
    used_global_settings = {}

    new_supplier_config = {}
    for name, param_default in supplier._get_setup_params().items():
        if (value := global_config.get(name)) is not None:
            used_global_settings[name] = value
        else:
            new_supplier_config[name] = supplier_config.get(name, param_default)

    if None in new_supplier_config.values():
        print(f"\nsetup {supplier.name} configuration:")
        for name, default in new_supplier_config.items():
            new_supplier_config[name] = input_default(name, default)
        success(f"setup {supplier.name} configuration!")

    supplier.setup(**new_supplier_config, **used_global_settings)

    return new_supplier_config

HOOKS_CONFIG = CONFIG_DIR / "hooks.py"
_PRE_CREATION_HOOKS = None
def get_pre_creation_hooks():
    global _PRE_CREATION_HOOKS
    if _PRE_CREATION_HOOKS is not None:
        return _PRE_CREATION_HOOKS

    _PRE_CREATION_HOOKS = []
    if not HOOKS_CONFIG.is_file():
        return _PRE_CREATION_HOOKS

    info("loading pre creation hooks ...")
    try:
        hooks_spec = importlib.util.spec_from_file_location(HOOKS_CONFIG.stem, HOOKS_CONFIG)
        hooks_module = importlib.util.module_from_spec(hooks_spec)
        sys.modules[HOOKS_CONFIG.stem] = hooks_module
        hooks_spec.loader.exec_module(hooks_module)
    except ImportError as e:
        error(f"failed to load '{HOOKS_CONFIG.name}' with {e}")
        return _PRE_CREATION_HOOKS

    _PRE_CREATION_HOOKS = [hook for hook in vars(hooks_module).values() if callable(hook)]
    success(f"loaded {len(_PRE_CREATION_HOOKS)} pre creation hooks!")
    return _PRE_CREATION_HOOKS

def input_currency(prompt="currency"):
    while True:
        currency = input(f"{prompt}: ").upper().strip()
        if currencies.get(alpha_3=currency):
            return currency
        error(f"'{currency}' is not a valid ISO 4217 currency code")

def input_language(prompt="language"):
    while True:
        language = input(f"{prompt}: ").lower().strip()
        if languages.get(alpha_2=language) or languages.get(alpha_3=language):
            return language.upper()
        error(f"'{language}' is not a valid ISO 639-2 language code")

def input_location(prompt="location"):
    while True:
        location = input(f"{prompt}: ").upper().strip()
        if countries.get(alpha_2=location) or countries.get(alpha_3=location):
            return location
        error(f"'{location}' is not a valid ISO 3166 country code")

def input_default(prompt, default_value=None):
    suffix = "" if default_value is None else f" [{default_value}]"
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if value or default_value:
            return value or default_value

NEW_CONFIGURATION_HINT = True
def print_new_configuration_hint():
    global NEW_CONFIGURATION_HINT
    if NEW_CONFIGURATION_HINT:
        hint("this is normal if you're using this program for the first time")
        NEW_CONFIGURATION_HINT = False
