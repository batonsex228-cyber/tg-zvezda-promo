from datetime import datetime,timezone
import hashlib,hmac,json
from urllib.parse import urlencode
import pytest
from app.security import verify_init_data,AuthError

TOKEN='987654321:TEST_ONLY_DONT_USE'

def make_init(user_id=100,now=None):
    now=now or int(datetime.now(timezone.utc).timestamp())
    fields={'auth_date':str(now),'user':json.dumps({'id':user_id,'first_name':'Алексей'},ensure_ascii=False,separators=(',',':'))}
    check='\n'.join(f'{k}={v}' for k,v in sorted(fields.items()))
    secret=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
    fields['hash']=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    return urlencode(fields)

def test_auth_success():
    assert verify_init_data(make_init(),TOKEN)['id']==100

def test_auth_tampering():
    with pytest.raises(AuthError,match='подпись'):
        verify_init_data(make_init().replace('100','101'),TOKEN)

def test_auth_expiry():
    with pytest.raises(AuthError,match='устарела'):
        verify_init_data(make_init(now=1700000000),TOKEN,now=1700500000)

def test_auth_rejects_no_token():
    with pytest.raises(AuthError):verify_init_data(make_init(),'')
