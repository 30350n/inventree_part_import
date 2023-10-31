import re
from types import MethodType

from bs4 import BeautifulSoup
from requests import Session
from requests.compat import quote

from .base import ApiPart, Supplier, money2float
from .scrape import scrape, REQUEST_TIMEOUT
from ..error_helper import *

BASE_URL = "https://reichelt.com/"
LOCALE_CHANGE_URL = f"{BASE_URL}index.html?ACTION=12&PAGE=46"
SEARCH_URL = f"{BASE_URL}index.html?ACTION=446&q={{}}"

class Reichelt(Supplier):
    def setup(self, language, location, scraping):
        if location not in LOCATION_MAP:
            error(f"failed to load '{self.name}' module (unsupported location '{location}')")
            return False

        if not scraping:
            error(f"failed to load '{self.name}' module (scraping is disabled)")
            return False

        self.language = language
        self.location = location
        self.localized_url = f"{BASE_URL}{self.location.lower()}/{self.language.lower()}/"
        self.locale_confirm_regex = re.compile(
            rf";CCOUNTRY={LOCATION_MAP[self.location]};LANGUAGE={self.language};CTYPE=1;"
        )

        return True

    def search(self, search_term):
        setup = self.setup_hook
        if SKU_REGEX.fullmatch(search_term):
            sku_link = f"{self.localized_url}-{search_term}.html"
            if sku_page := scrape(sku_link, setup_hook=setup):
                sku_page_soup = BeautifulSoup(sku_page.content, "html.parser")
                return [self.get_api_part(sku_page_soup, search_term, sku_link)], 1

        if not (result := scrape(SEARCH_URL.format(quote(search_term)), setup_hook=setup)):
            return [], 0

        soup = BeautifulSoup(result.content, "html.parser")

        api_parts = []
        search_results = soup.find_all("div", class_="al_gallery_article")
        for result in search_results:
            image_url = result.find("div", class_="al_artlogo").find("img")["data-original"]
            image_url = IMAGE_URL_FULLSIZE_REGEX.sub(IMAGE_URL_FULLSIZE_SUB, image_url)

            product_url = result.find("a", itemprop="url")["href"]
            sku = PRODUCT_URL_SKU_REGEX.match(product_url).group(1).upper()
            supplier_link = f"{self.localized_url}-{sku.lower()}.html"

            mpn = result.find("meta", itemprop="productID")["content"].replace(" ", "")

            if len(search_results) > 1:
                if not (
                    search_term.lower() in sku.lower() or search_term.lower() in mpn.lower()
                ):
                    continue

            availability = result.find("p", class_="availability").find("span")["class"][0]
            if not availability in AVAILABILITY_MAP:
                warning(f"unknown reichelt availability '{availability}' ({supplier_link})")

            price_breaks = {}
            if price := result.find("span", itemprop="price"):
                price_breaks[1] = money2float(price.text)
            if discounts := result.find("ul", _class="discounts"):
                for discount in discounts.find_all("li"):
                    price, quantity = discount.find_all("span")
                    price_breaks[float(quantity)] = money2float(price.text)

            currency = None
            if meta := result.find("meta", itemprop="priceCurrency"):
                currency = meta["content"]

            api_part = ApiPart(
                description=result.find("meta", itemprop="name")["content"],
                image_url=image_url,
                supplier_link=supplier_link,
                SKU=sku,
                manufacturer=None,
                manufacturer_link="",
                MPN=mpn,
                quantity_available=AVAILABILITY_MAP.get(availability),
                packaging="",
                category_path=None,
                parameters=None,
                price_breaks=price_breaks,
                currency=currency,
            )

            api_part.finalize_hook = MethodType(self.finalize_hook, api_part)

            api_parts.append(api_part)

        exact_matches = [
            api_part for api_part in api_parts
            if api_part.SKU.lower() == search_term.lower()
            or api_part.MPN.lower() == search_term.lower()
        ]
        if exact_matches:
            return exact_matches, len(exact_matches)

        return api_parts, len(api_parts)

    def get_api_part(self, soup, sku, link):
        image_url = soup.find(id="av_bildbox").find(id="bigimages").find("img")["src"]

        header = soup.find(id="av_articleheader")
        mpn = "".join(header.find().find_all(text=True, recursive=False)).replace(" ", "")

        availability = soup.find("p", class_="availability").find("span")["class"][0]
        if not availability in AVAILABILITY_MAP:
            warning(f"unknown reichelt availability '{availability}' ({link})")

        price_breaks = {}
        if price := soup.find("meta", itemprop="price"):
            price_breaks[1] = float(price["content"])
        if discounts := soup.find(id="av_price_discount"):
            for discount in discounts.find("tbody").find_all("td")[1:]:
                price, quantity = discount.find_all(text=True)
                price_breaks[float(quantity)] = money2float(price.text)

        currency = None
        if meta := soup.find("meta", itemprop="priceCurrency"):
            currency = meta["content"]

        api_part = ApiPart(
            description=header.find("span", itemprop="name").text,
            image_url=image_url,
            supplier_link=link,
            SKU=sku.upper(),
            manufacturer=None,
            manufacturer_link="",
            MPN=mpn,
            quantity_available=AVAILABILITY_MAP.get(availability),
            packaging="",
            category_path=None,
            parameters=None,
            price_breaks=price_breaks,
            currency=currency,
        )

        self.finalize_hook(api_part, soup)

        return api_part

    def finalize_hook(self, api_part: ApiPart, soup=None):
        if not soup:
            if not (result := scrape(api_part.supplier_link, setup_hook=self.setup_hook)):
                return False
            soup = BeautifulSoup(result.content, "html.parser")

        breadcrumb = soup.find("ol", id="breadcrumb")
        api_part.category_path = [
            li.find("a").text
            for li in breadcrumb.find_all("li", itemprop="itemListElement")[1:]
        ]

        api_part.parameters = {
            prop_name.text.strip(): prop_value.text.strip()
            for ul in soup.find("div", id="av_props_inline").find_all("ul", class_="clearfix")
            if (prop_name := ul.find("li", "av_propname"))
            and (prop_value := ul.find("li", "av_propvalue"))
        }

        if manufacturer := api_part.parameters.get("Manufacturer"):
            api_part.manufacturer = manufacturer
        else:
            api_part.manufacturer = "Reichelt"

        if mpn := api_part.parameters.get("Factory number"):
            api_part.MPN = mpn

        if not api_part.price_breaks:
            if price := soup.find("meta", itemprop="price"):
                api_part.price_breaks = {1: float(price["content"])}

        return True
    
    def setup_hook(self, session: Session):
        form_page = session.get(LOCALE_CHANGE_URL, timeout=REQUEST_TIMEOUT)
        if form_page.status_code == 200:
            soup = BeautifulSoup(form_page.content, "html.parser")
            form_url = soup.find("form", attrs={"name": "contentform"}).attrs["action"]

            result = session.post(form_url, timeout=REQUEST_TIMEOUT, data={
                "CCOUNTRY": LOCATION_MAP[self.location],
                "LANGUAGE": self.language,
                "CTYPE": 1,
            })
            if result.status_code == 200:
                soup = BeautifulSoup(result.content, "html.parser")
                statistics = soup.find("img", width="0", height="0")
                if self.locale_confirm_regex.search(statistics.get("src", "")):
                    return

        warning("failed to set Reichelt locales")

IMAGE_URL_FULLSIZE_REGEX = re.compile(r"/resize/[^/]+/[^/]+/")
IMAGE_URL_FULLSIZE_SUB = "/images/"
SKU_REGEX = re.compile(r"^[pP]\d+$")
PRODUCT_URL_SKU_REGEX = re.compile(r"^.*([pP]\d+)\.html[^\.]*$")

AVAILABILITY_MAP = {
    "status_1": None,
    "status_2": 0,
    "status_4": None,
    "status_5": 0,
    "status_6": 0,
    "status_8": 0,
}

LOCATION_MAP = {
    "AT": 458,
    "FR": 443,
    "DE": 445,
    "IT": 446,
    "NL": 662,
    "PL": 470,
    "CH": 459,
    "US": 550,
}
