from src.main import create_app

app = create_app(is_mock=True)

__all__ = ["app"]
