
from flask import Flask, request, jsonify
from Tagmodule import Tagmodule
from UrlModule import URLModule
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
import json
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from collections import Counter
from urllib.parse import urlparse, urlunparse, quote
import concurrent.futures
import threading
from supabase import create_client, Client
from dotenv import load_dotenv
import os

app = Flask(__name__)

# .envファイルから環境変数を読み込む
load_dotenv()

# 環境変数からSupabaseのURLとキーを取得
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Supabaseクライアントを初期化
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

class App:
    def __init__(self, url, desired_chars_per_cluster=5000):
        self.urlmodule = URLModule("q")
        self.tagmodule = Tagmodule()
        self.url = url
        self.desired_chars_per_cluster = desired_chars_per_cluster
        self.urls = []
        self.texts_per_url = {}
        self.all_paragraphs = []
        self.removed_paragraphs = []  # 削除されたパラグラフを追跡

    def extract_text_for_url(self, url):
        # Tagmoduleのインスタンスを作成
        tagmodule = Tagmodule()
        # URLごとにテキストと段落を抽出
        text, _ = tagmodule.extract_text_without_splitting(url)
        paragraphs = tagmodule.extract_paragraphs(text)
        return url, paragraphs

    def encode_url(self, url):
        # URLをコンポーネントに分割
        scheme, netloc, path, params, query, fragment = urlparse(url)
        # パスとクエリをエンコード
        path = quote(path)
        query = quote(query)
        # エンコードされたURLを再構築
        encoded_url = urlunparse((scheme, netloc, path, params, query, fragment))
        return encoded_url

    def extract_and_process_texts(self, structure):
        # ThreadPoolExecutorを使用して並行処理を実行
        self.urls = self.urlmodule.dispatch_url(self.url, structure=structure)

        print(f'抽出されたURLの数: {len(self.urls)}')
        print(self.urls)
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            # URLごとにextract_text_for_url関数を実行
            future_to_url = {executor.submit(self.extract_text_for_url, self.encode_url(url)): url for url in self.urls}

            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    _, paragraphs = future.result()
                    self.texts_per_url[url] = paragraphs
                    self.all_paragraphs.extend(paragraphs)
                except Exception as exc:
                    print(f'{url} の処理中にエラーが発生しました: {exc}')

        print(f'抽出されたURLの数: {len(self.urls)}')
        print(f'ユニークなパラグラフの数: {len(self.all_paragraphs)}')

    def remove_similar_paragraphs(self, threshold=0.5):
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform(self.all_paragraphs)
        cosine_sim_matrix = cosine_similarity(tfidf_matrix)

        to_remove = set()
        for i in range(len(cosine_sim_matrix)):
            for j in range(i + 1, len(cosine_sim_matrix)):
                if cosine_sim_matrix[i, j] > threshold:
                    to_remove.add(j)

        self.all_paragraphs = [p for i, p in enumerate(self.all_paragraphs) if i not in to_remove]
        print(f'類似度に基づいて削除されたパラグラフの数: {len(to_remove)}')

    def remove_duplicate_texts(self):
        """
        このメソッドでは、全てのパラグラフについて重複を検出し、
        それらをテキストブロックのリストから削除します。
        """
        paragraph_counter = Counter()
        for paragraphs in self.texts_per_url.values():
            for paragraph in paragraphs:
                paragraph_counter[paragraph] += 1

        # 重複しているパラグラフを削除
        for url, paragraphs in self.texts_per_url.items():
            self.texts_per_url[url] = [p for p in paragraphs if paragraph_counter[p] == 1]


    def create_text_blocks_and_count_chars(self, max_chars=5000):
        # remove_duplicate_textsメソッドを呼び出して重複を削除
        self.remove_duplicate_texts()

        text_blocks = []
        block_id = 1  # ブロックIDを数えるためのカウンタ
        for url, paragraphs in self.texts_per_url.items():
            current_block = []
            current_chars = 0
            for paragraph in paragraphs:
                paragraph_len = len(paragraph)
                if current_chars + paragraph_len > max_chars:
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

        self.final_blocks = text_blocks

    def save_final_blocks(self, output_file_path='text_blocks.json'):
        with open(output_file_path, 'w', encoding='utf-8') as f:
            json.dump(self.final_blocks, f, ensure_ascii=False, indent=2)
        print(f'テキストブロックが {output_file_path} に保存されました。')

def update_model_status_and_insert_result(model_id, result_json):
        # modelsテーブルのstatusを更新
        update_response = supabase.table("models").update({"status": "finished"}).eq("id", model_id).execute()
        # resultテーブルに新しいレコードを挿入
        insert_response = supabase.table("results").insert({"model_id": model_id, "result": result_json}).execute()

        if update_response.error or insert_response.error:
            print("データベースの更新または挿入に失敗しました。")
        else:
            print("データベースが正常に更新され、結果が挿入されました。")

def background_task(url, desired_chars_per_cluster, model_id, url_structure):
    app_instance = App(url, desired_chars_per_cluster)
    app_instance.extract_and_process_texts(url_structure)
    app_instance.remove_similar_paragraphs()
    app_instance.create_text_blocks_and_count_chars()
    app_instance.save_final_blocks()

    # 結果のJSONファイルのパス（またはJSONデータそのもの）
    result_json_path = "text_blocks.json"

    # JSONファイルからデータを読み込む
    with open(result_json_path, 'r', encoding='utf-8') as file:
        result_json = json.load(file)

    # データベースを更新し、結果を挿入
    update_model_status_and_insert_result(model_id, result_json)

@app.route('/train-model', methods=['POST'])
def train_model():
    data = request.json
    url = data.get('url')
    model_id = data.get('model_id')
    desired_chars_per_cluster = data.get('desired_chars_per_cluster', 5000)
    url_structure = data.get('structure')

    # バックグラウンドタスクをスレッドで実行
    thread = threading.Thread(target=background_task, args=(url, desired_chars_per_cluster, model_id, url_structure))
    thread.start()

    # レスポンスを直ちに返す
    return jsonify({"message": "Model training initiated"}), 202

if __name__ == '__main__':
    app.run(debug=True)
