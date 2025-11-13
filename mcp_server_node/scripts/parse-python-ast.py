#!/usr/bin/env python3
"""
Python AST Parser for Neo4j Graph Ingestion

Extracts code structure from Python files:
- Function definitions (name, parameters, return type hints, decorators)
- Class definitions (name, base classes, methods)
- Import statements (module, items, aliases)
- Function calls (caller context, callee name, line number)

Output: JSON format for consumption by CodeStructureIngester.js
"""

import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional


class PythonASTParser(ast.NodeVisitor):
    """Extract structural information from Python AST"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.functions: List[Dict[str, Any]] = []
        self.classes: List[Dict[str, Any]] = []
        self.imports: List[Dict[str, Any]] = []
        self.calls: List[Dict[str, Any]] = []
        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None
        
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Extract function/method definitions"""
        func_info = {
            'name': node.name,
            'line_number': node.lineno,
            'end_line': node.end_lineno,
            'parameters': [arg.arg for arg in node.args.args],
            'decorators': [self._get_decorator_name(dec) for dec in node.decorator_list],
            'is_async': False,
            'is_method': self.current_class is not None,
            'class_name': self.current_class,
            'docstring': ast.get_docstring(node)
        }
        
        # Extract return type hint if present
        if node.returns:
            func_info['return_type'] = self._get_type_annotation(node.returns)
        
        self.functions.append(func_info)
        
        # Track context for nested calls
        previous_function = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = previous_function
        
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Extract async function definitions"""
        func_info = {
            'name': node.name,
            'line_number': node.lineno,
            'end_line': node.end_lineno,
            'parameters': [arg.arg for arg in node.args.args],
            'decorators': [self._get_decorator_name(dec) for dec in node.decorator_list],
            'is_async': True,
            'is_method': self.current_class is not None,
            'class_name': self.current_class,
            'docstring': ast.get_docstring(node)
        }
        
        if node.returns:
            func_info['return_type'] = self._get_type_annotation(node.returns)
        
        self.functions.append(func_info)
        
        previous_function = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = previous_function
        
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Extract class definitions"""
        class_info = {
            'name': node.name,
            'line_number': node.lineno,
            'end_line': node.end_lineno,
            'base_classes': [self._get_base_class_name(base) for base in node.bases],
            'decorators': [self._get_decorator_name(dec) for dec in node.decorator_list],
            'docstring': ast.get_docstring(node)
        }
        
        self.classes.append(class_info)
        
        # Track context for methods
        previous_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = previous_class
        
    def visit_Import(self, node: ast.Import) -> None:
        """Extract import statements"""
        for alias in node.names:
            import_info = {
                'type': 'import',
                'module': alias.name,
                'alias': alias.asname,
                'line_number': node.lineno
            }
            self.imports.append(import_info)
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Extract from...import statements"""
        module = node.module or ''
        for alias in node.names:
            import_info = {
                'type': 'from_import',
                'module': module,
                'name': alias.name,
                'alias': alias.asname,
                'line_number': node.lineno,
                'level': node.level  # Relative import level (0 = absolute)
            }
            self.imports.append(import_info)
        self.generic_visit(node)
        
    def visit_Call(self, node: ast.Call) -> None:
        """Extract function calls"""
        callee_name = self._get_call_name(node.func)
        
        if callee_name:
            call_info = {
                'callee': callee_name,
                'line_number': node.lineno,
                'caller_function': self.current_function,
                'caller_class': self.current_class,
                'num_args': len(node.args),
                'num_kwargs': len(node.keywords)
            }
            self.calls.append(call_info)
        
        self.generic_visit(node)
        
    def _get_decorator_name(self, node: ast.expr) -> str:
        """Extract decorator name"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_attr_chain(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return self._get_call_name(node.func)
        return str(node)
        
    def _get_base_class_name(self, node: ast.expr) -> str:
        """Extract base class name"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_attr_chain(node.value)}.{node.attr}"
        return str(node)
        
    def _get_type_annotation(self, node: ast.expr) -> str:
        """Extract type annotation as string"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_attr_chain(node.value)}.{node.attr}"
        elif isinstance(node, ast.Subscript):
            return f"{self._get_type_annotation(node.value)}[...]"
        return "Any"
        
    def _get_call_name(self, node: ast.expr) -> Optional[str]:
        """Extract function call name"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_attr_chain(node.value)}.{node.attr}"
        return None
        
    def _get_attr_chain(self, node: ast.expr) -> str:
        """Recursively extract attribute chain (e.g., 'self.config.value')"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_attr_chain(node.value)}.{node.attr}"
        return "?"


def parse_python_file(file_path: str) -> Dict[str, Any]:
    """
    Parse Python file and extract code structure
    
    Args:
        file_path: Path to Python source file
        
    Returns:
        Dictionary with functions, classes, imports, and calls
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
            
        tree = ast.parse(source, filename=file_path)
        parser = PythonASTParser(file_path)
        parser.visit(tree)
        
        return {
            'file_path': file_path,
            'success': True,
            'functions': parser.functions,
            'classes': parser.classes,
            'imports': parser.imports,
            'calls': parser.calls,
            'stats': {
                'num_functions': len(parser.functions),
                'num_classes': len(parser.classes),
                'num_imports': len(parser.imports),
                'num_calls': len(parser.calls)
            }
        }
        
    except SyntaxError as e:
        return {
            'file_path': file_path,
            'success': False,
            'error': 'syntax_error',
            'error_message': str(e),
            'line_number': e.lineno
        }
    except Exception as e:
        return {
            'file_path': file_path,
            'success': False,
            'error': 'parse_error',
            'error_message': str(e)
        }


def main():
    """CLI entry point for parsing Python files"""
    if len(sys.argv) < 2:
        print(json.dumps({
            'error': 'Usage: parse-python-ast.py <file_path> [<file_path> ...]'
        }))
        sys.exit(1)
    
    results = []
    for file_path in sys.argv[1:]:
        result = parse_python_file(file_path)
        results.append(result)
    
    # Output JSON to stdout for Node.js consumption
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
