"""تست‌های ماژول :mod:`hesabyar.services.moadian`.

هیچ تستی به شبکه وصل نمی‌شود: :class:`~hesabyar.services.moadian.MoadianClient`
فقط با ``httpx.MockTransport`` آزموده می‌شود و بقیه‌ی توابع محض و بدون I/O‌اند.
چون ``pytest-asyncio`` نصب نیست، توابع async با ``asyncio.run`` اجرا می‌شوند.
مدل‌ها مستقیم در حافظه ساخته می‌شوند (بدون نشست)، مانند الگوی
``tests/test_invoice_pdf.py``.
"""
import asyncio
import hashlib
import json
import types

import httpx
import jdatetime
import pytest

from hesabyar.core import jalali
from hesabyar.db.models import Invoice, InvoiceItem, User
from hesabyar.services import moadian


def _build_invoice() -> tuple[Invoice, User]:
    """یک فاکتور نمونه با چند قلم و کسب‌وکار را در حافظه می‌سازد."""
    business = User(
        id=555_111,
        business_name="فروشگاه نمونه",
        phone="۰۹۱۲۳۴۵۶۷۸۹",
        address="تهران، خیابان آزادی",
    )
    issue_date = jdatetime.date(1403, 5, 1).togregorian()
    invoice = Invoice(
        number="۱۴۰۳-۰۰۰۱",
        seq=1,
        customer_name="آقای رضایی",
        customer_phone="۰۹۳۵۱۱۱۲۲۳۳",
        customer_address="کرج، بلوار طالقانی",
        issue_date=issue_date,
    )
    # ست‌کردن مستقیم اقلام روی رابطه (شیء transient بدون نشست).
    invoice.items = [
        InvoiceItem(title="دفتر ۱۰۰ برگ", quantity=3, unit_price=45_000),  # ۱۳۵٬۰۰۰
        InvoiceItem(title="خودکار آبی", quantity=10, unit_price=8_000),  # ۸۰٬۰۰۰
    ]
    return invoice, business


class TestComputeTotals:
    def test_vat_nine_percent(self):
        # جمع نمونه: ۱٬۰۰۰٬۰۰۰ تومان، مالیات ۹٪ = ۹۰٬۰۰۰، مبلغ نهایی ۱٬۰۹۰٬۰۰۰.
        invoice = types.SimpleNamespace(total=1_000_000)
        totals = moadian.compute_totals(invoice, vat_rate=0.09)
        assert totals == {"subtotal": 1_000_000, "vat": 90_000, "total": 1_090_000}
        # خروجی‌ها عدد صحیح‌اند.
        assert all(isinstance(v, int) for v in totals.values())


class TestBuildInvoicePayload:
    def test_structure_and_amounts(self):
        invoice, business = _build_invoice()

        payload = moadian.build_invoice_payload(
            invoice,
            business,
            economic_code="EC-42",
            seller_tin="SELLER-1",
            buyer_tin="BUYER-9",
            vat_rate=0.09,
        )

        # کلیدهای سطح بالا.
        assert set(payload) == {"header", "body", "totals"}

        # --- سربرگ ---
        header = payload["header"]
        assert header["inno"] == invoice.number
        assert header["indati2m"] == jalali.format_date(invoice.issue_date)
        assert header["inty"] == 1
        assert header["setm"] == 1
        assert header["seller"] == {
            "tin": "SELLER-1",
            "economic_code": "EC-42",
            "name": "فروشگاه نمونه",
        }
        assert header["buyer"] == {"tin": "BUYER-9", "name": "آقای رضایی"}

        # --- بدنه: تعداد ردیف‌ها برابر تعداد اقلام ---
        body = payload["body"]
        assert len(body) == len(invoice.items) == 2

        first = body[0]
        assert first["sstid"] == ""
        assert first["sstt"] == "دفتر ۱۰۰ برگ"
        assert first["am"] == 3
        assert first["fee"] == 45_000
        assert first["prdis"] == 0
        assert first["dis"] == 0
        assert first["vra"] == 0.09
        assert first["tsstam"] == 135_000  # مبلغ کل ردیف پیش از مالیات
        assert first["vam"] == 12_150  # ۹٪ از ۱۳۵٬۰۰۰

        assert body[1]["tsstam"] == 80_000
        assert body[1]["vam"] == 7_200  # ۹٪ از ۸۰٬۰۰۰

        # --- جمع‌ها ---
        # subtotal = ۱۳۵٬۰۰۰ + ۸۰٬۰۰۰ = ۲۱۵٬۰۰۰ ؛ مالیات ۹٪ = ۱۹٬۳۵۰.
        assert payload["totals"] == {
            "subtotal": 215_000,
            "vat": 19_350,
            "total": 234_350,
        }

    def test_without_business_leaves_seller_name_empty(self):
        # طبق قرارداد، اگر business=None باشد نام فروشنده خالی می‌ماند.
        invoice, _ = _build_invoice()
        payload = moadian.build_invoice_payload(invoice, None)
        assert payload["header"]["seller"]["name"] == ""


class TestDryRunClient:
    def test_reference_prefix_and_determinism(self):
        client = moadian.DryRunMoadianClient()
        payload = {"header": {"inno": "۱۴۰۳-۰۰۰۱"}, "body": [], "totals": {}}

        first = asyncio.run(client.submit(payload))
        second = asyncio.run(client.submit(payload))

        # وضعیت و پیشوند مرجع درست است.
        assert first["status"] == "dry-run"
        assert first["reference"].startswith("DRYRUN-")

        # برای ورودی ثابت، خروجی قطعی است (دو بار صدا زدن، نتیجه‌ی یکسان).
        assert first == second

        # مرجع دقیقاً از SHA-1 شماره‌ی صورتحساب ساخته می‌شود.
        expected = "DRYRUN-" + hashlib.sha1("۱۴۰۳-۰۰۰۱".encode()).hexdigest()[:8]
        assert first["reference"] == expected


class TestGetMoadianClient:
    def test_no_moadian_fields_returns_dry_run(self):
        settings = types.SimpleNamespace(bot_token="x")
        client = moadian.get_moadian_client(settings)
        assert isinstance(client, moadian.DryRunMoadianClient)

    def test_partial_config_returns_dry_run(self):
        # اگر فقط یکی از دو فیلد باشد، باز هم اجرای آزمایشی.
        settings = types.SimpleNamespace(moadian_base_url="https://moadian.example.test")
        client = moadian.get_moadian_client(settings)
        assert isinstance(client, moadian.DryRunMoadianClient)

    def test_full_config_returns_real_client(self):
        settings = types.SimpleNamespace(
            moadian_base_url="https://moadian.example.test",
            moadian_token="secret-token",
        )
        client = moadian.get_moadian_client(settings)
        assert isinstance(client, moadian.MoadianClient)


class TestMoadianClientSubmit:
    def test_submit_returns_json_and_keeps_injected_client_open(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization")
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"reference": "M-123"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        mc = moadian.MoadianClient(
            "https://moadian.example.test", "secret-token", client=client
        )

        result = asyncio.run(mc.submit({"header": {"inno": "۱۴۰۳-۰۰۰۱"}}))
        # کلاینتِ تزریق‌شده نباید بسته شده باشد؛ فراخوانی دوم هم باید کار کند.
        result2 = asyncio.run(mc.submit({"header": {"inno": "۱۴۰۳-۰۰۰۲"}}))
        asyncio.run(client.aclose())

        assert result == {"reference": "M-123"}
        assert result2 == {"reference": "M-123"}
        # درخواست به مسیر و با هدر احراز هویتِ درست رفته است.
        assert captured["url"].endswith("/invoices")
        assert captured["auth"] == "Bearer secret-token"
        assert captured["body"] == {"header": {"inno": "۱۴۰۳-۰۰۰۲"}}

    def test_http_error_raises_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        mc = moadian.MoadianClient(
            "https://moadian.example.test", "secret-token", client=client
        )
        with pytest.raises(moadian.MoadianUnavailable):
            asyncio.run(mc.submit({"header": {"inno": "x"}}))
        asyncio.run(client.aclose())

    def test_network_error_raises_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("شبکه در دسترس نیست")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        mc = moadian.MoadianClient(
            "https://moadian.example.test", "secret-token", client=client
        )
        with pytest.raises(moadian.MoadianUnavailable):
            asyncio.run(mc.submit({"header": {"inno": "x"}}))
        asyncio.run(client.aclose())
