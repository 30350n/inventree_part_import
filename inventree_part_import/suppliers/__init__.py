import importlib
from inspect import isclass
from multiprocessing.pool import ThreadPool
from pathlib import Path

from ..config import (SUPPLIERS_CONFIG, get_config, get_config_dir, load_suppliers_config,
                      update_config_file)
from ..error_helper import *
from ..inventree_helpers import Company
from .base import Supplier

_SUPPLIERS = None
def search(search_term, supplier_id: str = None, only_supplier=False):
    global _SUPPLIERS
    if _SUPPLIERS is None:
        assert _SUPPLIER_COMPANIES is not None, "call setup_supplier_companies(...) first"
        supplier_objects, _ = get_suppliers()
        assert supplier_objects.keys() == _SUPPLIER_COMPANIES.keys()
        _SUPPLIERS = dict(zip(
            supplier_objects.keys(),
            zip(supplier_objects.values(), _SUPPLIER_COMPANIES.values())
        ))

    suppliers = list(_SUPPLIERS.values())
    if supplier_id:
        if supplier := _SUPPLIERS.get(supplier_id):
            if only_supplier:
                suppliers = [supplier]
            else:
                suppliers.remove(supplier)
                suppliers.insert(0, supplier)
        else:
            error(f"supplier id '{supplier_id}' not defined in {SUPPLIERS_CONFIG}")
            return None

    thread_pool = ThreadPool(processes=8)
    return [
        (api_company, thread_pool.apply_async(supplier_object.search, (search_term,)))
        for supplier_object, api_company in suppliers
    ]

_SUPPLIER_COMPANIES = None
def setup_supplier_companies(inventree_api):
    global _SUPPLIER_COMPANIES
    _SUPPLIER_COMPANIES = {}
    global_config = get_config()
    with update_config_file(get_config_dir() / SUPPLIERS_CONFIG) as suppliers_config:
        for id, supplier_object in _SUPPLIER_OBJECTS.items():
            supplier_config = suppliers_config[id]
            api_company = Company(
                name=supplier_object.name,
                currency=supplier_config.get("currency", global_config["currency"]),
                is_supplier=True,
                primary_key=supplier_config.get("_primary_key"),
            ).setup(inventree_api)
            supplier_config["_primary_key"] = api_company.pk
            _SUPPLIER_COMPANIES[id] = api_company

_SUPPLIER_OBJECTS = None
_AVAILABLE_SUPPLIER_OBJECTS = None
def get_suppliers(reload=False, setup=True) -> (dict, dict):
    global _SUPPLIER_OBJECTS, _AVAILABLE_SUPPLIER_OBJECTS
    if not reload and _SUPPLIER_OBJECTS is not None:
        return _SUPPLIER_OBJECTS, _AVAILABLE_SUPPLIER_OBJECTS

    _SUPPLIER_OBJECTS = {}
    _AVAILABLE_SUPPLIER_OBJECTS = {}
    for path in Path(__file__).parent.glob("supplier_*.py"):
        module_name = path.stem
        try:
            if module_name in locals():
                module = importlib.reload(locals()[module_name])
            else:
                module = importlib.import_module(f".{module_name}", package=__package__)
        except ImportError as e:
            error(f"failed to load supplier module '{module_name}' with {e}")
            continue

        supplier_classes = [
            cls for cls in vars(module).values()
            if isclass(cls) and cls is not Supplier and issubclass(cls, Supplier)
        ]
        if len(supplier_classes) != 1:
            suffix = "multiple Supplier classes" if supplier_classes else "no Supplier class"
            error(f"failed to load supplier module '{module_name}' ({suffix} defined)")
            continue

        id = module_name.split("supplier_", 1)[-1]
        _AVAILABLE_SUPPLIER_OBJECTS[id] = supplier_classes[0]()

    _SUPPLIER_OBJECTS = load_suppliers_config(_AVAILABLE_SUPPLIER_OBJECTS, setup=setup)

    if (available := len(_AVAILABLE_SUPPLIER_OBJECTS)) > (loaded := len(_SUPPLIER_OBJECTS)):
        hint(f"only {loaded} of {available} available supplier modules are configured")

    return _SUPPLIER_OBJECTS, _AVAILABLE_SUPPLIER_OBJECTS
