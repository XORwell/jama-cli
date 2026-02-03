"""Data migration commands for export, import, and cloning."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn, TimeElapsedColumn
from rich.table import Table

from jama_cli.config import get_profile, get_profile_or_env, load_config
from jama_cli.core.client import JamaClient
from jama_cli.models import JamaProfile
from jama_cli.output import console, print_error, print_success, print_warning

app = typer.Typer(
    name="migrate",
    help="Export, import, and migrate Jama data between projects and instances",
)


# =============================================================================
# Data Models for Export/Import
# =============================================================================


class ExportMetadata:
    """Metadata for an export file."""

    def __init__(
        self,
        source_url: str,
        source_project: int,
        export_date: str,
        version: str = "1.1",
        item_count: int = 0,
        relationship_count: int = 0,
        attachment_count: int = 0,
    ) -> None:
        self.source_url = source_url
        self.source_project = source_project
        self.export_date = export_date
        self.version = version
        self.item_count = item_count
        self.relationship_count = relationship_count
        self.attachment_count = attachment_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_url": self.source_url,
            "source_project": self.source_project,
            "export_date": self.export_date,
            "item_count": self.item_count,
            "relationship_count": self.relationship_count,
            "attachment_count": self.attachment_count,
        }


class ExportData:
    """Complete export data structure."""

    def __init__(self, metadata: ExportMetadata) -> None:
        self.metadata = metadata
        self.item_types: list[dict[str, Any]] = []
        self.items: list[dict[str, Any]] = []
        self.relationships: list[dict[str, Any]] = []
        self.hierarchy: dict[int, list[int]] = {}  # parent_id -> [child_ids]
        self.attachments: dict[int, list[dict[str, Any]]] = {}  # item_id -> [attachment_info]

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "item_types": self.item_types,
            "items": self.items,
            "relationships": self.relationships,
            "hierarchy": {str(k): v for k, v in self.hierarchy.items()},
            "attachments": {str(k): v for k, v in self.attachments.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExportData":
        """Load export data from dictionary."""
        metadata = ExportMetadata(
            source_url=data["metadata"]["source_url"],
            source_project=data["metadata"]["source_project"],
            export_date=data["metadata"]["export_date"],
            version=data["metadata"].get("version", "1.0"),
            item_count=data["metadata"].get("item_count", 0),
            relationship_count=data["metadata"].get("relationship_count", 0),
            attachment_count=data["metadata"].get("attachment_count", 0),
        )
        export_data = cls(metadata)
        export_data.item_types = data.get("item_types", [])
        export_data.items = data.get("items", [])
        export_data.relationships = data.get("relationships", [])
        export_data.hierarchy = {int(k): v for k, v in data.get("hierarchy", {}).items()}
        export_data.attachments = {int(k): v for k, v in data.get("attachments", {}).items()}
        return export_data


# =============================================================================
# Export Command
# =============================================================================


@app.command("export")
def export_items(
    ctx: typer.Context,
    project_id: Annotated[int, typer.Argument(help="Project ID to export from")],
    output_file: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output file path (default: export_<project>_<date>.json)"),
    ] = None,
    item_type: Annotated[
        int | None,
        typer.Option("--type", "-t", help="Export only items of this type"),
    ] = None,
    parent_id: Annotated[
        int | None,
        typer.Option("--parent", "-p", help="Export only children of this item (recursive)"),
    ] = None,
    include_relationships: Annotated[
        bool,
        typer.Option("--relationships/--no-relationships", "-r", help="Include relationships (slower)"),
    ] = False,
    include_attachments: Annotated[
        bool,
        typer.Option("--attachments", "-a", help="Include attachment metadata (slower)"),
    ] = False,
    max_items: Annotated[
        int | None,
        typer.Option("--max", "-m", help="Maximum number of items to export"),
    ] = None,
) -> None:
    """Export items from a project to a JSON file.
    
    By default exports items only (fast). Use --relationships for full export (slower).

    Examples:
        jama migrate export 123                           # Fast: items only
        jama migrate export 123 --relationships           # Full: with relationships (slower)
        jama migrate export 123 --max 100                 # Export first 100 items
        jama migrate export 123 --type 45                 # Export only items of type 45
        jama migrate export 123 --parent 456              # Export children of item 456
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        # Generate output filename if not specified
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = Path(f"export_project{project_id}_{timestamp}.json")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # Create metadata
            metadata = ExportMetadata(
                source_url=profile.url,
                source_project=project_id,
                export_date=datetime.now().isoformat(),
            )
            export_data = ExportData(metadata)

            # Export item types (for reference during import)
            task = progress.add_task("Exporting item types...", total=None)
            export_data.item_types = client.get_item_types()
            progress.update(task, completed=True)

            # Get items
            task = progress.add_task("Fetching items...", total=None)
            if parent_id:
                # Export children of specific item recursively
                items = _get_items_recursive(client, parent_id, progress, max_items=max_items)
            else:
                # Use max_results for server-side limiting when possible
                items = client.get_items(project_id, item_type=item_type, max_results=max_items)
            progress.update(task, completed=True)
            
            console.print(f"[dim]Found {len(items)} items[/dim]")

            # Build hierarchy map
            task = progress.add_task("Building hierarchy...", total=None)
            for item in items:
                item_id = item.get("id")
                location = item.get("location", {})
                parent = location.get("parent", {})
                parent_item = parent.get("item")

                if parent_item:
                    if parent_item not in export_data.hierarchy:
                        export_data.hierarchy[parent_item] = []
                    export_data.hierarchy[parent_item].append(item_id)
            progress.update(task, completed=True)

            export_data.items = items
            export_data.metadata.item_count = len(items)

            # Export attachment metadata if requested
            if include_attachments:
                task = progress.add_task("Collecting attachment info...", total=None)
                attachment_count = 0
                for item in items:
                    item_id = item.get("id")
                    # Check if item has attachments field
                    attachments = item.get("attachments", [])
                    if attachments:
                        export_data.attachments[item_id] = []
                        for att in attachments:
                            # Get attachment details if we have an ID
                            att_id = att.get("id") if isinstance(att, dict) else att
                            if att_id:
                                try:
                                    att_details = client.get_attachment(att_id)
                                    export_data.attachments[item_id].append(att_details)
                                    attachment_count += 1
                                except Exception:
                                    # If we can't get details, store the reference
                                    export_data.attachments[item_id].append({"id": att_id})
                                    attachment_count += 1
                export_data.metadata.attachment_count = attachment_count
                progress.update(task, completed=True)

            # Export relationships if requested
            if include_relationships:
                console.print(f"[dim]Fetching relationships for {len(items)} items (this may take a while)...[/dim]")
                task = progress.add_task("Exporting relationships...", total=len(items))
                try:
                    # Get relationships for each item (more reliable than project-level)
                    item_ids = {item["id"] for item in items}
                    all_relationships: dict[int, dict[str, Any]] = {}

                    for i, item in enumerate(items):
                        item_id = item.get("id")
                        if item_id:
                            try:
                                # Get downstream relationships for this item
                                rels = client.get_item_downstream_relationships(item_id)
                                for rel in rels:
                                    rel_id = rel.get("id")
                                    if rel_id and rel_id not in all_relationships:
                                        # Only include if both ends are in our export
                                        from_item = rel.get("fromItem")
                                        to_item = rel.get("toItem")
                                        if from_item in item_ids and to_item in item_ids:
                                            all_relationships[rel_id] = rel
                            except Exception:
                                pass  # Skip items we can't get relationships for
                        progress.advance(task)

                    export_data.relationships = list(all_relationships.values())
                    export_data.metadata.relationship_count = len(export_data.relationships)
                except Exception as e:
                    print_warning(f"Could not export relationships: {e}")
                    export_data.relationships = []
                    export_data.metadata.relationship_count = 0

            # Write to file
            task = progress.add_task(f"Writing to {output_file}...", total=None)
            with open(output_file, "w") as f:
                json.dump(export_data.to_dict(), f, indent=2)
            progress.update(task, completed=True)

        # Summary
        print_success(f"Export completed: {output_file}")
        console.print(f"  Items: {export_data.metadata.item_count}")
        console.print(f"  Relationships: {export_data.metadata.relationship_count}")
        console.print(f"  Attachments: {export_data.metadata.attachment_count}")
        console.print(f"  Item Types: {len(export_data.item_types)}")

    except Exception as e:
        print_error(f"Export failed: {e}")
        raise typer.Exit(1) from e


def _get_items_recursive(
    client: JamaClient,
    parent_id: int,
    progress: Progress,
    depth: int = 0,
    max_items: int | None = None,
    collected: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Recursively get all children of an item."""
    if collected is None:
        collected = []
    
    # Check max limit
    if max_items and len(collected) >= max_items:
        return collected

    if depth == 0:
        # Include the parent item itself
        parent = client.get_item(parent_id)
        collected.append(parent)
        progress.console.print(f"[dim]Fetching children of {parent.get('documentKey', parent_id)}...[/dim]")

    children = client.get_item_children(parent_id)
    
    for child in children:
        if max_items and len(collected) >= max_items:
            break
        collected.append(child)
        
        child_id = child.get("id")
        if child_id:
            _get_items_recursive(client, child_id, progress, depth + 1, max_items, collected)

    return collected


# =============================================================================
# Import Command
# =============================================================================


@app.command("import")
def import_items(
    ctx: typer.Context,
    input_file: Annotated[Path, typer.Argument(help="JSON file to import from")],
    target_project: Annotated[int, typer.Option("--project", "-p", help="Target project ID")],
    target_parent: Annotated[
        int | None,
        typer.Option("--parent", help="Parent item ID for imported items"),
    ] = None,
    type_mapping: Annotated[
        str | None,
        typer.Option("--type-map", help="Item type mapping as JSON (e.g., '{\"45\": 67}')"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Preview import without making changes"),
    ] = False,
    skip_relationships: Annotated[
        bool,
        typer.Option("--skip-relationships", help="Don't import relationships"),
    ] = False,
) -> None:
    """Import items from a JSON export file.

    Examples:
        jama migrate import backup.json --project 456           # Import to project 456
        jama migrate import backup.json -p 456 --parent 789     # Import under item 789
        jama migrate import backup.json -p 456 --dry-run        # Preview without importing
        jama migrate import backup.json -p 456 --type-map '{"45": 67}'  # Map item types
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    if not input_file.exists():
        print_error(f"File not found: {input_file}")
        raise typer.Exit(1)

    try:
        # Load export data
        with open(input_file) as f:
            data = json.load(f)
        export_data = ExportData.from_dict(data)

        console.print(f"\n[bold]Import Preview[/bold]")
        console.print(f"  Source: {export_data.metadata.source_url}")
        console.print(f"  Source Project: {export_data.metadata.source_project}")
        console.print(f"  Export Date: {export_data.metadata.export_date}")
        console.print(f"  Items: {export_data.metadata.item_count}")
        console.print(f"  Relationships: {export_data.metadata.relationship_count}")

        # Parse type mapping
        type_map: dict[int, int] = {}
        if type_mapping:
            try:
                raw_map = json.loads(type_mapping)
                type_map = {int(k): int(v) for k, v in raw_map.items()}
            except (json.JSONDecodeError, ValueError) as e:
                print_error(f"Invalid type mapping: {e}")
                raise typer.Exit(1) from e

        if dry_run:
            console.print("\n[yellow]DRY RUN - No changes will be made[/yellow]\n")
            _preview_import(export_data, target_project, type_map)
            return

        # Confirm import
        if not typer.confirm(f"\nImport {export_data.metadata.item_count} items to project {target_project}?"):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

        client = JamaClient(profile)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # Import items maintaining hierarchy
            task = progress.add_task("Importing items...", total=len(export_data.items))

            # Map old IDs to new IDs
            id_mapping: dict[int, int] = {}

            # Sort items by hierarchy level (parents first)
            sorted_items = _sort_by_hierarchy(export_data.items, export_data.hierarchy)

            for item in sorted_items:
                old_id = item["id"]
                old_type = item.get("itemType")
                fields = _filter_writable_fields(item.get("fields", {}))

                # Map item type if needed
                new_type = type_map.get(old_type, old_type) if old_type else old_type

                # Determine parent (location format: {"item": parent_id})
                location: dict[str, Any] = {}
                old_parent = item.get("location", {}).get("parent", {}).get("item")

                if old_parent and old_parent in id_mapping:
                    # Use mapped parent
                    location["item"] = id_mapping[old_parent]
                elif target_parent:
                    # Use specified target parent
                    location["item"] = target_parent

                # Create item
                try:
                    new_id = client.create_item(
                        project_id=target_project,
                        item_type_id=new_type,
                        child_item_type_id=new_type,
                        location=location,
                        fields=fields,
                    )
                    id_mapping[old_id] = new_id
                except Exception as e:
                    print_warning(f"Failed to import item {old_id}: {e}")

                progress.advance(task)

            # Import relationships
            if not skip_relationships and export_data.relationships:
                task = progress.add_task(
                    "Importing relationships...",
                    total=len(export_data.relationships),
                )

                rel_count = 0
                for rel in export_data.relationships:
                    old_from = rel.get("fromItem")
                    old_to = rel.get("toItem")
                    rel_type = rel.get("relationshipType")

                    if old_from in id_mapping and old_to in id_mapping:
                        try:
                            client.create_relationship(
                                from_item=id_mapping[old_from],
                                to_item=id_mapping[old_to],
                                relationship_type=rel_type,
                            )
                            rel_count += 1
                        except Exception as e:
                            print_warning(f"Failed to create relationship: {e}")

                    progress.advance(task)

        # Summary
        print_success("Import completed!")
        console.print(f"  Items created: {len(id_mapping)}")
        if not skip_relationships:
            console.print(f"  Relationships created: {rel_count}")

    except Exception as e:
        print_error(f"Import failed: {e}")
        raise typer.Exit(1) from e


# Read-only fields that cannot be set when creating items
READ_ONLY_FIELDS = {
    "documentKey",
    "globalId",
    "createdDate",
    "modifiedDate",
    "createdBy",
    "modifiedBy",
    "lastActivityDate",
    # Test case specific read-only fields
    "testCaseStatus",
    "testRunResults",
}


def _filter_writable_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Filter out read-only fields that cannot be set when creating items."""
    return {k: v for k, v in fields.items() if k not in READ_ONLY_FIELDS}


def _sort_by_hierarchy(
    items: list[dict[str, Any]],
    hierarchy: dict[int, list[int]],
) -> list[dict[str, Any]]:
    """Sort items so parents come before children."""
    # Build reverse lookup (child -> parent)
    child_to_parent: dict[int, int] = {}
    for parent_id, children in hierarchy.items():
        for child_id in children:
            child_to_parent[child_id] = parent_id

    # Calculate depth for each item
    def get_depth(item_id: int, depth: int = 0) -> int:
        if item_id in child_to_parent:
            return get_depth(child_to_parent[item_id], depth + 1)
        return depth

    # Sort by depth (parents first)
    items_with_depth = [(item, get_depth(item["id"])) for item in items]
    items_with_depth.sort(key=lambda x: x[1])

    return [item for item, _ in items_with_depth]


def _preview_import(
    export_data: ExportData,
    target_project: int,
    type_map: dict[int, int],
) -> None:
    """Preview what would be imported."""
    # Count items by type
    type_counts: dict[int, int] = {}
    for item in export_data.items:
        item_type = item.get("itemType", 0)
        type_counts[item_type] = type_counts.get(item_type, 0) + 1

    # Create preview table
    table = Table(title="Items to Import")
    table.add_column("Item Type ID")
    table.add_column("Count")
    table.add_column("Maps To")

    for type_id, count in sorted(type_counts.items()):
        mapped = type_map.get(type_id, type_id)
        mapping_str = str(mapped) if mapped != type_id else "[dim]same[/dim]"
        table.add_row(str(type_id), str(count), mapping_str)

    console.print(table)

    if type_map:
        console.print(f"\n[dim]Type mapping: {type_map}[/dim]")


# =============================================================================
# Clone Command (same instance)
# =============================================================================


@app.command("clone")
def clone_items(
    ctx: typer.Context,
    source_project: Annotated[int, typer.Argument(help="Source project ID")],
    target_project: Annotated[int, typer.Argument(help="Target project ID")],
    source_parent: Annotated[
        int | None,
        typer.Option("--source-parent", "-s", help="Clone children of this item"),
    ] = None,
    target_parent: Annotated[
        int | None,
        typer.Option("--target-parent", "-t", help="Clone under this item"),
    ] = None,
    item_type: Annotated[
        int | None,
        typer.Option("--type", help="Clone only items of this type"),
    ] = None,
    include_relationships: Annotated[
        bool,
        typer.Option("--relationships", "-r", help="Clone relationships too"),
    ] = True,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Preview without cloning"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
    auto_container: Annotated[
        bool,
        typer.Option("--auto-container", "-a", help="Auto-create container hierarchy (Component/Set) if needed"),
    ] = False,
    container_name: Annotated[
        str | None,
        typer.Option("--container-name", help="Name for auto-created container (default: source item name)"),
    ] = None,
) -> None:
    """Clone items within the same Jama instance.

    Examples:
        jama migrate clone 123 456                        # Clone project 123 to 456
        jama migrate clone 123 456 --source-parent 789    # Clone children of item 789
        jama migrate clone 123 456 --type 45              # Clone only items of type 45
        jama migrate clone 123 456 --dry-run              # Preview the clone
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    if source_project == target_project and not target_parent:
        print_error("Cannot clone to same project without specifying --target-parent")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # Get source items
            task = progress.add_task("Fetching source items...", total=None)
            if source_parent:
                items = _get_items_recursive(client, source_parent, progress)
            else:
                items = client.get_items(source_project, item_type=item_type)
            progress.update(task, completed=True)

            # Get relationships if needed
            relationships: list[dict[str, Any]] = []
            if include_relationships:
                task = progress.add_task("Fetching relationships...", total=None)
                try:
                    item_ids = {item["id"] for item in items}
                    all_rels: dict[int, dict[str, Any]] = {}
                    for item in items:
                        item_id = item.get("id")
                        if item_id:
                            try:
                                rels = client.get_item_downstream_relationships(item_id)
                                for rel in rels:
                                    rel_id = rel.get("id")
                                    if rel_id and rel_id not in all_rels:
                                        from_item = rel.get("fromItem")
                                        to_item = rel.get("toItem")
                                        if from_item in item_ids and to_item in item_ids:
                                            all_rels[rel_id] = rel
                            except Exception:
                                pass
                    relationships = list(all_rels.values())
                except Exception as e:
                    print_warning(f"Could not fetch relationships: {e}")
                progress.update(task, completed=True)

        # Preview
        console.print(f"\n[bold]Clone Preview[/bold]")
        console.print(f"  Source Project: {source_project}")
        console.print(f"  Target Project: {target_project}")
        console.print(f"  Items to clone: {len(items)}")
        console.print(f"  Relationships: {len(relationships)}")

        if dry_run:
            console.print("\n[yellow]DRY RUN - No changes will be made[/yellow]")

            # Show item type breakdown
            type_counts: dict[int, int] = {}
            for item in items:
                item_type_id = item.get("itemType", 0)
                type_counts[item_type_id] = type_counts.get(item_type_id, 0) + 1

            table = Table(title="Items by Type")
            table.add_column("Type ID")
            table.add_column("Count")
            for type_id, count in sorted(type_counts.items()):
                table.add_row(str(type_id), str(count))
            console.print(table)
            return

        # Confirm
        if not yes and not typer.confirm(f"\nClone {len(items)} items to project {target_project}?"):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

        # Build hierarchy
        hierarchy: dict[int, list[int]] = {}
        for item in items:
            item_id = item.get("id")
            parent = item.get("location", {}).get("parent", {}).get("item")
            if parent:
                if parent not in hierarchy:
                    hierarchy[parent] = []
                hierarchy[parent].append(item_id)

        # Jama standard item type constants
        COMPONENT_TYPE = 30
        SET_TYPE = 31
        FOLDER_TYPE = 32
        
        import re  # For setKey generation
        
        # Auto-create container if needed
        container_parent_id: int | None = target_parent
        skip_source_ids: set[int] = set()  # Items to skip (like source Set when we create a new one)
        id_mapping: dict[int, int] = {}  # Pre-populate with mappings for skipped items
        
        if auto_container and not dry_run:
            # Find the root item(s) to determine what container we need
            root_items = [i for i in items if i.get("location", {}).get("parent", {}).get("item") == source_parent or 
                         i.get("location", {}).get("parent", {}).get("item") is None]
            
            if root_items:
                first_root = root_items[0]
                first_type = first_root.get("itemType")
                first_root_id = first_root.get("id")
                
                # Determine container name
                auto_name = container_name or first_root.get("fields", {}).get("name", "Cloned Items")
                
                # If first item is a Set, create Component + Set and map the source Set to the new Set
                if first_type == SET_TYPE:
                    console.print(f"\n[cyan]Auto-creating Component + Set container: {auto_name}[/cyan]")
                    try:
                        # Create Component
                        component_id = client.create_item(
                            project_id=target_project,
                            item_type_id=COMPONENT_TYPE,
                            child_item_type_id=COMPONENT_TYPE,
                            location={},  # Project root
                            fields={"name": auto_name},
                        )
                        console.print(f"  Created Component with ID: {component_id}")
                        
                        # Get setKey from source or generate
                        source_set_key = first_root.get("fields", {}).get("setKey", "")
                        set_key = source_set_key or re.sub(r'[^A-Z0-9]', '', auto_name.upper())[:10] or "CLONED"
                        
                        # Create Set under Component (use source Set's child type)
                        source_child_type = first_root.get("childItemType", SET_TYPE)
                        set_id = client.create_item(
                            project_id=target_project,
                            item_type_id=SET_TYPE,
                            child_item_type_id=source_child_type,
                            location={"item": component_id},
                            fields={"name": first_root.get("fields", {}).get("name", auto_name), "setKey": set_key},
                        )
                        console.print(f"  Created Set with ID: {set_id} (setKey: {set_key})")
                        
                        # Map the source Set ID to the new Set ID, so children will be placed under it
                        id_mapping[first_root_id] = set_id
                        skip_source_ids.add(first_root_id)  # Don't try to clone the source Set itself
                        
                        container_parent_id = set_id
                    except Exception as e:
                        print_error(f"Failed to create container hierarchy: {e}")
                        raise typer.Exit(1) from e
                
                # If first item is a Folder, we need Component + Set
                elif first_type == FOLDER_TYPE:
                    console.print(f"\n[cyan]Auto-creating Component + Set container: {auto_name}[/cyan]")
                    try:
                        component_id = client.create_item(
                            project_id=target_project,
                            item_type_id=COMPONENT_TYPE,
                            child_item_type_id=COMPONENT_TYPE,
                            location={},
                            fields={"name": auto_name},
                        )
                        console.print(f"  Created Component with ID: {component_id}")
                        
                        set_key = re.sub(r'[^A-Z0-9]', '', auto_name.upper())[:10] or "CLONED"
                        
                        set_id = client.create_item(
                            project_id=target_project,
                            item_type_id=SET_TYPE,
                            child_item_type_id=SET_TYPE,
                            location={"item": component_id},
                            fields={"name": f"{auto_name} - Set", "setKey": set_key},
                        )
                        container_parent_id = set_id
                        console.print(f"  Created Set with ID: {set_id}")
                    except Exception as e:
                        print_error(f"Failed to create container hierarchy: {e}")
                        raise typer.Exit(1) from e
                
                # If first item is a TestCase (88), we need Component + Set
                elif first_type not in (COMPONENT_TYPE, SET_TYPE, FOLDER_TYPE):
                    console.print(f"\n[cyan]Auto-creating Component + Set container for test cases: {auto_name}[/cyan]")
                    try:
                        component_id = client.create_item(
                            project_id=target_project,
                            item_type_id=COMPONENT_TYPE,
                            child_item_type_id=COMPONENT_TYPE,
                            location={},
                            fields={"name": auto_name},
                        )
                        console.print(f"  Created Component with ID: {component_id}")
                        
                        set_key = re.sub(r'[^A-Z0-9]', '', auto_name.upper())[:10] or "CLONED"
                        
                        set_id = client.create_item(
                            project_id=target_project,
                            item_type_id=SET_TYPE,
                            child_item_type_id=SET_TYPE,
                            location={"item": component_id},
                            fields={"name": f"{auto_name} - Set", "setKey": set_key},
                        )
                        container_parent_id = set_id
                        console.print(f"  Created Set with ID: {set_id}")
                    except Exception as e:
                        print_error(f"Failed to create container hierarchy: {e}")
                        raise typer.Exit(1) from e

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            # Clone items (skip items already mapped via auto-container)
            items_to_clone = [i for i in items if i.get("id") not in skip_source_ids]
            task = progress.add_task("Cloning items...", total=len(items_to_clone))

            sorted_items = _sort_by_hierarchy(items_to_clone, hierarchy)

            for item in sorted_items:
                old_id = item["id"]
                item_type_id = item.get("itemType")
                fields = _filter_writable_fields(item.get("fields", {}))

                # Determine parent in target
                location: dict[str, Any] = {}
                old_parent = item.get("location", {}).get("parent", {}).get("item")

                if old_parent and old_parent in id_mapping:
                    location["item"] = id_mapping[old_parent]
                elif container_parent_id:
                    location["item"] = container_parent_id

                try:
                    new_id = client.create_item(
                        project_id=target_project,
                        item_type_id=item_type_id,
                        child_item_type_id=item_type_id,
                        location=location,
                        fields=fields,
                    )
                    id_mapping[old_id] = new_id
                except Exception as e:
                    print_warning(f"Failed to clone item {old_id}: {e}")

                progress.advance(task)

            # Clone relationships
            rel_count = 0
            if include_relationships and relationships:
                task = progress.add_task("Cloning relationships...", total=len(relationships))

                for rel in relationships:
                    old_from = rel.get("fromItem")
                    old_to = rel.get("toItem")
                    rel_type = rel.get("relationshipType")

                    if old_from in id_mapping and old_to in id_mapping:
                        try:
                            client.create_relationship(
                                from_item=id_mapping[old_from],
                                to_item=id_mapping[old_to],
                                relationship_type=rel_type,
                            )
                            rel_count += 1
                        except Exception as e:
                            print_warning(f"Failed to clone relationship: {e}")

                    progress.advance(task)

        print_success("Clone completed!")
        console.print(f"  Items cloned: {len(id_mapping)}")
        console.print(f"  Relationships cloned: {rel_count}")

    except Exception as e:
        print_error(f"Clone failed: {e}")
        raise typer.Exit(1) from e


# =============================================================================
# Migrate Command (between instances)
# =============================================================================


@app.command("copy")
def copy_between_instances(
    ctx: typer.Context,
    source_project: Annotated[int, typer.Argument(help="Source project ID")],
    target_project: Annotated[int, typer.Argument(help="Target project ID")],
    source_profile: Annotated[str, typer.Option("--from", "-f", help="Source profile name")],
    target_profile: Annotated[str, typer.Option("--to", "-t", help="Target profile name")],
    source_parent: Annotated[
        int | None,
        typer.Option("--source-parent", "-s", help="Copy children of this item"),
    ] = None,
    target_parent: Annotated[
        int | None,
        typer.Option("--target-parent", help="Copy under this item in target"),
    ] = None,
    type_mapping: Annotated[
        str | None,
        typer.Option("--type-map", help="Item type mapping as JSON"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Preview without copying"),
    ] = False,
) -> None:
    """Copy items between different Jama instances.

    Requires two profiles configured for source and target instances.

    Examples:
        jama migrate copy 123 456 --from staging --to production
        jama migrate copy 123 456 -f dev -t prod --source-parent 789
        jama migrate copy 123 456 -f source -t target --type-map '{"45": 67}'
    """
    config = load_config()

    source = config.profiles.get(source_profile)
    target = config.profiles.get(target_profile)

    if not source:
        print_error(f"Source profile '{source_profile}' not found")
        raise typer.Exit(1)

    if not target:
        print_error(f"Target profile '{target_profile}' not found")
        raise typer.Exit(1)

    # Parse type mapping
    type_map: dict[int, int] = {}
    if type_mapping:
        try:
            raw_map = json.loads(type_mapping)
            type_map = {int(k): int(v) for k, v in raw_map.items()}
        except (json.JSONDecodeError, ValueError) as e:
            print_error(f"Invalid type mapping: {e}")
            raise typer.Exit(1) from e

    try:
        source_client = JamaClient(source)
        target_client = JamaClient(target)

        console.print(f"\n[bold]Cross-Instance Copy[/bold]")
        console.print(f"  From: {source.url} (profile: {source_profile})")
        console.print(f"  To: {target.url} (profile: {target_profile})")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # Get source items
            task = progress.add_task("Fetching source items...", total=None)
            if source_parent:
                items = _get_items_recursive(source_client, source_parent, progress)
            else:
                items = source_client.get_items(source_project)
            progress.update(task, completed=True)

        console.print(f"  Items to copy: {len(items)}")

        if dry_run:
            console.print("\n[yellow]DRY RUN - No changes will be made[/yellow]")

            # Show type breakdown
            type_counts: dict[int, int] = {}
            for item in items:
                item_type_id = item.get("itemType", 0)
                type_counts[item_type_id] = type_counts.get(item_type_id, 0) + 1

            table = Table(title="Items by Type")
            table.add_column("Source Type")
            table.add_column("Count")
            table.add_column("Target Type")
            for type_id, count in sorted(type_counts.items()):
                mapped = type_map.get(type_id, type_id)
                table.add_row(
                    str(type_id),
                    str(count),
                    str(mapped) if mapped != type_id else "[dim]same[/dim]",
                )
            console.print(table)

            if not type_map:
                print_warning(
                    "No type mapping specified. "
                    "Use --type-map if item types differ between instances."
                )
            return

        # Confirm
        if not typer.confirm(f"\nCopy {len(items)} items to {target.url}?"):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

        # Build hierarchy
        hierarchy: dict[int, list[int]] = {}
        for item in items:
            item_id = item.get("id")
            parent = item.get("location", {}).get("parent", {}).get("item")
            if parent:
                if parent not in hierarchy:
                    hierarchy[parent] = []
                hierarchy[parent].append(item_id)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Copying items...", total=len(items))
            id_mapping: dict[int, int] = {}

            sorted_items = _sort_by_hierarchy(items, hierarchy)

            for item in sorted_items:
                old_id = item["id"]
                old_type = item.get("itemType")
                fields = _filter_writable_fields(item.get("fields", {}))

                # Map item type
                new_type = type_map.get(old_type, old_type) if old_type else old_type

                # Determine parent (location format: {"item": parent_id})
                location: dict[str, Any] = {}
                old_parent = item.get("location", {}).get("parent", {}).get("item")

                if old_parent and old_parent in id_mapping:
                    location["item"] = id_mapping[old_parent]
                elif target_parent:
                    location["item"] = target_parent

                try:
                    new_id = target_client.create_item(
                        project_id=target_project,
                        item_type_id=new_type,
                        child_item_type_id=new_type,
                        location=location,
                        fields=fields,
                    )
                    id_mapping[old_id] = new_id
                except Exception as e:
                    print_warning(f"Failed to copy item {old_id}: {e}")

                progress.advance(task)

        print_success("Copy completed!")
        console.print(f"  Items copied: {len(id_mapping)}")

    except Exception as e:
        print_error(f"Copy failed: {e}")
        raise typer.Exit(1) from e


# =============================================================================
# Info Command
# =============================================================================


@app.command("info")
def show_export_info(
    input_file: Annotated[Path, typer.Argument(help="Export file to inspect")],
) -> None:
    """Show information about an export file.

    Example:
        jama migrate info backup.json
    """
    if not input_file.exists():
        print_error(f"File not found: {input_file}")
        raise typer.Exit(1)

    try:
        with open(input_file) as f:
            data = json.load(f)

        export_data = ExportData.from_dict(data)

        console.print(f"\n[bold]Export File Information[/bold]")
        console.print(f"  File: {input_file}")
        console.print(f"  Version: {export_data.metadata.version}")
        console.print(f"  Source URL: {export_data.metadata.source_url}")
        console.print(f"  Source Project: {export_data.metadata.source_project}")
        console.print(f"  Export Date: {export_data.metadata.export_date}")
        console.print(f"  Items: {export_data.metadata.item_count}")
        console.print(f"  Relationships: {export_data.metadata.relationship_count}")
        console.print(f"  Attachments: {export_data.metadata.attachment_count}")
        console.print(f"  Item Types: {len(export_data.item_types)}")

        # Item type breakdown
        if export_data.items:
            type_counts: dict[int, int] = {}
            for item in export_data.items:
                item_type = item.get("itemType", 0)
                type_counts[item_type] = type_counts.get(item_type, 0) + 1

            console.print("\n[bold]Items by Type:[/bold]")
            table = Table()
            table.add_column("Type ID")
            table.add_column("Count")

            for type_id, count in sorted(type_counts.items()):
                table.add_row(str(type_id), str(count))

            console.print(table)

    except Exception as e:
        print_error(f"Failed to read export file: {e}")
        raise typer.Exit(1) from e
