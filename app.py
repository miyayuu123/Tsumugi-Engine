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
    def __init__(self, url, desired_chars_per_cluster=5000, url_structure=None):
        self.urlmodule = URLModule("q")
        self.tagmodule = Tagmodule()
        self.url = url
        self.desired_chars_per_cluster = desired_chars_per_cluster
        self.urls = []
        self.texts_per_url = {}
        self.final_texts_per_url = {}
        self.removed_paragraphs = []  # 削除されたパラグラフを追跡
        self.retry_count = 0
        self.final_blocks = []
        self.max_urls = 10
        self.url_structure = url_structure

    def extract_text_for_url(self, url):
        # Tagmoduleのインスタンスを作成
        tagmodule = Tagmodule()
        # URLごとにテキストと段落を抽出
        paragraphs = tagmodule.extract_text_without_splitting(url)
        if paragraphs is None:
            paragraphs = []  # paragraphsがNoneの場合は空リストを返す
        return url, paragraphs

    def encode_url(self, url):
        # URLをコンポーネントに分割

        return url

    def extract_and_process_texts(self, structure):
        # ThreadPoolExecutorを使用して並行処理を実行
        print("extract_and_process_texts")
        self.urls = self.urlmodule.dispatch_url(self.url, structure=structure, max_urls=self.max_urls)
        # エンコードされたURLを保持するための新しいリスト
        encoded_urls = []

        # 各URLをエンコードして新しいリストに追加
        for url in self.urls:
            encoded_url = self.encode_url(url)
            encoded_urls.append(encoded_url)

        print(f'抽出されたURLの数: {len(encoded_urls)}')
        print(encoded_urls)
        with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
            # エンコードされたURLリストを使用して処理を実行
            future_to_url = {executor.submit(self.extract_text_for_url, url): url for url in encoded_urls}

            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    _, paragraphs = future.result()
                    # texts_per_urlの内容をfinal_texts_per_urlに統合
                    if url in self.final_texts_per_url:
                        # 既に存在するURLの場合、重複しないように新たなパラグラフを追加
                        existing_paragraphs = self.final_texts_per_url[url]
                        for paragraph in paragraphs:
                            if paragraph not in existing_paragraphs:
                                self.final_texts_per_url[url].append(paragraph)
                    else:
                        # 新しいURLの場合、直接追加
                        self.final_texts_per_url[url] = paragraphs
                except Exception as exc:
                    print(f'{url} の処理中にエラーが発生しました: {exc}')

        # texts_per_urlの内容をfinal_texts_per_urlに統合
        for url, paragraphs in self.texts_per_url.items():
            if url in self.final_texts_per_url:
                self.final_texts_per_url[url].extend(paragraphs)
            else:
                self.final_texts_per_url[url] = paragraphs

        print(f'抽出されたURLの数: {len(encoded_urls)}')
        print(f'ユニークなパラグラフの数: {len([paragraph for paragraphs in self.final_texts_per_url.values() for paragraph in paragraphs])}')

    def remove_similar_paragraphs(self, threshold=0.5):
        # 全パラグラフの集約
        all_paragraphs = [paragraph for paragraphs in self.final_texts_per_url.values() for paragraph in paragraphs]
        original_paragraph_count = len(all_paragraphs)  # 除去前のパラグラフ総数
        if original_paragraph_count == 0:
            return

        # TF-IDFベクトル化
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform(all_paragraphs)
        # コサイン類似度の計算
        cosine_sim_matrix = cosine_similarity(tfidf_matrix)

        # 類似パラグラフの除去
        to_remove = set()
        for i in range(len(cosine_sim_matrix)):
            for j in range(i + 1, len(cosine_sim_matrix)):
                if cosine_sim_matrix[i, j] > threshold:
                    to_remove.add(j)

        # 更新されたパラグラフセットを作成
        unique_paragraphs = [paragraph for i, paragraph in enumerate(all_paragraphs) if i not in to_remove]
        removed_paragraph_count = original_paragraph_count - len(unique_paragraphs)  # 削除されたパラグラフの個数

        # final_texts_per_urlを更新
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

        # 削除されたパラグラフの個数を出力
        print(f'削除されたパラグラフの個数: {removed_paragraph_count}')

    def remove_duplicate_texts(self):
        """
        このメソッドでは、全てのパラグラフについて重複を検出し、
        それらをテキストブロックのリストから削除します。
        """
        paragraph_counter = Counter()
        for paragraphs in self.final_texts_per_url.values():
            for paragraph in paragraphs:
                paragraph_counter[paragraph] += 1

        # 重複しているパラグラフを削除
        for url, paragraphs in self.final_texts_per_url.items():
            if paragraphs is None:
                continue
            self.final_texts_per_url[url] = [p for p in paragraphs if paragraph_counter[p] == 1]


    def create_text_blocks_and_count_chars(self, max_chars=5000):
        # remove_duplicate_textsメソッドを呼び出して重複を削除
        self.remove_duplicate_texts()

        print(len(self.final_texts_per_url))
        text_blocks = []
        block_id = 1  # ブロックIDを数えるためのカウンタ
        for url, paragraphs in self.final_texts_per_url.items():
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
            if current_block and current_chars > self.desired_chars_per_cluster / 10:
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

        # JavaScriptが含まれるブロックの割合が50%を超え、かつ総合文字数が500文字以下の場合、再取得する
        if js_ratio > 0.5 and total_chars <= 500:
            if self.retry_count < 3:  # 無料版は、再取得の試行回数に制限を設ける
                print("取得した結果の大半がJavaScriptを含んでいる、または総合文字数が500文字以下のため、再取得します。")
                self.retry_count += 1  # 試行回数をインクリメント
                self.final_blocks = []
                self.extract_and_process_texts(self.url_structure)
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
                self.retry_count += 1  # 再取得のためにリトライカウントをリセット
                additional_max_urls = self.max_urls - len(self.final_blocks)
                self.final_blocks = []
                self.max_urls = additional_max_urls
                self.urls = []  # URLリストをリセット
                self.extract_and_process_texts(self.url_structure)
                self.remove_similar_paragraphs()
                self.create_text_blocks_and_count_chars()
                self.save_final_blocks(model_id)
            else:
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.final_blocks, f, ensure_ascii=False, indent=2)
                print(f'テキストブロックが {output_file_path} に保存されました。')
                self.update_model_status_and_insert_result(model_id, self.final_blocks)
        else:
            # 条件を満たさない場合、通常通りにファイルに保存
            with open(output_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.final_blocks, f, ensure_ascii=False, indent=2)
            print(f'テキストブロックが {output_file_path} に保存されました。')
            self.update_model_status_and_insert_result(model_id, self.final_blocks)

    def update_model_status_and_insert_result(self, model_id, result_json):
        # modelsテーブルのstatusを更新
        update_response = supabase.table("models").update({"status": "finished"}).eq("model_id", model_id).execute()
        # resultテーブルに新しいレコードを挿入、result_jsonの各要素をresult_textカラムに格納
        for text_block in result_json:
            # Unicodeエスケープされた文字列を適切にエンコード
            formatted_text = json.dumps(text_block['content'], ensure_ascii=False)
            insert_response = supabase.table("results").insert({"model_id": model_id, "result_text": formatted_text}).execute()


def background_task(url, desired_chars_per_cluster, model_id, url_structure):
    app_instance = App(url, desired_chars_per_cluster, url_structure)  # url_structureを渡す
    app_instance.extract_and_process_texts(url_structure)
    app_instance.remove_similar_paragraphs()
    app_instance.create_text_blocks_and_count_chars()
    app_instance.save_final_blocks(model_id)

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

#if __name__ == '__main__':
#   app.run(debug=True)


if __name__ == '__main__':
    # テスト用のURLとパラメータを設定
    test_url = "https://www.jstage.jst.go.jp/browse/-char/ja"
    desired_chars_per_cluster = 5000
    model_id = "00"
    url_structure = "all"

    # background_task関数を直接呼び出して処理を実行
    background_task(test_url, desired_chars_per_cluster, model_id, url_structure)
