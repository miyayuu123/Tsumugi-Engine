from flask import Flask, request, jsonify
from Tagmodule import Tagmodule
from UrlModule import URLModule
from QueryModule import QueryModule
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from collections import Counter
import concurrent.futures
import threading
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import subprocess
import signal
import socket
import socks  # PySocksを使用
import json

app = Flask(__name__)

# 環境設定の読み込み
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Torの設定
def set_tor_proxy():
    socks.set_default_proxy(socks.SOCKS5, "localhost", 9052)
    socket.socket = socks.socksocket

def unset_tor_proxy():
    socket.socket = socket.SocketType

# テキスト処理のためのクラス
class TextProcessor:
    def __init__(self, url, desired_chars_per_cluster, url_structure, query):
        self.urlmodule = URLModule(query)
        self.tagmodule = Tagmodule()
        self.querymodule = QueryModule(gpt_api_key="")
        self.url = url
        self.desired_chars_per_cluster = desired_chars_per_cluster
        self.urls = []
        self.texts_per_url = {}
        self.final_texts_per_url = {}
        self.removed_paragraphs = []
        self.retry_count = 0
        self.final_blocks = []
        self.max_urls = 10
        self.url_structure = url_structure
        self.query = query

    def extract_text_for_url(self, url):
        paragraphs = self.tagmodule.extract_text_without_splitting(url)
        return url, paragraphs or []

    def encode_url(self, url):
        return url

    def extract_and_process_texts(self):
        print("extract_and_process_texts")
        self.urls = self.urlmodule.dispatch_url(self.url, structure=self.url_structure, max_urls=self.max_urls)
        encoded_urls = [self.encode_url(url) for url in self.urls]
        print(f'抽出されたURLの数: {len(encoded_urls)}')
        print(encoded_urls)
        with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
            future_to_url = {executor.submit(self.extract_text_for_url, url): url for url in encoded_urls}
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    _, paragraphs = future.result()
                    self.final_texts_per_url.setdefault(url, []).extend(p for p in paragraphs if p not in self.final_texts_per_url[url])
                except Exception as exc:
                    print(f'{url} の処理中にエラーが発生しました: {exc}')

    def remove_similar_paragraphs(self, threshold=0.5):
        all_paragraphs = [p for paragraphs in self.final_texts_per_url.values() for p in paragraphs]
        if not all_paragraphs:
            return
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform(all_paragraphs)
        cosine_sim_matrix = cosine_similarity(tfidf_matrix)
        to_remove = {j for i in range(len(cosine_sim_matrix)) for j in range(i + 1, len(cosine_sim_matrix)) if cosine_sim_matrix[i, j] > threshold}
        unique_paragraphs = [p for i, p in enumerate(all_paragraphs) if i not in to_remove]
        self.update_final_texts(unique_paragraphs)

    def update_final_texts(self, unique_paragraphs):
        new_final_texts_per_url = {}
        paragraph_index = 0
        for url, paragraphs in self.final_texts_per_url.items():
            new_paragraphs = []
            for _ in paragraphs:
                if paragraph_index < len(unique_paragraphs):
                    new_paragraphs.append(unique_paragraphs[paragraph_index])
                    paragraph_index += 1
            new_final_texts_per_url[url] = new_paragraphs
        self.final_texts_per_url = new_final_texts_per_url

    def remove_duplicate_texts(self):
        paragraph_counter = Counter(p for paragraphs in self.final_texts_per_url.values() for p in paragraphs)
        for url, paragraphs in self.final_texts_per_url.items():
            self.final_texts_per_url[url] = [p for p in paragraphs if paragraph_counter[p] == 1]

    def create_text_blocks_and_count_chars(self):
        self.remove_duplicate_texts()
        print(len(self.final_texts_per_url))
        text_blocks = []
        block_id = 1
        for url, paragraphs in self.final_texts_per_url.items():
            current_block = []
            current_chars = 0
            for paragraph in paragraphs:
                paragraph_len = len(paragraph)
                if current_chars + paragraph_len > self.desired_chars_per_cluster:
                    if current_block:
                        text_blocks.append({
                            "ID": f"クラスタ{block_id}",
                            "url": url,
                            "content": current_block
                        })
                        print(f"ID: クラスタ{block_id}, URL: {url}, ブロック文字数: {current_chars}, パラグラフ数: {len(current_block)}")
                        block_id += 1
                    current_block = [paragraph]
                    current_chars = paragraph_len
                else:
                    current_block.append(paragraph)
                    current_chars += paragraph_len
            if current_block:
                text_blocks.append({
                    "ID": f"クラスタ{block_id}",
                    "url": url,
                    "content": current_block
                })
                print(f"ID: クラスタ{block_id}, URL: {url}, ブロック文字数: {current_chars}, パラグラフ数: {len(current_block)}")
                block_id += 1
        self.final_blocks.extend(text_blocks)

    def save_final_blocks(self, model_id, output_file_path='text_blocks.json'):
        js_count = sum(1 for block in self.final_blocks if 'JavaScript' in ' '.join(block['content']))
        js_ratio = js_count / len(self.final_blocks) if self.final_blocks else 0
        total_chars = sum(len(' '.join(block['content'])) for block in self.final_blocks)
        if js_ratio > 0.5 and total_chars <= self.desired_chars_per_cluster / 10:
            if self.retry_count < 3:
                print("取得した結果の大半がJavaScriptを含んでいる、または総合文字数が500文字以下のため、再取得します。")
                self.retry_count += 1
                self.final_blocks = []
                self.extract_and_process_texts()
                self.remove_similar_paragraphs()
                self.create_text_blocks_and_count_chars()
                self.save_final_blocks(model_id)
            else:
                print("再取得の試行回数が上限に達しました。")
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.final_blocks, f, ensure_ascii=False, indent=2)
                print(f'テキストブロックが {output_file_path} に保存されました。')
                self.update_model_status_and_insert_result(model_id, self.final_blocks)
        elif len(self.final_blocks) <= self.max_urls / 2:
            if self.retry_count < 3:
                print("最終的なテキストブロック数が指定したmax_urlsの2分の1以下です。追加で取得します。")
                self.retry_count += 1
                additional_max_urls = self.max_urls - len(self.final_blocks)
                self.final_blocks = []
                self.max_urls = additional_max_urls
                self.urls = []
                self.extract_and_process_texts()
                self.remove_similar_paragraphs()
                self.create_text_blocks_and_count_chars()
                self.save_final_blocks(model_id)
            else:
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.final_blocks, f, ensure_ascii=False, indent=2)
                print(f'テキストブロックが {output_file_path} に保存されました。')
                self.update_model_status_and_insert_result(model_id, self.final_blocks)
        else:
            with open(output_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.final_blocks, f, ensure_ascii=False, indent=2)
            print(f'テキストブロックが {output_file_path} に保存されました。')
            self.update_model_status_and_insert_result(model_id, self.final_blocks)

    def update_model_status_and_insert_result(self, model_id, result_json):
        unset_tor_proxy()
        update_response = supabase.table("models").update({"status": "finished"}).eq("model_id", model_id).execute()
        if not update_response.data:
            print("Received an empty response from the API")
            return
        print(update_response.data)
        for text_block in result_json:
            formatted_text = json.dumps(text_block['content'], ensure_ascii=False)
            insert_response = supabase.table("results").insert({"model_id": model_id, "result_text": formatted_text}).execute()

# バックグラウンドタスクの定義
def background_task(url, desired_chars_per_cluster, model_id, url_structure, query):
    start_tor()
    app_instance = TextProcessor(url, desired_chars_per_cluster, url_structure, query)
    app_instance.extract_and_process_texts()
    app_instance.remove_similar_paragraphs()
    app_instance.create_text_blocks_and_count_chars()
    app_instance.save_final_blocks(model_id)

# Flaskルート定義
@app.route('/train-model', methods=['POST'])
def train_model():
    data = request.json
    url = data.get('url')
    model_id = data.get('model_id')
    desired_chars_per_cluster = data.get('desired_chars_per_cluster', 5000)
    url_structure = data.get('structure')
    query = data.get('query', '')

    thread = threading.Thread(target=background_task, args=(url, desired_chars_per_cluster, model_id, url_structure, query))
    thread.start()
    return jsonify({"message": "Model training initiated"}), 202

# Torプロセス管理
def kill_tor():
    try:
        pids = subprocess.check_output(["pgrep", "tor"]).decode().split()
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGTERM)
                print(f"Torプロセス {pid} を終了しました。")
            except PermissionError:
                print(f"Torプロセス {pid} の終了に必要な権限がありません。")
    except subprocess.CalledProcessError:
        print("実行中のTorプロセスはありません。")

def start_tor():
    global tor_process
    tor_executable_path = 'bin/tor-expert-bundle-dev/tor/tor'
    tor_config_path = 'torrc'
    kill_tor()
    tor_process = subprocess.Popen(
        [tor_executable_path, '-f', tor_config_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    print("新しいTorプロセスを起動しました。ログを監視しています...")
    while True:
        line = tor_process.stdout.readline()
        if not line:
            break
        print(line.strip())
        if "Bootstrapped 100% (done): Done" in line:
            print("Torが完全に起動しました。次の工程にみます。")
            break
    print("他のプロセスを開始します。")

if __name__ == '__main__':
    test_url = "https://ja.wikipedia.org/wiki/Wikipedia:%E3%82%A6%E3%82%A3%E3%82%AD%E3%83%9A%E3%83%87%E3%82%A3%E3%82%A2%E3%81%AB%E3%81%A4%E3%81%84%E3%81%A6"
    desired_chars_per_cluster = 500
    query = ""
    model_id = "6f3dcba3-c887-423a-b69a-61c2f346d44d"
    url_structure = "all"
    background_task(test_url, desired_chars_per_cluster, model_id, url_structure, query)
