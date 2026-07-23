from hesabyar.core import money


class TestParseAmount:
    def test_digits_with_currency(self):
        assert money.parse_amount("۵۰۰ هزار تومان") == 500_000

    def test_english_digits(self):
        assert money.parse_amount("500 هزار تومان") == 500_000

    def test_thousands_separator(self):
        assert money.parse_amount("۱۲۳٬۰۰۰ تومان") == 123_000
        assert money.parse_amount("۱,۲۰۰,۰۰۰") == 1_200_000

    def test_decimal_scale(self):
        assert money.parse_amount("۲.۵ میلیون") == 2_500_000

    def test_million(self):
        assert money.parse_amount("۳ میلیون تومان") == 3_000_000

    def test_milliard(self):
        assert money.parse_amount("۱ میلیارد") == 1_000_000_000

    def test_word_number_simple(self):
        assert money.parse_amount("پانصد هزار تومان") == 500_000

    def test_word_number_compound(self):
        assert money.parse_amount("دو میلیون و سیصد هزار") == 2_300_000

    def test_word_number_with_units(self):
        assert money.parse_amount("سه هزار و پانصد تومان") == 3_500

    def test_rial_to_toman(self):
        assert money.parse_amount("۵۰۰۰ ریال") == 500

    def test_pick_currency_adjacent_over_quantity(self):
        # «۳ کیلو» نباید به‌جای مبلغ گرفته شود
        assert money.parse_amount("۳ کیلو برنج ۵۰۰ هزار تومان") == 500_000

    def test_pick_max_when_no_currency(self):
        assert money.parse_amount("۲ عدد ۸۰ هزار") == 80_000

    def test_no_number(self):
        assert money.parse_amount("سلام خوبی") is None

    def test_empty(self):
        assert money.parse_amount("") is None

    def test_bare_number(self):
        assert money.parse_amount("۴۵۰۰۰") == 45_000

    def test_ta_currency_short(self):
        assert money.parse_amount("۲۰ هزار ت") == 20_000


class TestFormatAmount:
    def test_basic(self):
        assert money.format_amount(1_200_000) == "۱٬۲۰۰٬۰۰۰ تومان"

    def test_no_currency(self):
        assert money.format_amount(50_000, with_currency=False) == "۵۰٬۰۰۰"

    def test_zero(self):
        assert money.format_amount(0) == "۰ تومان"

    def test_custom_currency(self):
        assert money.format_amount(1000, currency="ریال") == "۱٬۰۰۰ ریال"


class TestDigits:
    def test_to_english(self):
        assert money.to_english_digits("۱۲۳۴۵۶۷۸۹۰") == "1234567890"
        assert money.to_english_digits("٤٥٦") == "456"

    def test_to_persian(self):
        assert money.to_persian_digits("1402") == "۱۴۰۲"


class TestParseInt:
    def test_simple(self):
        assert money.parse_int("۳ عدد") == 3

    def test_word(self):
        assert money.parse_int("دو") == 2

    def test_none(self):
        assert money.parse_int("بدون عدد") is None
