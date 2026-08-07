from app.core.config import settings
from app.core.storage import StorageService


def test_r2_url_uses_public_base(monkeypatch):
    monkeypatch.setattr(settings, "USE_S3", True)
    monkeypatch.setattr(settings, "S3_PUBLIC_BASE_URL", "https://media.example.com/")
    monkeypatch.setattr(
        settings,
        "S3_ENDPOINT_URL",
        "https://account-id.r2.cloudflarestorage.com",
    )

    assert StorageService().get_url("clients/photo.jpg") == (
        "https://media.example.com/clients/photo.jpg"
    )


def test_s3_url_falls_back_to_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "USE_S3", True)
    monkeypatch.setattr(settings, "S3_PUBLIC_BASE_URL", "")
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", "https://s3.example.test/")

    assert StorageService().get_url("video.mp4") == "https://s3.example.test/video.mp4"
