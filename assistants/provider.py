"""Minimal HTTPS Chat Completions adapter. stdlib only; no provider SDK needed.
Remote requests contain a redacted user question + fixed classifier prompt, never DB records.
"""
from dataclasses import dataclass
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from assistants.protocol import AIProtocolError, parse_decision, system_prompt

class ProviderError(RuntimeError):
    def __init__(self,code): self.code=code; super().__init__(code)

@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    api_key: str
    model: str
    allowed_hosts: tuple[str,...]
    timeout: int = 20
    token_field: str = "max_completion_tokens"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ProviderError("redirect_blocked")

def endpoint(config):
    try:
        u=urllib.parse.urlsplit(config.base_url)
        host=(u.hostname or "").lower()
        port=u.port
    except ValueError as exc: raise ProviderError("bad_configuration") from exc
    if (u.scheme!="https" or not host or u.username or u.password or u.query or u.fragment
        or port not in (None,443) or host not in config.allowed_hosts or host=="localhost"
        or host.endswith((".local",".internal")) or not re.fullmatch(r"[a-z0-9.-]+",host)):
        raise ProviderError("endpoint_not_allowed")
    try:
        ip=ipaddress.ip_address(host)
    except ValueError: pass
    else:
        if not ip.is_global: raise ProviderError("endpoint_not_allowed")
    if not config.api_key or "\n" in config.api_key or "\r" in config.api_key: raise ProviderError("missing_key")
    if not config.model or len(config.model)>120 or not re.fullmatch(r"[A-Za-z0-9._:/-]+",config.model): raise ProviderError("missing_model")
    if config.token_field not in ("max_completion_tokens","max_tokens") or not 2<=config.timeout<=30:
        raise ProviderError("bad_configuration")
    path=u.path.rstrip("/")
    if path.endswith("/chat/completions"): raise ProviderError("base_url_must_not_include_endpoint")
    return config.base_url.rstrip("/")+"/chat/completions"

def classify(message,audience,config):
    url=endpoint(config)
    body={"model":config.model,"messages":[{"role":"system","content":system_prompt(audience)},
          {"role":"user","content":message}],"response_format":{"type":"json_object"},
          config.token_field:256,"stream":False}
    req=urllib.request.Request(url,data=json.dumps(body,ensure_ascii=False).encode("utf-8"),
          headers={"Authorization":"Bearer "+config.api_key,"Content-Type":"application/json"},method="POST")
    # Fail closed on redirects; never forward a bearer token to a redirected host.
    opener=urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req,timeout=config.timeout) as response:
            raw=response.read(32769)
            if len(raw)>32768: raise ProviderError("response_too_large")
            obj=json.loads(raw.decode("utf-8"))
    except ProviderError: raise
    except urllib.error.HTTPError as exc:
        raise ProviderError("provider_auth" if exc.code in (401,403) else "provider_rate_limit" if exc.code==429 else "provider_http") from None
    except (urllib.error.URLError,TimeoutError,OSError): raise ProviderError("provider_unavailable") from None
    except (UnicodeError,ValueError): raise ProviderError("invalid_response") from None
    try:
        choice=obj["choices"][0]
        if choice.get("finish_reason")!="stop" or choice["message"].get("tool_calls") or choice["message"].get("refusal"):
            raise ProviderError("invalid_response")
        return parse_decision(choice["message"]["content"],audience)
    except (KeyError,IndexError,TypeError,AttributeError,AIProtocolError): raise ProviderError("invalid_response") from None
