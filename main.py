import base64
import hashlib
import hmac
import html
import logging
import os
import random
import re
import shutil
import tempfile

import functions_framework
import google.cloud.logging
from elasticsearch import Elasticsearch
from flask import abort
from icrawler.builtin import GoogleImageCrawler
from linebot import (LineBotApi, WebhookParser)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage,
                            ImageSendMessage)


def _cleaning(bot_utterance):
    bot_utterance = html.unescape(bot_utterance)
    bot_utterance = re.sub('<A[^>]+>', '', bot_utterance)
    bot_utterance = bot_utterance.replace('</A>', '')
    return bot_utterance


def _remove_emoticon(text):
    re_emoticon = re.compile("\([^\)]+\)")
    return re_emoticon.sub("", text)


def _search_image(query):
    re_url = re.compile("https?://[^/]+/[a-zA-Z0-9\-\.\+_/]+\.[a-z]{3,4}")

    temp_file = tempfile.mkstemp()[1]
    temp_dir = tempfile.mkdtemp()

    logger = logging.getLogger('downloader')
    handler = logging.FileHandler(filename=temp_file)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    google_crawler = GoogleImageCrawler(storage={'root_dir': temp_dir})
    filters = dict(size='medium')
    google_crawler.crawl(keyword=query, filters=filters, max_num=1)

    with open(temp_file) as f:
        contents = f.read()

    for m in re_url.finditer(contents):
        url = m.group(0)
        break

    os.remove(temp_file)
    shutil.rmtree(temp_dir)

    return url


@functions_framework.http
def atango(request):
    """HTTP Cloud Function.
    Args:
       request (flask.Request): The request object.
       <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
       The response text, or any set of values that can be turned into a
       Response object using `make_response`
       <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    """
    channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
    channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')

    line_bot_api = LineBotApi(channel_access_token)
    parser = WebhookParser(channel_secret)

    body = request.get_data(as_text=True)
    hash = hmac.new(channel_secret.encode('utf-8'), body.encode('utf-8'),
                    hashlib.sha256).digest()
    signature = base64.b64encode(hash).decode()

    if signature != request.headers[
            'x-line-signature'] and signature != request.headers[
                'X-LINE-SIGNATURE']:
        return abort(405)

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        return abort(400)

    es = Elasticsearch([os.environ.get('ES_SERVER') + ':9200'])
    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        if not isinstance(event.message, TextMessage):
            continue
        user_utterance = event.message.text.replace('ぁ単語', '貴殿')
        query = {
            "match": {
                "q1": {
                    "query": user_utterance,
                    "operator": "and",
                    "minimum_should_match": "25%",
                    "boost": 1.2
                }
            }
        }
        sort = {
            "_script": {
                "type": "number",
                "script": {
                    "source": 'doc.quoted_by.size() + _score',
                    "lang": "painless"
                },
                "order": "desc"
            }
        }
        result = es.search(index="sw_*", query=query, sort=sort)
        if result['hits']['total']['value'] == 0:
            if user_utterance.endswith(("？", "?")):
                bot_utterance = random.choice([
                    "ほんとにそれ知りたいの？(;´Д`)", "貴殿って興味津々なんだね(;´Д`)",
                    "それより他に知るべきことがあるんじゃないか？(;´Д`)", "大事なことだけ聞いてくれ(;´Д`)"
                ])
                message = TextSendMessage(text=bot_utterance)
            elif user_utterance.endswith(("！", "!")):
                bot_utterance = random.choice([
                    "へいへい(;´Д`)", "わかったよ(;´Д`)", "さすが(;´Д`)",
                    "出来る限りがんばるよ(;´Д`)"
                ])
                message = TextSendMessage(text=bot_utterance)
            elif user_utterance.endswith(("だよ", "んよ", "から")):
                bot_utterance = random.choice(
                    ['そうなのか(;´Д`)', "そうなんだねえ(;´Д`)", "そうそう(;´Д`)俺も言おうと思ってた"])
                message = TextSendMessage(text=bot_utterance)
            else:
                user_utterance = _remove_emoticon(user_utterance)
                url = _search_image(user_utterance)
                if url:
                    message = ImageSendMessage(original_content_url=url,
                                               preview_image_url=url)
                else:
                    bot_utterance = random.choice([
                        'ああ(;´Д`)', 'さすが(;´Д`)', '知らなかった(;´Д`)', 'すごい(;´Д`)',
                        'センスいいですね(;´Д`)', 'そっすね(;´Д`)', 'いいね(;´Д`)',
                        'へえ(;´Д`)', '知らんよ(;´Д`)', 'ああ(;´Д`)播磨灘', 'それな(;´Д`)',
                        '意外と好き(;´Д`)', 'それ好き(;´Д`)', 'よくやるよ(;´Д`)'
                    ])
                    message = TextSendMessage(text=bot_utterance)
        else:
            bot_utterance = result['hits']['hits'][0]['_source']['text']
            bot_utterance = _cleaning(bot_utterance)
            message = TextSendMessage(text=bot_utterance)
        line_bot_api.reply_message(event.reply_token, message)
    return 'ok'
