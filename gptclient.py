from openai import OpenAI
import re

class GPTClient:
    def __init__(self):
        self.api_key = "sk-YOUR_OPENAI_API_KEY"

    def generate_text(self, prompt, content, use_gpt4=False, use_gpt4o2=False):
        client = OpenAI(
            api_key=self.api_key,
            timeout=70.0,
        )

        # 連続する改行を単一の改行に置換
        cleaned_content = re.sub(r'\n+', '\n', content)

        # モデル選択
        model_version = "gpt-4o" if use_gpt4o2 else "gpt-4-turbo-preview" if use_gpt4 else "gpt-3.5-turbo"

        response = client.chat.completions.create(
            model=model_version,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": cleaned_content}
            ]
        )

        return response.choices[0].message.content
