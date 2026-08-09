"""
Configuration Integration Helper
Updates the actual module files with GUI configuration settings
"""

import ast
import re
import os
import sys
from pathlib import Path
from typing import Dict, Any


class ConfigIntegration:
    """Helper class to integrate GUI configuration with module files."""
    
    def __init__(self):
        self.modules_dir = Path("modules")
        
    def update_rpgmaker_config(self, config: Dict[str, Any]) -> bool:
        """Update rpgmakermvmz.py with configuration from GUI."""
        module_path = self.modules_dir / "rpgmakermvmz.py"
        
        if not module_path.exists():
            raise FileNotFoundError(f"Module file not found: {module_path}")
            
        try:
            # Read the current module file
            with open(module_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Update configuration values
            updated_content = self._update_config_values(content, config)
            
            # Write back to file
            with open(module_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)

            # The GUI may already have imported the engine for evaluation or a
            # prior speaker scan. Keep that live module aligned with the values
            # just persisted instead of requiring an application restart.
            live_module = sys.modules.get("modules.rpgmakermvmz")
            if live_module is not None:
                for key, value in config.items():
                    if hasattr(live_module, key):
                        setattr(live_module, key, value)
                
            return True
            
        except Exception as e:
            raise e
            
    def _update_config_values(self, content: str, config: Dict[str, Any]) -> str:
        """Update configuration values in the module content."""
        lines = content.split('\n')
        updated_lines = []
        
        # Track which configurations we found and updated
        found_configs = set()
        
        for line in lines:
            updated_line = line
            
            # Look for configuration assignments
            for config_key, config_value in config.items():
                # Match lines like: CONFIG_NAME = value  # comment
                pattern = rf'^({re.escape(config_key)})\s*=\s*.*?(#.*)?$'
                match = re.match(pattern, line.strip())
                
                if match:
                    # Preserve the comment if it exists
                    comment = match.group(2) if match.group(2) else ""
                    if comment:
                        comment = "  " + comment
                    
                    # Create the new line with proper formatting
                    rendered_value = (
                        repr(config_value)
                        if isinstance(config_value, str)
                        else str(config_value)
                    )
                    updated_line = f"{config_key} = {rendered_value}{comment}"
                    found_configs.add(config_key)
                    break
                    
            updated_lines.append(updated_line)
            
        # Check if all configurations were found
        missing_configs = set(config.keys()) - found_configs
        if missing_configs:
            print(f"Warning: Could not find these configurations in module: {missing_configs}")
            
        return '\n'.join(updated_lines)
        
    def update_env_file(self, config: Dict[str, Any], env_path: Path = None) -> bool:
        """Update .env file with configuration."""
        if env_path is None:
            env_path = Path(".env")
            
        try:
            from dotenv import set_key
            
            for key, value in config.items():
                set_key(env_path, key, str(value))
                
            return True
            
        except Exception as e:
            print(f"Error updating .env file: {e}")
            return False
            
    def read_current_config(self, module_path: Path = None) -> Dict[str, Any]:
        """Read current configuration from module file."""
        if module_path is None:
            module_path = self.modules_dir / "rpgmakermvmz.py"
            
        if not module_path.exists():
            return {}
            
        config = {}
        
        try:
            with open(module_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Find configuration lines used by the RPG Maker config UI.
            bool_pattern = (
                r'^(FIRSTLINESPEAKERS|INLINE401SPEAKERS|FACENAME101|NAMES|'
                r'BRFLAG|FIXTEXTWRAP|IGNORETLTEXT|PRESERVEORIGINAL|TLSYSTEMVARIABLES|'
                r'TLSYSTEMSWITCHES|JOIN408|SPEAKERS408|CODE\d+)\s*=\s*(True|False)'
            )
            int_pattern = r'^(CODE122_VAR_MIN|CODE122_VAR_MAX)\s*=\s*(\d+)'
            ranges_pattern = r'^CODE122_VAR_RANGES\s*=\s*(.+?)(?:\s+#.*)?$'
            
            for line in content.split('\n'):
                line = line.strip()
                match = re.match(bool_pattern, line)
                if match:
                    key = match.group(1)
                    value = match.group(2) == 'True'
                    config[key] = value
                    continue

                match = re.match(int_pattern, line)
                if match:
                    key = match.group(1)
                    config[key] = int(match.group(2))
                    continue

                match = re.match(ranges_pattern, line)
                if match:
                    value = ast.literal_eval(match.group(1))
                    if isinstance(value, str):
                        config["CODE122_VAR_RANGES"] = value
                        
        except Exception as e:
            print(f"Error reading configuration from {module_path}: {e}")
            
        return config
        
    def read_plugin_config(self, module_path: Path = None) -> Dict[str, Any]:
        """Read ENABLED_PLUGINS_357 and ENABLED_PATTERNS_355655 set literals from module file."""
        if module_path is None:
            module_path = self.modules_dir / "rpgmakermvmz.py"
        result: Dict[str, Any] = {
            "ENABLED_PLUGINS_357": set(),
            "ENABLED_PATTERNS_355655": set(),
        }
        if not module_path.exists():
            return result
        try:
            with open(module_path, "r", encoding="utf-8") as f:
                content = f.read()
            for var_name in ("ENABLED_PLUGINS_357", "ENABLED_PATTERNS_355655"):
                # Match:  VAR_NAME: set = set()  or  VAR_NAME: set = {"a", "b"}
                m = re.search(
                    rf'^{re.escape(var_name)}\s*(?::\s*set)?\s*=\s*(\{{[^}}]*\}}|set\(\))',
                    content,
                    re.MULTILINE,
                )
                if m:
                    bracket = m.group(1)
                    items = re.findall(r'"([^"]+)"|\'([^\']+)\'', bracket)
                    result[var_name] = {a or b for a, b in items}
        except Exception as e:
            print(f"Error reading plugin config: {e}")
        return result

    def update_plugin_config(
        self,
        enabled_357: set,
        enabled_355655: set,
        module_path: Path = None,
    ) -> bool:
        """Write ENABLED_PLUGINS_357 and ENABLED_PATTERNS_355655 set literals to module file."""
        if module_path is None:
            module_path = self.modules_dir / "rpgmakermvmz.py"
        if not module_path.exists():
            raise FileNotFoundError(f"Module file not found: {module_path}")

        def _fmt(s: set) -> str:
            if not s:
                return "set()"
            items = ", ".join(f'"{k}"' for k in sorted(s))
            return "{" + items + "}"

        try:
            with open(module_path, "r", encoding="utf-8") as f:
                content = f.read()
            for var_name, val_set in (
                ("ENABLED_PLUGINS_357", enabled_357),
                ("ENABLED_PATTERNS_355655", enabled_355655),
            ):
                content = re.sub(
                    rf'^{re.escape(var_name)}\s*(?::\s*set)?\s*=\s*(?:\{{[^}}]*\}}|set\(\))',
                    f'{var_name}: set = {_fmt(val_set)}',
                    content,
                    flags=re.MULTILINE | re.DOTALL,
                )
            with open(module_path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            raise e

    def validate_module_syntax(self, module_path: Path = None) -> bool:
        """Validate that the module file has correct Python syntax."""
        if module_path is None:
            module_path = self.modules_dir / "rpgmakermvmz.py"
            
        try:
            with open(module_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Try to compile the code
            compile(content, str(module_path), 'exec')
            return True
            
        except SyntaxError as e:
            print(f"Syntax error in {module_path}: {e}")
            return False
        except Exception as e:
            print(f"Error validating {module_path}: {e}")
            return False
            
    def create_config_template(self) -> Dict[str, Any]:
        """Create a template configuration with default values."""
        return {
            # General config
            "FIRSTLINESPEAKERS": False,
            "INLINE401SPEAKERS": False,
            "FACENAME101": False,
            "NAMES": False,
            "BRFLAG": False,
            "FIXTEXTWRAP": True,
            "IGNORETLTEXT": False,
            
            # Main Codes
            "CODE401": True,
            "CODE405": True,
            "CODE102": True,
            
            # Optional codes
            "CODE101": False,
            "CODE408": False,
            
            # Variable codes
            "CODE122": False,
            
            # Other codes
            "CODE355655": False,
            "CODE357": False,
            "CODE657": False,
            "CODE356": False,
            "CODE320": False,
            "CODE324": False,
            "CODE111": False,
            "CODE108": False
        }
        
    def get_config_descriptions(self) -> Dict[str, str]:
        """Get descriptions for all configuration options."""
        return {
            "FIRSTLINESPEAKERS": "If 1st line of 401 is a speaker, set to True",
            "INLINE401SPEAKERS": "Detect speaker from Name\u300cdialogue\u300d inline format in 401 lines",
            "FACENAME101": "Find Speakers in 101 Codes based on Face Name",
            "NAMES": "Output a list of all the character names found",
            "BRFLAG": "If the game uses <br> instead of newlines",
            "FIXTEXTWRAP": "Overwrites textwrap for better formatting",
            "IGNORETLTEXT": "Ignores all translated text",
            
            "CODE401": "Show Text - Main dialogue content",
            "CODE405": "Show Text (Scrolling) - Longer dialogue",
            "CODE102": "Show Choices - Player choice options",
            "CODE101": "Character Names - Turn on when names exist in 101",
            "CODE408": "Supported comment continuations - recognized player-facing 108 markers only",
            "CODE122": "Control Variables - Text stored in variables",
            
            "CODE355655": "Scripts - Text within script commands",
            "CODE357": "Picture Text - Text displayed on pictures",
            "CODE657": "Picture Text Extended - Extended picture text",
            "CODE356": "Plugin Commands - Plugin command parameters",
            "CODE320": "Change Name Input - Name input prompts",
            "CODE324": "Change Nickname - Nickname changes",
            "CODE111": "Conditional Branch - Conditional text",
            "CODE108": "Comments - Comment blocks"
        }
