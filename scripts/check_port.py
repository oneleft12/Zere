#!/usr/bin/env python3
"""Сквозная проверка Python-порта ZERE.

1) py_compile всех файлов пакета zere/ и main.py.
2) AST-проверка: каждый `from zere.X import Y` ссылается на существующий
   модуль, и каждый импортируемый символ где-то определён в пакете.
3) Сверка контрактов main.py: наличие обязательных символов.
"""

from __future__ import annotations

import ast
import py_compile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "zere"

errors: list[str] = []

# --- 1. py_compile ---------------------------------------------------------
py_files = sorted(PKG.rglob("*.py")) + [ROOT / "main.py", ROOT / "zere" / "paths.py"]
seen: set[Path] = set()
for f in py_files:
    if f in seen or "__pycache__" in str(f):
        continue
    seen.add(f)
    try:
        py_compile.compile(str(f), doraise=True)
    except py_compile.PyCompileError as e:
        errors.append(f"[py_compile] {e}")

# --- 2. Сбор определений и импортов ---------------------------------------
definitions: dict[str, set[str]] = {}  # module dotted -> names defined at top level
imports: list[tuple[str, str | None, str]] = []  # (module, name|None, file)

for f in sorted(seen):
    if not f.exists() or f.name == "paths.py" and f.parent.name != "zere":
        continue
    try:
        tree = ast.parse(f.read_text(encoding="utf-8"))
    except SyntaxError as e:
        errors.append(f"[ast] {f}: {e}")
        continue

    rel = f.relative_to(ROOT)
    if rel.parts[-1] == "paths.py" and rel.parts[0] == "zere" and len(rel.parts) == 2:
        mod = "zere.paths"
    elif rel.parts[0] == "zere":
        mod = ".".join(rel.with_suffix("").parts)
        if mod.endswith(".__init__"):
            mod = mod[: -len(".__init__")]
    else:
        mod = "main" if rel.name == "main.py" else str(rel)

    defs = definitions.setdefault(mod, set())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.startswith("zere"):
                for alias in node.names:
                    imports.append((node.module, alias.name, str(rel)))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            pass
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defs.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defs.add(node.target.id)

# all_names: symbol -> modules where defined
all_names: dict[str, set[str]] = {}
for mod, names in definitions.items():
    for n in names:
        all_names.setdefault(n, set()).add(mod)

for module, name, src in imports:
    if module not in definitions:
        # maybe importing a name directly from package root re-export
        errors.append(f"[import] {src}: модуль `{module}` не найден")
        continue
    if name == "*":
        continue
    # `from zere import paths` — импорт подмодуля, а не символа
    if f"{module}.{name}" in definitions:
        continue
    if name and name not in definitions[module]:
        # разрешим, если символ определён в другом модуле и re-export (from X import Y в __init__)
        if name in all_names:
            continue  # символ существует где-то в пакете — допустимо через re-export
        errors.append(f"[import] {src}: `{name}` не определён в `{module}`")

# --- 3. Контракты main.py --------------------------------------------------
main_src = (ROOT / "main.py").read_text(encoding="utf-8")
main_tree = ast.parse(main_src)
main_imports = {
    (n.module, a.name)
    for n in ast.walk(main_tree)
    if isinstance(n, ast.ImportFrom) and n.module
    for a in n.names
}

required = [
    ("zere.core.configuration.zere_config", "ZereConfig"),
    ("zere.core.dependencies.dependency_checker", "DependencyChecker"),
    ("zere.core.engine", "ZereEngine"),
    ("zere.core.logging.log_service", "LogService"),
    ("zere.core.plugins.plugin_config", "PluginConfig"),
    ("zere.core.plugins.plugin_manager", "PluginManager"),
    ("zere.core.plugins.settings.settings_menu", "SettingsMenu"),
    ("zere.core.services", "create_services"),
    ("zere.memory.database.memory_database", "MemoryDatabase"),
    ("zere.voice.voice_manager", "VoiceManager"),
]
for mod, name in required:
    if (mod, name) not in main_imports:
        errors.append(f"[main] нет импорта `{name}` из `{mod}`")
    elif mod not in definitions:
        errors.append(f"[main] модуль `{mod}` ещё не создан")
    elif name not in definitions.get(mod, set()) and name not in all_names.get(name, set()):
        errors.append(f"[main] `{name}` не определён в `{mod}`")

# --- Отчёт -----------------------------------------------------------------
print(f"Файлов проверено: {len(seen)}")
print(f"Модулей zere: {len([m for m in definitions if m.startswith('zere')])}")
if errors:
    print(f"\nОШИБКИ ({len(errors)}):")
    for e in errors:
        print("  " + e)
    sys.exit(1)
print("\nВсе проверки пройдены.")
