"""
Django Project Scanner for discovering functions and methods.

Uses AST parsing to safely analyze Python files without executing them.
"""

import ast
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from django.apps import apps
from django.conf import settings


@dataclass
class ParameterInfo:
    """Information about a function parameter."""
    name: str
    annotation: Optional[str] = None
    default: Optional[str] = None
    has_default: bool = False
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'annotation': self.annotation,
            'default': self.default,
            'has_default': self.has_default,
        }


@dataclass
class FunctionInfo:
    """Information about a discovered function."""
    name: str
    module_path: str
    function_path: str
    function_type: str
    file_path: str
    line_number: int
    signature: str
    docstring: str = ""
    class_name: str = ""
    parameters: list = field(default_factory=list)
    return_type: str = ""
    is_async: bool = False
    has_side_effects: bool = False
    is_private: bool = False
    decorators: list = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'module_path': self.module_path,
            'function_path': self.function_path,
            'function_type': self.function_type,
            'file_path': self.file_path,
            'line_number': self.line_number,
            'signature': self.signature,
            'docstring': self.docstring,
            'class_name': self.class_name,
            'parameters': [p.to_dict() if hasattr(p, 'to_dict') else p for p in self.parameters],
            'return_type': self.return_type,
            'is_async': self.is_async,
            'has_side_effects': self.has_side_effects,
            'is_private': self.is_private,
            'decorators': self.decorators,
        }


class ProjectScanner:
    """
    Scans a Django project to discover functions and methods.
    
    Uses AST parsing for safe code analysis without execution.
    """
    
    # Patterns that suggest side effects
    SIDE_EFFECT_PATTERNS = [
        'save', 'delete', 'create', 'update', 'write', 'send', 'post',
        'put', 'patch', 'remove', 'add', 'insert', 'modify', 'set_',
    ]
    
    # Django-specific patterns
    DJANGO_VIEW_DECORATORS = [
        'api_view', 'login_required', 'permission_required',
        'require_http_methods', 'csrf_exempt', 'cache_page',
    ]
    
    def __init__(
        self,
        project_root: Optional[str] = None,
        include_private: bool = False,
        include_tests: bool = False,
        app_filter: Optional[list] = None,
    ):
        """
        Initialize the scanner.
        
        Args:
            project_root: Root directory of the Django project
            include_private: Whether to include private functions (starting with _)
            include_tests: Whether to include test files
            app_filter: List of app names to scan (None = all apps)
        """
        self.project_root = Path(project_root or settings.BASE_DIR)
        self.include_private = include_private
        self.include_tests = include_tests
        self.app_filter = app_filter
        self.scan_session = str(uuid.uuid4())[:8]
    
    def scan(self) -> list[FunctionInfo]:
        """
        Scan the Django project and return discovered functions.
        
        Returns:
            List of FunctionInfo objects
        """
        discovered = []
        
        # Get Django apps to scan
        app_configs = self._get_apps_to_scan()
        
        for app_config in app_configs:
            app_path = Path(app_config.path)
            if not app_path.exists():
                continue
            
            # Scan Python files in the app
            for py_file in app_path.rglob('*.py'):
                # Skip tests if not included
                if not self.include_tests and self._is_test_file(py_file):
                    continue
                
                # Skip migrations
                if 'migrations' in py_file.parts:
                    continue
                
                functions = self._scan_file(py_file, app_config.name)
                discovered.extend(functions)

        return discovered

    def scan_directory(self, directory: str) -> list[FunctionInfo]:
        """
        Scan a specific directory for functions.

        Args:
            directory: Path to directory to scan

        Returns:
            List of FunctionInfo objects
        """
        discovered = []
        dir_path = Path(directory)

        if not dir_path.exists():
            return discovered

        for py_file in dir_path.rglob('*.py'):
            if not self.include_tests and self._is_test_file(py_file):
                continue
            if 'migrations' in py_file.parts:
                continue

            # Derive module path from file path
            rel_path = py_file.relative_to(self.project_root)
            module_path = str(rel_path.with_suffix('')).replace(os.sep, '.')

            functions = self._scan_file(py_file, module_path.split('.')[0])
            discovered.extend(functions)

        return discovered

    def _get_apps_to_scan(self):
        """Get list of Django apps to scan."""
        all_apps = apps.get_app_configs()

        if self.app_filter:
            return [a for a in all_apps if a.name in self.app_filter]

        # Filter to only project apps (not third-party)
        project_apps = []
        for app in all_apps:
            app_path = Path(app.path)
            try:
                app_path.relative_to(self.project_root)
                project_apps.append(app)
            except ValueError:
                # App is outside project root (third-party)
                pass

        return project_apps

    def _is_test_file(self, file_path: Path) -> bool:
        """Check if a file is a test file."""
        name = file_path.name
        return (
            name.startswith('test_') or
            name.endswith('_test.py') or
            name == 'tests.py' or
            'tests' in file_path.parts
        )

    def _scan_file(self, file_path: Path, app_name: str) -> list[FunctionInfo]:
        """Scan a single Python file for functions."""
        discovered = []

        try:
            source = file_path.read_text(encoding='utf-8')
            tree = ast.parse(source, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError) as e:
            # Skip files that can't be parsed
            return discovered

        # Calculate module path
        try:
            rel_path = file_path.relative_to(self.project_root)
            module_path = str(rel_path.with_suffix('')).replace(os.sep, '.')
        except ValueError:
            module_path = app_name

        # Scan top-level functions
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_info = self._extract_function_info(
                    node, module_path, str(file_path), None
                )
                if func_info and self._should_include(func_info):
                    discovered.append(func_info)

            elif isinstance(node, ast.ClassDef):
                # Scan class methods
                class_functions = self._scan_class(
                    node, module_path, str(file_path)
                )
                discovered.extend(class_functions)

        return discovered

    def _scan_class(
        self, class_node: ast.ClassDef, module_path: str, file_path: str
    ) -> list[FunctionInfo]:
        """Scan a class for methods."""
        discovered = []
        class_name = class_node.name

        # Determine class type
        is_model = self._is_django_model(class_node)
        is_view = self._is_django_view(class_node)
        is_manager = self._is_django_manager(class_node)

        for node in ast.iter_child_nodes(class_node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip magic methods except __call__
                if node.name.startswith('__') and node.name != '__call__':
                    continue

                func_info = self._extract_function_info(
                    node, module_path, file_path, class_name
                )
                if func_info:
                    # Set function type based on class type
                    if is_model:
                        func_info.function_type = 'model_method'
                    elif is_view:
                        func_info.function_type = 'view'
                    elif is_manager:
                        func_info.function_type = 'manager_method'
                    else:
                        func_info.function_type = 'method'

                    if self._should_include(func_info):
                        discovered.append(func_info)

        return discovered

    def _extract_function_info(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        module_path: str,
        file_path: str,
        class_name: Optional[str],
    ) -> Optional[FunctionInfo]:
        """Extract function information from an AST node."""
        name = node.name
        is_async = isinstance(node, ast.AsyncFunctionDef)
        is_private = name.startswith('_')

        # Build function path
        if class_name:
            function_path = f"{module_path}.{class_name}.{name}"
        else:
            function_path = f"{module_path}.{name}"

        # Extract parameters
        parameters = self._extract_parameters(node.args)

        # Extract return type
        return_type = ""
        if node.returns:
            return_type = self._annotation_to_string(node.returns)

        # Build signature string
        signature = self._build_signature(name, parameters, return_type, is_async)

        # Extract docstring
        docstring = ast.get_docstring(node) or ""

        # Extract decorators
        decorators = [self._decorator_to_string(d) for d in node.decorator_list]

        # Determine function type
        if class_name:
            function_type = 'method'
        elif any(d in decorators for d in self.DJANGO_VIEW_DECORATORS):
            function_type = 'view'
        else:
            function_type = 'function'

        # Check for side effects
        has_side_effects = self._detect_side_effects(name, node, docstring)

        return FunctionInfo(
            name=name,
            module_path=module_path,
            function_path=function_path,
            function_type=function_type,
            file_path=file_path,
            line_number=node.lineno,
            signature=signature,
            docstring=docstring,
            class_name=class_name or "",
            parameters=[p.to_dict() for p in parameters],
            return_type=return_type,
            is_async=is_async,
            has_side_effects=has_side_effects,
            is_private=is_private,
            decorators=decorators,
        )

    def _extract_parameters(self, args: ast.arguments) -> list[ParameterInfo]:
        """Extract parameter information from function arguments."""
        parameters = []

        # Calculate defaults offset
        num_args = len(args.args)
        num_defaults = len(args.defaults)
        defaults_offset = num_args - num_defaults

        for i, arg in enumerate(args.args):
            # Skip 'self' and 'cls'
            if arg.arg in ('self', 'cls'):
                continue

            annotation = None
            if arg.annotation:
                annotation = self._annotation_to_string(arg.annotation)

            default = None
            has_default = False
            default_idx = i - defaults_offset
            if default_idx >= 0 and default_idx < len(args.defaults):
                default = self._value_to_string(args.defaults[default_idx])
                has_default = True

            parameters.append(ParameterInfo(
                name=arg.arg,
                annotation=annotation,
                default=default,
                has_default=has_default,
            ))

        # Handle *args and **kwargs
        if args.vararg:
            parameters.append(ParameterInfo(
                name=f"*{args.vararg.arg}",
                annotation=self._annotation_to_string(args.vararg.annotation) if args.vararg.annotation else None,
            ))

        if args.kwarg:
            parameters.append(ParameterInfo(
                name=f"**{args.kwarg.arg}",
                annotation=self._annotation_to_string(args.kwarg.annotation) if args.kwarg.annotation else None,
            ))

        return parameters

    def _annotation_to_string(self, node: ast.expr) -> str:
        """Convert an annotation AST node to string."""
        if node is None:
            return ""
        try:
            return ast.unparse(node)
        except Exception:
            return ""

    def _value_to_string(self, node: ast.expr) -> str:
        """Convert a value AST node to string."""
        try:
            return ast.unparse(node)
        except Exception:
            return "..."

    def _decorator_to_string(self, node: ast.expr) -> str:
        """Convert a decorator AST node to string."""
        try:
            return ast.unparse(node)
        except Exception:
            return ""

    def _build_signature(
        self,
        name: str,
        parameters: list[ParameterInfo],
        return_type: str,
        is_async: bool,
    ) -> str:
        """Build a function signature string."""
        params = []
        for p in parameters:
            param_str = p.name
            if p.annotation:
                param_str += f": {p.annotation}"
            if p.has_default:
                param_str += f" = {p.default}"
            params.append(param_str)

        sig = f"{'async ' if is_async else ''}def {name}({', '.join(params)})"
        if return_type:
            sig += f" -> {return_type}"
        return sig

    def _detect_side_effects(
        self, name: str, node: ast.FunctionDef, docstring: str
    ) -> bool:
        """Detect if a function likely has side effects."""
        # Check name patterns
        name_lower = name.lower()
        for pattern in self.SIDE_EFFECT_PATTERNS:
            if pattern in name_lower:
                return True

        # Check docstring for side effect indicators
        doc_lower = docstring.lower()
        side_effect_words = ['creates', 'updates', 'deletes', 'modifies', 'writes', 'sends']
        for word in side_effect_words:
            if word in doc_lower:
                return True

        return False

    def _is_django_model(self, class_node: ast.ClassDef) -> bool:
        """Check if a class is a Django model."""
        for base in class_node.bases:
            base_str = self._annotation_to_string(base)
            if 'Model' in base_str or 'models.Model' in base_str:
                return True
        return False

    def _is_django_view(self, class_node: ast.ClassDef) -> bool:
        """Check if a class is a Django view."""
        for base in class_node.bases:
            base_str = self._annotation_to_string(base)
            if 'View' in base_str or 'APIView' in base_str:
                return True
        return False

    def _is_django_manager(self, class_node: ast.ClassDef) -> bool:
        """Check if a class is a Django manager."""
        for base in class_node.bases:
            base_str = self._annotation_to_string(base)
            if 'Manager' in base_str or 'QuerySet' in base_str:
                return True
        return False

    def _should_include(self, func_info: FunctionInfo) -> bool:
        """Determine if a function should be included in results."""
        if not self.include_private and func_info.is_private:
            return False
        return True

