from base64 import b64encode
from hashlib import sha1
import hmac
from types import MethodType

import requests
from requests.compat import quote, urlencode

from .base import ApiPart, Supplier
from ..error_helper import *

class TME(Supplier):
    def setup(self, api_token, api_secret, currency, language, location):
        self.tme_api = TMEApi(api_token, api_secret, language, location, currency)
        self.currency = currency
        return True

    def search(self, search_term):
        tme_part = self.tme_api.get_product(search_term)
        if tme_part:
            tme_stock = self.tme_api.get_prices_and_stocks([tme_part["Symbol"]])[0]
            return [self.get_api_part(tme_part, tme_stock)], 1

        if not (results := self.tme_api.product_search(search_term)):
            return [], 0

        filtered_matches = [
            tme_part for tme_part in results["ProductList"]
            if tme_part["OriginalSymbol"].lower().startswith(search_term.lower())
        ]

        exact_matches = [
            tme_part for tme_part in filtered_matches
            if tme_part["OriginalSymbol"].lower() == search_term.lower()
        ]
        if len(exact_matches) == 1:
            filtered_matches = exact_matches

        tme_stocks = self.tme_api.get_prices_and_stocks([m["Symbol"] for m in filtered_matches])
        return list(map(self.get_api_part, filtered_matches, tme_stocks)), len(filtered_matches)

    def get_api_part(self, tme_part, tme_stock):
        price_breaks = {
            price_break["Amount"]: price_break["PriceValue"]
            for price_break in tme_stock.get("PriceList", [])
        }

        api_part = ApiPart(
            description=tme_part.get("Description", ""),
            image_url=fix_tme_url(tme_part.get("Photo")),
            supplier_link=fix_tme_url(tme_part.get("ProductInformationPage")),
            SKU=tme_part.get("Symbol", ""),
            manufacturer=tme_part.get("Producer", ""),
            manufacturer_link="",
            MPN=tme_part.get("OriginalSymbol", ""),
            quantity_available=tme_stock.get("Amount", 0),
            packaging="",
            category_path=self.tme_api.get_category_path(tme_part["CategoryId"]),
            parameters=None,
            price_breaks=price_breaks,
            currency=self.currency,
        )

        api_part.finalize_hook = MethodType(self.finalize_hook, api_part)

        return api_part

    def finalize_hook(self, api_part: ApiPart):
        if not (parameters := self.tme_api.get_parameters(api_part.SKU)):
            return False

        api_part.parameters = {
            parameter["ParameterName"]: parameter["ParameterValue"]
            for parameter in parameters
        }

        return True

def fix_tme_url(url):
    if url and url.startswith("//"):
        return f"https:{url}"
    return url

class TMEApi:
    BASE_URL = "https://api.tme.eu/"
    def __init__(
        self, token, secret, language="EN", country="PL", currency="EUR", price_type="NET",
    ):
        self._categories = None
        self.token = token
        self.secret = secret
        self.language = language
        self.country = country
        self.currency = currency
        self.price_type = price_type

    def get_category_path(self, category_id):
        if self._categories is None:
            self._categories = {
                category["Id"]: (category["Name"], category["ParentId"])
                for category in self.get_categories()
            }

        parent_id = category_id
        category_path = []
        while True:
            name, parent_id = self._categories[parent_id]
            if not name:
                return category_path
            category_path.insert(0, name)

    def get_product(self, product_symbol):
        result = self._api_call("Products/GetProducts", {
            "Country": self.country,
            "Language": self.language,
            "SymbolList[0]": product_symbol,
        })
        if result:
            products = result.json()["Data"]["ProductList"]
            if products and len(products) == 1:
                return products[0]

    def product_search(self, search_term):
        result = self._api_call("Products/Search", {
            "Country": self.country,
            "Language": self.language,
            "SearchPlain": search_term,
        })
        if result:
            return result.json()["Data"]

    def get_prices_and_stocks(self, product_symbols):
        if not product_symbols:
            return []

        data = {
            "Country": self.country,
            "Language": self.language,
            "Currency": self.currency,
            "GrossPrices": "false",
        }
        for i, symbol in enumerate(product_symbols):
            data[f"SymbolList[{i}]"] = symbol

        if result := self._api_call("Products/GetPricesAndStocks", data):
            result_data = result.json()["Data"]
            assert result_data["Currency"] == self.currency
            assert result_data["PriceType"] == self.price_type
            return result_data["ProductList"]
        
        return []

    def get_parameters(self, product_symbol):
        result = self._api_call("Products/GetParameters", {
            "Country": self.country,
            "Language": self.language,
            "SymbolList[0]": product_symbol,
        })
        if result:
            return result.json()["Data"]["ProductList"][0]["ParameterList"]

    def get_categories(self):
        result = self._api_call("Products/GetCategories", {
            "Country": self.country,
            "Language": self.language,
            "Tree": "false",
        })
        return result.json()["Data"]["CategoryTree"]

    HEADERS = {"Content-type": "application/x-www-form-urlencoded"}
    def _api_call(self, action, data):
        url = f"{self.base_url}{action}.json"
        data_sorted = dict(sorted({**data, "Token": self.api_token}.items()))

        signature_base = f"POST&{quote(url, '')}&{quote(urlencode(data_sorted), '')}".encode()
        signature = b64encode(hmac.new(self.api_secret.encode(), signature_base, sha1).digest())
        data_sorted["ApiSignature"] = signature

        result = requests.post(url, urlencode(data_sorted), headers=self.HEADERS)
        if result.status_code != 200:
            try:
                status = result.json()['Status']
                if status in {"E_INPUT_PARAMS_VALIDATION_ERROR", "E_INVALID_SIGNATURE"}:
                    return None
                warning(f"'{action}' action failed with '{status}'")
            except (requests.exceptions.JSONDecodeError, KeyError):
                warning(f"'{action}' action failed with unknown error")
            return None

        return result
