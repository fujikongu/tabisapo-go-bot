
from flask import Flask, request, abort
from linebot.v3.messaging import MessagingApi, MessagingApiBlob
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.models import (
    MessageEvent, TextMessageContent, LocationMessageContent,
    TextMessage, QuickReply, QuickReplyItem, MessageAction
)
import os
import openai
import requests

app = Flask(__name__)

# 環境変数
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY
messaging_api = MessagingApi(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ジャンル記憶
user_selected_genre = {}

# 対応ジャンル
genre_labels = [
    "トイレ", "駐車場", "ラーメン", "和食", "中華", "焼肉", "ファミレス",
    "カフェ", "ホテル", "観光地", "温泉", "遊び場", "コンビニ"
]

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text

    if text in genre_labels:
        user_selected_genre[user_id] = text
        reply = TextMessage(text=f"📍「{text}」を探します！\n現在地を送信してください。")
    else:
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=label, text=label))
            for label in genre_labels[:13]  # 最大13個制限
        ]
        reply = TextMessage(
            text="👇 探したいジャンルを選んでください",
            quick_reply=QuickReply(items=quick_reply_items)
        )
    messaging_api.reply_message(reply_token=event.reply_token, messages=[reply])

@handler.add(MessageEvent, message=LocationMessageContent)
def handle_location(event):
    user_id = event.source.user_id
    genre = user_selected_genre.pop(user_id, None)

    if not genre:
        msg = TextMessage(text="先にジャンルを選んでください。")
        messaging_api.reply_message(reply_token=event.reply_token, messages=[msg])
        return

    lat = event.message.latitude
    lng = event.message.longitude

    maps_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": 10000,
        "keyword": genre,
        "language": "ja",
        "key": GOOGLE_API_KEY
    }
    res = requests.get(maps_url, params=params).json()
    results = res.get("results", [])

    if not results:
        msg = TextMessage(text=f"{genre}が近くに見つかりませんでした。")
        messaging_api.reply_message(reply_token=event.reply_token, messages=[msg])
        return

    messages = []
    for spot in results[:10]:  # 最大10件表示
        name = spot.get("name", "名称不明")
        address = spot.get("vicinity", "住所不明")
        place_lat = spot["geometry"]["location"]["lat"]
        place_lng = spot["geometry"]["location"]["lng"]
        map_link = f"https://www.google.com/maps/search/?api=1&query={place_lat},{place_lng}"

        # ChatGPT案内文生成
        prompt = f"""あなたは観光案内人です。以下のスポットを観光客におすすめするとしたら、どう紹介しますか？

名称：{name}
ジャンル：{genre}

場所の特徴や雰囲気、旅行者が嬉しいポイントを含めて、100文字以内でやさしい案内文をお願いします。
"""
        try:
            completion = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            gpt_message = completion.choices[0].message["content"].strip()
        except Exception as e:
            print("ChatGPTエラー:", e)
            gpt_message = "旅行者におすすめのスポットです！"

        text = f"🏞️ {name}\n📍 {address}\n\n{gpt_message}\n\n👉 [Googleマップで見る]({map_link})"
        messages.append(TextMessage(text=text))

    messaging_api.reply_message(reply_token=event.reply_token, messages=messages)

# Render起動コード（決定済み）
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
