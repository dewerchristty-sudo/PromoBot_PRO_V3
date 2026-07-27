import argparse
from datetime import datetime
from pathlib import Path
import shutil
import tempfile

from src.affiliates.config import DEFAULT_ENV_PATH
from src.affiliates.validation import product_identity, safe_absolute_url


VARIABLE = "MERCADOLIVRE_AFFILIATE_MAP"


def add_mapping(original_url, affiliate_url, env_path=DEFAULT_ENV_PATH):
    product_key = product_identity("Mercado Livre", original_url)
    if not product_key:
        raise ValueError("product_key_nao_encontrado")
    if not safe_absolute_url(affiliate_url, ("meli.la",)):
        raise ValueError("link_oficial_invalido")
    env_path = Path(env_path).resolve()
    if not env_path.is_file():
        raise FileNotFoundError(env_path)
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    indexes = [
        index for index, line in enumerate(lines)
        if line.startswith(VARIABLE + "=")
    ]
    if len(indexes) != 1:
        raise ValueError("variavel_ausente_ou_duplicada")
    index = indexes[0]
    ending = "\r\n" if lines[index].endswith("\r\n") else "\n"
    current = lines[index].rstrip("\r\n").split("=", 1)[1].strip()
    normalized = product_key.casefold().replace("-", "")
    if normalized in current.casefold().replace("-", ""):
        raise ValueError("produto_ja_mapeado")
    separator = ";" if current and not current.endswith(";") else ""
    lines[index] = (
        f"{VARIABLE}={current}{separator}"
        f"{product_key}={affiliate_url}{ending}"
    )
    backup_dir = env_path.parent / "backups" / "affiliate_config"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / (
        f"env_before_{product_key}_"
        f"{datetime.now():%Y%m%d_%H%M%S}.backup"
    )
    shutil.copy2(env_path, backup)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="",
        dir=env_path.parent, delete=False,
    ) as stream:
        stream.writelines(lines)
        temporary = Path(stream.name)
    temporary.replace(env_path)
    return {"product_key": product_key, "backup": backup}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-url", required=True)
    parser.add_argument("--affiliate-url", required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm:
        raise SystemExit("Use --confirm para autorizar a alteracao do .env.")
    result = add_mapping(args.original_url, args.affiliate_url)
    print("product_key:", result["product_key"])
    print("backup:", result["backup"])
    print("entrada adicionada: sim (link mascarado)")


if __name__ == "__main__":
    main()
