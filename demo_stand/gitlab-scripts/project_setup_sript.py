import requests
import os
from dotenv import load_dotenv
import sys
import logging
import yaml
from typing import List, Optional, Dict, Any
from dependency_manager import *

load_dotenv('../.env')


class GitLabProjectCreator:
    def __init__(self, base_url: str = None, timeout: int = 30):
        self.base_url = base_url or os.getenv("GITLAB_BASE_URL")
        self.api_url = f"{self.base_url}/api/v4"
        self.timeout = timeout
        self.token = os.getenv("GITLAB_ACCESS_TOKEN")
        self.user_id = os.getenv("GITLAB_USER_ID")

        if not self.token:
            logging.error("GITLAB_ACCESS_TOKEN environment variable is not set")
            sys.exit(1)

        if not self.user_id:
            logging.error("GITLAB_USER_ID environment variable is not set")
            sys.exit(1)

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        if not self._check_connection():
            sys.exit(1)

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

    def create_project_from_template(
        self, new_project_name: str, template_project_id: int, group_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        print(f"DEBUG: group_id = {group_id}") 
        data = {
            "name": new_project_name,
            "path": new_project_name.lower().replace(" ", "-"),
        }

        logging.info(
            f"Creating project '{new_project_name}' from template id: {template_project_id}"
        )

        if group_id:
            data["namespace_id"] = group_id
            print(f"DEBUG: Using namespace_id = {group_id}")
        else:
            namespace_id = self._get_user_namespace()
            print(f"DEBUG: User namespace_id = {namespace_id}")
            if namespace_id:
                data["namespace_id"] = namespace_id

        try:
            response = requests.post(
                f"{self.api_url}/projects/{template_project_id}/fork",
                headers=self.headers,
                json=data,
                timeout=self.timeout,
            )

            if response.status_code in [200, 201]:
                project = response.json()
                logging.info(f"Project created: {project['web_url']}")

                self._remove_fork(project["id"])
                return project
            else:
                logging.error(
                    f"Failed to create project: {response.status_code} - {response.text}"
                )
                return None

        except requests.exceptions.RequestException as e:
            logging.error(f"Network error: {e}")
            return None

    def _get_user_namespace(self) -> Optional[int]:
        try:
            response = requests.get(
                f"{self.api_url}/user", headers=self.headers, timeout=self.timeout
            )
            response.raise_for_status()
            return response.json().get("namespace_id")
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to get user info: {e}")
            return None

    def _remove_fork(self, project_id: int):
        try:
            response = requests.delete(
                f"{self.api_url}/projects/{project_id}/fork",
                headers=self.headers,
                timeout=self.timeout,
            )
            if response.status_code == 204:
                logging.info("Fork relationship removed")
            else:
                logging.debug(f"Could not remove fork: {response.status_code}")
        except Exception as e:
            logging.debug(f"Error removing fork: {e}")

    def _create_group(self, group_name: str, visibility: str = "private") -> Optional[int]:
        try:

            data = {
                "name": group_name,
                "path": group_name.lower().replace(" ", "-"),
                "visibility": visibility
            }
            
            response = requests.post(f"{self.api_url}/groups", headers=self.headers, json=data, timeout=self.timeout)
            print(response)
            if response.status_code == 201:
                group = response.json()
                logging.info(f"Group created: {group['web_url']}. Id: {group['id']}")
                return group["id"]        
            else:
                logging.error(f"Could not create group: {response.status_code} - {response.text}")
            return None
        
        except Exception as e:
            logging.error(f"Could not create group: {e}")
            return None

    def _get_group(self, group_id: int) -> Optional[Dict[str, Any]]:
        try:
            response = requests.get(
                f"{self.api_url}/groups/{group_id}",
                headers=self.headers,
                timeout=self.timeout
            )
            if response.status_code == 200:
                return response.json()
            else:
                logging.error(f"Could not find group with id={group_id}: {response.status_code}")
                return None
        except Exception as e:
            logging.error(f"Could not find group with id={group_id}: {e}")
            return None
        
    def _add_user_to_group(self, group_id: int, access_level: int = 40):
        data = {
            "user_id": self.user_id,
            "access_level": access_level
        }
        
        response = requests.post(
            f"{self.api_url}/groups/{group_id}/members",
            headers=self.headers,
            json=data
        )
        
        if response.status_code == 201:
            logging.info(f"Added user {self.user_id} to group {group_id} with access level {access_level}")
        else:
            logging.error(f"Failed to add user to group: {response.status_code}")

    def create_modules_from_config(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        group_id = config.get('group_id')
        group_name = config.get('group_name')
        if group_id is None:
            group_id = self._create_group(group_name)
            if group_id is None:
                logging.error("Failed to create group")
                return []
        else:
            group = self._get_group(group_id)
            if not group:
                logging.error(f"Group with id {group_id} not found")
                return []
            
        self._add_user_to_group(group_id)
        template_id = config.get('template_id')
        
        if not template_id:
            logging.error("Template ID is required in config")
            return []

        created_modules = []
        
        for module_config in config.get('modules', []):  
            module_name = module_config['name'] 
            logging.info(f"Creating module: {module_name}")
            

            project = self.create_project_from_template(
                new_project_name=module_name,
                template_project_id=template_id,
                group_id=group_id
            )
            
            if project:
                module_info = {
                    'name': module_name,
                    'project': project, 
                    'dependencies': module_config.get('dependencies', []),  
                    'description': module_config.get('description', '')  
                }
                created_modules.append(module_info)
                logging.info(f"Created module: {module_name}")
            else:
                logging.error(f"Failed to create module: {module_name}")

        return created_modules
    
    def update_dependencies(self, created_modules: List[Dict[str, Any]]):
        if not created_modules:
            logging.warning("No modules to update dependencies for")
            return
            
        modules_url = {m['name']: m['project']['http_url_to_repo'] for m in created_modules}
        
        for module_info in created_modules:
            if module_info['dependencies']:
                update_project_dependencies(
                    api_url=self.api_url,
                    headers=self.headers, 
                    timeout=self.timeout,
                    project_id=module_info['project']['id'],  
                    dependencies=module_info['dependencies'],
                    project_urls=modules_url
                )

def load_config():
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, 'config.yaml')
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise Exception("Config file not found") from None
    except yaml.YAMLError as e:
        raise Exception(f"Invalid YAML format: {e}") from None

def main():
    logging.basicConfig(
        level=logging.INFO, 
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    config = load_config()
    creator = GitLabProjectCreator()
    created_modules = creator.create_modules_from_config(config)
    
    if created_modules:
        creator.update_dependencies(created_modules)
        logging.info(f"Created and configured {len(created_modules)} modules")
    else:
        logging.error("No modules were created")
        sys.exit(1)

if __name__ == "__main__":
    main()