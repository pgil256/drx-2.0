#!/usr/bin/env python3
"""
Constants Validation Script
Checks that modules are using constants from constants.py rather than defining their own
"""
import os
import re
import sys
from collections import defaultdict

# Define patterns to search for that indicate locally defined constants
CONSTANT_PATTERNS = [
    r"^[A-Z][A-Z0-9_]+ = .*$",  # Constant definition (e.g., MAX_PRESSURE = 100)
    r"^[A-Z][A-Z0-9_]+ = \{.*$"  # Dictionary constant definition
]

# Modules that should be using centralized constants
TARGET_MODULES = [
    "main/modules/protocols/protocol_runner.py",
    "main/modules/protocols/protocol_settings.py",
    "main/modules/hardware/actuator_controller.py",
    "main/ui/dialogs/pressure_dialog.py",
    "main/ui/dialogs/timer_dialog.py"
]

# Constants that are allowed to be defined locally
ALLOWED_LOCAL_CONSTANTS = [
    "PROTOCOL_TYPES",
    "PHASE_",  # Module-specific phase constants
    "PASSWORD_",  # Security constants
    "RETRY_",  # Module-specific retry constants
    "__",  # Special constants like __version__
]

def should_ignore(line, constants_to_ignore):
    """Check if this constant definition should be ignored"""
    for allowed in constants_to_ignore:
        if allowed in line:
            return True
    return False

def find_local_constants(file_path, constants_to_ignore=None):
    """Find constants defined locally in a file"""
    if constants_to_ignore is None:
        constants_to_ignore = ALLOWED_LOCAL_CONSTANTS
        
    local_constants = []
    in_comment_block = False
    
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
            
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
                
            # Handle docstring blocks
            if line.startswith('"""') or line.startswith("'''"):
                in_comment_block = not in_comment_block
                continue
                
            if in_comment_block:
                continue
                
            # Skip comments
            if line.startswith('#'):
                continue
                
            # Check for constant definitions
            for pattern in CONSTANT_PATTERNS:
                if re.match(pattern, line) and not should_ignore(line, constants_to_ignore):
                    # Extract constant name
                    constant_name = line.split('=')[0].strip()
                    local_constants.append((constant_name, i + 1))
                    break
                    
        return local_constants
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return []

def find_imported_constants(file_path):
    """Find constants imported from constants.py"""
    imported_constants = []
    found_constants_import = False
    
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
            
        for line in lines:
            line = line.strip()
            
            # Look for imports from constants.py
            if "from main.config.constants import" in line:
                found_constants_import = True
                # Extract imported constants
                imports = line.split("import")[1].strip()
                if "(" in imports:  # Multi-line import
                    continue  # We'll handle this in the loop below
                
                # Handle single-line import
                constants = [c.strip() for c in imports.split(',')]
                imported_constants.extend(constants)
            
            # Handle multi-line imports
            elif found_constants_import and ")" not in line and "import" not in line:
                constants = [c.strip() for c in line.split(',') if c.strip()]
                imported_constants.extend(constants)
            
            # End of multi-line import
            elif found_constants_import and ")" in line:
                found_constants_import = False
                constants = [c.strip() for c in line.split(')')[0].split(',') if c.strip()]
                imported_constants.extend(constants)
                
        return imported_constants
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return []

def main():
    """Main function"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    all_issues = defaultdict(list)
    
    print("Checking modules for locally defined constants...")
    print("=" * 70)
    
    for module in TARGET_MODULES:
        file_path = os.path.join(base_dir, module)
        
        # Skip files that don't exist
        if not os.path.exists(file_path):
            print(f"File not found: {module}")
            continue
            
        print(f"\nChecking {module}:")
        print("-" * 50)
        
        # Find locally defined constants
        local_constants = find_local_constants(file_path)
        imported_constants = find_imported_constants(file_path)
        
        if local_constants:
            print(f"Found {len(local_constants)} locally defined constants:")
            for constant, line_num in local_constants:
                print(f"  - {constant} (line {line_num})")
                all_issues[module].append((constant, line_num))
        else:
            print("  ✓ No locally defined constants found")
            
        if imported_constants:
            print(f"Imported {len(imported_constants)} constants from constants.py")
        else:
            print("  ✗ No constants imported from constants.py")
            
    print("\n\nSummary of Issues:")
    print("=" * 70)
    
    if all_issues:
        for module, issues in all_issues.items():
            if issues:
                print(f"\n{module}: {len(issues)} issues")
                for constant, line_num in issues:
                    print(f"  - Move {constant} (line {line_num}) to constants.py")
    else:
        print("No issues found! All modules are using centralized constants.")
        
    return 0

if __name__ == "__main__":
    sys.exit(main())