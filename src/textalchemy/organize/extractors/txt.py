def read_txt(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="cp1251") as f:
                return f.read()
        except Exception:
            return ""
    except Exception:
        return ""


def read_djvu(file_path: str) -> str:
    try:
        import subprocess
        result = subprocess.run(
            ["djvutxt", file_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
        return ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    except Exception:
        return ""
