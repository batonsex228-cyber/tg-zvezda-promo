"""Offline adapter-level smoke: conversation sends correct Telegram replies without live token."""
import asyncio,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.config import Settings
from app.core import CoreResult
from app.db import Database
from app.operator import OperatorBridge
from app.telegram_adapter import TelegramAdapter
from app.responder import BotAnswer

class NoKnowledgeCore:
    async def process(self,text,*,intent=None):
        return CoreResult(text,intent,BotAnswer(False,None,reason='no_baseline_faq'),None)

async def main():
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)
        settings=Settings(site_url='https://zvezdaglazov.ru/',kb_file=p/'kb.json',db_file=p/'db.sqlite',
            crawl_max_pages=1,openai_api_key=None,openai_model='unused',faq_min_score=.72,
            retrieval_min_score=.48,camp_name='Звездочка',debug=False,show_source_links=True,
            telegram_bot_token='000:test',telegram_manager_user_id=99)
        db=Database(settings.db_file)
        operator=OperatorBridge(settings,db)
        a=TelegramAdapter(settings,NoKnowledgeCore(),db,operator)
        calls=[]
        async def fake_api(method,**payload):
            calls.append((method,payload))
            return {'message_id':len(calls)} if method=='sendMessage' else True
        a.api=fake_api
        operator.set_telegram_manager_sender(a.send_to_manager)
        operator.set_telegram_sender(a.send_plain_from_operator)
        operator.set_telegram_marker(a.mark_support_conversation)
        async def send(text,mid):
            before=len(calls)
            await a._dispatch_telegram({'update_id':mid,'message':{'message_id':mid,
                'chat':{'id':10,'type':'private'},'from':{'id':10,'first_name':'Тест'},'text':text}})
            return calls[before:]
        try:
            await send('/start',1)
            for mid,text,need in [
                (2,'Скок путёвка на лето 27 стоит?','40 000 ₽'),
                (3,'Если двое детей едет, скидон будет?','5%'),
                (4,'А телефон забирают и как часто кормят?','пятиразовое'),
                (5,'Мой Вася в каком корпусе живет?','не могу сообщать'),
                (6,'А на эту дату свободно?','не вижу подтверждённого количества'),
                (7,'А на 3 смену каковы даты?','22 июля'),
                (8,'а там сколько стоит?','40 000 ₽'),
                (9,'Хочу заезд на 31.06.2027','ошибка'),
                (10,'Чипсы с колой ребёнку можно?','нельзя'),
            ]:
                records=await send(text,mid)
                msgs=[r for method,r in records if method=='sendMessage' and r.get('chat_id')==10]
                assert msgs,(mid,text,records)
                body='\n'.join(m['text'] for m in msgs)
                assert need.lower() in body.lower(),(mid,text,body)
                assert any(m.get('reply_parameters',{}).get('message_id')==mid for m in msgs),(mid,records)
            records=await send('спасибкиии, оч помогли!!',11)
            assert any(method=='setMessageReaction' and payload['reaction'][0]['emoji']=='❤️' for method,payload in records),records
            with db._conn() as conn:
                assert conn.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]==0,'Normal FAQs caused support tickets'
            print('TELEGRAM SEMANTIC ADAPTER SMOKE: PASS - replies, context, privacy, social')
        finally:
            await a.close()

if __name__=='__main__':asyncio.run(main())
