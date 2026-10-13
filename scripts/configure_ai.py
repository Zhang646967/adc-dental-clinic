"""Run locally via a temporary Docker Python container; credentials never echoed.
Changes only AI_* entries of the existing .env. Makes no network calls.
"""
from getpass import getpass
from pathlib import Path
import os
import re
import sys
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]

def merge_env(text,values):
    output=[];seen=set()
    for line in text.splitlines():
        key=line.split("=",1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in values:
            if key not in seen: output.append(key+"="+values[key]);seen.add(key)
        else: output.append(line)
    for key,value in values.items():
        if key not in seen: output.append(key+"="+value)
    return "\n".join(output)+"\n"

def main():
    env=ROOT/".env"
    if not env.is_file(): raise SystemExit("Missing .env. Initialise or reuse the existing v0.3 .env first.")
    mode=input("AI mode [demo / remote / disabled] (demo): ").strip() or "demo"
    if mode not in ("demo","remote","disabled"): raise SystemExit("Invalid mode; no files changed.")
    values={"AI_MODE":mode}
    if mode=="remote":
        base=input("Approved provider base URL (https://api.openai.com/v1): ").strip() or "https://api.openai.com/v1"
        u=urlsplit(base)
        if u.scheme!="https" or not u.hostname or u.username or u.password or u.query or u.fragment or u.port not in (None,443):
            raise SystemExit("Use an HTTPS base URL; no embedded credential/query/non-443 port.")
        if not re.fullmatch(r"https://[A-Za-z0-9./_-]+",base) or base.rstrip("/").endswith("chat/completions"):
            raise SystemExit("Base URL must not contain the /chat/completions endpoint or special characters.")
        model=input("Model ID provided by your vendor: ").strip()
        if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,120}",model): raise SystemExit("Invalid model ID.")
        field=input("Token field [max_completion_tokens / max_tokens] (max_completion_tokens): ").strip() or "max_completion_tokens"
        if field not in ("max_completion_tokens","max_tokens"): raise SystemExit("Invalid token field.")
        key=getpass("API key (hidden; not saved to shell history): ").strip()
        # Avoid Compose interpolation/quoting ambiguities; typical bearer keys use this alphabet.
        if not re.fullmatch(r"[A-Za-z0-9._:/+=-]{8,4096}",key): raise SystemExit("Unsupported key format; no files changed. Never paste the key into chat.")
        values.update(AI_BASE_URL=base.rstrip("/"),AI_MODEL=model,AI_API_KEY=key,
                      AI_ALLOWED_HOSTS=u.hostname.lower(),AI_TOKEN_LIMIT_FIELD=field)
    new=merge_env(env.read_text(encoding="utf-8-sig"),values)
    tmp=ROOT/".env.ai.tmp"
    tmp.write_text(new,encoding="utf-8");os.replace(tmp,env)
    print("AI configuration saved. Database settings and Django secret preserved. No network request made.")
    print("Recreate web with: docker compose up -d --force-recreate web")

if __name__=="__main__": main()
