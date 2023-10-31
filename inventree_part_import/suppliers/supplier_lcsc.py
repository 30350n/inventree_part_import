import re
from requests import Session

from .base import ApiPart, Supplier
from ..error_helper import *
from .scrape import scrape, REQUEST_TIMEOUT

API_BASE_URL = "https://wmsc.lcsc.com/wmsc/"
CURRENCY_URL     = f"{API_BASE_URL}home/currency?currencyCode={{}}"
SEARCH_URL       = f"{API_BASE_URL}search/global?keyword={{}}"
PRODUCT_INFO_URL = f"{API_BASE_URL}product/detail?productCode={{}}"

class LCSC(Supplier):
    def setup(self, currency, ignore_duplicates=True):
        if not currency in CURRENCY_MAP.values():
            error(f"failed to load '{self.name}' module (unsupported currency '{currency}')")
            return False

        self.currency = currency
        self.ignore_duplicates = ignore_duplicates
        return True

    def search(self, search_term):
        setup = self.setup_hook
        if not (search_result := scrape(SEARCH_URL.format(search_term), setup_hook=setup)):
            return [], 0

        result = search_result.json()
        if product_detail := result["result"]["tipProductDetailUrlVO"]:
            url = PRODUCT_INFO_URL.format(product_detail["productCode"])
            if detail_request := scrape(url, setup_hook=setup):
                return [self.get_api_part(detail_request.json()["result"])], 1
        elif products := result["result"]["productSearchResultVO"]:
            filtered_matches = [
                product for product in products["productList"]
                if product["productModel"].lower().startswith(search_term.lower())
            ]

            exact_matches = [
                product for product in filtered_matches
                if product["productModel"].lower() == search_term.lower()
            ]
            if self.ignore_duplicates:
                exact_filtered = [
                    product for product in exact_matches
                    if product.get("stockNumber")
                    or product.get("productImageUrlBig")
                    or product.get("productImageUrl")
                    or product.get("productImages")
                ]
                exact_matches = exact_filtered if exact_filtered else exact_matches

            if exact_matches:
                filtered_matches = exact_matches

            return list(map(self.get_api_part, filtered_matches)), len(filtered_matches)

        return [], 0

    def get_api_part(self, lcsc_part):
        if not (description := lcsc_part.get("productDescEn")):
            description = lcsc_part.get("productIntroEn")
        description = description.strip() if description else ""

        image_url = lcsc_part.get("productImageUrlBig", lcsc_part.get("productImageUrl"))
        if not image_url and (image_urls := lcsc_part.get("productImages")):
            for image_url in reversed(image_urls):
                if "front" in image_url:
                    break

        if url := lcsc_part.get("url"):
            url_separator = "/product-detail/"
            prefix, product_url_id = url.split(url_separator)
            product_url_id = product_url_id
            supplier_link = url_separator.join((prefix, cleanup_url_id(product_url_id)))
        else:
            product_url_id = cleanup_url_id("_".join((
                lcsc_part["catalogName"], lcsc_part["title"], lcsc_part["productCode"]
            )))
            supplier_link = f"https://www.lcsc.com/product-detail/{product_url_id}.html"

        category_path = []
        if parent := lcsc_part.get("parentCatalogName"):
            category_path.append(parent)
        if category := lcsc_part.get("catalogName"):
            category_path.append(category)

        parameters = {}
        if lcsc_parameters := lcsc_part.get("paramVOList"):
            parameters = {
                parameter.get("paramNameEn"): parameter.get("paramValueEn")
                for parameter in lcsc_parameters
            }

        if package := lcsc_part.get("encapStandard"):
            parameters["Package Type"] = package

        price_list = lcsc_part.get("productPriceList", [])
        price_breaks = {
            price_break.get("ladder"): price_break.get("currencyPrice")
            for price_break in price_list
        }

        if price_list:
            currency = CURRENCY_MAP.get(price_list[0].get("currencySymbol"), self.currency)
        else:
            currency = self.currency

        return ApiPart(
            description=REMOVE_HTML_TAGS.sub("", description),
            image_url=image_url,
            supplier_link=supplier_link,
            SKU=lcsc_part.get("productCode", ""),
            manufacturer=lcsc_part.get("brandNameEn", ""),
            manufacturer_link="",
            MPN=lcsc_part.get("productModel", ""),
            quantity_available=float(lcsc_part.get("stockNumber", 0)),
            packaging=REMOVE_HTML_TAGS.sub("", lcsc_part.get("productArrange", "")),
            category_path=category_path,
            parameters=parameters,
            price_breaks=price_breaks,
            currency=currency,
        )

    def setup_hook(self, session: Session):
        session.get(CURRENCY_URL.format(self.currency), timeout=REQUEST_TIMEOUT)

REMOVE_HTML_TAGS = re.compile(r"<.*?>")

CLEANUP_URL_ID_REGEX = re.compile(r"[^\w\d\.]")
def cleanup_url_id(url):
    url = url.replace(" / ", "_")
    url = CLEANUP_URL_ID_REGEX.sub("_", url)
    return url

CURRENCY_MAP = {
    "€": "EUR",
    "US$": "USD",
}
