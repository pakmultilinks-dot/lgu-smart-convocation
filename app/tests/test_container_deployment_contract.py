"""No production files in container builds: static CI contract, no DB access."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ContainerDeploymentContractTests(unittest.TestCase):
    def test_dockerfile_uses_unprivileged_production_wsgi(self):
        docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("USER 10001", docker)
        self.assertIn('"run:app"', docker)
        self.assertIn('"gunicorn"', docker)
        self.assertIn('"--workers", "1"', docker)
        self.assertIn("/api/health", docker)
        self.assertNotIn("flask run", docker.lower())
        self.assertNotIn("LGU_ALLOW_DEMO_SECRETS=1", docker)
        self.assertNotIn("LGU_TESTING=1", docker)
        self.assertNotIn("LGU_APP_ENV=development", docker)

    def test_build_context_ignores_sensitive_artifacts(self):
        context = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        for required in (
            ".git/", ".env", "**/*.db", "**/*.sqlite",
            "**/*.sqlite3", "**/backups/", "**/data/",
            "**/*.pem", "**/*.key", "**/*.apk", "**/*.aab",
        ):
            with self.subTest(required=required):
                self.assertIn(required, context)

    def test_container_staging_workflow_never_pushes_or_deploys(self):
        workflow = (
            ROOT / ".github/workflows/container-staging-smoke.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("docker build", workflow)
        self.assertIn("docker run", workflow)
        self.assertIn("LGU_DB_PATH=/tmp/lgu-staging-ci.sqlite3", workflow)
        self.assertIn("LGU_APP_ENV=development", workflow)
        self.assertIn("LGU_APP_ENV=production", workflow)
        self.assertNotIn("docker push ", workflow)
        self.assertNotIn("kubectl ", workflow)


if __name__ == "__main__":
    unittest.main()
