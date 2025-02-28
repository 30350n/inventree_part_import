import logging, os

import digikey
from digikey import DigikeyApi
from digikey.v4.productinformation import KeywordRequest, KeywordResponse, Product
from digikey.v4.productinformation.api import ProductSearchApi
from platformdirs import user_cache_path

from .. import __package__ as parent_package
from ..localization import get_country, get_language
from ..retries import retry_timeouts
from .base import ApiPart, Supplier, SupplierSupportLevel

DIGIKEY_CACHE = user_cache_path(parent_package, ensure_exists=True) / "digikey"
DIGIKEY_CACHE.mkdir(parents=True, exist_ok=True)

class DigiKey(Supplier):
    
    SUPPORT_LEVEL = SupplierSupportLevel.OFFICIAL_API

    def setup(self, client_id, client_secret, currency, language, location):

        if not get_country(location):
            return self.load_error(f"invalid country code '{location}'")

        if not get_language(language):
            return self.load_error(f"invalid language code '{language}'")

        self.currency = currency
        self.language = language
        self.location = location

        logging.getLogger("digikey.v4.api").setLevel(logging.CRITICAL)
        self.client = DigikeyApi(
            client_id=client_id,
            client_secret=client_secret,
            storage_path=str(DIGIKEY_CACHE),
        )        
        
        return True

    def search(self, search_term):
        for retry in retry_timeouts():
            with retry:
                try:
                    digikey_part = self.client.product_details(search_term)
                except Exception as e:
                    digikey_part = None
                    continue
        # Removed matching on digikey part number as the new api matches on manufacturer product number
        # Thus, removing the need to use keyword_search to find manufacturers product number
        # The logic for keyword search is still useful for partial matches.
        # The line below is the original line updated for the v4 api.
        # if digikey_part and search_term == digikey_part.product.product_variations[0].digi_key_product_number:
        if digikey_part:
            return [self.get_api_part(digikey_part.product)], 1
        

        for retry in retry_timeouts():
            with retry:
                results = self.client.keyword_search(
                    body=KeywordRequest(keywords=search_term, limit=10),
                )

        if len(results.exact_matches) > 0:
            filtered_results = results.exact_matches
            product_count = len(results.exact_matches)
        else:
            filtered_results = [
                digikey_part for digikey_part in results.products
                if digikey_part.manufacturer_product_number.lower().startswith(search_term.lower())
            ]
            product_count = results.products_count

        exact_matches = [
            digikey_part for digikey_part in filtered_results
            if digikey_part.manufacturer_product_number.lower() == search_term.lower()
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

    def get_api_part(self, digikey_part: Product):
        quantity_available = (
            digikey_part.quantity_available + digikey_part.manufacturer_public_quantity)

        # Categories are stored in a tree structure, so we need to build the full path
        category_path = [digikey_part.category.name]
        num_child = len(digikey_part.category.child_categories)
        child_categories = digikey_part.category.child_categories

        while num_child > 0:
            child_category = child_categories[0]
            category_path.append(child_category.name)
            num_child = len(child_category.child_categories)
            child_categories = child_category.child_categories
        
        parameters = {
            parameter.parameter_text: parameter.value_text
            for parameter in digikey_part.parameters
        }
        # Only single unit pricing is available from the ProductDetails API
        # If we want to add price breaks need to make a seperate call to ProductPricing API 
        # https://developer.digikey.com/products/product-information-v4/productsearch/productpricing
        price_breaks = {1: digikey_part.unit_price}


        # Had issue with some products missing http/https in the datasheet url
        datasheet_url = digikey_part.datasheet_url
        if datasheet_url.startswith("//"):
            datasheet_url = "https:" + datasheet_url
        if not datasheet_url.startswith("http"):
            datasheet_url = ""
        
        # Digikey part number now stored in product_variations
        digikey_part_number = digikey_part.product_variations[0].digi_key_product_number

        return ApiPart(
            description=digikey_part.description.product_description,
            image_url=digikey_part.photo_url,
            datasheet_url=datasheet_url,
            supplier_link=digikey_part.product_url,
            SKU=digikey_part_number,
            manufacturer=digikey_part.manufacturer.name,
            manufacturer_link="",
            MPN=digikey_part.manufacturer_product_number,
            quantity_available=quantity_available,
            # packing information not in ProductDetails API
            packaging="",#digikey_part.packaging.value,
            category_path=category_path,
            parameters=parameters,
            price_breaks=price_breaks,
            currency=self.currency,
        )
