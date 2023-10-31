import os
from types import MethodType

from bs4 import BeautifulSoup
from mouser.api import MouserPartSearchRequest

from ..error_helper import *
from .base import ApiPart, Supplier, money2float
from .scrape import DOMAIN_REGEX, DOMAIN_SUB, scrape

class Mouser(Supplier):
    def setup(self, api_key, currency, scraping, locale_url="www.mouser.com"):
        os.environ["MOUSER_PART_API_KEY"] = api_key

        self.currency = currency
        self.use_scraping = scraping
        self.locale_url = locale_url

        return True

    def search(self, search_term):
        search_request = MouserPartSearchRequest("partnumber")
        search_request.part_search(search_term)

        if parts := search_request.get_response()["SearchResults"]["Parts"]:
            search_term_lower = search_term.lower()
            filtered_matches = [
                part for part in parts
                if part.get("ManufacturerPartNumber", "").lower().startswith(search_term_lower)
            ]

            exact_matches = [
                part for part in filtered_matches
                if part.get("ManufacturerPartNumber", "").lower() == search_term_lower
            ]
            if exact_matches:
                filtered_matches = exact_matches

            return list(map(self.get_api_part, filtered_matches)), len(filtered_matches)

        return [], 0

    def get_api_part(self, mouser_part):
        mouser_part_number = mouser_part.get("MouserPartNumber")

        supplier_link = DOMAIN_REGEX.sub(
            DOMAIN_SUB.format(self.locale_url), mouser_part.get("ProductDetailUrl"))

        mouser_price_breaks = mouser_part.get("PriceBreaks", [])
        price_breaks = {
            price_break.get("Quantity"): money2float(price_break.get("Price"))
            for price_break in mouser_price_breaks
        }

        currency = None
        if mouser_price_breaks:
            currency = mouser_price_breaks[0].get("Currency")
        if not currency:
            currency = self.currency

        if not (quantity_available := mouser_part.get("AvailabilityInStock")):
            quantity_available = 0

        api_part = ApiPart(
            description=mouser_part.get("Description", ""),
            image_url=mouser_part.get("ImagePath"),
            supplier_link=supplier_link,
            SKU=mouser_part_number,
            manufacturer=mouser_part.get("Manufacturer", ""),
            manufacturer_link="",
            MPN=mouser_part.get("ManufacturerPartNumber", ""),
            quantity_available=float(quantity_available),
            packaging="",
            category_path=None,
            parameters=None,
            price_breaks=price_breaks,
            currency=currency,
        )

        api_part.finalize_hook = MethodType(self.finalize_hook, api_part)

        return api_part

    def finalize_hook(self, api_part: ApiPart):
        if not self.use_scraping:
            hint("scraping is disabled: can't finalize parameters and category_path")
            api_part.parameters = {}
            return True

        url = api_part.supplier_link
        if not (result := scrape(url, fallback_domains=FALLBACK_DOMAINS)):
            warning(f"failed to finalize part specifications from '{url}' (blocked)")
            return False

        soup = BeautifulSoup(result.content, "html.parser")

        if specs_table := soup.find("table", class_="specs-table"):
            api_part.parameters = dict(
                tuple(map(lambda column: column.text.strip().strip(":"), row.find_all("td")[:2]))
                for row in specs_table.find_all("tr")[1:]
            )
        else:
            warning(f"failed to get part specifications from '{url}' (might be blocked)")
            return False

        if breadcrumb := soup.find("ol", class_="breadcrumb"):
            api_part.category_path = [li.text.strip() for li in breadcrumb.find_all("li")[1:-1]]
        else:
            warning(f"failed to get category path from '{url}' (might be blocked)")
            return False

        return True

FALLBACK_DOMAINS = (
    "www2.mouser.com",
    "eu.mouser.com",
)
