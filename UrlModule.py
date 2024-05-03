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
from random import shuffle
import socks
import socket
import gc  # Garbage collection module imported

class URLModule:
    SBR_WS_CDP = 'wss://brd-customer-hl_334d7f0d-zone-scraping_browser1:m30rrqh0eidq@brd.superproxy.io:9222'
    CERT_PATH = os.path.join(os.path.dirname(__file__), 'ssl_cert.pem')
    def __init__(self, gpt_api_key):
        self.gpt_client = GPTClient(gpt_api_key)
        self.socks_port = 9052  # TorのSOCKSポートを指定

    def build_opener(self, ssl_context=None):
        if ssl_context is None:
            ssl_context = ssl._create_unverified_context()  # SSL検証を無効にする

        socks.set_default_proxy(socks.SOCKS5, "localhost", self.socks_port)
        socket.socket = socks.socksocket

        return urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl_context)
        )

    def dispatch_url(self, url, structure=None, max_urls=10):
        if 'wikipedia' in url:
            chosen_structure = "https://ja.wikipedia.org/wiki/"
            return self.crawl_by_structure(url, chosen_structure, max_urls)
        elif 'j-platpat' in url:
            return self.inpit_search_from_input_box_sync(url, "AI")
        else:
            if structure is None:
                return
            elif structure == "all":
                result_with_js = self.fetch_links_from_js_page(url, max_urls)
                if not result_with_js:
                    return self.get_related_urls(url, max_urls)
                else:
                    return result_with_js
            else:
                chosen_structure = structure
                result_with_js = self.crawl_by_structure_with_js_sync(url, chosen_structure, max_urls)
                if not result_with_js:
                    return self.crawl_by_structure(url, chosen_structure, max_urls)
                else:
                    return result_with_js

    def crawl_by_structure(self, base_url, chosen_structure, max_urls=10):
        print(base_url, chosen_structure)
        visited = set()
        to_visit = [base_url]
        similar_structure_urls = []

        # SSLコンテキストとオープナーの準備
        ssl_context = ssl.create_default_context()
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

                soup = BeautifulSoup(html_content, 'html.parser')
                links = soup.find_all('a', href=True)
                shuffle(links)  # リンクのリストをランダムにシャッフル

                for link in links:
                    href = urljoin(current_url, link['href'])
                    # 選択された構造に基づくURLをフィルター
                    if href.startswith(chosen_structure) and href not in visited:
                        similar_structure_urls.append(href)
                        to_visit.append(href)
                        url_count += 1  # カウンターをインクリメント

                        # 最大URL数に達した場合、ループを抜ける
                        if url_count >= max_urls:
                            print(f"Reached the maximum number of URLs: {max_urls}")
                            break

        return similar_structure_urls

    async def crawl_by_structure_with_js(self, base_url, chosen_structure, max_urls=10):
        visited = set()
        to_visit = [base_url]
        similar_structure_urls = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(proxy={
                'server': f'socks5://localhost:{self.socks_port}'  # クラスで定義されたSOCKSポートを使用
            })
            try:
                page = await browser.new_page()

                # 取得したURLの数をカウントする
                url_count = 0

                while to_visit and url_count < max_urls:
                    current_url = to_visit.pop()
                    if current_url not in visited:
                        visited.add(current_url)

                        try:
                            await page.goto(current_url, wait_until='networkidle')
                            html_content = await page.content()
                        except Exception as e:
                            print(f"Error fetching {current_url}: {e}")
                            continue

                        soup = BeautifulSoup(html_content, 'html.parser')
                        links = soup.find_all('a', href=True)
                        shuffle(links)  # リンクのリストをランダムにシャッフル

                        for link in links:
                            href = urljoin(current_url, link['href'])
                            # 選択された構造に基づくURLをフィルター
                            if href.startswith(chosen_structure) and href not in visited:
                                similar_structure_urls.append(href)
                                to_visit.append(href)
                                url_count += 1  # カウンターをインクリメント

                                # 最大URL数に達した場合、ループを抜ける
                                if url_count >= max_urls:
                                    print(f"Reached the maximum number of URLs: {max_urls}")
                                    break
            finally:
                await browser.close()

        return similar_structure_urls

    # 同期コードから非同期メソッドを呼び出すためのメソッド
    def crawl_by_structure_with_js_sync(self, base_url, chosen_structure, max_urls=10):
        return asyncio.run(self.crawl_by_structure_with_js(base_url, chosen_structure, max_urls))

    async def get_links_from_js_page(self, url, max_urls=10):
        try:
            visited = set()
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(proxy={
                    'server': f'socks5://localhost:{self.socks_port}'  # クラスで定義されたSOCKSポートを使用
                })
                try:
                    page = await browser.new_page()
                    await page.goto(url)
                    links = await page.query_selector_all('a[href]')
                    shuffle(links)
                    index = 0
                    while len(visited) < max_urls and index < len(links):
                        link = links[index]
                        href = await link.get_attribute('href')
                        absolute_url = urljoin(url, href)
                        visited.add(absolute_url)
                        index += 1
                finally:
                    await page.close()
                    await browser.close()
                    gc.collect()  # Garbage collection after browser session
            return visited
        except Exception as e:
            print(f"An error occurred: {e}")

    def fetch_links_from_js_page(self, url, max_urls=10):
        return asyncio.run(self.get_links_from_js_page(url, max_urls))

    def get_related_urls(self, url, max_urls=10):
        visited = set()

        try:
            ssl_context = ssl.create_default_context()
            opener = self.build_opener(ssl_context)
            with opener.open(url) as response:
                html_content = response.read()
        except Exception as e:
            logging.error(f"Error occurred while fetching URL: {url}: {e}")
            return visited  # エラーが発生した場合は、空の集合を返す

        soup = BeautifulSoup(html_content, 'html.parser')
        links = soup.find_all('a', href=True)
        shuffle(links)
        for link in links:
            if len(visited) >= max_urls:
                break  # max_urlsに達したらループを抜ける
            href = link['href']
            absolute_url = urljoin(url, href)  # 相対URLを絶対URLに変換
            visited.add(absolute_url)  # 絶対URLを集合に追加

        return visited

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
