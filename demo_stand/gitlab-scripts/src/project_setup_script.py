import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from dependency_manager import DependencyManager
from dotenv import load_dotenv
from gitlab_api import GitLabAPI

script_path = Path(__file__)
env_path = script_path.parent.parent.parent / ".env"
load_dotenv(env_path)


class GitLabProjectCreator:
    def __init__(
        self,
    ):
        self.user_id = os.getenv("GITLAB_USER_ID")
        self.api = GitLabAPI()

        if not self.user_id:
            logging.error("GITLAB_USER_ID environment variable is not set")
            sys.exit(1)

    def create_project_from_template(
        self,
        new_project_name: str,
        template_project_id: int,
        group_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:

        try:
            data = {
                "name": new_project_name,
                "path": new_project_name.lower().replace(" ", "-"),
            }
            if group_id:
                data["namespace_id"] = group_id
            else:
                namespace_id = self.api.get_user_namespace()
                if namespace_id:
                    data["namespace_id"] = namespace_id
            project = self.api.fork_project(template_project_id, data)
            logging.info(
                f"{new_project_name} created from template: {project['web_url']}"
            )
            self.api.remove_fork(project["id"])
            return project

        except Exception as e:
            logging.error(f"Failed to create {new_project_name}: {e}")
            return None

    def _create_group(
        self, group_name: str, visibility: str = "private"
    ) -> Optional[int]:
        try:
            data = {
                "name": group_name,
                "path": group_name.lower().replace(" ", "-"),
                "visibility": visibility,
            }
            group = self.api.create_group(data)
            logging.info(f"Group created: {group['web_url']}, id={group['id']}")
            return group["id"]
        except Exception as e:
            logging.error(f"Could not create group {group_name}: {e}")
            return None

    def _get_group(self, group_id: int) -> Optional[Dict[str, Any]]:
        try:
            group = self.api.get_group(group_id)
            logging.info(f"Get group: {group.get('name')}, id={group_id}")
            return group
        except Exception as e:
            logging.error(f"Could not get group {group_id}: {e}")
            return None

    def _add_user_to_group(self, group_id: int, access_level: int = 40) -> bool:
        try:
            data = {"user_id": self.user_id, "access_level": access_level}
            self.api.add_user_to_group(group_id, data)
            logging.info(f"Added user {self.user_id} to group {group_id}")
            return True
        except Exception as e:
            logging.error(f"Could not add user to group {group_id}: {e}")
            return False

    def create_modules_from_config(
        self, config: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        group_id = config.get("group_id")
        group_name = config.get("group_name")

        if group_id is None:
            group_id = self._create_group(group_name)
            if group_id is None:
                return [], None
        else:
            group = self._get_group(group_id)
            if not group:
                return [], None

        if not self._add_user_to_group(group_id):
            logging.warning(
                f"Failed to add user to group id={group_id}, the structure will be created, but the projects will not be modified"
            )
        template_id = config.get("template_id")

        if not template_id:
            logging.error("Template ID is required in config")
            return [], None

        created_modules = []

        for module_config in config.get("modules", []):
            module_name = module_config["name"]
            logging.info(f"Creating module: {module_name}")

            project = self.create_project_from_template(
                new_project_name=module_name,
                template_project_id=template_id,
                group_id=group_id,
            )

            if project:
                module_info = {
                    "id": project["id"],
                    "dependencies": module_config.get("dependencies", []),
                }
                created_modules.append(module_info)
                logging.info(f"Created module: {module_name}")
            else:
                logging.error(f"Failed to create module: {module_name}")

        return created_modules, group_id

    def write_dependencies_in_toml(self, group_id: int, modules: List[Dict[str, Any]]):
        if not modules:
            logging.warning("No modules to update dependencies for")
            return
        try:
            dp_manager = DependencyManager(group_id)

            for module_info in modules:
                dp_manager.init_project_dependencies(
                    module_info["id"],
                    module_info["dependencies"],
                )
            logging.info("All dependencies updated")
        except Exception as e:
            logging.error(
                f"Failed to update dependencies for modules in group id={group_id}: {e}"
            )


def load_config():
    try:
        script_path = Path(__file__)
        project_root = script_path.parent.parent
        config_path = project_root / "config.yaml"
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise Exception("Config file not found") from None
    except yaml.YAMLError as e:
        raise Exception(f"Invalid YAML format: {e}") from None
    except Exception as e:
        logging.error(f"Some error loading config: {e}")
        raise


def main():
    config = load_config()
    creator = GitLabProjectCreator()
    created_modules, group_id = creator.create_modules_from_config(config)

    if created_modules:
        creator.write_dependencies_in_toml(group_id, created_modules)
        logging.info(f"Created and configured {len(created_modules)} modules")
    else:
        logging.error("No modules were created")
        sys.exit(1)


if __name__ == "__main__":
    main()
