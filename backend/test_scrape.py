import ipaddress
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import requests
from flask import Flask
from flask_login import LoginManager

from routes import scrape
from routes.scrape import scrape_bp


class _ProductPageHandler(BaseHTTPRequestHandler):
    hosts = []
    pages = {"/": b"<html><head><title>Test product</title></head></html>"}

    def do_GET(self):
        self.hosts.append(self.headers["Host"])
        body = _ProductPageHandler.pages.get(self.path, _ProductPageHandler.pages["/"])
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _ForbiddenHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"blocked"
        self.send_response(403)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ScrapeHelpersTestCase(unittest.TestCase):
    def test_parse_price_text(self):
        cases = {
            "16,96€": 16.96,
            " 28,50€ ": 28.5,
            "19,95 €": 19.95,
            "1.234,56 €": 1234.56,
            "44.72": 44.72,
            "12.5": 12.5,
            "1.234": 1234.0,
            "59,50 EUR": 59.5,
            "Prezzo consigliato: 19,95€": 19.95,
            "7,13€": 7.13,
            "16,96\u00a0€": 16.96,
        }
        for text, expected in cases.items():
            self.assertEqual(scrape.parse_price_text(text), expected, text)
        self.assertIsNone(scrape.parse_price_text(""))
        self.assertIsNone(scrape.parse_price_text("no price here"))

    def test_is_amazon_url(self):
        self.assertTrue(scrape.is_amazon_url("https://www.amazon.it/dp/183866632X/"))
        self.assertTrue(scrape.is_amazon_url("https://amazon.com/dp/B09RF2ST6T"))
        self.assertTrue(scrape.is_amazon_url("https://smile.amazon.co.uk/dp/X"))
        self.assertFalse(scrape.is_amazon_url("https://www.amazonius.it/dp/X"))
        self.assertFalse(scrape.is_amazon_url("https://kaufland.it/product/1/"))

    def test_amazon_details_prefers_list_price_and_hires_image(self):
        content = b"""
        <html><head><title>Le Toy Van - bambole : Amazon.it: Giochi e giocattoli</title></head><body>
        <span id="title">Le Toy Van - La mia famiglia di 4 bambole</span>
        <div class="a-price a-text-price apex-basisprice-value" data-a-strike="true">
          <span class="a-offscreen">34,05&euro;</span><span aria-hidden="true">34,05&euro;</span>
        </div>
        <div class="a-price aok-align-center reinventPricePriceToPayMargin priceToPay">
          <span class="a-price-whole">28</span><span class="a-price-decimal">,</span>
          <span class="a-price-fraction">50</span><span class="a-price-symbol">&euro;</span>
        </div>
        <img data-a-image-name="mainImage" src="https://m.media-amazon.com/images/I/71Jil1yKA7L._AC_UF350,350_QL50_.jpg"
             data-a-hires="https://m.media-amazon.com/images/I/71Jil1yKA7L._AC_UF1000,1000_QL80_.jpg">
        </body></html>
        """
        details = scrape.amazon_details(content)
        self.assertEqual(details["title"], "Le Toy Van - La mia famiglia di 4 bambole")
        self.assertEqual(details["price"], 34.05)
        self.assertEqual(details["image_url"], "https://m.media-amazon.com/images/I/71Jil1yKA7L._AC_UF1000,1000_QL80_.jpg")

    def test_amazon_details_uses_current_price_without_list_price(self):
        content = b"""
        <html><body>
        <span id="title">Solo un prezzo</span>
        <div class="a-price aok-align-center priceToPay">
          <span class="a-price-whole">12</span><span class="a-price-decimal">,</span>
          <span class="a-price-fraction">34</span><span class="a-price-symbol">&euro;</span>
        </div>
        </body></html>
        """
        details = scrape.amazon_details(content)
        self.assertEqual(details["title"], "Solo un prezzo")
        self.assertEqual(details["price"], 12.34)

    def test_amazon_details_reads_desktop_landing_image(self):
        content = b"""
        <html><body>
        <span id="productTitle">Spaghetti! An interactive recipe book</span>
        <img id="landingImage" src="https://m.media-amazon.com/images/I/819Y1ARj4gL._SY342_.jpg"
             data-a-dynamic-image="{&quot;https://m.media-amazon.com/images/I/819Y1ARj4gL._SY342_.jpg&quot;:[342,343],&quot;https://m.media-amazon.com/images/I/819Y1ARj4gL._SY500_.jpg&quot;:[500,501]}">
        </body></html>
        """
        details = scrape.amazon_details(content)
        self.assertEqual(details["title"], "Spaghetti! An interactive recipe book")
        self.assertEqual(details["price"], None)
        self.assertEqual(details["image_url"], "https://m.media-amazon.com/images/I/819Y1ARj4gL._SY500_.jpg")

    def test_largest_dynamic_image_accepts_entity_escaped_json(self):
        attr = '{"https://x._SY342_.jpg":[342,343],"https://x._SY500_.jpg":[500,501]}'
        self.assertEqual(scrape.largest_dynamic_image(attr), "https://x._SY500_.jpg")
        self.assertIsNone(scrape.largest_dynamic_image("{not json"))
        self.assertIsNone(scrape.largest_dynamic_image(None))


class _FakeCffiResponse:
    def __init__(self, body=b"", status_code=200, text=None):
        self._body = body
        self.status_code = status_code
        self._text = text if text is not None else (body.decode("utf-8") if isinstance(body, bytes) else body)

    @property
    def text(self):
        return self._text

    def iter_content(self, chunk_size):
        yield self._body

    def close(self):
        pass


class _FakeCffiSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, timeout=None, curl_options=None):
        self.calls.append(("post", url, json))
        return self.responses.pop(0)

    def get(self, url, headers=None, timeout=None, allow_redirects=None, curl_options=None, stream=None):
        self.calls.append(("get", url))
        return self.responses.pop(0)


class InterstitialTestCase(unittest.TestCase):
    INTERSTITIAL = b"""
    <html><head><meta http-equiv="refresh" content="5; URL='/'"><title>&nbsp;</title>
    <script> var i = 1795130450; var j = i + Number("7157" + "55659"); </script></head>
    <body><iframe src="/interstitial/ic.html"></iframe>
    <script>function triggerInterstitialChallenge(){var xhr=new XMLHttpRequest();
    xhr.open("POST","/_sec/verify?provider=interstitial",false);
    xhr.send(JSON.stringify({"bm-verify":"AAQAAAAOtest123","pow-response":j}));}</script></body></html>
    """

    def setUp(self):
        self.session = _FakeCffiSession([
            _FakeCffiResponse(text='{"reload": true}'),
            _FakeCffiResponse(b"<html><head><title>Real page</title></head></html>"),
        ])

    def test_replays_challenge_and_refetches(self):
        result = scrape.verify_interstitial(self.session, "https://www.zara.com/it/it/x.html", self.INTERSTITIAL, {})

        self.assertEqual(result, b"<html><head><title>Real page</title></head></html>")
        kind, url, payload = self.session.calls[0]
        self.assertEqual(kind, "post")
        self.assertEqual(url, "https://www.zara.com/_sec/verify?provider=interstitial")
        self.assertEqual(payload, {"bm-verify": "AAQAAAAOtest123", "pow-response": "2510886109"})
        self.assertEqual(self.session.calls[1], ("get", "https://www.zara.com/it/it/x.html"))

    def test_returns_none_when_not_an_interstitial(self):
        body = b"<html><head><title>Normal page</title></head></html>"
        self.assertIsNone(scrape.verify_interstitial(self.session, "https://www.zara.com/it/it/x.html", body, {}))
        self.assertEqual(self.session.calls, [])

    def test_returns_none_when_verify_rejects(self):
        self.session.responses = [_FakeCffiResponse(text='{"reload": false}')]
        result = scrape.verify_interstitial(self.session, "https://www.zara.com/it/it/x.html", self.INTERSTITIAL, {})
        self.assertIsNone(result)

    def test_returns_none_when_refetch_fails(self):
        self.session.responses = [_FakeCffiResponse(text='{"reload": true}'), _FakeCffiResponse(status_code=403)]
        result = scrape.verify_interstitial(self.session, "https://www.zara.com/it/it/x.html", self.INTERSTITIAL, {})
        self.assertIsNone(result)

    def test_returns_none_when_session_raises(self):
        class _ExplodingSession:
            def post(self, *args, **kwargs):
                raise OSError("network down")

        result = scrape.verify_interstitial(_ExplodingSession(), "https://www.zara.com/it/it/x.html", self.INTERSTITIAL, {})
        self.assertIsNone(result)

    def test_amazon_details_tolerates_unrelated_page(self):
        details = scrape.amazon_details(b"<html><head><title>Not amazon</title></head></html>")
        self.assertEqual(details, {"title": None, "price": None, "image_url": None})


class ScrapeTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY="test-secret", TESTING=True, LOGIN_DISABLED=True)
        LoginManager(self.app)
        self.app.register_blueprint(scrape_bp)
        self.client = self.app.test_client()

        _ProductPageHandler.hosts = []
        _ProductPageHandler.pages = {
            "/": b"<html><head><title>Test product</title></head></html>",
            "/kaufland-graph": (
                b'<html><head><title>shop</title>'
                b'<script type="application/ld+json">{"@context":"https://schema.org","@graph":['
                b'{"@type":"WebPage","name":"Birilli Vilac Penguin 6 pezzi - Kaufland.it"},'
                b'{"@type":"Product","name":"Birilli Vilac Penguin 6 pezzi",'
                b'"image":"https://media.cdn.kaufland.de/product-images/original/b3fbc5a845dcf9ffc3695287a302aa8b.jpg",'
                b'"brand":{"@type":"Brand","name":"Vilac"},'
                b'"offers":{"@type":"Offer","price":68.88,"priceCurrency":"EUR"}}]}</script>'
                b"</head></html>"
            ),
            "/mixed-image": (
                b'<html><head><title>mixed shop</title>'
                b'<meta property="og:image" content="http://cdn.shop.example/img/product.jpg?v=1&width=1024"/>'
                b'<meta property="product:price:amount" content="12,34"/>'
                b'<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
                b'"name":"Mixed product","image":"https://cdn.shop.example/img/product.jpg?v=1&width=1024",'
                b'"offers":{"@type":"Offer","price":12.34,"priceCurrency":"EUR"}}</script>'
                b"</head></html>"
            ),
            "/multi-variant": (
                b'<html><head><title>multi variant</title>'
                b'<meta property="product:price:amount" content="15,95"/>'
                b'<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
                b'"name":"Donkino",'
                b'"offers":[{"@type":"Offer","name":"Red","price":16.95,"priceCurrency":"EUR"},'
                b'{"@type":"Offer","name":"Blue","price":15.95,"priceCurrency":"EUR"}]}</script>'
                b"</head></html>"
            ),
        }
        self.server = HTTPServer(("127.0.0.1", 0), _ProductPageHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_rejects_internal_address_up_front(self):
        response = self.client.post("/api/scrape", json={"url": f"http://127.0.0.1:{self.port}/"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(_ProductPageHandler.hosts, [])

    def test_dns_rebinding_to_internal_address_never_connects(self):
        real_getaddrinfo = socket.getaddrinfo
        calls = []

        def rebinding_getaddrinfo(host, port=None, *args, **kwargs):
            if host != "rebind.test":
                return real_getaddrinfo(host, port, *args, **kwargs)
            calls.append(host)
            # public for the up-front check, internal for every lookup after it
            ip = "93.184.215.14" if len(calls) == 1 else "127.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]

        with mock.patch("socket.getaddrinfo", rebinding_getaddrinfo):
            response = self.client.post("/api/scrape", json={"url": f"http://rebind.test:{self.port}/"})

        self.assertEqual(response.status_code, 400)
        self.assertGreater(len(calls), 1)
        self.assertEqual(_ProductPageHandler.hosts, [])

    def test_connects_to_checked_address_with_original_host(self):
        # pretend shop.test is public and lives at 127.0.0.1, without any real DNS for it:
        # the request can only arrive if the connection goes to the checked address
        def resolve(hostname):
            return [ipaddress.ip_address("127.0.0.1")] if hostname == "shop.test" else None

        with mock.patch.object(scrape, "resolve_public_ips", resolve), \
                mock.patch.object(scrape, "impersonated_fetch", mock.Mock(return_value=None)):
            response = self.client.post("/api/scrape", json={"url": f"http://shop.test:{self.port}/"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["title"], "Test product")
        self.assertEqual(_ProductPageHandler.hosts, [f"shop.test:{self.port}"])

    def test_parses_kaufland_style_graph_jsonld(self):
        def resolve(hostname):
            return [ipaddress.ip_address("127.0.0.1")] if hostname == "shop.test" else None

        with mock.patch.object(scrape, "resolve_public_ips", resolve):
            response = self.client.post("/api/scrape", json={"url": f"http://shop.test:{self.port}/kaufland-graph"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["title"], "Birilli Vilac Penguin 6 pezzi")
        self.assertEqual(data["price"], 68.88)
        self.assertEqual(data["image_url"], "https://media.cdn.kaufland.de/product-images/original/b3fbc5a845dcf9ffc3695287a302aa8b.jpg")
        self.assertEqual(data["brand"], "Vilac")

    def test_prefers_https_image_when_og_image_is_plain_http(self):
        def resolve(hostname):
            return [ipaddress.ip_address("127.0.0.1")] if hostname == "shop.test" else None

        with mock.patch.object(scrape, "resolve_public_ips", resolve):
            response = self.client.post("/api/scrape", json={"url": f"http://shop.test:{self.port}/mixed-image"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["image_url"], "https://cdn.shop.example/img/product.jpg?v=1&width=1024")
        self.assertEqual(data["price"], 12.34)

    def test_jsonld_variant_price_wins_over_cheapest_meta_price(self):
        def resolve(hostname):
            return [ipaddress.ip_address("127.0.0.1")] if hostname == "shop.test" else None

        with mock.patch.object(scrape, "resolve_public_ips", resolve):
            response = self.client.post("/api/scrape", json={"url": f"http://shop.test:{self.port}/multi-variant"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["price"], 16.95)

    def test_retries_through_impersonated_client_when_interstitial_served(self):
        def resolve(hostname):
            return [ipaddress.ip_address("93.184.216.14")] if hostname in ("shop.test", "www.zara.com") else None

        # the "stub" the plain client gets is a 200 interstitial asking for the POST it
        # can't perform; the impersonated client replays the challenge and gets the page
        stub = b'<html><head><title>&nbsp;</title><script>xhr.open("POST","/_sec/verify?provider=interstitial",false);</script></head></html>'
        real = (
            b'<html><head><title>Real Zara product</title>'
            b'<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
            b'"name":"Real Zara product","offers":{"@type":"Offer","price":15.95,"priceCurrency":"EUR"}}</script>'
            b"</head></html>"
        )
        fake_fetch = mock.Mock(return_value=real)
        with mock.patch.object(scrape, "resolve_public_ips", resolve), \
                mock.patch.object(scrape, "fetch_page", mock.Mock(return_value=stub)), \
                mock.patch.object(scrape, "impersonated_fetch", fake_fetch):
            response = self.client.post("/api/scrape", json={"url": f"https://www.zara.com/it/it/x.html"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["title"], "Real Zara product")
        self.assertEqual(data["price"], 15.95)
        fake_fetch.assert_called_once_with("https://www.zara.com/it/it/x.html", scrape.SCRAPE_HEADERS_BROWSER)

    def test_retries_through_impersonated_client_when_price_missing(self):
        def resolve(hostname):
            return [ipaddress.ip_address("93.184.216.14")] if hostname in ("shop.test", "shop.example") else None

        stripped = (
            b'<html><head><title>Tuminy</title>'
            b'<meta property="og:title" content="Tuminy"/>'
            b'<meta property="og:image" content="http://cdn.shop.example/img/tuminy.jpg"/>'
            b"<body></body></html>"
        )
        complete = (
            b'<html><head><title>Tuminy</title>'
            b'<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
            b'"name":"Tuminy","image":"https://cdn.shop.example/img/tuminy.jpg",'
            b'"brand":{"@type":"Brand","name":"Comomg"},'
            b'"offers":{"@type":"Offer","price":61.95,"priceCurrency":"EUR"}}</script>'
            b"</head></html>"
        )

        def fake_fetch_page(session, url, headers):
            return stripped

        fake_fetch = mock.Mock(return_value=complete)
        with mock.patch.object(scrape, "resolve_public_ips", resolve), \
                mock.patch.object(scrape, "fetch_page", fake_fetch_page), \
                mock.patch.object(scrape, "impersonated_fetch", fake_fetch):
            response = self.client.post("/api/scrape", json={"url": "https://shop.example/en/products/tuminy-m"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        # everything the stripped page carried stays, the retry only fills the gaps
        self.assertEqual(data["title"], "Tuminy")
        self.assertEqual(data["image_url"], "http://cdn.shop.example/img/tuminy.jpg")
        self.assertEqual(data["price"], 61.95)
        self.assertEqual(data["brand"], "Comomg")

    def test_no_impersonated_retry_when_everything_was_found(self):
        def resolve(hostname):
            return [ipaddress.ip_address("127.0.0.1")] if hostname == "shop.test" else None

        complete = (
            b'<html><head><title>Full product</title>'
            b'<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
            b'"name":"Full product","image":"https://cdn.example/img.jpg",'
            b'"offers":{"@type":"Offer","price":9.99,"priceCurrency":"EUR"}}</script>'
            b"</head></html>"
        )
        with mock.patch.object(scrape, "resolve_public_ips", resolve), \
                mock.patch.object(scrape, "fetch_page", mock.Mock(return_value=complete)), \
                mock.patch.object(scrape, "impersonated_fetch", mock.Mock(side_effect=AssertionError("must not be called"))):
            response = self.client.post("/api/scrape", json={"url": f"http://shop.test:{self.port}/"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["price"], 9.99)

    def test_enriches_amazon_results_from_mobile_page(self):
        def resolve(hostname):
            return [ipaddress.ip_address("93.184.216.14")] if hostname == "www.amazon.it" else None

        def fake_fetch_page(session, url, headers):
            if "iPhone" in headers.get("User-Agent", ""):
                return b"""
                <html><head><title>Le Toy Van - bambole : Amazon.it: Giochi e giocattoli</title></head><body>
                <span id="title">Le Toy Van - La mia famiglia di 4 bambole</span>
                <div class="a-price a-text-price apex-basisprice-value" data-a-strike="true">
                  <span class="a-offscreen">34,05&euro;</span><span aria-hidden="true">34,05&euro;</span>
                </div>
                <div class="a-price aok-align-center priceToPay">
                  <span class="a-price-whole">28</span><span class="a-price-decimal">,</span>
                  <span class="a-price-fraction">50</span><span class="a-price-symbol">&euro;</span>
                </div>
                <img data-a-image-name="mainImage" src="https://m.media-amazon.com/images/I/71Jil1yKA7L._AC_UF350,350_QL50_.jpg"
                     data-a-hires="https://m.media-amazon.com/images/I/71Jil1yKA7L._AC_UF1000,1000_QL80_.jpg">
                </body></html>
                """
            return b"""
            <html><head>
            <meta property="og:title" content="Amazon"/>
            <meta property="og:description" content="Amazon"/>
            <meta property="og:image" content="https://m.media-amazon.com/images/G/01/share-icons/previewdoh/amazon.png"/>
            <title>Le Toy Van - bambole : Amazon.it: Giochi e giocattoli</title>
            </head></html>
            """

        with mock.patch.object(scrape, "resolve_public_ips", resolve), \
                mock.patch.object(scrape, "fetch_page", fake_fetch_page):
            response = self.client.post("/api/scrape", json={"url": "https://www.amazon.it/dp/183866632X/"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["title"], "Le Toy Van - La mia famiglia di 4 bambole")
        self.assertEqual(data["price"], 34.05)
        self.assertEqual(data["image_url"], "https://m.media-amazon.com/images/I/71Jil1yKA7L._AC_UF1000,1000_QL80_.jpg")

    def test_amazon_enrichment_failure_keeps_generic_result(self):
        def resolve(hostname):
            return [ipaddress.ip_address("93.184.216.14")] if hostname == "www.amazon.it" else None

        def fake_fetch_page(session, url, headers):
            if "iPhone" in headers.get("User-Agent", ""):
                raise requests.RequestException("mobile page blocked")
            return b"<html><head><title>Le Toy Van - bambole : Amazon.it</title></head></html>"

        with mock.patch.object(scrape, "resolve_public_ips", resolve), \
                mock.patch.object(scrape, "fetch_page", fake_fetch_page):
            response = self.client.post("/api/scrape", json={"url": "https://www.amazon.it/dp/B09RF2ST6T"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["title"], "Le Toy Van - bambole : Amazon.it")
        self.assertNotIn("price", data)
        self.assertIsNone(data["image_url"])

    def test_falls_back_to_impersonated_client_when_blocked(self):
        blocked = HTTPServer(("127.0.0.1", 0), _ForbiddenHandler)
        blocked_port = blocked.server_address[1]
        threading.Thread(target=blocked.serve_forever, daemon=True).start()
        try:
            def resolve(hostname):
                return [ipaddress.ip_address("127.0.0.1")] if hostname == "shop.test" else None

            fake_fetch = mock.Mock(return_value=(
                b"<html><head><title>Block bypass</title>"
                b'<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
                b'"name":"Block bypass","offers":{"@type":"Offer","price":1.23,"priceCurrency":"EUR"}}</script>'
                b"</head></html>"
            ))
            url = f"http://shop.test:{blocked_port}/"
            with mock.patch.object(scrape, "resolve_public_ips", resolve), \
                    mock.patch.object(scrape, "impersonated_fetch", fake_fetch):
                response = self.client.post("/api/scrape", json={"url": url})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["title"], "Block bypass")
            fake_fetch.assert_called_once_with(url, scrape.SCRAPE_HEADERS_BROWSER)
        finally:
            blocked.shutdown()
            blocked.server_close()

    def test_impersonated_failure_still_returns_error(self):
        blocked = HTTPServer(("127.0.0.1", 0), _ForbiddenHandler)
        blocked_port = blocked.server_address[1]
        threading.Thread(target=blocked.serve_forever, daemon=True).start()
        try:
            def resolve(hostname):
                return [ipaddress.ip_address("127.0.0.1")] if hostname == "shop.test" else None

            with mock.patch.object(scrape, "resolve_public_ips", resolve), \
                    mock.patch.object(scrape, "impersonated_fetch", mock.Mock(return_value=None)):
                response = self.client.post("/api/scrape", json={"url": f"http://shop.test:{blocked_port}/"})

            self.assertEqual(response.status_code, 400)
        finally:
            blocked.shutdown()
            blocked.server_close()


if __name__ == "__main__":
    unittest.main()
