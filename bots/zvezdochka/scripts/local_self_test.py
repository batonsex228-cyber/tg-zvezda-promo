"""Offline tests without contacting Telegram or requiring a bot token."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock
from app.config import Settings
from app.db import Database
from app.telegram_adapter import TelegramAdapter
from app.telegram_keyboards import shift_consent_keyboard, shift_review_keyboard, main_keyboard, manager_booking_keyboard

async def run():
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp)
        settings=Settings(site_url='https://zvezdaglazov.ru/',kb_file=folder/'kb.json',db_file=folder/'db.sqlite',
          crawl_max_pages=40,openai_api_key=None,openai_model='gpt-5.6',faq_min_score=.72,
          retrieval_min_score=.48,camp_name='DZL',debug=False,show_source_links=True,
          telegram_bot_token='123456:test', telegram_manager_user_id=0)
        adapter=TelegramAdapter(settings,None,Database(settings.db_file),None)
        adapter.api=AsyncMock(return_value={'message_id':123})
        mark=adapter._telegram_keyboard(shift_consent_keyboard(),peer_id=42)
        assert len(mark['inline_keyboard'][0])==2
        for row in mark['inline_keyboard']:
          for b in row:
            assert len(b['callback_data'].encode())<=64
            assert adapter._lookup_callback(42,b['callback_data'])['action']=='shift_parent'
            assert not adapter._lookup_callback(99,b['callback_data'])
        review=adapter._telegram_keyboard(shift_review_keyboard(),42)
        assert len(review['inline_keyboard'])==2
        assert len(adapter._telegram_keyboard(main_keyboard(),42)['keyboard'])==5
        manager=adapter._telegram_keyboard(manager_booking_keyboard('very-long-booking-id-0123456789'),42)
        assert 'booking_manager' == adapter._lookup_callback(42,manager['inline_keyboard'][0][0]['callback_data'])['action']
        msg={'update_id':1,'message':{'from':{'id':42,'first_name':'Иван'},'chat':{'id':42,'type':'private'},'text':'🍲 Питание'}}
        translated=adapter._translate_update(msg)
        assert json.loads(translated['object']['message']['payload'])['intent']=='food'
        cb={'update_id':2,'callback_query':{'id':'QUERY','from':{'id':42,'first_name':'Иван'},
          'message':{'chat':{'id':42,'type':'private'}},'data':mark['inline_keyboard'][0][0]['callback_data']}}
        translated=adapter._translate_update(cb)
        assert translated['type']=='message_event' and translated['object']['payload']['cmd']=='consent_yes'
        assert adapter._translate_update({'message':{'from':{'id':42},'chat':{'id':99,'type':'group'},'text':'oops'}}) is None
        sent=await adapter.send_message(42,'Привет!',keyboard=shift_consent_keyboard())
        assert sent==123 and adapter.api.await_args.args[0]=='sendMessage'
        await adapter.close()
    print('TELEGRAM OFFLINE SELFTEST: PASS')

if __name__=='__main__': asyncio.run(run())
