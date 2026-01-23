"""
Tool Generator for converting discovered functions to tool schemas.

Automatically generates JSON Schema parameters and descriptions from
function signatures and docstrings.
"""

import re
from dataclasses import dataclass
from typing import Optional

from django_agent_runtime.dynamic_tools.scanner import FunctionInfo


@dataclass
class GeneratedToolSchema:
    """A generated tool schema ready for storage."""
    name: str
    description: str
    parameters_schema: dict
    function_path: str
    source_file: str
    source_line: int
    is_safe: bool
    requires_confirmation: bool
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'description': self.description,
            'parameters_schema': self.parameters_schema,
            'function_path': self.function_path,
            'source_file': self.source_file,
            'source_line': self.source_line,
            'is_safe': self.is_safe,
            'requires_confirmation': self.requires_confirmation,
        }


class ToolGenerator:
    """
    Generates tool schemas from discovered functions.
    
    Converts function signatures and docstrings into JSON Schema
    format suitable for LLM tool calling.
    """
    
    # Python type to JSON Schema type mapping
    TYPE_MAPPING = {
        'str': 'string',
        'string': 'string',
        'int': 'integer',
        'integer': 'integer',
        'float': 'number',
        'number': 'number',
        'bool': 'boolean',
        'boolean': 'boolean',
        'list': 'array',
        'List': 'array',
        'dict': 'object',
        'Dict': 'object',
        'None': 'null',
        'NoneType': 'null',
        'Any': 'string',  # Default to string for Any
    }
    
    def __init__(
        self,
        default_requires_confirmation: bool = True,
        name_prefix: str = "",
        name_suffix: str = "",
    ):
        """
        Initialize the generator.
        
        Args:
            default_requires_confirmation: Default value for requires_confirmation
            name_prefix: Prefix to add to tool names
            name_suffix: Suffix to add to tool names
        """
        self.default_requires_confirmation = default_requires_confirmation
        self.name_prefix = name_prefix
        self.name_suffix = name_suffix
    
    def generate(self, func_info: FunctionInfo) -> GeneratedToolSchema:
        """
        Generate a tool schema from a function info.
        
        Args:
            func_info: FunctionInfo from the scanner
            
        Returns:
            GeneratedToolSchema ready for storage
        """
        # Generate tool name
        name = self._generate_name(func_info)
        
        # Generate description from docstring
        description = self._generate_description(func_info)
        
        # Generate parameters schema
        parameters_schema = self._generate_parameters_schema(func_info)
        
        # Determine safety
        is_safe = not func_info.has_side_effects
        requires_confirmation = (
            self.default_requires_confirmation or func_info.has_side_effects
        )
        
        return GeneratedToolSchema(
            name=name,
            description=description,
            parameters_schema=parameters_schema,
            function_path=func_info.function_path,
            source_file=func_info.file_path,
            source_line=func_info.line_number,
            is_safe=is_safe,
            requires_confirmation=requires_confirmation,
        )
    
    def generate_batch(
        self, functions: list[FunctionInfo]
    ) -> list[GeneratedToolSchema]:
        """Generate tool schemas for multiple functions."""
        return [self.generate(f) for f in functions]
    
    def _generate_name(self, func_info: FunctionInfo) -> str:
        """Generate a tool name from function info."""
        # Use function name, converting to snake_case if needed
        name = func_info.name
        
        # If it's a method, include class name
        if func_info.class_name:
            name = f"{func_info.class_name.lower()}_{name}"
        
        # Apply prefix/suffix
        if self.name_prefix:
            name = f"{self.name_prefix}_{name}"
        if self.name_suffix:
            name = f"{name}_{self.name_suffix}"
        
        # Ensure valid tool name (alphanumeric and underscores only)
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        name = re.sub(r'_+', '_', name)  # Remove duplicate underscores
        name = name.strip('_')
        
        return name
    
    def _generate_description(self, func_info: FunctionInfo) -> str:
        """Generate a description from function docstring."""
        if func_info.docstring:
            # Parse docstring - get first paragraph
            lines = func_info.docstring.strip().split('\n\n')
            description = lines[0].strip()
            
            # Clean up whitespace
            description = ' '.join(description.split())
            
            return description
        
        # Generate description from function name
        name = func_info.name
        # Convert snake_case to words
        words = name.replace('_', ' ')
        return f"Execute {words}"

    def _generate_parameters_schema(self, func_info: FunctionInfo) -> dict:
        """Generate JSON Schema for function parameters."""
        properties = {}
        required = []

        for param in func_info.parameters:
            param_name = param.get('name', '')

            # Skip *args and **kwargs
            if param_name.startswith('*'):
                continue

            param_schema = self._generate_parameter_schema(param, func_info.docstring)
            properties[param_name] = param_schema

            # Add to required if no default
            if not param.get('has_default', False):
                required.append(param_name)

        schema = {
            'type': 'object',
            'properties': properties,
        }

        if required:
            schema['required'] = required

        return schema

    def _generate_parameter_schema(
        self, param: dict, docstring: str
    ) -> dict:
        """Generate JSON Schema for a single parameter."""
        param_name = param.get('name', '')
        annotation = param.get('annotation', '')
        default = param.get('default')

        # Determine JSON Schema type
        json_type = self._python_type_to_json_type(annotation)

        schema = {'type': json_type}

        # Try to extract description from docstring
        description = self._extract_param_description(param_name, docstring)
        if description:
            schema['description'] = description

        # Add default if present
        if default is not None and default != 'None':
            try:
                # Try to evaluate simple defaults
                if default in ('True', 'False'):
                    schema['default'] = default == 'True'
                elif default.isdigit():
                    schema['default'] = int(default)
                elif default.replace('.', '').isdigit():
                    schema['default'] = float(default)
                elif default.startswith(("'", '"')) and default.endswith(("'", '"')):
                    schema['default'] = default[1:-1]
            except Exception:
                pass

        # Handle array types
        if json_type == 'array' and annotation:
            items_type = self._extract_array_items_type(annotation)
            if items_type:
                schema['items'] = {'type': items_type}

        return schema

    def _python_type_to_json_type(self, annotation: str) -> str:
        """Convert Python type annotation to JSON Schema type."""
        if not annotation:
            return 'string'  # Default to string

        # Handle Optional types
        if annotation.startswith('Optional['):
            inner = annotation[9:-1]
            return self._python_type_to_json_type(inner)

        # Handle Union types (simplified)
        if annotation.startswith('Union['):
            # Take first non-None type
            inner = annotation[6:-1]
            types = [t.strip() for t in inner.split(',')]
            for t in types:
                if t != 'None':
                    return self._python_type_to_json_type(t)

        # Handle List/Dict with type params
        base_type = annotation.split('[')[0].strip()

        return self.TYPE_MAPPING.get(base_type, 'string')

    def _extract_array_items_type(self, annotation: str) -> Optional[str]:
        """Extract the items type from a List annotation."""
        if '[' in annotation and ']' in annotation:
            inner = annotation[annotation.index('[') + 1:annotation.rindex(']')]
            return self._python_type_to_json_type(inner)
        return None

    def _extract_param_description(
        self, param_name: str, docstring: str
    ) -> Optional[str]:
        """Extract parameter description from docstring."""
        if not docstring:
            return None

        # Try Google-style docstring
        # Args:
        #     param_name: Description
        pattern = rf'{param_name}\s*:\s*(.+?)(?:\n\s*\w+\s*:|$)'
        match = re.search(pattern, docstring, re.DOTALL)
        if match:
            desc = match.group(1).strip()
            # Clean up multi-line descriptions
            desc = ' '.join(desc.split())
            return desc

        # Try NumPy-style docstring
        # param_name : type
        #     Description
        pattern = rf'{param_name}\s*:\s*\w+\s*\n\s+(.+?)(?:\n\w|\n\n|$)'
        match = re.search(pattern, docstring, re.DOTALL)
        if match:
            desc = match.group(1).strip()
            desc = ' '.join(desc.split())
            return desc

        return None
