"""What the game has to choose from, read from its content: obstacles and the parameters their scripts take, segments, looks."""
import re

from . import project

# mgGetInt("beams", 5), mgGetColor("color", 1, 0.5, 0.5): a parameter and what it is without one.
PARAMETER = re.compile(r'mgGet(String|Int|Float|Bool|Color)\(\s*"([^"]+)"\s*(?:,\s*([^)]*))?\)')


def obstacles():
    return project.base_names("obstacles", ".lua")


def segments():
    return project.base_names("segments", ".xml")


def looks():
    return project.base_names("looks", ".json")


def obstacle_parameters(kind):
    """[(name, type, default as a parameter's value)] in the order the script reads them, each once."""
    data = project.read_base(f"obstacles/{kind}.lua")
    if not data:
        return []
    found, seen = [], set()
    for what, name, default in PARAMETER.findall(data.decode("utf-8", "replace")):
        if name in seen:
            continue
        seen.add(name)
        default = (default or "").strip()
        if what == "String":
            default = default.strip('"')
        elif what == "Color":
            default = " ".join(part.strip() for part in default.split(","))
        found.append((name, what.lower(), default))
    return found
