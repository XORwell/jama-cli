"""stdout carries only the requested data when a machine-readable format is asked for."""

from __future__ import annotations

import csv
import io
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from jama_cli.main import app

runner = CliRunner()

ITEMS = [
    {"id": i, "documentKey": f"KEY-{i}", "itemType": 33, "fields": {"name": f"Login {i}"}}
    for i in range(1, 4)
]


def invoke(module: str, args: list[str], client: MagicMock) -> Any:
    with (
        patch(f"jama_cli.commands.{module}.JamaClient", return_value=client),
        patch(f"jama_cli.commands.{module}.get_profile_or_env", return_value=MagicMock()),
    ):
        result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


@pytest.fixture
def client() -> MagicMock:
    mock = MagicMock()
    mock.get_items.return_value = ITEMS
    mock.get_projects.return_value = [{"id": 1, "name": "Demo"}]
    return mock


class TestStdoutIsPureData:
    def test_items_list_json_with_limit_hint(self, client: MagicMock) -> None:
        # len(items) == limit triggers the "Showing first N items" hint.
        result = invoke("items", ["-o", "json", "items", "list", "1", "--limit", "3"], client)

        data = json.loads(result.stdout)
        assert [row["id"] for row in data] == [1, 2, 3]
        assert "Showing first 3 items" in result.stderr

    def test_items_list_csv_with_limit_hint(self, client: MagicMock) -> None:
        result = invoke("items", ["-o", "csv", "items", "list", "1", "--limit", "3"], client)

        rows = list(csv.reader(io.StringIO(result.stdout)))
        assert rows[0][0] == "id"
        assert len(rows) == 4
        assert "Showing" not in result.stdout

    def test_items_list_yaml_with_limit_hint(self, client: MagicMock) -> None:
        result = invoke("items", ["-o", "yaml", "items", "list", "1", "--limit", "3"], client)

        assert len(yaml.safe_load(result.stdout)) == 3

    def test_search_json_with_limit_hint(self, client: MagicMock) -> None:
        result = invoke(
            "search", ["-o", "json", "search", "items", "Login", "-p", "1", "-l", "2"], client
        )

        assert len(json.loads(result.stdout)) == 2
        assert "Showing first 2 results" in result.stderr
        assert "Searching for" in result.stderr

    def test_search_json_without_matches_is_an_empty_list(self, client: MagicMock) -> None:
        result = invoke("search", ["-o", "json", "search", "items", "nothing", "-p", "1"], client)

        assert json.loads(result.stdout) == []

    def test_empty_list_json_is_an_empty_list(self, client: MagicMock) -> None:
        client.get_items.return_value = []
        result = invoke("items", ["-o", "json", "items", "list", "1"], client)

        assert json.loads(result.stdout) == []

    def test_table_output_still_shows_the_hint(self, client: MagicMock) -> None:
        result = invoke("items", ["items", "list", "1", "--limit", "3"], client)

        assert "Showing first 3 items" in result.output


class TestItemsListOfTestTypes:
    """`GET /items?project=` never returns test plans, cycles or runs."""

    TYPES = [
        {"id": 33, "typeKey": "TXT", "display": "Text"},
        {"id": 35, "typeKey": "TSTPL", "display": "Test Plan"},
        {"id": 36, "typeKey": "TSTCY", "display": "Test Cycle"},
        {"id": 37, "typeKey": "TSTRN", "display": "Test Run"},
        {"id": 38, "typeKey": "XYZ", "category": "TEST_RUN", "display": "Renamed run type"},
    ]

    @pytest.mark.parametrize(
        ("type_id", "kind", "pointer"),
        [
            (35, "test plan", "test plans"),
            (36, "test cycle", "jama tests cycle"),
            (37, "test run", "jama tests runs"),
            (38, "test run", "jama testruns get"),
        ],
    )
    def test_fails_with_a_hint_instead_of_an_empty_list(
        self, client: MagicMock, type_id: int, kind: str, pointer: str
    ) -> None:
        client.get_item_types.return_value = self.TYPES
        client.get_items.return_value = []
        with (
            patch("jama_cli.commands.items.JamaClient", return_value=client),
            patch("jama_cli.commands.items.get_profile_or_env", return_value=MagicMock()),
        ):
            result = runner.invoke(
                app, ["-o", "json", "items", "list", "1", "--type", str(type_id)]
            )

        message = " ".join(result.output.split())
        assert result.exit_code == 1
        assert f"is the {kind} type" in message and pointer in message
        assert result.stdout == ""
        client.get_items.assert_not_called()

    def test_ordinary_type_is_listed_as_before(self, client: MagicMock) -> None:
        client.get_item_types.return_value = self.TYPES
        result = invoke("items", ["-o", "json", "items", "list", "1", "--type", "33"], client)

        assert len(json.loads(result.stdout)) == 3
        client.get_items.assert_called_once()

    def test_a_failing_type_lookup_does_not_block_the_listing(self, client: MagicMock) -> None:
        client.get_item_types.side_effect = RuntimeError("no item types")
        result = invoke("items", ["-o", "json", "items", "list", "1", "--type", "37"], client)

        assert len(json.loads(result.stdout)) == 3
