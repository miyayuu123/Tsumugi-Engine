import os
import ssl
import urllib.request
import logging

class ProxyHandler:
    PROXY_SERVER = 'http://brd-customer-hl_334d7f0d-zone-serp:hq9vurjfbil2@brd.superproxy.io:22225'
    CERT_PATH = os.path.join(os.path.dirname(__file__), 'ssl_cert.pem')

    def build_opener(self, ssl_context):
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({'http': self.PROXY_SERVER, 'https': self.PROXY_SERVER}),
            urllib.request.HTTPSHandler(context=ssl_context)
        )

    def open_url(self, url):
        logging.debug(f"Opening URL: {url}")
        try:
            ssl_context = ssl.create_default_context(cafile=self.CERT_PATH)
            opener = self.build_opener(ssl_context)
            return opener.open(url)
        except Exception as e:
            logging.error(f"Error occurred while opening URL: {url}")
            logging.error(str(e))
            return None
