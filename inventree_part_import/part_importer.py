from enum import Enum
from multiprocessing.pool import ThreadPool
import re

from cutie import select
from inventree.company import Company, ManufacturerPart, SupplierPart, SupplierPriceBreak
from inventree.part import Parameter, Part
from requests.exceptions import HTTPError
from thefuzz import fuzz

from .categories import setup_categories_and_parameters
from .config import CATEGORIES_CONFIG, get_config, get_pre_creation_hooks
from .error_helper import *
from .inventree_helpers import (create_manufacturer, get_manufacturer_part,
                                get_parameter_templates, get_part, get_supplier_part,
                                update_object_data, upload_image)
from .suppliers import search
from .suppliers.base import ApiPart

class ImportResult(Enum):
    ERROR = 0
    FAILURE = 1
    INCOMPLETE = 2
    SUCCESS = 3

    def __or__(self, other):
        return self if self.value < other.value else other

class PartImporter:
    def __init__(self, inventree_api, interactive=False):
        self.api = inventree_api
        self.interactive = interactive
        self.dry_run = hasattr(inventree_api, "DRY_RUN")

        # preload pre_creation_hooks
        get_pre_creation_hooks()

        self.category_map, self.parameter_map = setup_categories_and_parameters(self.api)
        self.parameter_templates = get_parameter_templates(self.api)

        self.part_category_to_category = {
            category.part_category.pk: category
            for category in self.category_map.values()
        }
        self.categories = set(self.category_map.values())

    def import_part(self, search_term, supplier_id=None, only_supplier=False):
        info(f"searching for {search_term} ...", end="\n")
        import_result = ImportResult.SUCCESS

        self.existing_manufacturer_part = None
        search_results = search(search_term, supplier_id, only_supplier)
        for supplier, async_results in search_results:
            info(f"searching at {supplier.name} ...")
            results, result_count = async_results.get()

            if not results:
                hint(f"no results at {supplier.name}")
                continue

            if len(results) == 1:
                api_part = results[0]
            elif self.interactive:
                prompt(f"found multiple parts at {supplier.name}, select which one to import")
                results = results[:get_config()["max_results"]]
                if result_count > len(results):
                    hint(f"found {result_count} results, only showing the first {len(results)}")
                if not (api_part := self.select_api_part(results)):
                    import_result |= ImportResult.INCOMPLETE
                    continue
            else:
                warning(f"found {result_count} parts at {supplier.name}, skipping import")
                import_result |= ImportResult.INCOMPLETE
                continue

            import_result |= self.import_supplier_part(supplier, api_part)
            if import_result == ImportResult.ERROR:
                # let the other api calls finish
                for _, other_results in search_results:
                    other_results.wait()
                return ImportResult.ERROR

        if not self.existing_manufacturer_part:
            import_result |= ImportResult.FAILURE

        return import_result

    @staticmethod
    def select_api_part(api_parts: list[ApiPart]):
        mpns = [api_part.MPN for api_part in api_parts]
        max_mpn_length = max(len(mpn) for mpn in mpns)
        mpns = [mpn.ljust(max_mpn_length) for mpn in mpns]

        manufacturers = [str(api_part.manufacturer) for api_part in api_parts]
        max_manufacturer_length = max(len(man) for man in manufacturers)
        manufacturers = [man.ljust(max_manufacturer_length) for man in manufacturers]

        skus = [api_part.SKU for api_part in api_parts]
        max_sku_length = max(len(sku) for sku in skus)
        skus = [sku.ljust(max_sku_length) for sku in skus]

        links = [f"({api_part.supplier_link})" for api_part in api_parts]

        choices = [*map(" ".join, zip(map(" | ".join, zip(mpns, manufacturers, skus)), links))]
        choices.append(f"{ITALIC}Skip ...{ITALIC_END}")

        index = select(choices, deselected_prefix="  ", selected_prefix="> ")
        return [*api_parts, None][index]

    def import_supplier_part(self, supplier: Company, api_part: ApiPart):
        import_result = ImportResult.SUCCESS

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
                result = self.create_manufacturer_part(api_part)
                if isinstance(result, ImportResult):
                    return result
                manufacturer_part, part = result

        update_part = (
            not self.existing_manufacturer_part
            or self.existing_manufacturer_part.pk != manufacturer_part.pk
        )
        if not part and not self.dry_run:
            part = Part(self.api, manufacturer_part.part)

            if update_part:
                if not api_part.finalize():
                    return ImportResult.FAILURE
                update_object_data(part, api_part.get_part_data(), f"part {api_part.MPN}")

        if not self.dry_run:
            if not part.image and api_part.image_url:
                upload_image(part, api_part.image_url)

        if api_part.parameters:
            result = self.setup_parameters(part, api_part, update_part)
            import_result |= result

        self.existing_manufacturer_part = manufacturer_part

        supplier_part_data = api_part.get_supplier_part_data()
        if supplier_part:
            updating = True
            update_object_data(supplier_part, supplier_part_data, f"{supplier.name} part")
        else:
            updating = False
            try:
                supplier_part = SupplierPart.create(self.api, {
                    "part": 0 if self.dry_run else part.pk,
                    "manufacturer_part": manufacturer_part.pk,
                    "supplier": supplier.pk,
                    "SKU": api_part.SKU,
                    **supplier_part_data,
                })
            except HTTPError as e:
                error(f"failed to create {supplier.name} part with: {e.args[0]['body']}")
                return ImportResult.ERROR

        self.setup_price_breaks(supplier_part, api_part)

        url = self.api.base_url + supplier_part.url[1:]
        actioned = "updated" if updating else "added"
        success(f"{actioned} {supplier.name} part {supplier_part.SKU} ({url})")
        return import_result

    def create_manufacturer_part(self, api_part: ApiPart) -> tuple[ManufacturerPart, Part]:
        part_data = api_part.get_part_data()
        if part := get_part(self.api, api_part.MPN):
            update_object_data(part, part_data, f"part {api_part.MPN}")
        else:
            for subcategory in reversed(api_part.category_path):
                if category := self.category_map.get(subcategory):
                    break
            else:
                path_str = f" {BOLD}/{BOLD_END} ".join(api_part.category_path)
                if not self.interactive:
                    error(f"failed to match category for '{path_str}'")
                    return ImportResult.FAILURE

                prompt(f"failed to match category for '{path_str}', select category")
                if not (category := self.select_category(api_part.category_path)):
                    return ImportResult.FAILURE
                category.add_alias(api_part.category_path[-1])

            info(f"creating part {api_part.MPN} in '{category.part_category.pathstring}' ...")
            try:
                part = Part.create(self.api, {
                    "category": category.part_category.pk,
                    **part_data,
                })
            except HTTPError as e:
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

    def select_category(self, category_path):
        search_terms = [category_path[-1], " ".join(category_path[-2:])]

        def rate_category(category):
            return max(
                fuzz.ratio(term, name)
                for name in (category.name, " ".join(category.path[-2:]))
                for term in search_terms
            )
        category_matches = sorted(self.categories, key=rate_category, reverse=True)

        N_MATCHES = 5
        choices = (
            *(" / ".join(category.path) for category in category_matches[:N_MATCHES]),
            f"{ITALIC}Enter Manually ...{ITALIC_END}",
            f"{ITALIC}Skip ...{ITALIC_END}"
        )
        while True:
            index = select(choices, deselected_prefix="  ", selected_prefix="> ")
            if index == N_MATCHES + 1:
                return None
            elif index < N_MATCHES:
                return category_matches[index]

            name = prompt_input("category name")
            if (category := self.category_map.get(name)) and category.name == name:
                return category
            warning(f"category '{name}' does not exist")
            prompt("select category")

    def setup_price_breaks(self, supplier_part, api_part: ApiPart):
        price_breaks = {
            price_break.quantity: price_break
            for price_break in SupplierPriceBreak.list(self.api, part=supplier_part.pk)
        }

        updated_pricing = False
        for quantity, price in api_part.price_breaks.items():
            if price_break := price_breaks.get(quantity):
                if price == float(price_break.price):
                    continue
                price_break.save({"price": price, "price_currency": api_part.currency})
                updated_pricing = True
            else:
                SupplierPriceBreak.create(self.api, {
                    "part": supplier_part.pk,
                    "quantity": quantity,
                    "price": price,
                    "price_currency": api_part.currency,
                })
                updated_pricing = True

        if updated_pricing:
            info("updating price breaks ...")

    def setup_parameters(self, part, api_part: ApiPart, update_existing=True):
        import_result = ImportResult.SUCCESS

        if self.dry_run and not part:
            return import_result

        if not (category := self.part_category_to_category.get(part.category)):
            name = part.getCategory().pathstring
            error(f"category '{name}' is not defined in {CATEGORIES_CONFIG}")
            return ImportResult.FAILURE

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

        thread_pool = ThreadPool(4)
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
                elif not self.dry_run:
                    warning(f"failed to find template parameter for '{name}'")
                    import_result |= ImportResult.INCOMPLETE

        if async_results:
            info("updating part parameters ...")

        for result in async_results:
            if warning_str := result.get():
                warning(warning_str)
                import_result |= ImportResult.INCOMPLETE

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
            import_result |= ImportResult.INCOMPLETE

        return import_result

def create_parameter(inventree_api, part, parameter_template, value):
    try:
        Parameter.create(inventree_api, {
            "part": part.pk,
            "template": parameter_template.pk,
            "data": value,
        })
    except HTTPError as e:
        msg = e.args[0]["body"]
        return f"failed to create parameter '{parameter_template.name}' with '{msg}'"

def update_parameter(parameter, value):
    try:
        parameter.save({"data": value})
    except HTTPError as e:
        msg = e.args[0]["body"]
        return f"failed to update parameter '{parameter.name}' to '{value}' with '{msg}'"

SANITIZE_PARAMETER = re.compile("±")

def sanitize_parameter_value(value: str) -> str:
    value = value.strip()
    if value == "-":
        return ""
    value = SANITIZE_PARAMETER.sub("", value)
    value = value.replace("Ohm", "ohm").replace("ohms", "ohm")
    return value
