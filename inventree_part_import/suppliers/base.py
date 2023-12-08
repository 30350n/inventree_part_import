from dataclasses import dataclass
from functools import cache
import inspect
from inspect import _empty
import re

from ..config import get_pre_creation_hooks

@dataclass
class ApiPart:
    description: str
    image_url: str
    datasheet_url: str
    supplier_link: str
    SKU: str
    manufacturer: str
    manufacturer_link: str
    MPN: str
    quantity_available: float
    packaging: str
    category_path: list[str]
    parameters: dict[str, str]
    price_breaks: dict[int, float]
    currency: str

    def finalize(self):
        if not self.finalize_hook():
            return False
        for pre_creation_hook in get_pre_creation_hooks():
            pre_creation_hook(self)
        return True

    def finalize_hook(self):
        return True

    def get_part_data(self):
        return {
            "name": self.MPN,
            "description": self.description,
            "link": self.manufacturer_link,
            "active": True,
            "component": True,
            "purchaseable": True,
        }

    def get_manufacturer_part_data(self):
        return {
            "MPN": self.MPN,
            "description": self.description,
            "link": self.manufacturer_link,
        }

    def get_supplier_part_data(self):
        data = {
            "description": self.description,
            "link": self.supplier_link,
            "packaging": self.packaging,
        }
        if self.quantity_available:
            data["available"] = min(float(self.quantity_available), 9999999.0)
        return data

class Supplier:
    def setup(self) -> bool:
        pass

    def _get_setup_params(self):
        return {
            name: parameter.default if parameter.default is not _empty else None
            for name, parameter in inspect.signature(self.setup).parameters.items()
            if name != "self"
        }

    def search(self, search_term: str) -> (list[ApiPart], int):
        raise NotImplementedError()

    @cache
    def cached_search(self, search_term: str) -> (list[ApiPart], int):
        return self.search(search_term)

    @property
    def name(self):
        return self.__class__.__name__

def money2float(money):
    money = MONEY2FLOAT_CLEANUP.sub("", money).strip()
    decimal, fraction = MONEY2FLOAT_SPLIT.match(money).groups()
    decimal = MONEY2FLOAT_CLEANUP2.sub("", decimal).strip()
    fraction = MONEY2FLOAT_CLEANUP2.sub("", fraction).strip()
    return float(f"{decimal}.{fraction}")

MONEY2FLOAT_CLEANUP = re.compile(r"[^(\d,.\-)]")
MONEY2FLOAT_SPLIT = re.compile(r"(.*)(?:\.|,)(\d+)")
MONEY2FLOAT_CLEANUP2 = re.compile(r"[^\d\-]")
