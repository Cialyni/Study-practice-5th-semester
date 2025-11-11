import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import tomlkit
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
        self._group_id = group_id

        if group_id:
            self._projects = self._load_group_projects(group_id)
        else:
            logging.error("DependencyManager didn't get group_id")
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
                projects[id] = ProjectInfo(name, url, dep)

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
            dependencies[project["name"]] = project_dependencies
        return dependencies

    def _refresh_projects_data(self):
        if not self.group_id:
            return
        try:
            self._projects = self._load_group_projects(self.group_id)
            logging.info("Refreshed projects data from GitLab")
        except Exception as e:
            logging.error(f"Error refreshing projects data: {e}")

    def init_project_dependencies(self, project_id: int, dependencies: List[str]):
        try:
            self._projects[project_id].dependencies = dependencies
            current_content = self.api.get_pyproject_toml(project_id)
            if current_content is None:
                logging.warning(f"pyproject.toml for project id={project_id} is None")
                return

            doc = tomlkit.parse(current_content)
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

            updated_content = tomlkit.dumps(doc)
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

        except Exception as e:
            logging.error(f"Error updating dependencies for project {project_id}: {e}")

    def _find_dependency_url(self, dep_name: str) -> Optional[str]:
        for project_info in self._projects.values():
            if project_info.name == dep_name:
                return project_info.url
        return None

    def _get_depended_projects_id(
        self,
        project_name: str,
    ) -> List[int]:
        depended_projects = []
        for id, project in self._projects.items():
            for dep in project.dependencies:
                if project_name in dep:
                    depended_projects.append(id)
        return depended_projects

    def update_all_direct_dependencies(self, package_info: Dict[str, Any]):
        self._refresh_projects_data()
        depended_projects = self._get_depended_projects_id(package_info["name"])
        for proj_id in depended_projects:
            branch_name = (
                f"auto-update-{package_info['name']}-{package_info['version']}"
            )
            self.api.create_branch(proj_id, branch_name, "main")
            content = self.api.get_pyproject_toml(proj_id, branch_name)
            updated_content = self._update_toml_dependencies(
                content, package_info["name"], package_info["version"]
            )
            self._create_commit_for_toml_updation(
                proj_id, updated_content, branch=branch_name
            )

            tag_name = f"v{package_info['version']}-mr-auto"
            self.api.create_tag(proj_id, tag_name, branch_name)
            mr_data = {
                "source_branch": branch_name,
                "target_branch": "main",
                "title": f"Update {package_info['name']}",
                "remove_source_branch": True,
            }

            mr_response = self.api.create_merge_request(proj_id, mr_data)
            logging.info(
                f"Сreated MR for {self._projects[proj_id].name}: {mr_response.get('web_url')}"
            )

    def _update_toml_dependencies(
        self, content: str, package_name: str, package_version: str
    ) -> str:
        doc = tomlkit.parse(content)
        deps_array = doc["project"]["dependencies"]
        updated_deps_array = tomlkit.array()
        for dep in deps_array:
            dep_str = str(dep).strip()

            if dep_str.startswith(f"{package_name} @ git+"):
                updated_dep = f"{package_name}>={package_version}"
                logging.info(
                    f"Rewrite dependency from GitLab to Nexus: {dep} -> {updated_dep}"
                )

            elif dep_str.startswith(f"{package_name}>="):
                updated_dep = f"{package_name}>={package_version}"
                logging.info(f"Nexus version update: {dep} -> {updated_dep}")

            elif dep_str.startswith(f"{package_name}=="):
                updated_dep = f"{package_name}>={package_version}"
                logging.info(f"Nexus version update: {dep} -> {updated_dep}")

            else:
                updated_dep = dep

            updated_deps_array.append(updated_dep)

        doc["project"]["dependencies"] = updated_deps_array
        updated_content = tomlkit.dumps(doc)
        return updated_content

    def _create_commit_for_toml_updation(
        self,
        project_id: int,
        updated_content: str,
        commit_message: str = "Update pyproject.toml",
        branch: str = "main",
    ):
        commit_data = {
            "branch": branch,
            "commit_message": commit_message,
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
