from dataclasses import dataclass
from functools import cache
import re

from inventree.api import InvenTreeAPI
from inventree.base import ImageMixin, InventreeObject
from inventree.company import Company as InventreeCompany
from inventree.company import ManufacturerPart, SupplierPart
from inventree.part import ParameterTemplate, Part
from platformdirs import user_cache_path
import requests
from requests.compat import urlparse
from requests.exceptions import HTTPError, Timeout

from .error_helper import *
from .retries import retry_timeouts

INVENTREE_CACHE = user_cache_path(__package__, ensure_exists=True) / "inventree"
INVENTREE_CACHE.mkdir(parents=True, exist_ok=True)

def get_supplier_part(inventree_api: InventreeCompany, sku):
    supplier_parts = SupplierPart.list(inventree_api, SKU=sku)
    if len(supplier_parts) == 1:
        return supplier_parts[0]

    assert len(supplier_parts) == 0
    return None

def get_manufacturer_part(inventree_api: InvenTreeAPI, mpn):
    manufacturer_parts = ManufacturerPart.list(inventree_api, MPN=mpn)
    if len(manufacturer_parts) == 1:
        return manufacturer_parts[0]

    assert len(manufacturer_parts) == 0
    return None

def get_part(inventree_api: InvenTreeAPI, name):
    name_sanitized = FILTER_SPECIAL_CHARS_REGEX.sub(FILTER_SPECIAL_CHARS_SUB, name)
    parts = Part.list(inventree_api, name_regex=f"^{name_sanitized}$")
    if len(parts) == 1:
        return parts[0]

    assert len(parts) == 0
    return None

FILTER_SPECIAL_CHARS_REGEX = re.compile(r"([^\\])([\[\].^$*+?{}|()])")
FILTER_SPECIAL_CHARS_SUB = r"\g<1>\\\g<2>"

def update_object_data(obj: InventreeObject, data: dict, info_label=""):
    for name, value in data.items():
        if value != type(value)(obj[name]):
            if info_label:
                info(f"updating {info_label} ...")
            obj.save(data)
            return

@cache
def get_parameter_templates(inventree_api: InvenTreeAPI):
    return {
        parameter_template.name: parameter_template
        for parameter_template in ParameterTemplate.list(inventree_api)
    }

@cache
def create_manufacturer(inventree_api: InvenTreeAPI, name):
    manufacturers = [
        manufacturer for manufacturer in InventreeCompany.list(inventree_api, search=name)
        if name.lower() == manufacturer.name.lower()
    ]
    if len(manufacturers) == 1:
        return manufacturers[0]
    assert len(manufacturers) == 0

    info(f"creating manufacturer '{name}' ...")
    return InventreeCompany.create(inventree_api, {
        "name": name,
        "description": name,
        "is_manufacturer": True,
        "is_supplier": False,
        "is_customer": False,
    })

def download_image_content(api_object: ImageMixin):
    if not api_object.image:
        return b""

    api_image_path = INVENTREE_CACHE / f"api_image.{api_object.image.rsplit('.')[-1]}"
    api_image_path.unlink(missing_ok=True)
    api_object.downloadImage(str(api_image_path))

    with open(api_image_path, "rb") as file:
        return file.read()

def upload_image(api_object: ImageMixin, image_url: str):
    info("uploading image ...")
    if not (image_content := _download_image_content(image_url)):
        warning(f"failed to download image from '{image_url}'")
        return

    url_path = urlparse(image_url).path
    if "." in url_path:
        file_extension = url_path.rsplit(".")[-1]
    else:
        file_extension = image_url.rsplit(".")[-1]
    if not file_extension.isalnum():
        warning(f"failed to get file extension for image from '{image_url}'")
        return

    image_path = INVENTREE_CACHE / f"temp_image.{file_extension}"
    with open(image_path, "wb") as file:
        file.write(image_content)

    try:
        api_object.uploadImage(str(image_path))
    except HTTPError as e:
        warning(f"failed to upload image with: {e.args[0]['body']}")

DOWNLOAD_HEADERS = {"User-Agent": "Mozilla/5.0"}

from ssl import PROTOCOL_TLSv1_2

class TLSv1_2HTTPAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = requests.packages.urllib3.poolmanager.PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_version=PROTOCOL_TLSv1_2,
        )

@cache
def _download_image_content(url):
    session = requests.Session()
    session.mount("https://", TLSv1_2HTTPAdapter())

    try:
        for retry in retry_timeouts():
            with retry:
                result = session.get(url, headers=DOWNLOAD_HEADERS)
                result.raise_for_status()
    except (HTTPError, Timeout) as e:
        warning(f"failed to download image with '{e}'")
        return None

    return result.content

@dataclass
class Company:
    name: str
    currency: str = None
    is_supplier: bool = False
    is_manufacturer: bool = False
    is_customer: bool = False
    primary_key: int = None

    def setup(self, inventree_api):
        api_company = None
        if self.primary_key is not None:
            try:
                api_company = InventreeCompany(inventree_api, self.primary_key)
            except HTTPError as e:
                if not e.args or e.args[0].get("status_code") != 404:
                    raise e

        if not api_company:
            api_companies = InventreeCompany.list(inventree_api, name=self.name)
            if len(api_companies) == 1:
                api_company = api_companies[0]

        if api_company:
            if self.name != api_company.name:
                info(f"updating name for '{api_company.name}' ...")
                api_company.save({"name": self.name})

            if self.currency != api_company.currency:
                info(f"updating currency for '{self.name}' ...")
                api_company.save({"currency": self.currency})

            return api_company

        info(f"creating supplier '{self.name}' ...")
        return InventreeCompany.create(inventree_api, {
            "name": self.name,
            "currency": self.currency,
            "is_supplier": self.is_supplier,
            "is_manufacturer": self.is_manufacturer,
            "is_customer": self.is_customer,
        })
