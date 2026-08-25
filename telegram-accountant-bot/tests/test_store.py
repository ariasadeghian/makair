from fakes import FakeClient, FakeSpreadsheet

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
    """تراکنش در اسپردشیتِ اختصاصیِ کاربر می‌نشیند و پس از reload برمی‌گردد."""
    central, client = FakeSpreadsheet(), FakeClient()
    s = Store(central, client=client, folder_id="f")
    await s.load()
    await s.add("users", User(id=1, business_name="بوتیک"))
    await s.ensure_user_spreadsheet(1)

    now = jalali.now()
    await s.add(
        "transactions",
        Transaction(user_id=1, kind=Kind.INCOME, amount=1_000_000,
                    category="فروش کالا", description="فروش", occurred_at=now),
    )
    await s.flush()

    # بارگذاری دوباره از همان اسپردشیت‌ها
    s2 = Store(central, client=client, folder_id="f")
    await s2.load()
    assert s2.list("transactions") == []      # هنوز دفترِ کاربر خوانده نشده
    await s2.load_user(1)
    rows = s2.list("transactions")
    assert len(rows) == 1
    assert rows[0].amount == 1_000_000
    assert rows[0].kind == Kind.INCOME
    assert rows[0].occurred_at.isoformat() == now.isoformat()


async def test_central_spreadsheet_holds_only_registry_tabs():
    """اسپردشیت مرکزی نباید تبِ دفترِ کسب‌وکار داشته باشد."""
    from hesabyar.db.models import CENTRAL_TABLES, USER_TABLES

    central = FakeSpreadsheet()
    s = Store(central, client=FakeClient(), folder_id="f")
    await s.load()
    titles = {ws.title for ws in central.worksheets()}
    assert titles == set(CENTRAL_TABLES)
    assert not (titles & USER_TABLES)


async def test_each_user_gets_own_sheet_and_data_is_isolated():
    """دو کاربر: شیت جدا، و تراکنشِ یکی در شیتِ دیگری دیده نمی‌شود."""
    central, client = FakeSpreadsheet(), FakeClient()
    s = Store(central, client=client, folder_id="folder-x")
    await s.load()
    now = jalali.now()

    for uid, name in ((1, "الف"), (2, "ب")):
        await s.add("users", User(id=uid, business_name=name))
        await s.ensure_user_spreadsheet(uid)

    sheet1 = s.get("users", 1).sheet_id
    sheet2 = s.get("users", 2).sheet_id
    assert sheet1 and sheet2 and sheet1 != sheet2
    # داخلِ پوشه‌ی خواسته‌شده ساخته شده‌اند
    assert all(folder == "folder-x" for _title, folder in client.created)

    await s.add("transactions", Transaction(
        user_id=1, kind=Kind.INCOME, amount=111, occurred_at=now))
    await s.add("transactions", Transaction(
        user_id=2, kind=Kind.INCOME, amount=222, occurred_at=now))
    await s.flush()

    # هر شیت فقط ردیفِ خودش را دارد
    rows1 = client.sheets[sheet1].worksheet("transactions").get_all_records()
    rows2 = client.sheets[sheet2].worksheet("transactions").get_all_records()
    assert [int(r["amount"]) for r in rows1] == [111]
    assert [int(r["amount"]) for r in rows2] == [222]

    # با بارگذاریِ فقط کاربر ۱، داده‌ی کاربر ۲ اصلاً در حافظه نمی‌آید
    s2 = Store(central, client=client, folder_id="folder-x")
    await s2.load()
    await s2.load_user(1)
    amounts = [t.amount for t in s2.list("transactions")]
    assert amounts == [111]


async def test_ids_do_not_collide_across_users():
    """شمارنده‌ی مرکزی باید شناسه‌های یکتا بدهد تا داده روی هم نیفتد."""
    central, client = FakeSpreadsheet(), FakeClient()
    s = Store(central, client=client, folder_id="f")
    await s.load()
    now = jalali.now()
    for uid in (1, 2):
        await s.add("users", User(id=uid))
        await s.ensure_user_spreadsheet(uid)
    a = await s.add("transactions", Transaction(user_id=1, amount=1, occurred_at=now))
    b = await s.add("transactions", Transaction(user_id=2, amount=2, occurred_at=now))
    assert a.id != b.id
    await s.flush()

    # شمارنده در اسپردشیت مرکزی ذخیره شده و پس از reload ادامه پیدا می‌کند
    s2 = Store(central, client=client, folder_id="f")
    await s2.load()
    assert s2.next_id("transactions") > b.id


async def test_ensure_user_spreadsheet_is_idempotent():
    central, client = FakeSpreadsheet(), FakeClient()
    s = Store(central, client=client, folder_id="f")
    await s.load()
    await s.add("users", User(id=7, business_name="مغازه"))
    first = await s.ensure_user_spreadsheet(7)
    second = await s.ensure_user_spreadsheet(7)
    assert first == second
    assert len(client.created) == 1
