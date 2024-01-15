import logging
import os

import digikey
from digikey.v3.productinformation import KeywordSearchRequest, ProductDetailsResponse
from platformdirs import user_cache_path

from .. import __package__ as parent_package
from ..retries import retry_timeouts
from .base import ApiPart, Supplier

DIGIKEY_CACHE = user_cache_path(parent_package, ensure_exists=True) / "digikey"
DIGIKEY_CACHE.mkdir(parents=True, exist_ok=True)

class DigiKey(Supplier):
    def setup(self, client_id, client_secret, currency, language, location):
        os.environ["DIGIKEY_CLIENT_ID"] = client_id
        os.environ["DIGIKEY_CLIENT_SECRET"] = client_secret
        os.environ["DIGIKEY_CLIENT_SANDBOX"] = "False"
        os.environ["DIGIKEY_STORAGE_PATH"] = str(DIGIKEY_CACHE)

        self.currency = currency
        self.language = language
        self.location = location

        logging.getLogger("digikey.v3.api").setLevel(logging.CRITICAL)

        return True

    def search(self, search_term):
        for retry in retry_timeouts():
            with retry:
                results = digikey.keyword_search(
                    body=KeywordSearchRequest(keywords=search_term, record_count=10),
                    x_digikey_locale_currency=self.currency,
                    x_digikey_locale_site=self.location,
                    x_digikey_locale_language=self.language,
                )

        if results.exact_manufacturer_products_count > 0:
            filtered_results = results.exact_manufacturer_products
            product_count = results.exact_manufacturer_products_count
        else:
            filtered_results = [
                digikey_part for digikey_part in results.products
                if digikey_part.manufacturer_part_number.lower().startswith(search_term.lower())
            ]
            product_count = results.products_count

        exact_matches = [
            digikey_part for digikey_part in filtered_results
            if digikey_part.manufacturer_part_number.lower() == search_term.lower()
        ]
        if len(exact_matches) == 1:
            return [self.get_api_part(exact_matches[0])], 1

        if not exact_matches and product_count == 1 and len(filtered_results) > 1:
            # the digikey api returns all product variants of the same product if the full MPN
            # was not specified, in that case: pick the Cut Tape one if possible
            for digikey_part in filtered_results:
                packaging = digikey_part.packaging.value
                if "Cut Tape" in packaging or "CT" in packaging:
                    return [self.get_api_part(digikey_part)], 1
            return [self.get_api_part(filtered_results[0])], 1

        product_count = max(product_count, len(filtered_results))
        return list(map(self.get_api_part, filtered_results)), product_count

    def get_api_part(self, digikey_part):
        quantity_available = (
            digikey_part.quantity_available + digikey_part.manufacturer_public_quantity)

        manufacturer_link = ""
        if isinstance(digikey_part, ProductDetailsResponse):
            for media in digikey_part.media_links:
                if media.media_type == "Manufacturer Product Page":
                    manufacturer_link = media.url
                    break

        category_path = [digikey_part.category.value, *digikey_part.family.value.split(" - ")]

        parameters = {
            parameter.parameter: parameter.value
            for parameter in digikey_part.parameters
        }

        price_breaks = {
            price_break.break_quantity: price_break.unit_price
            for price_break in digikey_part.standard_pricing
        }

        return ApiPart(
            description=digikey_part.product_description,
            image_url=digikey_part.primary_photo,
            datasheet_url=digikey_part.primary_datasheet,
            supplier_link=digikey_part.product_url,
            SKU=digikey_part.digi_key_part_number,
            manufacturer=digikey_part.manufacturer.value,
            manufacturer_link=manufacturer_link,
            MPN=digikey_part.manufacturer_part_number,
            quantity_available=quantity_available,
            packaging=digikey_part.packaging.value,
            category_path=category_path,
            parameters=parameters,
            price_breaks=price_breaks,
            currency=self.currency,
        )
