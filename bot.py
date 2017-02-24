# -*- coding: utf-8 -*-
import json
import os
from logging import DEBUG, StreamHandler, getLogger

from elasticsearch import Elasticsearch
import falcon
import requests


# logger
logger = getLogger(__name__)
handler = StreamHandler()
handler.setLevel(DEBUG)
logger.setLevel(DEBUG)
logger.addHandler(handler)

REPLY_ENDPOINT = 'https://api.line.me/v2/bot/message/reply'
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
ES = os.environ.get('ES_SERVER', '')
es = Elasticsearch([ES])


class CallbackResource(object):
    header = {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer {}'.format(LINE_CHANNEL_ACCESS_TOKEN)
    }

    def _build_sort(self, sort):
        sort_item = []
        for (field, order) in sort:
            sort_item.append({
                '_script': {
                    'script': "doc.%s.size()" % field,
                    "lang": "groovy",
                    "type": "string",
                    'order': order
                }
            })
        return sort_item

    def _search(self, query):
        es_query = {
            'match': {
                'q1': {
                    'query': query,
                    'operator': 'and',
                    'minimum_should_match': '85%'
                }
            }
        }
        body = {
            "query": {
                "filtered": {
                    "query": es_query,
                    "filter": []
                }
            },
            'size': 100
        }
        sort_item = self._build_sort([('quoted_by', 'desc')])
        body.update({'sort': sort_item})
        logger.debug(body)
        result = es.search(index=['qwerty', 'misao'], body=body, _source=True)
        return [x['_source'] for x in result['hits']['hits']]

    def on_post(self, req, resp):
        body = req.stream.read()
        if not body:
            raise falcon.HTTPBadRequest('Empty request body',
                                        'A valid JSON document is required.')

        receive_params = json.loads(body.decode('utf-8'))
        logger.debug('receive_params: {}'.format(receive_params))

        for event in receive_params['events']:

            logger.debug('event: {}'.format(event))

            if event['type'] == 'message':
                try:
                    user_utt = event['message']['text']
                    sys_utt = self._search(user_utt)[0]['text']

                except Exception as e:
                    raise falcon.HTTPError(falcon.HTTP_503,
                                           'sw_words Elasticseaarch server Error.')

                logger.debug('sw_words_res: {}'.format(sys_utt))

                send_content = {
                    'replyToken': event['replyToken'],
                    'messages': [
                        {
                            'type': 'text',
                            'text': sys_utt
                        }
                    ]
                }
                send_content = json.dumps(send_content)
                logger.debug('send_content: {}'.format(send_content))

                res = requests.post(REPLY_ENDPOINT, data=send_content, headers=self.header)
                logger.debug('res: {} {}'.format(res.status_code, res.reason))

                resp.body = json.dumps('OK')


api = falcon.API()
api.add_route('/callback', CallbackResource())