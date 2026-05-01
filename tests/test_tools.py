"""Tests for src/tools.py — core tool registry."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from tools import run_shell, dispatch_tool, fetch_news


def test_run_shell_basic():
    result = run_shell('echo jarvis_test_ok')
    assert 'jarvis_test_ok' in result, f"Expected echo output, got: {result!r}"


def test_run_shell_error_captured():
    result = run_shell('dir /nonexistent_path_xyz')
    assert isinstance(result, str) and len(result) > 0


def test_dispatch_unknown_tool():
    result = dispatch_tool('totally_unknown_tool', {})
    assert 'Unknown tool' in result


def test_dispatch_run_shell():
    result = dispatch_tool('run_shell', {'command': 'echo dispatch_ok'})
    assert 'dispatch_ok' in result


def test_dispatch_read_nonexistent_file():
    result = dispatch_tool('read_file', {'path': 'C:/nonexistent_xyz.txt'})
    assert 'error' in result.lower() or 'File read error' in result


def test_fetch_news_returns_string():
    result = fetch_news(max_items=2)
    assert isinstance(result, str) and len(result) > 0


def test_run_claude_code_non_blocking():
    """run_claude_code must return quickly — it opens a terminal, doesn't wait."""
    from tools import run_claude_code
    t0 = time.time()
    result = run_claude_code("echo hello from jarvis test", working_dir=r"C:\Users\micha\jarvis")
    elapsed = time.time() - t0
    assert elapsed < 8.0, f"run_claude_code blocked for {elapsed:.1f}s — should be instant"
    assert isinstance(result, str)
    assert len(result) > 0


def test_dispatch_get_system_info():
    result = dispatch_tool('get_system_info', {})
    assert 'CPU' in result or 'error' in result.lower()


if __name__ == '__main__':
    tests = [
        test_run_shell_basic,
        test_run_shell_error_captured,
        test_dispatch_unknown_tool,
        test_dispatch_run_shell,
        test_dispatch_read_nonexistent_file,
        test_fetch_news_returns_string,
        test_run_claude_code_non_blocking,
        test_dispatch_get_system_info,
    ]
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {e}")
    print(f"\nDone.")
