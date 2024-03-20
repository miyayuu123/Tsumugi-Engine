import urllib.request
from bs4 import BeautifulSoup, NavigableString
import re
import os
import ssl

class Tagmodule:
    PROXY_SERVER = 'http://brd-customer-hl_334d7f0d-zone-unblocker:l04btgzq53bu@brd.superproxy.io:22225'
    CERT_PATH = os.path.join(os.path.dirname(__file__), 'ssl_cert.pem')

    def __init__(self):
        # SSLコンテキストの作成
        self.ssl_context = ssl.create_default_context(cafile=self.CERT_PATH)
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    def build_opener(self):
        # プロキシハンドラーとHTTPSハンドラーを設定
        proxy_handler = urllib.request.ProxyHandler({
            'http': self.PROXY_SERVER,
            'https': self.PROXY_SERVER,
        })
        https_handler = urllib.request.HTTPSHandler(context=self.ssl_context)

        # オープナーの作成
        opener = urllib.request.build_opener(proxy_handler, https_handler)
        return opener
    def extract_text_without_splitting(self, url):
        opener = self.build_opener()
        # オープナーを使用してリクエストを実行
        with opener.open(url) as response:
            html = response.read()

        soup = BeautifulSoup(html, 'html.parser')
        # ページのタイトルを取得
        page_title = soup.title.string if soup.title else "No Title"
        main_content = soup.find('main')
        if main_content is None:
            main_content = soup
        for tag in main_content(['script', 'style', 'header', 'footer', 'nav', 'aside', 'td', 'h1', 'table', 'li', 'ul', 'ol']):
            tag.extract()

        def join_texts(tag):
            texts = []
            for child in tag.descendants:
                if isinstance(child, NavigableString):
                    child_str = str(child)
                    # ここで改行をそのまま保持
                    texts.append(child_str)
            # テキスト間の不要な空白を削除しつつ、改行は保持
            return ''.join(texts)

        complete_text = join_texts(main_content)
        complete_text = re.sub(r'[!"#$%&\'\\\\()*+,-./:;<=>?@[\\]^_`{|}~「」〔〕“”〈〉『』【】＆＊・（）＄＃＠。、？！｀＋￥％]', '', complete_text)
        complete_text = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}|\（.*?\）', '', complete_text)
        complete_text = re.sub(r"<.*?>", "", complete_text)


        complete_text = re.sub(r' +', ' ', complete_text)
        complete_text = re.sub(r'\n ', '\n', complete_text)
        complete_text = re.sub(r' \n', '\n', complete_text)
        complete_text = re.sub(r'^\s+', '', complete_text)

        if "wikipedia" in url:
            # "出典: フリー百科事典『ウィキペディア』"で始まるかチェック
            if not complete_text.startswith("出典: フリー百科事典『ウィキペディア』"):
                return "", "No Title"  # 条件に合わない場合は空テキストとデフォルトタイトルを返す
            else:
                # 条件に合う場合はその文言を除いたテキストを返す
                return complete_text.replace("出典: フリー百科事典『ウィキペディア』", "").strip(), page_title
        # テキストとタイトルを返す
        return complete_text, page_title

    def extract_sentences(self, text, min_length=10):
        pattern = r'[^。]+[。]'
        sentences = re.findall(pattern, text)
        sentences_filtered = []
        exclusion_keywords = ["詳細は", "脚注", "注釈", "出典", "参考文献", "関連項目", "ロンドル", "ウィキペディア", "ウィキメディア"]

        # 漢字が7回以上連続しているパターン
        kanji_sequence_pattern = re.compile(r'[\u4e00-\u9faf\u3400-\u4dbf]{7,}')

        for sentence in sentences:
            if any(keyword in sentence for keyword in exclusion_keywords):
                continue  # 指定されたキーワードを含む文はスキップ
            if kanji_sequence_pattern.search(sentence):
                continue  # 漢字が7回以上連続している文はスキップ
            sentence_trimmed = sentence.strip()
            if len(sentence_trimmed) >= min_length:
                sentences_filtered.append(sentence_trimmed)
        return sentences_filtered


    def extract_paragraphs(self, text):
        paragraphs = text.split('\n')  # 改行でテキストを分割してパラグラフを取得
        meaningful_paragraphs = []

        temp_paragraph = ""  # 一時的にパラグラフを保持する変数
        for paragraph in paragraphs:
            cleaned_paragraph = paragraph.strip()
            if '。' in cleaned_paragraph:
                if temp_paragraph and not temp_paragraph.endswith('。'):
                    # 一時的なパラグラフが「。」で終わっていない場合は、現在のパラグラフと結合
                    temp_paragraph += cleaned_paragraph
                    if temp_paragraph.endswith('。'):
                        # 結合後に「。」で終わっていれば、追加して一時的なパラグラフをクリア
                        meaningful_paragraphs.append(temp_paragraph)
                        temp_paragraph = ""
                else:
                    # 一時的なパラグラフが空、または既に「。」で終わっている場合
                    temp_paragraph = cleaned_paragraph  # 現在のパラグラフを一時的なパラグラフとして設定

                    # 現在のパラグラフが「。」で終わっていれば、すぐに追加
                    if cleaned_paragraph.endswith('。'):
                        meaningful_paragraphs.append(temp_paragraph)
                        temp_paragraph = ""  # 追加後はクリア

            # 文章の最後が「。」で終わっていない場合の処理
            if temp_paragraph:
                pass

        return meaningful_paragraphs


if __name__ == "__main__":
    # ここでテストしたいURLを設定します
    test_url = "https://business.nikkei.com/"
    tagmodule = Tagmodule()
    text, title = tagmodule.extract_text_without_splitting(test_url)
    paragraphs = tagmodule.extract_paragraphs(text)

    print(f"Title: {title}\n")
    print("Extracted Paragraphs:")
    for i, paragraph in enumerate(paragraphs):
        print(f"Paragraph {i+1}: {paragraph}\n")
