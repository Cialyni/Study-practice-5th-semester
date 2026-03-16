import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from .dependency_manager import DependencyManager
from dotenv import load_dotenv
from .gitlab_api import GitLabAPI

script_path = Path(__file__)
env_path = script_path.parent.parent.parent / ".env"
load_dotenv(env_path)


class GitLabProjectCreator:
    def __init__(self):
        self.user_id = os.getenv("GITLAB_USER_ID")
        self.group_id = os.getenv("GROUP_ID")  
        self.api = GitLabAPI()

        if not self.user_id:
            logging.error("GITLAB_USER_ID environment variable is not set")
            sys.exit(1)
        
        if not self.group_id:
            logging.error("GROUP_ID environment variable is not set. Run TestStandSetup first!")
            sys.exit(1)

    def create_project_from_template(
        self,
        new_project_name: str,
        template_project_id: int,
    ) -> Optional[Dict[str, Any]]:
        try:
            data = {
                "name": new_project_name,
                "path": new_project_name.lower().replace(" ", "-"),
                "namespace_id": self.group_id, 
            }
            project = self.api.fork_project(template_project_id, data)
            logging.info(f"{new_project_name} created from template: {project['web_url']}")
            self.api.remove_fork(project["id"])
            return project
        except Exception as e:
            logging.error(f"Failed to create {new_project_name}: {e}")
            return None

    def create_modules_from_config(
        self, config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        template_id = config.get("template_id")

        if not template_id:
            logging.error("Template ID is required in config")
            return []

        created_modules = []

        for module_config in config.get("modules", []):
            module_name = module_config["name"]
            logging.info(f"Creating module: {module_name}")

            project = self.create_project_from_template(
                new_project_name=module_name,
                template_project_id=template_id,
            )

            if project:
                module_info = {
                    "id": project["id"],
                    "name": module_name,
                    "dependencies": module_config.get("dependencies", []),
                }
                created_modules.append(module_info)
                logging.info(f"Created module: {module_name}")
            else:
                logging.error(f"Failed to create module: {module_name}")

        return created_modules

    def write_dependencies_in_toml(self, modules: List[Dict[str, Any]]):
        if not modules:
            logging.warning("No modules to update dependencies for")
            return
        try:
            dp_manager = DependencyManager(int(self.group_id))
            
            for module_info in modules:
                if module_info["id"] in dp_manager._projects:
                    dp_manager._projects[module_info["id"]].name = module_info["name"]
                    
            for module_info in modules:
                dp_manager.init_project_dependencies(
                    module_info["id"],
                    module_info["dependencies"],
                )
            logging.info("All dependencies updated")
        except Exception as e:
            logging.error(f"Failed to update dependencies for modules in group id={self.group_id}: {e}")


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
    created_modules = creator.create_modules_from_config(config)

    if created_modules:
        creator.write_dependencies_in_toml(created_modules)
        logging.info(f"Created and configured {len(created_modules)} modules")
    else:
        logging.error("No modules were created")
        sys.exit(1)


if __name__ == "__main__":
    main()