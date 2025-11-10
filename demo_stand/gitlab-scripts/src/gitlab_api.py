from dataclasses import dataclass
from pathlib import Path
import requests
import os
from dotenv import load_dotenv
import base64
import sys
import logging
from typing import List, Optional, Dict, Any


script_path = Path(__file__)
env_path = script_path.parent.parent.parent / ".env"
load_dotenv(env_path)


class GitLabAPI:
    def __init__(self, base_url: str = None, timeout: int = 30):
        self.base_url = base_url or os.getenv("GITLAB_BASE_URL")
        self.api_url = f"{self.base_url}/api/v4"
        self.timeout = timeout
        self.token = os.getenv("GITLAB_ACCESS_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        if not self.token:
            logging.error("GITLAB_ACCESS_TOKEN environment variable is not set")
            raise ValueError("GITLAB_ACCESS_TOKEN is required")

        if not self._check_connection():
            raise ConnectionError("Failed to connect to GitLab")

    def _check_connection(self) -> bool:
        try:
            response = requests.get(
                f"{self.api_url}/user", headers=self.headers, timeout=self.timeout
            )
            if response.status_code == 200:
                logging.info("Connected to GitLab")
                return True
            else:
                logging.error(f"Failed to connect to GitLab: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Connection error: {e}")
            return False

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        url = f"{self.api_url}{endpoint}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers={**self.headers, **kwargs.pop("headers", {})},
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json() if response.content else None
        except Exception as e:
            logging.error(f"GitLab API error {method} {endpoint}: {e}")
            raise

    def _get(self, endpoint: str, **kwargs) -> Any:
        return self._request("GET", endpoint, **kwargs)

    def _post(self, endpoint: str, **kwargs) -> Any:
        return self._request("POST", endpoint, **kwargs)

    def _put(self, endpoint: str, **kwargs) -> Any:
        return self._request("PUT", endpoint, **kwargs)

    def _delete(self, endpoint: str, **kwargs) -> Any:
        return self._request("DELETE", endpoint, **kwargs)

    def get_all_projects_from_group(self, group_id: int) -> List[Dict[str, Any]]:
        projects = self._get(f"/groups/{group_id}/projects")
        return projects

    def get_project(self, project_id: int) -> Dict[str, Any]:
        project = self._get(f"/projects/{project_id}")
        return project

    def get_user_namespace(self) -> Optional[int]:
        user_data = self._get(f"/user")
        namespace_id = user_data.get("namespace_id") if user_data else None
        return namespace_id

    def get_group(self, group_id: int) -> Dict[str, Any]:
        group = self._get(f"/groups/{group_id}")
        return group

    def get_pyproject_toml(self, project_id: int, ref: str = "main") -> Optional[str]:
        try:
            file_data = self._get(
                f"/projects/{project_id}/repository/files/pyproject.toml",
                params={"ref": ref},
            )
            logging.debug(
                f"Received pyproject.toml from project id={project_id}, ref: {ref}"
            )
            return base64.b64decode(file_data["content"]).decode("utf-8")
        except Exception as e:
            logging.error(
                f"Error with getting pyproject.toml from project id={project_id}: {e}"
            )
            return None

    def fork_project(self, project_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._post(f"/projects/{project_id}/fork", json=data)

    def create_group(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._post(f"/groups", json=data)

    def add_user_to_group(self, group_id: int, data: Any) -> Dict[str, Any]:
        result = self._post(f"/groups/{group_id}/members", json=data)
        return result

    def commit_changes(self, project_id: int, data: Any) -> Dict[str, Any]:
        commit = self._post(f"/projects/{project_id}/repository/commits", json=data)
        logging.info(
            f"Created commit in project id={project_id}: {commit.get('id')} - {commit.get('title')}"
        )
        return commit

    def remove_fork(self, project_id: int):
        try:
            self._delete(f"/projects/{project_id}/fork")
            logging.info(f"Fork relationship removed for project id={project_id}")
        except Exception as e:
            logging.debug(f"Error removing fork for project id={project_id}: {e}")
