import sqlite3

from job_agent.credentials import CredentialStore


class FakeProtector:
	name = "Test protector"

	def protect(self, value: str) -> str:
		return "protected:" + value[::-1]

	def unprotect(self, value: str) -> str:
		assert value.startswith("protected:")
		return value.removeprefix("protected:")[::-1]


def test_computrabajo_credentials_are_protected_and_not_returned(tmp_path):
	db_path = tmp_path / "job-agent.db"
	store = CredentialStore(db_path, protector=FakeProtector())
	password = "super-secret-password"

	status = store.save_computrabajo("user@example.com", password)

	assert status["configured"] is True
	assert status["username"] == "user@example.com"
	assert "password" not in status
	assert store.load_computrabajo() == ("user@example.com", password)

	with sqlite3.connect(db_path) as connection:
		row = connection.execute("SELECT secret_blob FROM local_credentials WHERE service = 'computrabajo'").fetchone()
	assert row is not None
	assert password not in str(row[0])


def test_computrabajo_credentials_can_be_cleared(tmp_path):
	store = CredentialStore(tmp_path / "job-agent.db", protector=FakeProtector())
	store.save_computrabajo("user@example.com", "secret")

	store.clear_computrabajo()

	assert store.computrabajo_status()["configured"] is False
	assert store.load_computrabajo() is None
