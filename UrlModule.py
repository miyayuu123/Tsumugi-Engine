# urlmodule.py
from bs4 import BeautifulSoup
import urllib.parse
from urllib.parse import urlparse, urlunparse, urljoin
import logging
from gptclient import GPTClient
import re
import requests
import os
import ssl
import asyncio
from playwright.async_api import async_playwright
from playwright.async_api import async_playwright, TimeoutError
from concurrent.futures import ThreadPoolExecutor, as_completed

class URLModule:
    PROXY_SERVER = 'http://brd-customer-hl_334d7f0d-zone-unblocker:l04btgzq53bu@brd.superproxy.io:22225'
    SBR_WS_CDP = 'wss://brd-customer-hl_334d7f0d-zone-scraping_browser1:m30rrqh0eidq@brd.superproxy.io:9222'
    CERT_PATH = os.path.join(os.path.dirname(__file__), 'ssl_cert.pem')
    def __init__(self, gpt_api_key):
        self.gpt_client = GPTClient(gpt_api_key)

    def build_opener(self, ssl_context):
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({'http': self.PROXY_SERVER, 'https': self.PROXY_SERVER}),
            urllib.request.HTTPSHandler(context=ssl_context)
        )

    def dispatch_url(self, url, structure=None, max_urls=150):
        if 'wikipedia' in url:
            chosen_structure = "https://ja.wikipedia.org/wiki/"
            return self.crawl_by_structure(url, chosen_structure, max_urls)
        elif 'j-platpat' in url:
            return self.inpit_search_from_input_box_sync(url, "AI")
        else:
                if structure is None:
                    return
                else:
                    chosen_structure = structure
                print(chosen_structure)
                return self.crawl_by_structure(url, chosen_structure, max_urls)


    # get_child_page_urlsメソッドの更新版
    def get_child_page_urls(self, url, max_urls=15):
        try:
            ssl_context = ssl.create_default_context(cafile=self.CERT_PATH)
            opener = self.build_opener(ssl_context)
            with opener.open(url) as response:
                html_content = response.read()
        except Exception as e:
            logging.error(f"Failed to open URL {url}: {e}")
            return None

        soup = BeautifulSoup(html_content, 'html.parser')
        base_url = "{0.scheme}://{0.netloc}".format(urlparse(url))
        child_urls = set()

        for link in soup.find_all('a', href=True):
            if len(child_urls) >= max_urls:
                break  # 最大URL数に達したらループを抜ける
            href = link['href']
            full_url = urljoin(base_url, href)
            if full_url.startswith(base_url):
                child_urls.add(full_url)

        return child_urls


    def crawl_by_structure(self, base_url, chosen_structure, max_urls=15):
        visited = set()
        to_visit = [base_url]
        similar_structure_urls = []

        # SSLコンテキストとオープナーの準備
        ssl_context = ssl.create_default_context(cafile=self.CERT_PATH)
        opener = self.build_opener(ssl_context)

        # 取得したURLの数をカウントする
        url_count = 0

        while to_visit and url_count < max_urls:
            current_url = to_visit.pop()
            if current_url not in visited:
                visited.add(current_url)

                try:
                    response = opener.open(current_url)
                    html_content = response.read()
                except Exception as e:
                    print(f"Error fetching {current_url}: {e}")
                    continue

                print(f"Processing: {current_url}")  # 現在処理しているURLを表示

                soup = BeautifulSoup(html_content, 'html.parser')
                for link in soup.find_all('a', href=True):
                    href = urljoin(current_url, link['href'])
                    # 選択された構造に基づくURLをフィルター
                    if href.startswith(chosen_structure) and href not in visited:
                        print(f"Found matching link: {href}")
                        similar_structure_urls.append(href)
                        to_visit.append(href)
                        url_count += 1  # カウンターをインクリメント

                        # 最大URL数に達した場合、ループを抜ける
                        if url_count >= max_urls:
                            print(f"Reached the maximum number of URLs: {max_urls}")
                            break

        return similar_structure_urls

    async def get_links_from_js_page(self, url):
        visited = set()  # 取得したURLの集合を初期化
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(self.SBR_WS_CDP)
            #browser = await pw.chromium.launch(headless=False)  # ヘッドレスモードでブラウザを起動
            try:
                page = await browser.new_page()
                await page.goto(url)
                links = await page.query_selector_all('a[href]')
                for link in links:
                    href = await link.get_attribute('href')
                    absolute_url = urljoin(url, href)
                    visited.add(absolute_url)
            finally:
                await browser.close()
        return visited

    # 同期コードから非同期メソッドを呼び出すためのメソッド
    def fetch_links_from_js_page(self, url):
        return asyncio.run(self.get_links_from_js_page(url))









###使用しない
    async def inpit_search_from_input_box(self, url, search_query):
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)  # ヘッドレスモードでブラウザを起動
            try:
                page = await browser.new_page()
                await page.goto(url)

                # 検索窓にクエリを入力
                await page.fill('#s01_srchCondtn_txtSimpleSearch', search_query)
                # 検索ボタンをクリック
                await page.click('#s01_srchBtn_btnSearch')
                # 「特許」という文言を含むリンクをクリック
                await page.click("//a[contains(text(), '特許') and contains(@class, 'ng-star-inserted')]")
                # ラジオボタンをクリック
                await page.click('#rdoTxtPdfView_1-input')
                # `<embed>`タグの`src`属性からPDFのURLを取得
                pdf_url = await page.get_attribute('#p0201_pdfObj', 'src')
                # PDFファイルをダウンロード
                response = requests.get(pdf_url)
                if response.status_code == 200:
                    with open('downloaded_pdf.pdf', 'wb') as f:
                        f.write(response.content)
                    print("PDFをダウンロードしました。")
                else:
                    print("PDFのダウンロードに失敗しました。")

            finally:
                await browser.close()


    def inpit_search_from_input_box_sync(self, url, search_query):
        return asyncio.run(self.inpit_search_from_input_box(url, search_query))
