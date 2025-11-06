import logging
from typing import Dict, List, Optional
import requests
import base64
import tomlkit


def update_project_dependencies(api_url: str, headers: Dict, timeout: int, project_id: int, dependencies: List[str], project_urls: Dict[str, str]):
    try:
        current_content = get_pyproject_toml(api_url, headers, timeout, project_id)
        if current_content is None:
            return

        updated_content = update_toml_dependencies(current_content, dependencies, project_urls)
        commit_changes(api_url, headers, timeout, project_id, updated_content)
        
    except requests.exceptions.RequestException as e:
        logging.error(f"Error updating dependencies for project {project_id}: {e}")


def get_pyproject_toml(api_url: str, headers: Dict, timeout: int, project_id: int) -> Optional[str]:
    response = requests.get(
        f"{api_url}/projects/{project_id}/repository/files/pyproject.toml",
        headers=headers,
        params={"ref": "main"},
        timeout=timeout
    )
    
    if response.status_code == 200:
        content_b64 = response.json()['content']
        return base64.b64decode(content_b64).decode('utf-8')
    else:
        logging.error(f"Could not get pyproject.toml for project {project_id}: {response.status_code}")
        return None

def update_toml_dependencies(content: str, dependencies: List[str], project_urls: Dict[str, str]) -> str:
    doc = tomlkit.parse(content)
    
    deps_array = tomlkit.array()
    for dep in dependencies:
        if dep in project_urls:
            deps_array.append(f"{dep} @ git+{project_urls[dep]}.git@main")
    
    doc['project']['dependencies'] = deps_array
    
    return tomlkit.dumps(doc)

def commit_changes(api_url: str, headers: Dict, timeout: int, project_id: int, updated_content: str):
    commit_data = {
        "branch": "main",
        "commit_message": "Update dependencies from config",
        "actions": [{
            "action": "update",
            "file_path": "pyproject.toml",
            "content": updated_content
        }]
    }
    
    response = requests.post(
        f"{api_url}/projects/{project_id}/repository/commits",
        headers=headers,
        json=commit_data,
        timeout=timeout
    )
    
    if response.status_code == 201:
        logging.info(f"Updated dependencies for project {project_id}")
    else:
        logging.error(f"Failed to update dependencies for project {project_id}: {response.status_code}")