from gptclient import GPTClient
import logging
from bs4 import BeautifulSoup
import urllib.parse
import ssl
from urllib.parse import urlparse, urlunparse
import urllib.request
import os
import socks
import socket
import requests

class QueryModule:
    CERT_PATH = os.path.join(os.path.dirname(__file__), 'ssl_cert.pem')
    def __init__(self, gpt_api_key):
        self.gpt_client = GPTClient()
        self.generated_keywords = set()  # 生成されたキーワードを追跡するセット
        self.socks_port = 9052  # TorのSOCKSポートを指定
        socks.set_default_proxy(socks.SOCKS5, "localhost", self.socks_port)
        socket.socket = socks.socksocket

    def build_opener(self, ssl_context):
        logging.debug("Building opener with proxy and SSL context")
        if ssl_context is None:
            ssl_context = ssl.create_default_context()  # SSL検証を無効にする
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl_context)
        )

    def getUrlFromDB(self, query):
        print(query)
        url = 'https://yfoilupoajwkyfnkyaig.supabase.co/functions/v1/search_data'
        headers = {
            'Content-Type': 'application/json',
            'apikey': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inlmb2lsdXBvYWp3a3lmbmt5YWlnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MTA1NTU0ODcsImV4cCI6MjAyNjEzMTQ4N30.7a9P5p4x7QcRNN0PVIwKjKmk0CcNIIuBUutzX-lI5c0'
        }
        data = {
            'search': query
        }

        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()  # ステータスコードが200系以外は例外を発生させる
            print(response)
            # JSONレスポンスからURLを抽出する場合（レスポンスの形式に依存）
            url_data = response.json()
            if 'result' in url_data and url_data['result']:
                first_result = url_data['result'][0]
                if 'url' in first_result:
                    return [first_result['url']]
                else:
                    print("URLがレスポンスの最初の結果に含まれていません。")
                    return None
            else:
                print("結果がレスポンスに含まれていません。")
                return None
        except requests.exceptions.HTTPError as errh:
            print(f"HTTPエラーが発生しました: {errh}")
        except requests.exceptions.ConnectionError as errc:
            print(f"接続エラーが発生しました: {errc}")
        except requests.exceptions.Timeout as errt:
            print(f"タイムアウトエラーが発生しました: {errt}")
        except requests.exceptions.RequestException as err:
            print(f"リクエスト中にエラーが発生しました: {err}")
        return None

    def generate_search_keyword(self, criteria, existing_queries=[]):
        logging.debug(f"Generating search keyword for criteria: {criteria}")
        prompt = f"あなたは、下記条件に合致する企業の企業情報を掲載したページ(単一ページか、一覧・リスト・まとめページ。臨機応変に。)が出てくると想定される、Googleでの検索キーワードを生成するAIです。検索キーワードなので、端的に短く、が基本です。もし、これまでに実行されたクエリが渡されていた場合、そことは違う角度でキーワードを返してください。キーワードのみ、端的に返してください。そのまま検索が実行されます。条件: {criteria} これまで実行したクエリ: {existing_queries}"
        attempt_count = 0
        content = ""
        while attempt_count < 5:  # 重複を避けるために最大5回まで試行します。
            result = self.gpt_client.generate_text(prompt, content, use_gpt4=True).replace('"', '')
            if result not in self.generated_keywords and result not in existing_queries:
                self.generated_keywords.add(result)  # 新しいキーワードをセットに追加
                return result
            attempt_count += 1
        logging.warning(f"重複しないキーワードの生成に失敗しました。最後に生成されたキーワードを使用します: {result}")
        return result  # 5回の試行後も新しいキーワードが見つからない場合、最後に生成されたキーワードを返します。


    def evaluate_search_result(self, url, title, first_100_chars, user_criteria):
        logging.debug(f"Evaluating search result for URL: {url}")

        prompt = """
        以下のURLが、特定の企業の公式コーポレートサイトであるか、またユーザーの指定条件にどの程度合致しているかを評価せよ。評価基準は次の通りである：
        0点（非企業URL）: URLが企業の公式サイトではない、またはまとめ・一覧サイトである場合。
        1点（非合致企業URL）: 企業の公式サイトであるが、ユーザーの条件に合致しない場合。
        2点（部分合致企業URL）: 企業の公式サイトであり、ユーザーの条件に部分的or大幅に合致する場合。
        99点：ユーザーの条件に合致するが、企業のまとめや一覧サイトの可能性がある場合。
        URL、タイトル、およびユーザーの条件をもとに評価を行い、0から2のスコアで回答せよ。例外的に、99もありえる。必ず与えたURLを閲覧した上で、0 1 2の数値のみ、明確に返してください。その数値を受けて、システムが自動実行されます。
        """
        content = f"URL: {url}\nタイトル: {title}\nユーザーの指定条件: {user_criteria}"
        evaluation = self.gpt_client.generate_text(prompt, content, use_gpt4=True)
        logging.debug(f"Evaluation score: {evaluation}")
        return self.convert_evaluation_to_score(evaluation)


    @staticmethod
    def convert_evaluation_to_score(evaluation):
        logging.debug(f"Converting evaluation to score: {evaluation}")
        if "3" in evaluation:
            return 3
        elif "2" in evaluation:
            return 2
        elif "1" in evaluation:
            return 1
        elif "99" in evaluation:
            return 99
        else:
            return 0


    def pinpoint_search(self, company_name):
        logging.debug(f"Starting pinpoint search for: {company_name}")
        # 会社名に「企業概要」を追加したクエリを生成
        query = f"{company_name} 企業概要"
        encoded_query = urllib.parse.quote(query, safe="")
        url = f"https://www.google.com/search?q={encoded_query}&num=1"
        logging.debug(f"Searching URL: {url}")

        try:
            ssl_context = ssl.create_default_context(cafile=self.CERT_PATH)
            opener = self.build_opener(ssl_context)
            response = opener.open(url)
            soup = BeautifulSoup(response.read(), 'lxml')

            # 検索結果から最初のURLを抽出
            search_div = soup.find(class_='yuRUbf')
            if search_div:
                result_url = search_div.a.get('href')
                logging.info(f"Found result URL: {result_url}")
                return result_url
            else:
                logging.warning("No results found.")
                return None
        except Exception as e:
            logging.error(f"Error during search: {e}")
            return None
