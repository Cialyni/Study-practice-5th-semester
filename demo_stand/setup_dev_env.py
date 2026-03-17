import time
import requests
import subprocess
import base64
from pathlib import Path


def send_token_to_webhook(token):
    try:
        response = requests.post(
            "http://localhost:8000/reload-token", json={"new_token": token}, timeout=2
        )
        if response.status_code == 200:
            print("  Token sent to webhook")
    except Exception as e:
        print(f"  Failed to send token to webhook: {e}")


class TestStandSetup:
    def __init__(self):
        self.gitlab_url = "http://localhost:8080"
        self.gitlab_internal_url = "http://gitlab:80"
        self.nexus_url = "http://localhost:8081"
        self.gitlab_token = None

    def wait_for_service(self, url, name, max_attempts=30):
        print(f"Waiting for {name}")
        for i in range(max_attempts):
            try:
                if requests.get(url, timeout=5).status_code == 200:
                    print(f"  {name} ready")
                    return True
            except:
                time.sleep(5)
        return False

    def get_gitlab_root_password(self):
        result = subprocess.run(
            ["docker", "exec", "gitlab", "cat", "/etc/gitlab/initial_root_password"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.split("\n"):
            if "Password:" in line:
                return line.split("Password:")[-1].strip()

    def create_gitlab_token(self):
        cmd = [
            "docker",
            "exec",
            "gitlab",
            "gitlab-rails",
            "runner",
            "user = User.find_by_username('root'); "
            "token = user.personal_access_tokens.create("
            "scopes: ['api', 'read_repository', 'write_repository'], "
            "name: 'dev-token', expires_at: 365.days.from_now); "
            "token.save!; puts token.token",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.gitlab_token = result.stdout.strip()
        print(f"  Token created")
        send_token_to_webhook(self.gitlab_token)
        return self.gitlab_token

    def setup_nexus(self):
        print("Setting up Nexus:")

        self.wait_for_service(
            f"{self.nexus_url}/service/rest/v1/status", "Nexus API", 60
        )

        session = requests.Session()
        session.auth = ("admin", "admin123")

        try:
            session.post(
                f"{self.nexus_url}/service/rest/internal/ui/onboarding/onboarding-wizard",
                json={"skip": True},
            )
        except:
            pass

        repo_data = {
            "name": "test-repo",
            "online": True,
            "storage": {
                "blobStoreName": "default",
                "writePolicy": "ALLOW",
                "strictContentTypeValidation": True,
            },
        }

        response = session.post(
            f"{self.nexus_url}/service/rest/v1/repositories/pypi/hosted", json=repo_data
        )

        if response.status_code == 201:
            print("  Repository created")
        elif response.status_code == 409:
            print("  Repository already exists")
        else:
            print(f"  Failed: {response.status_code}")
            print(f"  Response: {response.text}")

        webhook_data = {
            "type": "webhook.repository",
            "enabled": True,
            "properties": {
                "repository": "test-repo",
                "names": "asset",
                "url": "http://webhook-app:8000/webhook/nexus",
            },
        }

        webhook_response = session.post(
            f"{self.nexus_url}/service/rest/v1/capabilities", json=webhook_data
        )

        if webhook_response.status_code == 201:
            print("  Webhook created")
        else:
            print(f"  Webhook status: {webhook_response.status_code}")
            print(f"  Response: {webhook_response.text}")

        self.nexus_password = "admin123"
        print("  Nexus setup complete")
        return True

    def register_runner(self):
        print("Registering GitLab Runner:")

        networks = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
        )

        network_name = "ts-net"
        for net in networks.stdout.split("\n"):
            if net.endswith("_ts-net") or net == "ts-net":
                network_name = net
                break

        result = subprocess.run(
            [
                "docker",
                "exec",
                "gitlab",
                "gitlab-rails",
                "runner",
                "puts Gitlab::CurrentSettings.current_application_settings.runners_registration_token",
            ],
            capture_output=True,
            text=True,
        )
        token = result.stdout.strip()
        print(f"  Token obtained: {token[:8]}...")

        cmd = [
            "docker",
            "exec",
            "gitlab-runner",
            "gitlab-runner",
            "register",
            "--non-interactive",
            "--url",
            "http://gitlab:80",
            "--registration-token",
            token,
            "--executor",
            "docker",
            "--docker-image",
            "python:3.12",
            "--description",
            "auto-runner",
            "--tag-list",
            "docker,automated",
            "--run-untagged=true",
            "--locked=false",
            "--docker-volumes",
            "/var/run/docker.sock:/var/run/docker.sock",
            "--docker-network-mode",
            network_name,
            "--docker-privileged",
            "true",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print("  Runner registered successfully!")
        else:
            print(f"  Error: {result.stderr}")

    def create_group(self):
        headers = {"PRIVATE-TOKEN": self.gitlab_token}

        group_data = {"name": "my-org", "path": "my-org", "visibility": "internal"}

        response = requests.post(
            f"{self.gitlab_url}/api/v4/groups", headers=headers, json=group_data
        )

        group_id = response.json()["id"]
        print(f"  Group created, ID: {group_id}")
        return group_id

    def setup_group_variables(self, group_id):
        headers = {"PRIVATE-TOKEN": self.gitlab_token}

        variables = [
            {"key": "NEXUS_URL", "value": "http://nexus:8081/repository/test-repo/"},
            {"key": "NEXUS_USER", "value": "admin"},
            {"key": "NEXUS_PASSWORD", "value": "admin123"},
        ]

        for var in variables:
            requests.post(
                f"{self.gitlab_url}/api/v4/groups/{group_id}/variables",
                headers=headers,
                json=var,
            )
            print(f"    Created {var['key']}")

    def setup_project_in_group(self, group_id):
        headers = {"PRIVATE-TOKEN": self.gitlab_token}

        project_data = {
            "name": "python-module-template",
            "namespace_id": group_id,
            "visibility": "internal",
            "initialize_with_readme": "false",
        }

        response = requests.post(
            f"{self.gitlab_url}/api/v4/projects", headers=headers, json=project_data
        )

        project_id = response.json()["id"]
        print(f"  Project created in group, ID: {project_id}")

        template_path = Path("gitlab-stand")
        for file_path in template_path.rglob("*"):
            if not file_path.is_file():
                continue

            rel_path = file_path.relative_to(template_path)
            with open(file_path, "rb") as f:
                content = f.read()

            file_data = {
                "branch": "main",
                "commit_message": f"Add {rel_path}",
                "actions": [
                    {
                        "action": "create",
                        "file_path": str(rel_path),
                        "content": base64.b64encode(content).decode("utf-8"),
                        "encoding": "base64",
                    }
                ],
            }

            requests.post(
                f"{self.gitlab_url}/api/v4/projects/{project_id}/repository/commits",
                headers=headers,
                json=file_data,
            )

        return project_id

    def create_env_file(self, root_pass, project_id, group_id):
        headers = {"PRIVATE-TOKEN": self.gitlab_token}
        try:
            r = requests.get(f"{self.gitlab_url}/api/v4/user", headers=headers)
            user_id = r.json()["id"]
        except:
            user_id = 1

        with open(".env", "w") as f:
            f.write(
                f"""GITLAB_ACCESS_TOKEN={self.gitlab_token}
GITLAB_INTERNAL_URL=http://gitlab:80        
GITLAB_EXTERNAL_URL=http://localhost:8080 
GITLAB_USER_ID={user_id}
GITLAB_ROOT_PASSWORD={root_pass}
NEXUS_URL=http://nexus:8081/repository/test-repo/
NEXUS_INTERNAL_URL=http://nexus:8081
NEXUS_EXTERNAL_URL=http://localhost:8081
NEXUS_USERNAME=admin    
NEXUS_PASSWORD=admin123                                             
GROUP_ID={group_id}             
TEMPLATE_PROJECT_ID={project_id}
"""
            )
        # nexus temporaly passsword (need to remove in future)
        print("  .env file created")

    def run(self):
        self.wait_for_service(f"{self.gitlab_url}/users/sign_in", "GitLab", 60)
        root_pass = self.get_gitlab_root_password()
        self.create_gitlab_token()

        self.wait_for_service(f"{self.nexus_url}/service/rest/v1/status", "Nexus", 60)
        self.setup_nexus()

        self.register_runner()

        group_id = self.create_group()
        self.setup_group_variables(group_id)
        project_id = self.setup_project_in_group(group_id)

        self.create_env_file(root_pass, project_id, group_id)

        print("\nSetup complete!")
        print(f"Group ID: {group_id}")
        print(f"Template Project ID: {project_id}")
        print("Configuration saved to .env file")


if __name__ == "__main__":
    TestStandSetup().run()
