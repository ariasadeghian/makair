import asyncio
import io

import httpx
import pytest

from hesabyar.services import ingest


class TestFindUrl:
    def test_extracts(self):
        assert ingest.find_url("فاکتور https://x.com/a.jpg مرسی") == "https://x.com/a.jpg"

    def test_strips_trailing_punct(self):
        assert ingest.find_url("اینجا: https://x.com/a.jpg.") == "https://x.com/a.jpg"

    def test_none(self):
        assert ingest.find_url("بدون لینک") is None
        assert ingest.find_url("") is None


class TestSafety:
    def test_ip_is_safe(self):
        assert ingest._ip_is_safe("8.8.8.8") is True
        assert ingest._ip_is_safe("1.1.1.1") is True
        assert ingest._ip_is_safe("127.0.0.1") is False
        assert ingest._ip_is_safe("10.0.0.1") is False
        assert ingest._ip_is_safe("192.168.1.5") is False
        assert ingest._ip_is_safe("169.254.1.1") is False
        assert ingest._ip_is_safe("::1") is False

    def test_is_safe_url_scheme(self):
        assert ingest.is_safe_url("ftp://8.8.8.8/x") is False
        assert ingest.is_safe_url("file:///etc/passwd") is False

    def test_is_safe_url_public_ip(self):
        assert ingest.is_safe_url("https://8.8.8.8/a.jpg") is True

    def test_is_safe_url_private_ip(self):
        assert ingest.is_safe_url("http://127.0.0.1/a") is False
        assert ingest.is_safe_url("http://10.0.0.5/a") is False


class TestFetchBytes:
    def _fetch(self, url, content, headers, **kw):
        def handler(request):
            return httpx.Response(200, content=content, headers=headers)

        async def run():
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                return await ingest.fetch_bytes(url, client=client, check_safety=False, **kw)
            finally:
                await client.aclose()

        return asyncio.run(run())

    def test_fetch_ok(self):
        data, ct = self._fetch(
            "https://x.com/a.jpg", b"IMAGEDATA", {"content-type": "image/jpeg"}
        )
        assert data == b"IMAGEDATA"
        assert "image" in ct

    def test_size_limit(self):
        with pytest.raises(ingest.IngestError):
            self._fetch(
                "https://x.com/big", b"X" * 100, {"content-type": "image/png"},
                max_bytes=10,
            )

    def test_http_error(self):
        def handler(request):
            return httpx.Response(404)

        async def run():
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                return await ingest.fetch_bytes(
                    "https://x.com/missing", client=client, check_safety=False
                )
            finally:
                await client.aclose()

        with pytest.raises(ingest.IngestError):
            asyncio.run(run())


class TestPrepareImage:
    def test_image_passthrough(self):
        png = b"\x89PNG\r\n\x1a\nrest"
        assert ingest.prepare_image(png, "image/png") == png

    def test_empty_raises(self):
        with pytest.raises(ingest.IngestError):
            ingest.prepare_image(b"")

    def test_pdf_to_image(self):
        # یک PDF کوچک با reportlab بساز
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(100, 700, "Invoice 12345")
        c.showPage()
        c.save()
        pdf_bytes = buf.getvalue()
        assert ingest.looks_like_pdf(pdf_bytes)
        out = ingest.prepare_image(pdf_bytes, "application/pdf")
        assert out[:8] == b"\x89PNG\r\n\x1a\n"  # به PNG تبدیل شد
