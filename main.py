from src.app import PromoBot
from src.core.desktop_shortcut import ensure_desktop_shortcut


def main() -> None:
    ensure_desktop_shortcut()
    sistema = PromoBot()
    sistema.run()


if __name__ == "__main__":
    main()
