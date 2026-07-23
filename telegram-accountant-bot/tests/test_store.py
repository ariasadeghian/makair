from fakes import FakeSpreadsheet

from hesabyar.core import jalali
from hesabyar.db.models import Kind, Transaction, User
from hesabyar.db.store import Store


async def test_load_empty(store):
    assert store.list("users") == []
    assert store.next_id("transactions") == 1


async def test_add_assigns_id_and_created_at(store):
    t = await store.add(
        "transactions",
        Transaction(user_id=1, kind=Kind.EXPENSE, amount=500, occurred_at=jalali.now()),
    )
    assert t.id == 1
    assert t.created_at is not None
    assert store.get("transactions", 1) is t
    assert store.next_id("transactions") == 2


async def test_user_preset_id(store):
    u = await store.add("users", User(id=555, business_name="بوتیک"))
    assert u.id == 555
    assert store.get("users", 555).business_name == "بوتیک"


async def test_list_predicate_and_sort(store):
    for i in range(3):
        await store.add("transactions", Transaction(user_id=1, amount=i, occurred_at=jalali.now()))
    await store.add("transactions", Transaction(user_id=2, amount=99, occurred_at=jalali.now()))
    mine = store.list("transactions", lambda t: t.user_id == 1)
    assert len(mine) == 3
    assert [t.id for t in mine] == sorted(t.id for t in mine)


async def test_update_and_delete(store):
    t = await store.add("transactions", Transaction(user_id=1, amount=1, occurred_at=jalali.now()))
    t.amount = 777
    await store.update("transactions", t)
    assert store.get("transactions", t.id).amount == 777
    await store.delete("transactions", t.id)
    assert store.get("transactions", t.id) is None


async def test_flush_persists_and_reloads():
    ss = FakeSpreadsheet()
    s = Store(ss)
    await s.load()
    now = jalali.now()
    await s.add(
        "transactions",
        Transaction(user_id=1, kind=Kind.INCOME, amount=1_000_000,
                    category="فروش کالا", description="فروش", occurred_at=now),
    )
    await s.flush()
    # بارگذاری دوباره از همان اسپردشیت
    s2 = Store(ss)
    await s2.load()
    rows = s2.list("transactions")
    assert len(rows) == 1
    assert rows[0].amount == 1_000_000
    assert rows[0].kind == Kind.INCOME
    assert rows[0].occurred_at.isoformat() == now.isoformat()
