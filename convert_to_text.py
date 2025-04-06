import os
import sys


def process_files(current_dir, is_concatenated, concat_file=None):
    if not os.path.exists(current_dir):
        print(f"Skipping: {current_dir} (directory does not exist)")
        return

    try:
        entries = os.listdir(current_dir)
    except Exception as e:
        print(f"Error reading directory {current_dir}: {e}")
        return

    for entry in entries:
        entry_path = os.path.join(current_dir, entry)
        relative_path = os.path.relpath(entry_path, root_dir)

        # Skip ignored files/directories
        if any(pattern in relative_path for pattern in ignored_patterns):
            continue

        if os.path.isdir(entry_path):
            process_files(entry_path, is_concatenated, concat_file)
        else:
            try:
                with open(entry_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"Error reading file {relative_path}: {e}")
                continue

            file_header = f"// Original Path: {relative_path}\n\n"

            if is_concatenated:
                concat_file.write(file_header + content + "\n\n")
            else:
                # Replace os.sep (or '/') with '_' to form a valid filename and add .txt extension
                new_file_name = relative_path.replace(os.sep, "_") + ".txt"
                new_file_path = os.path.join(output_dir, new_file_name)
                try:
                    with open(new_file_path, "w", encoding="utf-8") as out_file:
                        out_file.write(file_header + content)
                    print(f"Converted: {relative_path} -> {new_file_name}")
                except Exception as e:
                    print(f"Error writing file {new_file_name}: {e}")


if __name__ == "__main__":
    # Set the root directory as the location of this script
    root_dir = os.path.dirname(os.path.abspath(__file__))

    # Define output directory and file for concatenated output
    output_dir = os.path.join(root_dir, "git_to_text")
    output_file = os.path.join(output_dir, "concatenated_output.txt")

    # Patterns to ignore
    ignored_patterns = ["__pycache__", "git_to_text", ".ui", ".gitignore"]

    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Determine if concatenation is requested via command line argument "--concat"
    is_concatenated = "--concat" in sys.argv

    if is_concatenated:
        with open(output_file, "w", encoding="utf-8") as concat_file:
            process_files(root_dir, is_concatenated, concat_file)
        print(f"All files concatenated into: {output_file}")
    else:
        process_files(root_dir, is_concatenated)
        print("All files have been converted separately!")
