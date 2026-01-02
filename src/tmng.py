#!/usr/bin/env python3
"""
tmng - Tool Manager
A comprehensive tool for managing scripts and binaries with rich interactive interface.
"""

import os
import sys
import argparse
import yaml
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
import subprocess
import re

# Third-party imports
try:
    from rich.console import Console
    from rich.table import Table
    from rich.tree import Tree
    from rich.panel import Panel
    from rich.box import ROUNDED, SQUARE
    from rich import print as rprint
    from rich.text import Text
    from rich.columns import Columns
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.prompt import Prompt, Confirm, IntPrompt
    from rich.syntax import Syntax
    from rich.layout import Layout
    from rich.live import Live
    from rich.align import Align
    import inquirer
    from inquirer.themes import GreenPassion
except ImportError as e:
    print(f"Error: Missing required dependency - {e}")
    print("Please install required packages:")
    print("pip install rich>=12.0.0 inquirer>=2.8.0 PyYAML>=6.0")
    sys.exit(1)

# Tool category enumeration
class Category(Enum):
    STARTUP = "startup"
    TOOL = "tool"

# Tool status enumeration
class Status(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"

@dataclass
class Tool:
    """Data class representing a managed tool."""
    name: str
    alias: str
    category: str
    group: Optional[str] = None
    path: str = ""
    description: str = ""
    enabled: bool = True
    
    def to_dict(self) -> Dict:
        """Convert tool to dictionary for YAML serialization."""
        return {
            "name": self.name,
            "alias": self.alias,
            "category": self.category,
            "group": self.group if self.group is not None else "None",
            "path": self.path,
            "description": self.description,
            "enabled": self.enabled
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Tool":
        """Create Tool instance from dictionary."""
        group = data.get("group")
        if group == "None":
            group = None
        return cls(
            name=data["name"],
            alias=data["alias"],
            category=data["category"],
            group=group,
            path=data.get("path", ""),
            description=data.get("description", ""),
            enabled=data.get("enabled", True)
        )

def get_project_root(config_path: Optional[Path] = None) -> Path:
    if config_path and config_path.exists():
        return config_path.parent
    
    search_dirs = []
    
    search_dirs.append(Path.cwd())
    
    if getattr(sys, 'frozen', False):
        exe_path = Path(sys.executable).resolve()
        search_dirs.append(exe_path.parent)
        search_dirs.append(exe_path.parent.parent)
    else:
        script_path = Path(__file__).resolve()
        search_dirs.append(script_path.parent)
        search_dirs.append(script_path.parent.parent)
    
    for dir_path in search_dirs:
        config_file = dir_path / "tools.yaml"
        if config_file.exists():
            return dir_path
    
    return Path.cwd()

def ensure_project_directories(root_path: Path) -> None:
    """确保项目目录结构存在。"""
    for dir_name in ["bin", "startup", "tool"]:
        dir_path = root_path / dir_name
        dir_path.mkdir(exist_ok=True)

class TmngConfig:
    """Configuration manager for tmng."""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.console = Console()
        
        if config_path is None:
            project_root = get_project_root()
            config_path = project_root / "tools.yaml"
        else:
            project_root = config_path.parent
        
        self.config_path = config_path.resolve()
        self.project_root = project_root.resolve()
        
        ensure_project_directories(self.project_root)
        
        self._change_to_project_root()
        
        self.console.print(f"[dim]Project root: {self.project_root}[/dim]")
        self.console.print(f"[dim]Config path: {self.config_path}[/dim]")
        
        self.tools: List[Tool] = []
        self.load_config()
    
    def _change_to_project_root(self) -> None:
        try:
            current_dir = Path.cwd()
            if current_dir != self.project_root:
                os.chdir(self.project_root)
        except Exception as e:
            self.console.print(f"[yellow]Warning: Could not change to project root: {e}[/yellow]")
            self.console.print(f"[yellow]Continuing in current directory: {current_dir}[/yellow]")
    
    def load_config(self) -> None:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            self.console.print(f"[yellow]Config file not found, creating default at: {self.config_path}[/yellow]")
            self._create_default_config()
            return
        
        try:
            with open(self.config_path, 'r') as f:
                config_data = yaml.safe_load(f) or {}
            
            self.tools = [
                Tool.from_dict(tool_data) 
                for tool_data in config_data.get("tools", [])
            ]
            
        except yaml.YAMLError as e:
            self.console.print(f"[bold red]Error loading config: {e}[/bold red]")
            self._create_default_config()
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error loading config: {e}[/bold red]")
            self._create_default_config()
    
    def _create_default_config(self) -> None:
        """Create default configuration."""
        self.tools = []
        self.save_config()
    
    def save_config(self) -> None:
        """Save configuration to YAML file."""
        config_data = {
            "version": "1.0",
            "tools": [tool.to_dict() for tool in self.tools]
        }
        
        # Ensure config directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(self.config_path, 'w') as f:
                yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
            
            self.update_symlinks()
            self.update_shell_conf()
        except Exception as e:
            self.console.print(f"[bold red]Error saving config: {e}[/bold red]")
    
    def update_symlinks(self) -> None:
        """Update symbolic links in startup and tool directories."""
        # Create directories if they don't exist
        startup_dir = self.project_root / "startup"
        tool_dir = self.project_root / "tool"
        bin_dir = self.project_root / "bin"
        
        for directory in [startup_dir, tool_dir, bin_dir]:
            directory.mkdir(exist_ok=True)
        
        # Clear existing symlinks
        for directory in [startup_dir, tool_dir]:
            for item in directory.iterdir():
                if item.is_symlink():
                    try:
                        item.unlink()
                    except Exception as e:
                        self.console.print(f"[yellow]Warning: Could not remove symlink {item}: {e}[/yellow]")
        
        # Create new symlinks
        for tool in self.tools:
            if not tool.enabled:
                continue
            
            # Expand user home directory in path
            tool_path_str = tool.path.strip()
            if not tool_path_str:
                continue
                
            tool_path = Path(tool_path_str).expanduser()
            
            if not tool_path.exists():
                self.console.print(f"[yellow]Warning: Tool path does not exist: {tool_path}[/yellow]")
                continue
            
            # Determine target directory
            target_dir = startup_dir if tool.category == Category.STARTUP.value else tool_dir
            
            # Create symlink
            symlink_path = target_dir / tool.alias
            try:
                if symlink_path.exists() or symlink_path.is_symlink():
                    if symlink_path.is_symlink():
                        symlink_path.unlink()
                    elif symlink_path.exists():
                        # Remove if it's a regular file
                        symlink_path.unlink()
                
                # Make the symlink
                symlink_path.symlink_to(tool_path.resolve())
                
                # Make executable if it's a script
                if tool_path.suffix in ['.sh', '.py'] and tool_path.exists():
                    try:
                        tool_path.chmod(0o755)
                    except Exception as e:
                        self.console.print(f"[yellow]Warning: Could not make {tool_path} executable: {e}[/yellow]")
                
            except Exception as e:
                self.console.print(f"[red]Error creating symlink for {tool.alias}: {e}[/red]")
    
    def update_shell_conf(self) -> None:
        """Update shell configuration file."""
        shell_conf = self.project_root / "shell.conf"
        
        # Get absolute paths
        try:
            startup_dir = (self.project_root / "startup").resolve()
            tool_dir = (self.project_root / "tool").resolve()
            bin_dir = (self.project_root / "bin").resolve()
        except Exception as e:
            self.console.print(f"[red]Error resolving paths: {e}[/red]")
            return
        
        # Build shell configuration
        lines = [
            "# tmng shell configuration - DO NOT EDIT MANUALLY",
            "# Generated automatically by tmng tool manager",
            "",
            "# Add tmng directories to PATH",
            f'export PATH="$PATH:{bin_dir}:{tool_dir}:{startup_dir}"',
            "",
            "# Execute startup scripts",
            f'if [ -d "{startup_dir}" ]; then',
            f'  for script in {startup_dir}/*; do',
            '    if [ -x "$script" ]; then',
            '      "$script"',
            '    fi',
            '  done',
            'fi',
            ""
        ]
        
        try:
            with open(shell_conf, 'w') as f:
                f.write('\n'.join(lines))
            
            # Make shell.conf executable
            shell_conf.chmod(0o755)
            
            # Check and update .bashrc/.zshrc
            self._update_shell_init_files()
        except Exception as e:
            self.console.print(f"[red]Error updating shell.conf: {e}[/red]")
    
    def _update_shell_init_files(self) -> None:
        """Add shell.conf to shell initialization files if not already present."""
        shell_init_files = [
            Path.home() / ".bashrc",
            Path.home() / ".zshrc",
        ]
        
        shell_conf_path = (self.project_root / "shell.conf").resolve()
        source_line = f'\nsource "{shell_conf_path}"\n'
        
        for shell_file in shell_init_files:
            if not shell_file.exists():
                continue
            
            try:
                with open(shell_file, 'r') as f:
                    content = f.read()
                
                # Check if already sourced
                if str(shell_conf_path) in content:
                    continue
                
                # Append source line
                with open(shell_file, 'a') as f:
                    f.write(source_line)
                
                self.console.print(f"[green]Updated {shell_file.name}[/green]")
                
            except Exception as e:
                self.console.print(f"[yellow]Could not update {shell_file.name}: {e}[/yellow]")

class TmngManager:
    """Main manager class for tmng tool."""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.console = Console()
        self.config = TmngConfig(config_path)
        self.theme = GreenPassion()
    
    def clear_screen(self):
        """Clear the screen in a cross-platform way."""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def print_header(self) -> None:
        """Print tmng header."""
        header = Text.assemble(
            ("tmng ", "bold cyan"),
            ("Tool Manager", "bold white"),
            (" v1.0", "dim cyan")
        )
        self.console.print(Panel(header, border_style="cyan", padding=(1, 2)))
    
    def print_help(self) -> None:
        """Print help information."""
        self.clear_screen()
        self.print_header()
        
        help_text = """
tmng is a tool manager for organizing and managing your scripts and binaries.

[bold cyan]Usage:[/bold cyan]
  tmng [command] [options]

[bold cyan]Commands:[/bold cyan]
  [bold]no command[/bold]         Show this help message
  [bold]-h, --help[/bold]         Show this help message
  [bold]-l, --list[/bold]         List all tools with interactive management
  [bold]-a, --add[/bold]          Add new tool(s) to the manager
  [bold]-s, --stats[/bold]        Show statistics about managed tools
  [bold]--update-shell[/bold]     Update shell configuration manually
  [bold]--config PATH[/bold]      Use alternative config file

[bold cyan]Examples:[/bold cyan]
  tmng -l                    List and manage tools
  tmng -a                   Add new tool
  tmng --stats              Show tool statistics
  tmng --config ~/my-tools.yaml  Use custom config file
        """
        
        self.console.print(help_text)
    
    def show_statistics(self) -> None:
        """Display statistics about managed tools."""
        self.clear_screen()
        self.print_header()
        
        tools = self.config.tools
        
        if not tools:
            self.console.print("[yellow]No tools managed yet. Use 'tmng -a' to add some.[/yellow]")
            return
        
        # Calculate statistics
        total_tools = len(tools)
        enabled_tools = sum(1 for t in tools if t.enabled)
        disabled_tools = total_tools - enabled_tools
        
        startup_tools = sum(1 for t in tools if t.category == Category.STARTUP.value)
        tool_tools = sum(1 for t in tools if t.category == Category.TOOL.value)
        
        # Group by category
        groups = {}
        for tool in tools:
            if tool.group:
                groups[tool.group] = groups.get(tool.group, 0) + 1
        
        # Create statistics table
        table = Table(title="tmng Statistics", box=ROUNDED, border_style="cyan")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="green", justify="right")
        table.add_column("Percentage", style="yellow", justify="right")
        
        table.add_row("Total Tools", str(total_tools), "100%")
        if total_tools > 0:
            table.add_row("Enabled Tools", str(enabled_tools), f"{(enabled_tools/total_tools)*100:.1f}%")
            table.add_row("Disabled Tools", str(disabled_tools), f"{(disabled_tools/total_tools)*100:.1f}%")
            table.add_row("Startup Tools", str(startup_tools), f"{(startup_tools/total_tools)*100:.1f}%")
            table.add_row("Regular Tools", str(tool_tools), f"{(tool_tools/total_tools)*100:.1f}%")
        else:
            table.add_row("Enabled Tools", "0", "0%")
            table.add_row("Disabled Tools", "0", "0%")
            table.add_row("Startup Tools", "0", "0%")
            table.add_row("Regular Tools", "0", "0%")
        
        table.add_row("Tool Groups", str(len(groups)), "")
        
        self.console.print(table)
        
        # Show group breakdown if there are groups
        if groups:
            self.console.print("\n[bold cyan]Groups Breakdown:[/bold cyan]")
            group_table = Table(box=ROUNDED, border_style="blue")
            group_table.add_column("Group", style="blue")
            group_table.add_column("Tool Count", style="green", justify="right")
            
            for group_name, count in sorted(groups.items()):
                group_table.add_row(group_name, str(count))
            
            self.console.print(group_table)
        
        self.console.print("\n[dim]Press Enter to continue...[/dim]")
        input()
    
    def list_tools_interactive(self) -> None:
        """Display tools in interactive list with management options."""
        if not self.config.tools:
            self.clear_screen()
            self.print_header()
            self.console.print("[yellow]No tools managed yet. Use 'tmng -a' to add some.[/yellow]")
            return
        
        while True:
            self.clear_screen()
            self.print_header()
            
            # Create tree view
            tree = Tree("[bold cyan]Managed Tools[/bold cyan]", guide_style="cyan")
            
            # Group tools by group
            grouped_tools = {}
            for tool in self.config.tools:
                group = tool.group or "Ungrouped"
                if group not in grouped_tools:
                    grouped_tools[group] = []
                grouped_tools[group].append(tool)
            
            # Build tree
            for group_name in sorted(grouped_tools.keys()):
                if group_name == "Ungrouped":
                    group_node = tree.add(f"[dim]{group_name}[/dim]")
                else:
                    group_node = tree.add(f"[bold blue]{group_name}[/bold blue]")
                
                for tool in sorted(grouped_tools[group_name], key=lambda x: x.name):
                    status_icon = "●"  # 小圆点
                    status_color = "green" if tool.enabled else "red"
                    
                    category_icon = "⚡" if tool.category == Category.STARTUP.value else "🛠️"
                    
                    tool_text = Text.assemble(
                        (status_icon, status_color),
                        (" ", ""),
                        (category_icon, ""),
                        (" ", ""),
                        (f"{tool.alias}", "bold green" if tool.enabled else "dim red"),
                        (" (", "dim"),
                        (f"{tool.name}", "dim cyan"),
                        (")", "dim"),
                        (" - ", "dim"),
                        (tool.description, "white")
                    )
                    
                    group_node.add(tool_text)
            
            self.console.print(tree)
            self.console.print()
            
            # Interactive options
            try:
                questions = [
                    inquirer.List(
                        "action",
                        message="Select action",
                        choices=[
                            ("Toggle tool status", "toggle"),
                            ("Toggle group status", "toggle_group"),
                            ("Delete tool", "delete"),
                            ("Delete group", "delete_group"),
                            ("Refresh view", "refresh"),
                            ("Exit to main menu", "exit")
                        ],
                        carousel=True
                    )
                ]
                
                answer = inquirer.prompt(questions, theme=self.theme)
                if not answer:
                    break
                
                action = answer["action"]
                
                if action == "exit":
                    break
                elif action == "refresh":
                    continue
                elif action == "toggle":
                    self._toggle_tool_status()
                elif action == "toggle_group":
                    self._toggle_group_status()
                elif action == "delete":
                    self._delete_tool()
                elif action == "delete_group":
                    self._delete_group()
                
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Operation cancelled.[/yellow]")
                break
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
                break
    
    def _toggle_tool_status(self) -> None:
        """Toggle enabled status of a specific tool."""
        if not self.config.tools:
            self.console.print("[yellow]No tools available.[/yellow]")
            return
        
        # Build tool choices
        choices = []
        for tool in self.config.tools:
            status = "● Enabled" if tool.enabled else "● Disabled"
            group = f" ({tool.group})" if tool.group else ""
            choices.append(
                (f"{tool.alias} - {tool.description}{group} [{status}]", tool.name)
            )
        
        questions = [
            inquirer.List(
                "tool_name",
                message="Select tool to toggle",
                choices=choices,
                carousel=True
            )
        ]
        
        try:
            answers = inquirer.prompt(questions, theme=self.theme)
            if not answers:
                return
            
            tool_name = answers["tool_name"]
            
            # Find and toggle tool
            for tool in self.config.tools:
                if tool.name == tool_name:
                    tool.enabled = not tool.enabled
                    status = "enabled" if tool.enabled else "disabled"
                    self.console.print(f"[green]✓ Tool '{tool.alias}' {status}[/green]")
                    break
            
            self.config.save_config()
            self.console.print("\n[dim]Press Enter to continue...[/dim]")
            input()
            
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Operation cancelled.[/yellow]")
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
    
    def _toggle_group_status(self) -> None:
        """Toggle enabled status of an entire group."""
        # Get unique groups
        groups = sorted(set(tool.group for tool in self.config.tools if tool.group))
        
        if not groups:
            self.console.print("[yellow]No groups defined.[/yellow]")
            self.console.print("\n[dim]Press Enter to continue...[/dim]")
            input()
            return
        
        questions = [
            inquirer.List(
                "group_name",
                message="Select group to toggle",
                choices=groups,
                carousel=True
            )
        ]
        
        try:
            answers = inquirer.prompt(questions, theme=self.theme)
            if not answers:
                return
            
            group_name = answers["group_name"]
            
            # Toggle all tools in group
            toggled_count = 0
            for tool in self.config.tools:
                if tool.group == group_name:
                    tool.enabled = not tool.enabled
                    toggled_count += 1
            
            self.console.print(f"[green]✓ Toggled {toggled_count} tools in group '{group_name}'[/green]")
            self.config.save_config()
            self.console.print("\n[dim]Press Enter to continue...[/dim]")
            input()
            
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Operation cancelled.[/yellow]")
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
    
    def _delete_tool(self) -> None:
        """Delete a specific tool."""
        if not self.config.tools:
            self.console.print("[yellow]No tools available.[/yellow]")
            self.console.print("\n[dim]Press Enter to continue...[/dim]")
            input()
            return
        
        choices = []
        for tool in self.config.tools:
            group = f" ({tool.group})" if tool.group else ""
            choices.append(
                (f"{tool.alias} - {tool.description}{group}", tool.name)
            )
        
        questions = [
            inquirer.List(
                "tool_name",
                message="Select tool to delete",
                choices=choices,
                carousel=True
            )
        ]
        
        try:
            answers = inquirer.prompt(questions, theme=self.theme)
            if not answers:
                return
            
            tool_name = answers["tool_name"]
            
            # Confirm deletion
            confirm_question = [
                inquirer.Confirm(
                    "confirm",
                    message=f"Are you sure you want to delete tool '{tool_name}'?",
                    default=False
                )
            ]
            
            confirm_answer = inquirer.prompt(confirm_question, theme=self.theme)
            if not confirm_answer or not confirm_answer["confirm"]:
                return
            
            # Remove tool
            self.config.tools = [t for t in self.config.tools if t.name != tool_name]
            self.config.save_config()
            self.console.print(f"[green]✓ Tool '{tool_name}' deleted[/green]")
            self.console.print("\n[dim]Press Enter to continue...[/dim]")
            input()
            
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Operation cancelled.[/yellow]")
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
    
    def _delete_group(self) -> None:
        """Delete an entire group of tools."""
        groups = sorted(set(tool.group for tool in self.config.tools if tool.group))
        
        if not groups:
            self.console.print("[yellow]No groups defined.[/yellow]")
            self.console.print("\n[dim]Press Enter to continue...[/dim]")
            input()
            return
        
        questions = [
            inquirer.List(
                "group_name",
                message="Select group to delete",
                choices=groups,
                carousel=True
            )
        ]
        
        try:
            answers = inquirer.prompt(questions, theme=self.theme)
            if not answers:
                return
            
            group_name = answers["group_name"]
            
            # Count tools to be deleted
            deleted_count = sum(1 for t in self.config.tools if t.group == group_name)
            
            # Confirm deletion
            confirm_question = [
                inquirer.Confirm(
                    "confirm",
                    message=f"Are you sure? This will delete ALL {deleted_count} tools in group '{group_name}'.",
                    default=False
                )
            ]
            
            confirm_answer = inquirer.prompt(confirm_question, theme=self.theme)
            if not confirm_answer or not confirm_answer["confirm"]:
                return
            
            # Remove tools in group
            self.config.tools = [t for t in self.config.tools if t.group != group_name]
            self.config.save_config()
            self.console.print(f"[green]✓ Deleted {deleted_count} tools in group '{group_name}'[/green]")
            self.console.print("\n[dim]Press Enter to continue...[/dim]")
            input()
            
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Operation cancelled.[/yellow]")
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
    
    def add_tool_interactive(self) -> None:
        """Interactively add new tool(s)."""
        while True:
            self.clear_screen()
            self.print_header()
            self.console.print("[bold cyan]Add New Tool[/bold cyan]\n")
            
            # Ask for group
            questions = [
                inquirer.Text(
                    "group",
                    message="Enter group name (leave empty for no group, or 'none' for existing)",
                    default=""
                )
            ]
            
            try:
                group_answer = inquirer.prompt(questions, theme=self.theme)
                if not group_answer:
                    break
                
                group_name = group_answer["group"].strip() or None
                if group_name and group_name.lower() == "none":
                    group_name = None
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Operation cancelled.[/yellow]")
                return
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
                return
            
            # Check if we're adding to an existing group
            existing_tools_in_group = []
            if group_name:
                existing_tools_in_group = [t for t in self.config.tools if t.group == group_name]
                if existing_tools_in_group:
                    self.console.print(f"[cyan]Found {len(existing_tools_in_group)} existing tools in group '{group_name}'[/cyan]")
            
            while True:
                tool = self._add_single_tool(group_name)
                if tool:
                    self.config.tools.append(tool)
                    self.config.save_config()
                    self.console.print(f"[green]✓ Tool '{tool.alias}' added successfully[/green]")
                
                # Ask if user wants to add another tool to the same group
                if group_name:
                    continue_question = [
                        inquirer.Confirm(
                            "continue",
                            message=f"Add another tool to group '{group_name}'?",
                            default=True
                        )
                    ]
                    try:
                        continue_answer = inquirer.prompt(continue_question, theme=self.theme)
                        if not continue_answer or not continue_answer["continue"]:
                            break
                    except KeyboardInterrupt:
                        self.console.print("\n[yellow]Operation cancelled.[/yellow]")
                        break
                    except Exception as e:
                        self.console.print(f"[red]Error: {e}[/red]")
                        break
                else:
                    break
            
            # Ask if user wants to add another tool (possibly in a different group)
            another_tool_question = [
                inquirer.Confirm(
                    "another",
                    message="Add another tool?",
                    default=False
                )
            ]
            try:
                another_answer = inquirer.prompt(another_tool_question, theme=self.theme)
                if not another_answer or not another_answer["another"]:
                    break
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Operation cancelled.[/yellow]")
                break
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
                break
    
    def _add_single_tool(self, group_name: Optional[str] = None) -> Optional[Tool]:
        """Add a single tool with interactive prompts."""
        self.clear_screen()
        self.console.print("[bold cyan]Add New Tool[/bold cyan]\n")
        
        questions = [
            inquirer.List(
                "category",
                message="Select tool category",
                choices=[
                    ("Startup (runs on shell startup)", Category.STARTUP.value),
                    ("Tool (manual execution)", Category.TOOL.value)
                ],
                carousel=True
            ),
            inquirer.Path(
                "path",
                message="Enter tool path",
                path_type=inquirer.Path.FILE,
                exists=True
            ),
            inquirer.Text(
                "alias",
                message="Enter tool alias (name in PATH)",
                validate=lambda _, x: bool(x.strip()) and not any(c in x for c in '/\\:?*"<>|')
            ),
            inquirer.Text(
                "description",
                message="Enter tool description"
            )
        ]
        
        try:
            answers = inquirer.prompt(questions, theme=self.theme)
            if not answers:
                return None
            
            # Check if alias already exists
            alias = answers["alias"].strip()
            for tool in self.config.tools:
                if tool.alias == alias:
                    self.console.print(f"[red]Error: Alias '{alias}' already exists[/red]")
                    self.console.print("\n[dim]Press Enter to continue...[/dim]")
                    input()
                    return None
            
            # Create tool name from alias (replace non-alphanumeric with underscores)
            name = re.sub(r'[^a-zA-Z0-9]', '_', alias)
            
            # Check if name already exists
            existing_names = {t.name for t in self.config.tools}
            counter = 1
            original_name = name
            while name in existing_names:
                name = f"{original_name}_{counter}"
                counter += 1
            
            tool = Tool(
                name=name,
                alias=alias,
                category=answers["category"],
                group=group_name,
                path=answers["path"],
                description=answers["description"].strip(),
                enabled=True
            )
            
            # Show summary
            self.clear_screen()
            self.console.print("[bold cyan]Tool Summary[/bold cyan]\n")
            self.console.print(f"  Name: {tool.name}")
            self.console.print(f"  Alias: {tool.alias}")
            self.console.print(f"  Category: {tool.category}")
            self.console.print(f"  Group: {tool.group or 'None'}")
            self.console.print(f"  Path: {tool.path}")
            self.console.print(f"  Description: {tool.description}")
            
            confirm_question = [
                inquirer.Confirm(
                    "confirm",
                    message="\nAdd this tool?",
                    default=True
                )
            ]
            
            confirm_answer = inquirer.prompt(confirm_question, theme=self.theme)
            if not confirm_answer or not confirm_answer["confirm"]:
                return None
            
            return tool
            
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Operation cancelled.[/yellow]")
            return None
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
            return None
    
    def update_shell_config(self) -> None:
        """Manually update shell configuration."""
        self.clear_screen()
        self.print_header()
        
        with self.console.status("[bold cyan]Updating shell configuration...[/bold cyan]"):
            self.config.update_symlinks()
            self.config.update_shell_conf()
        
        self.console.print("[green]✓ Shell configuration updated[/green]")
        self.console.print("[cyan]You may need to restart your shell or run:[/cyan]")
        self.console.print("[bold]source ~/.bashrc[/bold] (or [bold]source ~/.zshrc[/bold])")
        self.console.print("\n[dim]Press Enter to continue...[/dim]")
        input()

def main():
    """Main entry point for tmng."""
    parser = argparse.ArgumentParser(
        description="tmng - Tool Manager for organizing scripts and binaries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False
    )
    
    parser.add_argument(
        "-h", "--help",
        action="store_true",
        help="Show this help message"
    )
    
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List and manage tools interactively"
    )
    
    parser.add_argument(
        "-a", "--add",
        action="store_true",
        help="Add new tool(s) interactively"
    )
    
    parser.add_argument(
        "-s", "--stats",
        action="store_true",
        help="Show statistics about managed tools"
    )
    
    parser.add_argument(
        "--update-shell",
        action="store_true",
        help="Update shell configuration manually"
    )
    
    # Add config file option
    parser.add_argument(
        "--config",
        type=str,
        help="Use alternative configuration file"
    )
    
    # Parse arguments
    try:
        args = parser.parse_args()
    except SystemExit:
        # Handle -h without arguments
        manager = TmngManager()
        manager.print_help()
        return
    
    # Initialize manager with optional config path
    config_path = Path(args.config).expanduser().resolve() if args.config else None
    manager = TmngManager(config_path)
    
    # Handle arguments
    if args.list:
        manager.list_tools_interactive()
    elif args.add:
        manager.add_tool_interactive()
    elif args.stats:
        manager.show_statistics()
    elif args.update_shell:
        manager.update_shell_config()
    else:
        manager.print_help()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[yellow]Operation cancelled by user.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console = Console()
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)
