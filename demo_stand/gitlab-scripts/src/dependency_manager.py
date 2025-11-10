from dataclasses import dataclass
from pathlib import Path
import logging
import os
import sys
import requests
import base64
import tomlkit
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from gitlab_api import GitLabAPI


script_path = Path(__file__)
env_path = script_path.parent.parent.parent / ".env"
load_dotenv(env_path)


@dataclass
class ProjectInfo:
    name: str
    url: str
    dependencies: List[str]


class DependencyManager:

    def __init__(self, group_id=None):
        self.api = GitLabAPI()
        self._projects: Dict[int, ProjectInfo] = {}

        if group_id:
            self._projects = self._load_group_projects(group_id)
        else:
            logging.error("DependencyManager didn't get group_id.")
            raise ValueError

    def _load_group_projects(self, group_id: int) -> Dict[int, ProjectInfo]:
        try:
            projects = {}
            projects_response: List[Dict[str, any]] = (
                self.api.get_all_projects_from_group(group_id)
            )
            dependencies: Dict[str, Optional[List[str]]] = (
                self._parse_dependencies_from_response(projects_response)
            )
            for proj_repsonse in projects_response:
                name = proj_repsonse["name"]
                url = proj_repsonse["http_url_to_repo"]
                dep = dependencies.get(name, [])
                id = proj_repsonse["id"]
                project_info = ProjectInfo(name, url, dep)
                projects[id] = project_info
            logging.info(f"Loaded {len(projects)} projects from group {group_id}")
            return projects
        except Exception as e:
            logging.error(f"Failed to load projects from group {group_id}: {e}")
            raise

    def _parse_dependencies_from_response(
        self, response: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        dependencies: Dict[str, List[str]] = {}

        for project in response:
            project_toml = self.api.get_pyproject_toml(project["id"])

            if project_toml is None:
                logging.warning(
                    f"pyproject.toml not found in {project['name']}, id={project['id']})"
                )
                dependencies[project["name"]] = []
                continue
            doc = tomlkit.parse(project_toml)
            project_dependencies = doc.get("project", {}).get("dependencies", [])
            dependencies[project["name"]] = [
                dep.split("@")[0].strip() for dep in project_dependencies
            ]
        return dependencies

    def init_project_dependencies(self, project_id: int, dependencies: List[str]):
        try:
            self._projects[project_id].dependencies = dependencies
            current_content = self.api.get_pyproject_toml(project_id)
            if current_content is None:
                logging.warning(f"pyproject.toml for project id={project_id} is None")
                return

            updated_content = self._update_toml_dependencies(
                current_content, project_id
            )
            self._commit_changes(project_id, updated_content)

        except Exception as e:
            logging.error(f"Error updating dependencies for project {project_id}: {e}")

    def _update_toml_dependencies(self, content: str, project_id: int) -> str:
        doc = tomlkit.parse(content)

        doc["project"]["name"] = self._projects[project_id].name
        dependencies = self._projects[project_id].dependencies
        deps_array = tomlkit.array()
        for dep_name in dependencies:
            dep_url = self._find_dependency_url(dep_name)
            if dep_url:
                deps_array.append(f"{dep_name} @ git+{dep_url}@main")
            else:
                logging.warning(f"Dependency '{dep_name}' not found in group")

        doc["project"]["dependencies"] = deps_array

        return tomlkit.dumps(doc)

    def _find_dependency_url(self, dep_name: str) -> Optional[str]:
        for project_info in self._projects.values():
            if project_info.name == dep_name:
                return project_info.url
        return None

    def _commit_changes(
        self,
        project_id: int,
        updated_content: str,
    ):
        commit_data = {
            "branch": "main",
            "commit_message": "Update dependencies from config",
            "actions": [
                {
                    "action": "update",
                    "file_path": "pyproject.toml",
                    "content": updated_content,
                }
            ],
        }

        self.api.commit_changes(project_id, commit_data)

    def build_module_map(self) -> str:
        dependencies: Dict[str, List[str]] = {}
        for project in self._projects.values():
            dependencies[project.name] = project.dependencies

        mermaid_lines = [
            "graph TD",
            "classDef root fill:#dcfce7,stroke:#22c55e,color:#166534,stroke-width:2px",
            "classDef middle fill:#fef3c7,stroke:#f59e0b,color:#92400e,stroke-width:2px",
            "classDef leaf fill:#fee2e2,stroke:#ef4444,color:#991b1b,stroke-width:3px",
        ]

        root_modules = [key for key, deps in dependencies.items() if not deps]
        all_deps = {dep for deps_list in dependencies.values() for dep in deps_list}
        leaf_modules = set(dependencies.keys()) - all_deps

        for module in sorted(set(dependencies.keys())):
            if module in root_modules:
                mermaid_lines.append(f"{module}:::root")
            elif module in leaf_modules:
                mermaid_lines.append(f"{module}:::leaf")
            else:
                mermaid_lines.append(f"{module}:::middle")

        for module, deps in dependencies.items():
            for dep in deps:
                mermaid_lines.append(f"{dep} --> {module}")

        return "\n".join(mermaid_lines)


if __name__ == "__main__":
    """dp = DependencyManager(30) # test value for existing test group
    mrm = dp.build_module_map()
    print(mrm)"""
