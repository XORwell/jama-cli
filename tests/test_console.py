"""Unit tests for console output utilities."""

from unittest.mock import patch

from jama_cli.output.console import (
    confirm,
    console,
    error_console,
    is_interactive,
    print_error,
    print_info,
    print_success,
    print_warning,
)

# Patch targets: patch where the objects are used, not where they're defined.
# We use the module's __name__ to avoid name shadowing between
# jama_cli.output.console (module) and jama_cli.output.console (Console object).
_MODULE = "jama_cli.output.console"


class TestConsoleInstances:
    """Tests for console instances."""

    def test_console_exists(self):
        """Test console instance exists."""
        assert console is not None

    def test_error_console_exists(self):
        """Test error console instance exists."""
        assert error_console is not None


class TestPrintFunctions:
    """Tests for print functions."""

    def test_print_error(self):
        """Test print_error function."""
        with patch.object(error_console, "print") as mock_print:
            print_error("Test error message")
            mock_print.assert_called()

    def test_print_error_with_details(self):
        """Test print_error with details."""
        with patch.object(error_console, "print") as mock_print:
            print_error("Test error", details="Additional details")
            assert mock_print.call_count == 2

    def test_print_success(self):
        """Test print_success function."""
        with patch.object(console, "print") as mock_print:
            print_success("Test success message")
            mock_print.assert_called()

    def test_print_warning(self):
        """Test print_warning function."""
        with patch.object(error_console, "print") as mock_print:
            print_warning("Test warning message")
            mock_print.assert_called()

    def test_print_info(self):
        """Test print_info function."""
        with patch.object(console, "print") as mock_print:
            print_info("Test info message")
            mock_print.assert_called()


class TestConfirm:
    """Tests for confirm function."""

    def test_confirm_yes(self):
        """Test confirm with yes response."""
        with patch.object(console, "input", return_value="y"):
            result = confirm("Continue?")
            assert result is True

    def test_confirm_no(self):
        """Test confirm with no response."""
        with patch.object(console, "input", return_value="n"):
            result = confirm("Continue?")
            assert result is False

    def test_confirm_default_yes(self):
        """Test confirm with default yes and empty response."""
        with patch.object(console, "input", return_value=""):
            result = confirm("Continue?", default=True)
            assert result is True

    def test_confirm_default_no(self):
        """Test confirm with default no and empty response."""
        with patch.object(console, "input", return_value=""):
            result = confirm("Continue?", default=False)
            assert result is False

    def test_confirm_yes_full(self):
        """Test confirm with 'yes' spelled out."""
        with patch.object(console, "input", return_value="yes"):
            result = confirm("Continue?")
            assert result is True


class TestIsInteractive:
    """Tests for is_interactive function."""

    @patch("sys.stdin")
    @patch("sys.stdout")
    def test_is_interactive_true(self, mock_stdout, mock_stdin):
        """Test is_interactive returns True."""
        mock_stdin.isatty.return_value = True
        mock_stdout.isatty.return_value = True
        assert is_interactive() is True

    @patch("sys.stdin")
    @patch("sys.stdout")
    def test_is_interactive_false_stdin(self, mock_stdout, mock_stdin):
        """Test is_interactive returns False when stdin not tty."""
        mock_stdin.isatty.return_value = False
        mock_stdout.isatty.return_value = True
        assert is_interactive() is False

    @patch("sys.stdin")
    @patch("sys.stdout")
    def test_is_interactive_false_stdout(self, mock_stdout, mock_stdin):
        """Test is_interactive returns False when stdout not tty."""
        mock_stdin.isatty.return_value = True
        mock_stdout.isatty.return_value = False
        assert is_interactive() is False
