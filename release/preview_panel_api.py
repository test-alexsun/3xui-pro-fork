"""Pinned panel API client: loopback only, no redirects or secret-bearing errors."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

class PanelAPIError(RuntimeError):
    pass

class PanelAPI:
    def __init__(self, state, timeout=20):
        self.domain=state['domain'];self.path=state['layout']['panel_path'];self.token=state['api_token'];self.timeout=timeout
        if not re.fullmatch(r'/[A-Za-z0-9_-]{16,80}/',self.path):
            raise PanelAPIError('unsupported private panel path')
        if any(c in self.token for c in '\r\n') or not self.token:
            raise PanelAPIError('invalid private API credential')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):
                raise PanelAPIError('panel API redirect refused')
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def call(self, route, payload=None, form=False):
        if not re.fullmatch(r'[A-Za-z0-9_./%@+-]+',route) or '..' in route:
            raise PanelAPIError('unsupported API operation')
        content='application/x-www-form-urlencoded' if form else 'application/json'
        data=None if payload is None else (urllib.parse.urlencode(payload).encode() if form else json.dumps(payload).encode())
        request=urllib.request.Request('http://127.0.0.1:2053'+self.path+'panel/api/'+route,data=data,headers={'Host':self.domain,'Authorization':'Bearer '+self.token,'Content-Type':content})
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                result=json.load(response)
                if response.status!=200 or not isinstance(result,dict) or not result.get('success'):
                    raise PanelAPIError('panel API rejected operation; response withheld')
        except (OSError,ValueError,urllib.error.URLError):
            raise PanelAPIError('panel API request failed; response withheld') from None
        return result.get('obj')
