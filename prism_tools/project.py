"""Where things are: in the Prism repository when the .blend is in one, and beside the .blend when it is not (a modeller's
machine has no repository: the game is the web build, and what is exported goes into a `Content` folder by the scene)."""
import os
import shutil
import tempfile

import bpy

PACKAGE = __package__
# Where the web build is served for the team (Web/README.md): what a machine without the repository plays the scene in.
DEFAULT_RUNTIME = "https://prism.type.link"


def root():
    """The repository: PRISM_ROOT, the folders above this .blend, or the one in the add-on's preferences."""
    env = os.environ.get("PRISM_ROOT")
    if env:
        return env
    path = bpy.data.filepath
    while path and os.path.dirname(path) != path:
        path = os.path.dirname(path)
        if os.path.exists(os.path.join(path, "project.yml")) and os.path.isdir(os.path.join(path, "Content")):
            return path
    addon = bpy.context.preferences.addons.get(PACKAGE)
    return bpy.path.abspath(addon.preferences.project_root) if addon and addon.preferences.project_root else ""


def preferences():
    addon = bpy.context.preferences.addons.get(PACKAGE)
    return addon.preferences if addon else None


def content(r=None):
    """Where 'Export' writes: the repository's Content/, or a Content folder beside the .blend."""
    r = r or root()
    if r:
        return os.path.join(r, "Content")
    blend = bpy.data.filepath
    return os.path.join(os.path.dirname(blend), "Content") if blend else ""


def runtime():
    """Where the web build comes from, a folder or an address: PRISM_RUNTIME, the preferences, the repository's own pack when
    it has one, or the team's address."""
    prefs = preferences()
    chosen = (os.environ.get("PRISM_RUNTIME") or (prefs.runtime if prefs else "") or "").strip()
    if chosen:
        return chosen if chosen.startswith(("http://", "https://")) else bpy.path.abspath(chosen)
    r = root()
    local = os.path.join(r, "build", "web", "site") if r else ""
    return local if local and os.path.exists(os.path.join(local, "index.html")) else DEFAULT_RUNTIME


def runtime_cache():
    """Where the web build's files are kept once fetched from an address."""
    try:
        return bpy.utils.extension_path_user(PACKAGE, path="runtime", create=True)
    except (AttributeError, ValueError, OSError):
        return os.path.join(tempfile.gettempdir(), "prism-runtime")


def game_data(r=None):
    return os.path.join(r or root(), "game-data")


def products(r=None):
    return os.path.join(r or root(), "build", "Build", "Products", "Release")


def tool(r=None):
    return os.path.join(products(r), "prism")


def app(r=None):
    return os.path.join(products(r), "Prism.app", "Contents", "MacOS", "Prism")


def shaders(r=None):
    return os.path.join(r or root(), "Engine", "Render", "Shaders")


def scratch_overlay(name):
    """A copy of Content/ to export into: what is being tried does not touch tracked files until 'Export'."""
    r = root()
    target = os.path.join(r, "out", name)
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(content(r), target)
    return target


def own_files():
    """Without a repository: what the modeller keeps in the Content folder by the scene (scripts of obstacles of their own,
    rooms written by hand, sounds), path -> file. In a repository the web build already holds its Content."""
    if root():
        return {}
    base = content()
    found = {}
    if base and os.path.isdir(base):
        for folder, _, names in os.walk(base):
            for name in names:
                if not name.startswith("."):
                    path = os.path.join(folder, name)
                    found[os.path.relpath(path, base).replace(os.sep, "/")] = path
    return found


def exists_in_content(rel):
    """Whether the game would find this file. Without a repository that is known once the web build's content is on this
    machine (after the first time the scene was opened in a browser); until then nothing is held against the scene."""
    r = root()
    if r:
        return os.path.exists(os.path.join(content(r), rel)) or os.path.exists(os.path.join(game_data(r), rel))
    from . import web
    if rel in own_files():
        return True
    base = web.base_files(web.runtime() or web.Runtime(runtime(), runtime_cache()))
    return True if base is None else rel in base


def base_names(folder, ext):
    """Names of the game's files below `folder` ending in `ext`, without either: the obstacles there are, the music."""
    r = root()
    names = set()
    if r:
        for base in (content(r), game_data(r)):
            top = os.path.join(base, folder)
            for where, _, files in os.walk(top):
                for f in files:
                    if f.endswith(ext):
                        names.add(os.path.relpath(os.path.join(where, f), top).replace(os.sep, "/")[:-len(ext)])
    else:
        from . import web
        base = web.base_files(web.runtime() or web.Runtime(runtime(), runtime_cache())) or {}
        for rel in list(base) + list(own_files()):
            if rel.startswith(folder + "/") and rel.endswith(ext):
                names.add(rel[len(folder) + 1:-len(ext)])
    return sorted(names)


def read_base(rel):
    """Bytes of one of the game's files, or None."""
    r = root()
    if r:
        for base in (content(r), game_data(r)):
            path = os.path.join(base, rel)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    return f.read()
        return None
    own = own_files().get(rel)
    if own:
        with open(own, "rb") as f:
            return f.read()
    from . import web
    return web.base_read(rel, web.runtime() or web.Runtime(runtime(), runtime_cache()))


class PrismPreferences(bpy.types.AddonPreferences):
    bl_idname = PACKAGE
    project_root: bpy.props.StringProperty(name="Prism repository", subtype='DIR_PATH',
                                           description="Only for .blend files kept outside the repository")
    runtime: bpy.props.StringProperty(name="Web build", description="Where the game for the browser comes from: an address or a folder "
                                      f"that has it. Empty: the repository's own, or {DEFAULT_RUNTIME}")
    browser_port: bpy.props.IntProperty(name="Browser port", default=47812, min=1024, max=65500,
                                        description="The scene is served to the browser on this port of this machine")

    def draw(self, context):
        self.layout.prop(self, "runtime")
        self.layout.prop(self, "browser_port")
        self.layout.prop(self, "project_root")
