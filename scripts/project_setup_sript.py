import requests
import os
import sys
import logging
import time
from typing import Optional, Dict, Any

class GitLabProjectCreator:
    def __init__(self, base_url: str = None, timeout: int = 30):
        self.base_url = base_url or os.getenv("GITLAB_BASE_URL", "http://localhost")
        self.api_url = f"{self.base_url}/api/v4"
        self.timeout = timeout
        self.token = os.getenv("GITLAB_ACCESS_TOKEN")
        
        if not self.token:
            logging.error("GITLAB_ACCESS_TOKEN environment variable is not set")
            sys.exit(1)
            
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        if not self._check_connection():
            sys.exit(1)
    
    def _check_connection(self) -> bool:
        try:
            response = requests.get(
                f"{self.api_url}/user",
                headers=self.headers,
                timeout=self.timeout
            )
            if response.status_code == 200:
                logging.info("Connected to GitLab successfully")
                return True
            else:
                logging.error(f"Failed to connect to GitLab: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Connection error: {e}")
            return False

    def create_project_from_template(self, new_project_name: str, template_project_id: int) -> Optional[Dict[str, Any]]:
        """Создает проект из шаблона через FORK (работает в GitLab CE)"""
        
        namespace_id = self._get_user_namespace()
        if not namespace_id:
            logging.error("Could not get user namespace")
            return None
        
        data = {
            "name": new_project_name,
            "namespace_id": namespace_id,
            "path": new_project_name.lower().replace(" ", "-")
        }
        
        logging.info(f"Creating project '{new_project_name}' from template ID: {template_project_id}")
        
        try:
            # Используем FORK API
            response = requests.post(
                f"{self.api_url}/projects/{template_project_id}/fork",
                headers=self.headers,
                json=data,
                timeout=self.timeout
            )
            
            if response.status_code in [200, 201]:
                project = response.json()
                logging.info(f"✅ Project created successfully: {project['web_url']}")
                
                # Опционально: удаляем связь с оригиналом если нужен независимый проект
                self._remove_fork_relationship(project['id'])
                
                return project
            else:
                logging.error(f"❌ Failed to create project: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Network error: {e}")
            return None

    def _get_user_namespace(self) -> Optional[int]:
        """Получает namespace ID текущего пользователя"""
        try:
            response = requests.get(
                f"{self.api_url}/user", 
                headers=self.headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json().get("namespace_id")
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to get user info: {e}")
            return None

    def _remove_fork_relationship(self, project_id: int):
        """Удаляет связь форка (делает проект независимым)"""
        try:
            response = requests.delete(
                f"{self.api_url}/projects/{project_id}/fork",
                headers=self.headers,
                timeout=self.timeout
            )
            if response.status_code == 204:
                logging.info("Fork relationship removed - project is now independent")
            else:
                logging.debug(f"Could not remove fork relationship: {response.status_code}")
        except Exception as e:
            logging.debug(f"Error removing fork relationship: {e}")

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    template_id = os.getenv("GITLAB_TEMPLATE_ID")
    if not template_id:
        logging.error("GITLAB_TEMPLATE_ID environment variable is required")
        sys.exit(1)
    
    creator = GitLabProjectCreator()
    project_name = os.getenv("PROJECT_NAME", "project-from-template")
    
    result = creator.create_project_from_template(
        new_project_name=project_name,
        template_project_id=int(template_id)
    )

    if result:
        logging.info(f"🎉 Project creation completed successfully: {result['web_url']}")
    else:
        logging.error("❌ Project creation failed")
        sys.exit(1)

if __name__ == "__main__":
    main()