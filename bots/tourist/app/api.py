"""FastAPI backend for Tourist Telegram Mini App."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, Request, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.config import settings, ROOT
from app.version import VERSION
from app.database import initialize_storage
from app.security import verify_init_data, AuthError
from app import service, sheets, notifications, maintenance, operations, assistant


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_storage()
    task=asyncio.create_task(sheets.background_sync())
    notify_task=asyncio.create_task(notifications.background_notifications())
    backup_task=asyncio.create_task(maintenance.background_backups())
    try:
        yield
    finally:
        task.cancel()
        notify_task.cancel()
        backup_task.cancel()
        await asyncio.gather(task, notify_task, backup_task, return_exceptions=True)

app = FastAPI(title='Турист · Club API',version=VERSION,lifespan=lifespan,docs_url=None,redoc_url=None)
webdir=ROOT / 'web'
app.mount('/assets',StaticFiles(directory=str(webdir)),name='assets')


@app.middleware('http')
async def security_headers(request:Request,call_next):
    resp=await call_next(request)
    resp.headers['X-Content-Type-Options']='nosniff'
    resp.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    resp.headers['Content-Security-Policy']=("default-src 'self'; base-uri 'none'; object-src 'none'; "
        "frame-ancestors 'self' https://web.telegram.org; form-action 'self'; connect-src 'self'; "
        "script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:")
    resp.headers['Referrer-Policy']='no-referrer'
    resp.headers['Cache-Control']='no-store' if request.url.path.startswith('/api/') or request.url.path in ('/health','/ready') else 'public, max-age=120'
    # API and Mini App served same origin; no permissive CORS.
    return resp


@app.exception_handler(service.BusinessError)
async def business_error(_request:Request, exc:service.BusinessError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status,content={'detail':exc.message})


@app.get('/')
async def home():
    return FileResponse(str(webdir/'index.html'))


@app.get('/health')
async def health():
    return {'ok':True,'version':VERSION,'google_sheets_configured':sheets.enabled()}


@app.get('/ready')
async def readiness():
    """Container readiness probe. Never expose database paths, secrets, or user details."""
    from fastapi.responses import JSONResponse
    from app.database import database_path, assert_existing_bot_identity
    import sqlite3
    try:
        # Do not create or migrate databases in a probe.
        path = database_path()
        if not path.is_file():
            raise RuntimeError('database missing')
        assert_existing_bot_identity()
        with sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True, timeout=2) as c:
            if c.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('database integrity')
            c.execute('SELECT revision FROM sync_jobs WHERE id=1').fetchone()
        return {'ready': True, 'version': VERSION}
    except (sqlite3.DatabaseError, OSError, RuntimeError, ValueError):
        return JSONResponse(status_code=503, content={'ready': False})


async def user_id(request:Request):
    raw=request.headers.get('X-Telegram-Init-Data','')
    if settings.demo_mode and not settings.bot_token and request.client and request.client.host in ('127.0.0.1','::1','testclient') and request.url.hostname in ('127.0.0.1','localhost','testserver'):
        try:
            tgid=int(request.headers.get('X-Demo-User-ID','900001'))
            if not (1 <= tgid <= 999999999999): raise ValueError()
        except ValueError:
            raise HTTPException(401,'Неверный тестовый ID')
        return service.ensure_user(tgid,'Гость')
    try:
        obj=verify_init_data(raw,settings.bot_token)
    except AuthError as e:
        raise HTTPException(401,str(e)) from e
    return service.ensure_user(obj['id'],obj['first_name'])


def require_admin(user=Depends(user_id)):
    if user['role'] not in ('owner','senior','admin') or (user['role']=='owner' and user['telegram_id']!=settings.owner_telegram_id):
        raise HTTPException(403,'Только для администратора')
    return user


class ProfileData(BaseModel):
    full_name:str=Field(min_length=2,max_length=100)
    phone:str=Field(min_length=10,max_length=24)
    nickname:str=Field(min_length=2,max_length=24)


class BookingData(BaseModel):
    starts_at:str
    hours:int=Field(ge=1,le=4)
    guest_count:int=Field(ge=1,le=30)


class EventData(BaseModel):
    kind:Literal['mafia','poker']
    title:str
    starts_at:str
    capacity:int=Field(ge=1,le=100)
    format:str=''
    min_players:int=1
    stack:str=''
    blinds:str=''


class DecisionData(BaseModel):
    category:Literal['event','billiard']
    request_id:int=Field(ge=1)
    approve:bool


class EventEditData(EventData):
    status:Literal['open','closed','cancelled']='open'


class AssistantQuestionData(BaseModel):
    text: str = Field(min_length=1,max_length=1500)


class SupportQuestionData(BaseModel):
    text: str = Field(min_length=5,max_length=1500)


class SupportAnswerData(BaseModel):
    text: str = Field(min_length=2,max_length=2000)


class RoleData(BaseModel):
    telegram_id:int=Field(gt=0)
    role:Literal['guest','admin','senior']


@app.post('/api/assistant/reply')
async def assistant_reply(p: AssistantQuestionData,u=Depends(user_id)):
    reply=assistant.answer(p.text, user_id=u['telegram_id'])
    if reply is None:
        return {'matched':False,'answer':'Пока не нашёл надёжного ответа на этот вопрос. Могу передать его администратору — нажмите «Связь».', 'needs_admin':True}
    return {'matched':True,'answer':reply,'needs_admin':False}


@app.get('/api/billiard/busy')
async def busy(date:str):
    return {'date':date,'busy':service.billiard_busy(date)}


@app.get('/api/config')
async def public_config():
    # No private settings or secrets are returned to the browser.
    return {'club_timezone':settings.club_timezone,'booking_horizon_days':7,
            'reminders_enabled':settings.reminder_hours_before > 0,
            'showcase_mode':settings.showcase_mode}


@app.get('/api/schedule')
async def schedule():
    return service.list_events()


@app.get('/api/me')
async def me(u=Depends(user_id)):
    return {'user':u,'profile_ready':service.profile_ready(u),'requests':service.my_requests(u['telegram_id'])}


@app.put('/api/profile')
async def update_profile(p:ProfileData,u=Depends(user_id)):
    return {'user':service.set_profile(u['telegram_id'],p.full_name,p.phone,p.nickname)}


@app.post('/api/events/{event_id}/join')
async def join(event_id:int,u=Depends(user_id), request_key:str|None=Header(default=None,alias='X-Idempotency-Key')):
    rid=service.join_event(u['telegram_id'],event_id,request_key)
    return {'id':rid,'status':service.request_status(u['telegram_id'],'event',rid)}


@app.get('/api/events/{event_id}/confirmed')
async def confirmed(event_id:int):
    return service.event_members(event_id)


@app.post('/api/billiard')
async def book(p:BookingData,u=Depends(user_id), request_key:str|None=Header(default=None,alias='X-Idempotency-Key')):
    rid=service.billiard_book(u['telegram_id'],p.starts_at,p.hours,p.guest_count,request_key)
    return {'id':rid,'status':service.request_status(u['telegram_id'],'billiard',rid),'payment':'в клубе'}


@app.post('/api/{category}/{request_id}/cancel')
async def cancel(category:Literal['event','billiard'],request_id:int,u=Depends(user_id)):
    service.request_cancel(u['telegram_id'],category,request_id)
    return {'status':'cancel_requested'}


@app.post('/api/support/tickets')
async def support_create(p:SupportQuestionData,u=Depends(user_id),request_key:str|None=Header(default=None,alias='X-Idempotency-Key')):
    tid=service.create_support_ticket(u['telegram_id'],p.text,request_key)
    return {'id':tid,'status':'open'}


@app.get('/api/support/mine')
async def support_mine(u=Depends(user_id)):
    return service.my_support_tickets(u['telegram_id'])


@app.get('/api/admin/support')
async def support_admin(u=Depends(require_admin)):
    return service.list_support_tickets(u['telegram_id'])


@app.post('/api/admin/support/{ticket_id}/reply')
async def support_reply(ticket_id:int,p:SupportAnswerData,u=Depends(require_admin)):
    return service.answer_support_ticket(u['telegram_id'],ticket_id,p.text)


@app.get('/api/admin/pending')
async def pending(u=Depends(require_admin)):
    return service.list_pending(u['telegram_id'])


@app.post('/api/admin/decide')
async def decide(p:DecisionData,u=Depends(require_admin)):
    result=service.decide(u['telegram_id'],p.category,p.request_id,p.approve)
    return result


@app.post('/api/admin/events')
async def create_event(p:EventData,u=Depends(require_admin)):
    return service.create_event(u['telegram_id'],p.kind,p.title,p.starts_at,p.capacity,p.format,p.min_players,p.stack,p.blinds)


@app.get('/api/admin/events')
async def all_admin_events(u=Depends(require_admin)):
    return service.admin_events(u['telegram_id'])


@app.put('/api/admin/events/{event_id}')
async def edit_event(event_id:int,p:EventEditData,u=Depends(require_admin)):
    return service.edit_event(u['telegram_id'],event_id,p.kind,p.title,p.starts_at,p.capacity,p.format,p.min_players,p.stack,p.blinds,p.status)


@app.get('/api/admin/users')
async def admin_users(q:str='',u=Depends(require_admin)):
    return service.search_users(u['telegram_id'],q)


@app.get('/api/admin/audit')
async def admin_audit(u=Depends(require_admin)):
    return service.audit_feed(u['telegram_id'])


@app.get('/api/admin/notifications')
async def admin_notifications(u=Depends(require_admin)):
    return notifications.pending_status()


@app.post('/api/admin/roles')
async def role(p:RoleData,u=Depends(require_admin)):
    return service.set_role(u['telegram_id'],p.telegram_id,p.role)


@app.get('/api/admin/sync')
async def sync_status(u=Depends(require_admin)):
    return sheets.status()



@app.get('/api/admin/dashboard')
async def dashboard(u=Depends(require_admin)):
    return service.admin_dashboard(u['telegram_id'])


@app.get('/api/admin/backups')
async def admin_backups(u=Depends(require_admin)):
    # Read-only status: never send local file names, database contents, or credentials.
    return maintenance.backup_status()


def require_owner(u=Depends(user_id)):
    # Other staff must not inspect disk and integration diagnostics.
    if not settings.owner_telegram_id or u['telegram_id'] != settings.owner_telegram_id or u['role'] != 'owner':
        raise HTTPException(403,'Только для владельца')
    return u


@app.post('/api/admin/notifications/retry')
async def retry_notifications(u=Depends(require_owner)):
    # Explicit owner action only; never send messages synchronously in an HTTP request.
    return notifications.retry_transient_failures()


@app.get('/api/admin/operations')
async def admin_operations(u=Depends(require_owner)):
    return await asyncio.to_thread(operations.snapshot)
