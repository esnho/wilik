import ipaddress
import json
import re
import socket
from html import unescape
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Blueprint, jsonify, request
from flask_login import login_required
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.util import connection as urllib3_connection

SCRAPE_MAX_BYTES = 5 * 1024 * 1024
MAX_SCRAPE_REDIRECTS = 5
# different sites' bot detection disagrees on what looks suspicious: some (e.g.
# coolblue.be's AWS WAF) block a bare bot UA outright since a real browser always
# sends a full header set alongside it; others (e.g. decathlon.pl) do the opposite
# and block a browser-like UA specifically *because* the rest of the request (TLS/
# JA3 fingerprint, no JS execution) doesn't actually match a browser, while they
# let an honestly-labeled bot through. No single header set satisfies both, so
# scrape_url() tries the honest one first and only falls back to the disguised one
# on failure.
SCRAPE_HEADERS_BOT = {"User-Agent": "Mozilla/5.0 (compatible; WilikBot/1.0)"}
SCRAPE_HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}
# amazon serves its desktop page to both header sets above with no price at all and a
# generic og:image; the mobile layout (iPhone UA) has the product image and the price
# server-rendered, so amazon URLs get a second request with this set (see amazon_details)
SCRAPE_HEADERS_MOBILE = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

scrape_bp = Blueprint("scrape", __name__, url_prefix="/api")


def resolve_public_ips(hostname):
    """Every address hostname resolves to, or None if it doesn't resolve or any of them
    is loopback/private/link-local/reserved/multicast."""
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return None
    ips = []
    for family, _, _, _, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return None
        if ip not in ips:
            ips.append(ip)
    return ips


def is_safe_scrape_url(url):
    """Blocks SSRF: only allow public http(s) hosts, never loopback/private/link-local addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    return resolve_public_ips(parsed.hostname) is not None


class _PublicOnlyConnectionMixin:
    """Resolves and checks the host at the moment the socket is opened, then connects to
    exactly those checked addresses. Checking a URL up front isn't enough on its own: the
    socket layer would resolve the name a second time, and a DNS server that answers with
    a public IP first and an internal one the next time (DNS rebinding) would get past it.
    The hostname itself stays untouched, so the Host header, SNI and certificate checks
    work as usual."""

    def _new_conn(self):
        ips = resolve_public_ips(self._dns_host)
        if ips is None:
            raise NewConnectionError(self, f"Refusing to connect to {self.host}: not a public address")
        error = None
        for ip in ips:
            try:
                return urllib3_connection.create_connection(
                    (str(ip), self.port),
                    self.timeout,
                    source_address=self.source_address,
                    socket_options=self.socket_options,
                )
            except OSError as e:
                error = e
        raise NewConnectionError(self, f"Failed to establish a new connection: {error}") from error


class _PublicOnlyHTTPConnection(_PublicOnlyConnectionMixin, HTTPConnection):
    pass


class _PublicOnlyHTTPSConnection(_PublicOnlyConnectionMixin, HTTPSConnection):
    pass


class _PublicOnlyHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = _PublicOnlyHTTPConnection


class _PublicOnlyHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = _PublicOnlyHTTPSConnection


class _PublicOnlyAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {
            "http": _PublicOnlyHTTPConnectionPool,
            "https": _PublicOnlyHTTPSConnectionPool,
        }


def public_only_session():
    session = requests.Session()
    # no HTTP(S)_PROXY from the environment: through a proxy, it's the proxy that resolves
    # and connects to the target, so the address check above would never see it
    session.trust_env = False
    adapter = _PublicOnlyAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


@scrape_bp.route("/scrape", methods=["POST"])
@login_required
def scrape_url():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400
    if not is_safe_scrape_url(url):
        return jsonify({"error": "That URL can't be fetched"}), 400

    def try_fetch(headers):
        try:
            with public_only_session() as session:
                return fetch_page(session, url, headers)
        except requests.RequestException:
            return None

    content = try_fetch(SCRAPE_HEADERS_BOT)
    if content is None:
        content = try_fetch(SCRAPE_HEADERS_BROWSER)
    if content is None:
        try:
            content = impersonated_fetch(url, SCRAPE_HEADERS_BROWSER)
        except requests.RequestException:
            content = None
    if content is None:
        return jsonify({"error": "Could not fetch that URL"}), 400

    soup = BeautifulSoup(content, "html.parser")

    def meta(*keys):
        for key in keys:
            tag = soup.find("meta", property=key) or soup.find("meta", attrs={"name": key})
            if tag and tag.get("content", "").strip():
                return tag["content"].strip()
        return None

    products = list(find_jsonld_products(soup))

    og_title = meta("og:title")
    og_description = meta("og:description")
    # some sites (e.g. Amazon) reuse one generic value for every og:title/og:description
    # on every page instead of real per-page content; JSON-LD is more trustworthy then
    og_is_generic = og_title is not None and og_title == og_description
    fallback_title = soup.title.string.strip() if soup.title and soup.title.string else None

    result = {
        "title": (None if og_is_generic else og_title) or jsonld_value(products, "name") or fallback_title,
        "image_url": (None if og_is_generic else meta("og:image", "og:image:url")) or jsonld_image(products),
        "brand": meta("product:brand", "og:brand") or jsonld_brand(products),
    }

    price = meta("product:price:amount", "og:price:amount") or jsonld_price(products)
    if price is not None:
        try:
            result["price"] = float(price)
        except (TypeError, ValueError):
            pass

    if is_amazon_url(url):
        enrich_from_amazon_mobile(result, url)

    return jsonify(result)


def fetch_page(session, url, headers):
    """Reads at most SCRAPE_MAX_BYTES of url's body through session, following redirects
    by hand. Raises requests.RequestException on any HTTP, connection or redirect problem.

    The session only ever connects to public addresses (see _PublicOnlyConnectionMixin),
    redirects included. Following them by hand still keeps a redirect to another scheme
    (file:, ftp:, ...) out and gives a clear error for an internal target."""
    current_url = url
    for _ in range(MAX_SCRAPE_REDIRECTS + 1):
        response = session.get(current_url, timeout=5, headers=headers, stream=True, allow_redirects=False)
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise requests.RequestException("Redirect with no Location header")
            current_url = urljoin(current_url, location)
            if not is_safe_scrape_url(current_url):
                raise requests.RequestException("Redirected to an unsafe URL")
            continue
        response.raise_for_status()
        # product price data (JSON-LD) is often placed in <body>, not <head>, so read
        # a generous prefix rather than stopping at </head>
        chunks = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            chunks += chunk
            if len(chunks) >= SCRAPE_MAX_BYTES:
                break
        return bytes(chunks)
    raise requests.RequestException("Too many redirects")


def impersonated_fetch(url, headers):
    """Last resort for shops that answer every plain-HTTP client with a bot-block page
    (e.g. kaufland.it behind a Cloudflare challenge): fetches url through curl_cffi
    speaking TLS with Chrome's fingerprint. Returns at most SCRAPE_MAX_BYTES of the body,
    raises requests.RequestException on any problem, and returns None when curl_cffi
    isn't installed.

    The public-address rule survives the switch of HTTP client: every hop is resolved
    with resolve_public_ips() and pinned via CURLOPT_RESOLVE, so libcurl cannot connect
    anywhere else even while following redirects."""
    try:
        from curl_cffi import requests as impersonated_requests
        from curl_cffi.const import CurlOpt
    except ImportError:
        return None
    current_url = url
    for _ in range(MAX_SCRAPE_REDIRECTS + 1):
        parsed = urlparse(current_url)
        ips = resolve_public_ips(parsed.hostname)
        if ips is None:
            raise requests.RequestException(f"Refusing to fetch {current_url}: not a public address")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            response = impersonated_requests.get(
                current_url,
                headers=headers,
                # 10s instead of the 5s elsewhere: the challenge-fronted CDN answers
                # slower on the cold TLS handshake this path always pays for
                timeout=10,
                impersonate="chrome",
                allow_redirects=False,
                stream=True,
                curl_options={CurlOpt.RESOLVE: [f"{parsed.hostname}:{port}:{ip}" for ip in ips]},
            )
        except Exception as error:
            # curl_cffi raises its own error types; normalize them for the caller
            raise requests.RequestException(str(error)) from error
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise requests.RequestException("Redirect with no Location header")
            current_url = urljoin(current_url, location)
            if not is_safe_scrape_url(current_url):
                raise requests.RequestException("Redirected to an unsafe URL")
            continue
        if response.status_code >= 400:
            response.close()
            raise requests.RequestException(f"HTTP {response.status_code}")
        chunks = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            chunks += chunk
            if len(chunks) >= SCRAPE_MAX_BYTES:
                break
        response.close()
        return bytes(chunks)
    raise requests.RequestException("Too many redirects")


# "19,95€", "1.234,56 €": European prices put the decimal comma last, dots appear only
# as thousand separators
PRICE_TEXT_RE = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?")


def parse_price_text(text):
    """Turns a price as rendered in text (e.g. '19,95€', '1.234,56 €') into a float, or
    None when the text holds no number. Currency words and symbols around it are ignored."""
    if not text:
        return None
    match = PRICE_TEXT_RE.search(text.replace("\u00a0", "").replace("\u202f", ""))
    if not match:
        return None
    number = match.group(0).replace(".", "").replace(",", ".")
    try:
        return float(number)
    except ValueError:
        return None


def is_amazon_url(url):
    """True for amazon retail hosts (www.amazon.it, amazon.com, smile.amazon.co.uk, ...):
    one of the host's labels below the TLD part is exactly "amazon"."""
    labels = (urlparse(url).hostname or "").split(".")
    return len(labels) >= 2 and "amazon" in labels[:-1]


def largest_dynamic_image(attr):
    """Picks the widest URL from amazon's data-a-dynamic-image attribute, a JSON object
    mapping image URL to its [width, height]. Returns None when it can't be read."""
    if not attr:
        return None
    try:
        sizes = json.loads(attr)
    except ValueError:
        try:
            # raw HTML keeps the JSON entity-escaped; BeautifulSoup usually decodes it,
            # this covers the attribute arriving verbatim
            sizes = json.loads(unescape(attr))
        except ValueError:
            return None
    if not isinstance(sizes, dict) or not sizes:
        return None
    try:
        return max(sizes, key=lambda image_url: sizes[image_url])
    except (TypeError, ValueError):
        return None


def amazon_details(content):
    """Title, price and image from amazon's mobile layout (see SCRAPE_HEADERS_MOBILE).

    The price is the list price when amazon shows one struck through, because the
    wishlist tracks the stable list price rather than the promotion-dependent current
    one; without a strike-through the current price *is* the list price and priceToPay
    holds it. Every field is None when the layout doesn't match, so callers can fall
    back to whatever the generic extraction found."""
    soup = BeautifulSoup(content, "html.parser")

    title = None
    # desktop pages carry span#productTitle, mobile pages span#title; books on mobile
    # use h1#title instead, so the id is matched regardless of the tag
    for element_id in ("productTitle", "title"):
        span = soup.find(id=element_id)
        if span and span.get_text(strip=True):
            title = span.get_text(strip=True)
            break

    # "apex-" classes belong to the buy box, which sits before any related-products
    # carousel in the page, so the first match is this product's price. amazon splits
    # the digits across several spans (whole/decimal/fraction), so gather the element
    # text without the whitespace between the spans before parsing
    price = None
    list_price = soup.find(class_="apex-basisprice-value")
    if list_price:
        offscreen = list_price.find(class_="a-offscreen")
        price = parse_price_text("".join((offscreen or list_price).get_text().split()))
    if price is None:
        current_price = soup.find(class_="priceToPay")
        if current_price:
            price = parse_price_text("".join(current_price.get_text().split()))

    image = None
    main_image = soup.find("img", attrs={"data-a-image-name": "mainImage"})
    if main_image:
        image = main_image.get("data-a-hires") or main_image.get("src")
    if not image:
        landing_image = soup.find(id="landingImage")
        if landing_image:
            image = largest_dynamic_image(landing_image.get("data-a-dynamic-image")) or landing_image.get("src")

    return {"title": title, "price": price, "image_url": image}


def enrich_from_amazon_mobile(result, url):
    """Fills result in place with what amazon only serves on its mobile layout: the
    desktop page has no price and a generic og:image (see SCRAPE_HEADERS_MOBILE). Best
    effort: any fetch or parse problem leaves the generic result untouched."""
    try:
        with public_only_session() as session:
            content = fetch_page(session, url, SCRAPE_HEADERS_MOBILE)
    except requests.RequestException:
        return
    details = amazon_details(content)
    # amazon's og tags and <title> are generic or cluttered with site suffixes, so the
    # product title the page itself carries is the better one even if one was found
    if details["title"]:
        result["title"] = details["title"]
    if details["price"] is not None and result.get("price") is None:
        result["price"] = details["price"]
    if details["image_url"] and not result.get("image_url"):
        result["image_url"] = details["image_url"]


def find_jsonld_products(soup):
    """Every schema.org Product/Book-like object on the page, including nested
    variants/editions (ProductGroup.hasVariant, Book.workExample, ...) that sites
    often use to carry the actual price instead of a top-level offer."""
    products = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue

        blocks = data if isinstance(data, list) else [data]
        items = []
        for block in blocks:
            if isinstance(block, dict) and isinstance(block.get("@graph"), list):
                items.extend(block["@graph"])
            else:
                items.append(block)

        for item in list(items):
            if not isinstance(item, dict):
                continue
            for key in ("hasVariant", "workExample"):
                if isinstance(item.get(key), list):
                    items.extend(item[key])

        for item in items:
            if not isinstance(item, dict):
                continue
            item_types = item.get("@type", "")
            item_types = item_types if isinstance(item_types, list) else [item_types]
            if any(t and ("product" in str(t).lower() or "book" in str(t).lower()) for t in item_types):
                products.append(item)
    return products


def jsonld_price(products):
    for product in products:
        offers = product.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else None
        if not isinstance(offers, dict):
            continue
        price = offers.get("price") or (offers.get("priceSpecification") or {}).get("price")
        if price:
            return price
    return None


def jsonld_image(products):
    for product in products:
        image = product.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        if isinstance(image, dict):
            image = image.get("url")
        if image:
            return image
    return None


def jsonld_brand(products):
    for product in products:
        brand = product.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        if brand:
            return brand
    return None


def jsonld_value(products, key):
    for product in products:
        value = product.get(key)
        if value:
            return value
    return None
