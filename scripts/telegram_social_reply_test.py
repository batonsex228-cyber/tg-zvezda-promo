"""End-to-end offline Telegram Reply and ❤️ social UX checks (no Bot API calls)."""
import asyncio
import tempfile
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.core import CoreResult
from app.conversation import classify_social_only
from app.db import Database
from app.operator import OperatorBridge
from app.presentation import PresentedAnswer
from app.responder import BotAnswer
from app.telegram_adapter import TelegramAdapter, TelegramAPIError


class StubCore:
    def __init__(self):
        self.questions = []

    async def process(self, text, *, intent=None):
        self.questions.append((text, intent))
        return CoreResult(
            requested_text=text, intent=intent,
            answer=BotAnswer(True, text='✅ Ответ по скидкам лагеря.', confidence=1.0,
                             faq_id='discounts', reason='approved_intent'),
            presented=PresentedAnswer('✅ Ответ по скидкам лагеря.'),
        )


async def main():
    assert classify_social_only('спасибо, хорошо') == 'thanks'
    assert classify_social_only('Спасибо тебе за помощь!') == 'thanks'
    assert classify_social_only('Хорошо, спасибо, всё понятно 💛') == 'thanks'
    assert classify_social_only('До свидания, спасибо!') == 'farewell'
    assert classify_social_only('Хорошо') == 'acknowledgement'
    assert classify_social_only('Спасибо, а сколько стоит путёвка?') is None
    assert classify_social_only('Спасибо! Когда заезд?') is None
    assert classify_social_only('Пока не знаю дату') is None

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = Settings(
            site_url='https://zvezdaglazov.ru/', kb_file=root/'kb.json',
            db_file=root/'db.sqlite', crawl_max_pages=40, openai_api_key=None,
            openai_model='gpt-5.6', faq_min_score=.72, retrieval_min_score=.48,
            camp_name='ДЗЛ Звёздочка', debug=False, show_source_links=True,
            telegram_bot_token='123:test', telegram_manager_user_id=99,
        )
        db = Database(settings.db_file)
        core = StubCore()
        operator = OperatorBridge(settings, db)
        adapter = TelegramAdapter(settings, core, db, operator)
        calls = []
        fail_reactions = False
        async def fake_api(method, **params):
            calls.append((method, params))
            if fail_reactions and method == 'setMessageReaction':
                raise TelegramAPIError(method, 400, 'REACTION_INVALID')
            return {'message_id': len(calls)} if method == 'sendMessage' else True
        adapter.api = fake_api
        operator.set_telegram_manager_sender(adapter.send_to_manager)
        operator.set_telegram_sender(adapter.send_plain_from_operator)
        operator.set_telegram_marker(adapter.mark_support_conversation)

        async def message(text, ident):
            before = len(calls)
            await adapter._dispatch_telegram({'update_id':ident, 'message':{
                'message_id': ident, 'chat':{'id':10,'type':'private'},
                'from':{'id':10,'first_name':'Иван'}, 'text':text,
            }})
            return calls[before:]

        started = await message('/start', 1)
        assert started[0][0] == 'sendMessage'
        assert 'reply_parameters' not in started[0][1], started

        greeted = await message('Добрый вечер, а у вас есть скидки?', 2)
        texts = [params for method, params in greeted if method == 'sendMessage']
        assert len(texts) == 2, greeted
        assert texts[0]['text'] == 'Здравствуйте! 👋'
        assert 'reply_parameters' not in texts[0]
        assert texts[1]['reply_parameters']['message_id'] == 2
        assert ('5%' in texts[1]['text'] or 'Ответ по скидкам' in texts[1]['text']), texts[1]['text']
        assert 'Добрый вечер' not in texts[1]['text']
        assert core.questions[-1][0] == 'а у вас есть скидки?' if core.questions else ('5%' in texts[1]['text'])

        before_questions = len(core.questions)
        for id_, phrase, expected_kind in [
            (3, 'спасибо, хорошо', 'thanks'),
            (4, 'Спасибо тебе за помощь!', 'thanks'),
            (5, 'До свидания, спасибо!', 'farewell'),
            (6, 'Хорошо', 'acknowledgement'),
        ]:
            result = await message(phrase, id_)
            reactions = [params for method, params in result if method == 'setMessageReaction']
            assert len(reactions) == 1, (phrase, result)
            assert reactions[0]['message_id'] == id_
            assert reactions[0]['chat_id'] == 10
            assert reactions[0]['reaction'] == [{'type':'emoji','emoji':'❤️'}]
            replies = [params for method, params in result if method == 'sendMessage']
            assert len(replies) == 1 and 'reply_parameters' not in replies[0], (phrase,result)
            assert classify_social_only(phrase) == expected_kind
        assert len(core.questions) == before_questions, core.questions
        with db._conn() as conn:
            assert conn.execute('SELECT COUNT(*) FROM tickets').fetchone()[0] == 0

        ordinary = await message('Спасибо, а сколько стоит путёвка?', 7)
        assert not [r for r in ordinary if r[0] == 'setMessageReaction'], ordinary
        assert len(core.questions) in {before_questions, before_questions+1}
        assert any(params.get('reply_parameters',{}).get('message_id') == 7
                   for method, params in ordinary if method == 'sendMessage'), ordinary

        pure = await message('Добрый вечер', 8)
        assert len(pure)==1 and pure[0][0]=='sendMessage'
        assert 'Здравствуйте' in pure[0][1]['text']
        assert 'Добрый вечер' not in pure[0][1]['text']
        assert 'reply_parameters' not in pure[0][1]

        fail_reactions = True
        failed = await message('Спасибо большое!', 9)
        assert [m for m in failed if m[0]=='setMessageReaction']
        assert [m for m in failed if m[0]=='sendMessage'], failed

        # A manager's different chat must never quote the parent's question.
        token = adapter._incoming_reply.set((10, 123))
        try:
            await adapter.send_message(99, 'Менеджеру пришла заявка')
        finally:
            adapter._incoming_reply.reset(token)
        assert 'reply_parameters' not in calls[-1][1]
        await adapter.close()
        print('TELEGRAM SOCIAL/REPLY/HEART TEST: PASS')


if __name__ == '__main__':
    asyncio.run(main())
