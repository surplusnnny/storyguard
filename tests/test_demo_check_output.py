import io

from tools import demo_check


def test_cp949_console_does_not_crash_on_check_mark():
    """cp949 출력(파이프, 옛 콘솔)에서 ✓가 UnicodeEncodeError를 내지 않아야 한다."""
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp949")
    demo_check.make_output_safe(stream)
    print("  ✓ 한글도 그대로", file=stream)
    stream.flush()
    text = raw.getvalue().decode("cp949")
    assert "한글도 그대로" in text
