import asyncio
from types import SimpleNamespace

import httpx
import jdatetime
import pytest

from hesabyar.core import jalali
from hesabyar.db.models import Kind
from hesabyar.services import extract


def _now():
    return jalali.now()


class TestRuleExtract:
    def test_basic(self):
        r = extract.rule_extract("دیروز ۵۰۰ هزار خرید مواد اولیه از فروشگاه آفتاب", _now())
        assert r is not None
        assert r.kind == Kind.EXPENSE
        assert r.amount == 500_000
        assert "آفتاب" in r.vendor

    def test_income(self):
        r = extract.rule_extract("امروز ۲ میلیون فروختم", _now())
        assert r.kind == Kind.INCOME and r.amount == 2_000_000

    def test_no_amount(self):
        assert extract.rule_extract("سلام خوبی", _now()) is None

    def test_invoice_number(self):
        assert extract._guess_invoice_number("شماره فاکتور: ۱۴۰۳-۰۰۱۲") == "۱۴۰۳-۰۰۱۲"

    def test_vendor_label(self):
        assert "شرکت پخش" in extract._guess_vendor("فروشنده: شرکت پخش البرز")


def _mock_client(content):
    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _run_extract(content, text="متن فاکتور"):
    async def run():
        client = _mock_client(content)
        try:
            ex = extract.LlmExtractor("http://x/v1", "k", "gpt-4o-mini", client=client)
            return await ex.extract(text, base=_now())
        finally:
            await client.aclose()

    return asyncio.run(run())


class TestLlmExtractor:
    def test_maps_fields(self):
        content = (
            '{"type":"expense","amount":1500000,'
            '"category":"خرید کالا و مواد اولیه","date":"1403/05/01",'
            '"description":"خرید","vendor":"فروشگاه آفتاب","invoice_number":"12"}'
        )
        r = _run_extract(content)
        assert r is not None
        assert r.kind == Kind.EXPENSE
        assert r.amount == 1_500_000
        assert r.category == "خرید کالا و مواد اولیه"
        assert r.vendor == "فروشگاه آفتاب"
        assert r.invoice_number == "12"
        assert r.occurred_at.date() == jdatetime.date(1403, 5, 1).togregorian()

    def test_amount_as_string(self):
        r = _run_extract('{"type":"income","amount":"850000"}')
        assert r.kind == Kind.INCOME and r.amount == 850_000

    def test_amount_null_returns_none(self):
        assert _run_extract('{"type":"expense","amount":null}') is None

    def test_code_fenced_json(self):
        r = _run_extract('```json\n{"type":"expense","amount":1000}\n```')
        assert r is not None and r.amount == 1000

    def test_bad_json_raises(self):
        with pytest.raises(extract.ExtractError):
            _run_extract("this is not json")


class TestExtractTransaction:
    def test_rule_when_llm_disabled(self):
        s = SimpleNamespace(llm_enabled=False, llm_creds=None)
        r = asyncio.run(extract.extract_transaction(s, "۵۰۰ هزار خرید", base=_now()))
        assert r is not None and r.amount == 500_000

    def test_falls_back_on_llm_error(self, monkeypatch):
        class Boom:
            def __init__(self, *a, **k):
                pass

            async def extract(self, text, base=None):
                raise extract.ExtractError("boom")

        monkeypatch.setattr(extract, "LlmExtractor", Boom)
        s = SimpleNamespace(llm_enabled=True, llm_creds=("u", "k", "m"))
        r = asyncio.run(extract.extract_transaction(s, "۵۰۰ هزار خرید", base=_now()))
        assert r is not None and r.amount == 500_000  # از روش قاعده‌محور
