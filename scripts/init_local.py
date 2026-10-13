"""Create local-only random secrets; never overwrite existing configuration."""
from pathlib import Path
import secrets

if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / ".env"
    content = (
        "# Local synthetic-data development only. Do not commit.\n"
        f"DJANGO_SECRET_KEY={secrets.token_urlsafe(64)}\n"
        "POSTGRES_DB=adc_local\nPOSTGRES_USER=adc_local\n"
        f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n"
        "DB_HOST=127.0.0.1\nDB_PORT=54329\nADC_READ_ONLY=0\n"
    )
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(content)
        try:
            target.chmod(0o600)
        except OSError:
            pass  # Windows ACLs are managed by the OS/user.
        print("Created .env with random local secrets. Existing databases were not changed.")
    except FileExistsError:
        print(".env already exists; left unchanged.")
