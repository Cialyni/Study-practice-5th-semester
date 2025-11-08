import logging
from typing import Dict, List, Optional
import requests
import base64
import tomlkit


def update_project_dependencies(
    api_url: str,
    headers: Dict,
    timeout: int,
    project_id: int,
    dependencies: List[str],
    project_urls: Dict[str, str],
):
    try:
        current_content = get_pyproject_toml(api_url, headers, timeout, project_id)
        if current_content is None:
            return

        updated_content = update_toml_dependencies(
            current_content, dependencies, project_urls
        )
        commit_changes(api_url, headers, timeout, project_id, updated_content)

    except requests.exceptions.RequestException as e:
        logging.error(f"Error updating dependencies for project {project_id}: {e}")


def get_pyproject_toml(
    api_url: str, headers: Dict, timeout: int, project_id: int
) -> Optional[str]:
    response = requests.get(
        f"{api_url}/projects/{project_id}/repository/files/pyproject.toml",
        headers=headers,
        params={"ref": "main"},
        timeout=timeout,
    )

    if response.status_code == 200:
        content_b64 = response.json()["content"]
        return base64.b64decode(content_b64).decode("utf-8")
    else:
        logging.error(
            f"Could not get pyproject.toml for project {project_id}: {response.status_code}"
        )
        return None


def update_toml_dependencies(
    content: str, dependencies: List[str], project_urls: Dict[str, str]
) -> str:
    doc = tomlkit.parse(content)

    deps_array = tomlkit.array()
    for dep in dependencies:
        if dep in project_urls:
            deps_array.append(f"{dep} @ git+{project_urls[dep]}@main")

    doc["project"]["dependencies"] = deps_array

    return tomlkit.dumps(doc)


def get_dependencies_in_group(
    api_url: str, headers: Dict, timeout: int, group_id: int
) -> Dict[str, List[str]]:
    try:
        dependencies: Dict[str, List[str]] = {}
        response = requests.get(
            f"{api_url}/groups/{group_id}/projects",
            headers=headers,
            timeout=timeout,
        )
        projects_response = response.json()
        if response.status_code == 200:
            logging.info(f"get all project in group with id={group_id}")
            for project in projects_response:
                project_toml = get_pyproject_toml(
                    api_url, headers, timeout, project["id"]
                )
                if project_toml is None:
                    logging.warning(
                        f"pyproject.toml not found in {project['name']} (ID: {project['id']})"
                    )
                    dependencies[project["name"]] = []
                    continue
                doc = tomlkit.parse(project_toml)
                project_dependencies = doc.get("project", {}).get("dependencies", [])
                dependencies[project["name"]] = [
                    dep.split("@")[0][:-1] for dep in project_dependencies
                ]
        else:
            logging.error(
                f"Could not get all project in group with id={group_id}: {response.status_code}"
            )
            return dependencies
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error while fetching group {group_id}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error in group {group_id}: {e}")

    return dependencies


def commit_changes(
    api_url: str, headers: Dict, timeout: int, project_id: int, updated_content: str
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

    response = requests.post(
        f"{api_url}/projects/{project_id}/repository/commits",
        headers=headers,
        json=commit_data,
        timeout=timeout,
    )

    if response.status_code == 201:
        logging.info(f"Updated dependencies for project {project_id}")
    else:
        logging.error(
            f"Failed to update dependencies for project {project_id}: {response.status_code}"
        )


def build_module_map(dependencies: Dict[str, List[str]]) -> str:
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
    print(
        get_dependencies_in_group(
            group_id=25,
            timeout=30,
            api_url="http://localhost/api/v4",
            headers={
                "Authorization": f"Bearer glpat-pimIytXp1Xe5InFb8CA8Sm86MQp1OjEH.01.0w0jl0003",
                "Content-Type": "application/json",
            },
        )
    )
    print(
        build_module_map(
            get_dependencies_in_group(
                group_id=25,
                timeout=30,
                api_url="http://localhost/api/v4",
                headers={
                    "Authorization": f"Bearer glpat-pimIytXp1Xe5InFb8CA8Sm86MQp1OjEH.01.0w0jl0003",
                    "Content-Type": "application/json",
                },
            )
        )
    )
