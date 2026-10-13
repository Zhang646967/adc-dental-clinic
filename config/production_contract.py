"""Fail-closed deployment input checks. These do not certify an environment."""
from dataclasses import dataclass
import re
from typing import Mapping

@dataclass(frozen=True)
class ProductionInputs:
    host: str
    sslmode: str
    read_only: bool

def validate_production_inputs(env: Mapping[str,str]) -> ProductionInputs:
    if env.get('ADC_DEPLOYMENT_STAGE') not in ('staging','production'):
        raise ValueError('Set ADC_DEPLOYMENT_STAGE only after reviewing the release checklist.')
    host=env.get('ADC_PUBLIC_HOST','').strip().lower()
    if not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',host):
        raise ValueError('ADC_PUBLIC_HOST must be one explicit DNS hostname, without scheme, path or wildcard.')
    if len(env.get('DJANGO_SECRET_KEY','')) < 50:
        raise ValueError('A separate production DJANGO_SECRET_KEY of at least 50 characters is required.')
    runtime=env.get('POSTGRES_USER','')
    owner=env.get('ADC_DATABASE_OWNER','')
    if not owner or not runtime or runtime in ('postgres',owner):
        raise ValueError('Runtime DB user must differ from the migration owner and postgres.')
    if not env.get('POSTGRES_DB') or len(env.get('POSTGRES_PASSWORD',''))<20:
        raise ValueError('Explicit database name and a separate runtime database password are required.')
    port = env.get('DB_PORT', '5432')
    if not env.get('DB_HOST') or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError('Explicit database host and numeric port are required.')
    mode=env.get('ADC_DB_SSLMODE','require')
    if mode not in ('require','verify-ca','verify-full','disable'):
        raise ValueError('Unsupported ADC_DB_SSLMODE.')
    if mode=='disable' and env.get('ADC_PRIVATE_DB_NETWORK_ACK')!='1':
        raise ValueError('Unencrypted DB links are limited to explicitly acknowledged private networks.')
    if env.get('ADC_TRUST_PROXY_HEADERS')!='1':
        raise ValueError('A trusted proxy that strips and sets X-Forwarded-Proto is required.')
    if env.get('ADC_READ_ONLY','1') not in ('0','1'):
        raise ValueError('ADC_READ_ONLY must be 0 or 1.')
    return ProductionInputs(host,mode,env.get('ADC_READ_ONLY','1')=='1')
