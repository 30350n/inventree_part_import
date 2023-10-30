from enum import Enum
from multiprocessing.pool import ThreadPool
import requests, re

from inventree.part import Part, Parameter
from inventree.company import Company, ManufacturerPart, SupplierPart, SupplierPriceBreak

from .categories import setup_categories_and_parameters, CATEGORIES_CONFIG
from .config import get_pre_creation_hooks
from .error_helper import *
from .inventree_helpers import (
    create_manufacturer, get_parameter_templates, get_part, get_manufacturer_part,
    get_supplier_part, update_object_data, upload_image,
)
from .suppliers import search
from .suppliers.base import ApiPart

class ImportResult(Enum):
    ERROR = 0
    FAILURE = 1
    SUCCESS = 2

class PartImporter:
    def __init__(self, inventree_api):
        self.api = inventree_api

        # preload pre_creation_hooks
        get_pre_creation_hooks()

        self.category_map, self.parameter_map = setup_categories_and_parameters(self.api)
        self.parameter_templates = get_parameter_templates(self.api)

        self.part_category_to_category = {
            category.part_category.pk: category
            for category in self.category_map.values()
        }

    def import_part(self, search_term, supplier_id=None, only_supplier=False, import_all=False):
        import_success = False

        self.existing_manufacturer_part = None
        for supplier, async_results in search(search_term, supplier_id, only_supplier):
            info(f"searching at {supplier.name} ...")
            results, result_count = async_results.get()

            if not results:
                hint(f"no results at {supplier.name}")
                continue
            if len(results) > 1 and not import_all:
                warning(f"found {result_count} parts at {supplier.name}, skipping import")
                continue

            if result_count > len(results):
                hint(
                    f"found {result_count} parts at {supplier.name}, only importing "
                    f"{len(results)}"
                )

            for api_part in results:
                if import_all:
                    self.existing_manufacturer_part = None
                match self.import_supplier_part(supplier, api_part):
                    case ImportResult.ERROR:
                        return False
                    case ImportResult.FAILURE:
                        pass
                    case ImportResult.SUCCESS:
                        import_success = True

        return import_success

    def import_supplier_part(self, supplier: Company, api_part: ApiPart):
        part = None
        if supplier_part := get_supplier_part(self.api, api_part.SKU):
            info(f"found existing {supplier.name} part {supplier_part.SKU} ...")
            manufacturer_part = ManufacturerPart(self.api, supplier_part.manufacturer_part)
        else:
            info(f"importing {supplier.name} part {api_part.SKU} ...")
            if manufacturer_part := get_manufacturer_part(self.api, api_part.MPN):
                pass
            elif self.existing_manufacturer_part:
                manufacturer_part = self.existing_manufacturer_part
            else:
                if not api_part.finalize():
                    return ImportResult.FAILURE
                result = self.setup_manufacturer_part(api_part)
                if isinstance(result, ImportResult):
                    return result
                manufacturer_part, part = result

        update_part = (
            not self.existing_manufacturer_part
            or self.existing_manufacturer_part.pk != manufacturer_part.pk
        )
        if not part:
            part = Part(self.api, manufacturer_part.part)

            if not self.existing_manufacturer_part:
                if not api_part.finalize():
                    return ImportResult.FAILURE
            if update_part:
                update_object_data(part, api_part.get_part_data(), f"part {api_part.MPN}")

        if not part.image and api_part.image_url:
            upload_image(part, api_part.image_url)

        if api_part.parameters:
            if not (category := self.part_category_to_category.get(part.category)):
                name = part.getCategory().pathstring
                error(f"category '{name}' is not defined in {CATEGORIES_CONFIG.name}")
                return ImportResult.FAILURE

            self.setup_parameters(part, api_part, category, update_part)

        self.existing_manufacturer_part = manufacturer_part

        supplier_part_data = api_part.get_supplier_part_data()
        if supplier_part:
            updating = True
            update_object_data(supplier_part, supplier_part_data, f"{supplier.name} part")
        else:
            updating = False
            try:
                supplier_part = SupplierPart.create(self.api, {
                    "part": part.pk,
                    "manufacturer_part": manufacturer_part.pk,
                    "supplier": supplier.pk,
                    "SKU": api_part.SKU,
                    **supplier_part_data,
                })
            except requests.exceptions.HTTPError as e:
                error(f"failed to create {supplier.name} part with: {e.args[0]['body']}")
                return ImportResult.ERROR

        self.setup_price_breaks(supplier_part, api_part)

        url = self.api.base_url + supplier_part.url[1:]
        actioned = "updated" if updating else "added"
        success(f"{actioned} {supplier.name} part {supplier_part.SKU} ({url})")
        return ImportResult.SUCCESS

    def setup_manufacturer_part(self, api_part: ApiPart) -> tuple[ManufacturerPart, Part]:
        for subcategory in reversed(api_part.category_path):
            if (category := self.category_map.get(subcategory)) and not category.structural:
                break
        else:
            error(f"failed to match category for '{' / '.join(api_part.category_path)}'")
            return ImportResult.FAILURE

        part_data = api_part.get_part_data()
        if part := get_part(self.api, api_part.MPN):
            update_object_data(part, part_data, f"part {api_part.MPN}")
        else:
            info(f"creating part {api_part.MPN} in '{category.part_category.pathstring}' ...")
            try:
                part = Part.create(self.api, {
                    "category": category.part_category.pk,
                    **part_data,
                })
            except requests.exceptions.HTTPError as e:
                error(f"failed to create part with: {e.args[0]['body']}")
                return ImportResult.ERROR

        manufacturer = create_manufacturer(self.api, api_part.manufacturer)
        info(f"creating manufacturer part {api_part.MPN} ...")
        manufacturer_part = ManufacturerPart.create(self.api, {
            "part": part.pk,
            "manufacturer": manufacturer.pk,
            **api_part.get_manufacturer_part_data(),
        })

        return manufacturer_part, part

    def setup_price_breaks(self, supplier_part, api_part: ApiPart):
        price_breaks = {
            price_break.quantity: price_break
            for price_break in SupplierPriceBreak.list(self.api, part=supplier_part.pk)
        }

        updated_pricing = False
        for quantity, price in api_part.price_breaks.items():
            if price_break := price_breaks.get(quantity):
                if price != float(price_break.price):
                    price_break.save(data={
                        "price": price,
                        "price_currency": api_part.currency,
                    })
                    updated_pricing = True
            else:
                price_break = SupplierPriceBreak.create(self.api, {
                    "part": supplier_part.pk,
                    "quantity": quantity,
                    "price": price,
                    "price_currency": api_part.currency,
                })
                updated_pricing = True

        if updated_pricing:
            info("updating price breaks ...")

    def setup_parameters(self, part, api_part: ApiPart, category, update_existing=True):
        existing_parameters = {
            parameter.template_detail["name"]: parameter
            for parameter in Parameter.list(self.api, part=part.pk)
        }

        matched_parameters = {}
        for api_part_parameter, value in api_part.parameters.items():
            for parameter in self.parameter_map.get(api_part_parameter, []):
                name = parameter.name
                if name not in matched_parameters and name in category.parameters:
                    matched_parameters[name] = value
                    break

        thread_pool = ThreadPool(8)
        async_results = []
        for name, value in matched_parameters.items():
            if not (value := sanitize_parameter_value(value)):
                continue

            if existing_parameter := existing_parameters.get(name):
                if update_existing and existing_parameter.data != value:
                    async_results.append(thread_pool.apply_async(
                        update_parameter, (existing_parameter, value)
                    ))
            else:
                if parameter_template := self.parameter_templates.get(name):
                    async_results.append(thread_pool.apply_async(
                        create_parameter, (self.api, part, parameter_template, value)
                    ))
                else:
                    warning(f"failed to find template parameter for '{name}'")

        if async_results:
            info("updating part parameters ...")

        for result in async_results:
            if warning_str := result.get():
                warning(warning_str)

        already_set_parameters = {
            name for name, parameter in existing_parameters.items() if parameter.data}
        unassigned_parameters = (
            set(category.parameters) - set(matched_parameters) - already_set_parameters)
        if unassigned_parameters:
            plural = "s" if len(unassigned_parameters) > 1 else ""
            warning(
                f"failed to match {len(unassigned_parameters)} parameter{plural} from supplier "
                f"API ({str(unassigned_parameters)[1:-1]})"
            )

def create_parameter(inventree_api, part, parameter_template, value):
    try:
        Parameter.create(inventree_api, {
            "part": part.pk,
            "template": parameter_template.pk,
            "data": value,
        })
    except requests.exceptions.HTTPError as e:
        return f"failed to create parameter {parameter_template.name} with: {e.args[0]['body']}"

def update_parameter(parameter, value):
    try:
        parameter.save({"data": value})
    except requests.exceptions.HTTPError as e:
        error_msg = e.args[0]["body"]
        return f"failed to update parameter {parameter.name} to '{value}' with: {error_msg}"

SANITIZE_PARAMETER = re.compile("±")

def sanitize_parameter_value(value: str) -> str:
    value = value.strip()
    if value == "-":
        return ""
    value = SANITIZE_PARAMETER.sub("", value)
    value = value.replace("Ohm", "ohm").replace("ohms", "ohm")
    return value
