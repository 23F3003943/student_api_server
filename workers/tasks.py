
import os
import tempfile
from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from app.models import Task, Base

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")
celery_app = Celery("worker", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"))

# DB setup
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


from github import Github
import subprocess
import uuid


import time
import requests
from datetime import datetime
from app.schemas import EvaluationPayload
from tenacity import retry, stop_after_delay, wait_exponential, retry_if_exception_type


@celery_app.task(name="workers.tasks.process_task")
def process_task(task_id: int):
	db = SessionLocal()
	try:
		# Fetch Task
		task = db.query(Task).filter(Task.id == task_id).first()
		if not task:
			return
		github_token = os.getenv("GITHUB_TOKEN")
		start_time = time.time()
		try:
			# State: GENERATING_PROJECT
			task.status = "GENERATING_PROJECT"
			db.commit()

			# Create project files safely (use getattr for optional fields)
			with tempfile.TemporaryDirectory() as tmpdir:
				task_brief = getattr(task, 'brief', '') or ''
				index_path = os.path.join(tmpdir, "index.html")
				with open(index_path, "w", encoding="utf-8") as f:
					f.write(f"<html><body><p>{task_brief}</p></body></html>")

				readme_path = os.path.join(tmpdir, "README.md")
				with open(readme_path, "w", encoding="utf-8") as f:
					f.write(f"# Task Brief\n{task_brief}\n\nNonce: {task.nonce}")

				license_path = os.path.join(tmpdir, "LICENSE")
				mit_text = """MIT License\n\nCopyright (c) {year} {author}\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\nof this software and associated documentation files (the \"Software\"), to deal\nin the Software without restriction, including without limitation the rights\nto use, copy, modify, merge, publish, distribute, sublicense, and/or sell\ncopies of the Software, and to permit persons to whom the Software is\nfurnished to do so, subject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all\ncopies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\nIMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\nFITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\nAUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\nLIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\nOUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\nSOFTWARE.\n""".format(year="2025", author=task.email)
				with open(license_path, "w", encoding="utf-8") as f:
					f.write(mit_text)

				# State: CREATE_REPO
				task.status = "CREATE_REPO"
				db.commit()
				repo_url = create_github_repo(task, github_token)
				if repo_url:
					task.repo_url = repo_url
					db.commit()

				# State: PUSH_COMMIT
				task.status = "PUSH_COMMIT"
				db.commit()
				commit_sha = push_to_github(task, tmpdir, repo_url, github_token)
				if commit_sha:
					task.commit_sha = commit_sha
					db.commit()

				# State: ENABLE_PAGES
				task.status = "ENABLE_PAGES"
				db.commit()
				enable_github_pages(task, github_token)

				# State: VERIFY_PAGES
				task.status = "VERIFY_PAGES"
				db.commit()
				pages_url = verify_pages_deployment(task)
				if pages_url:
					task.pages_url = pages_url
					db.commit()

				# State: NOTIFY_EVALUATOR
				task.status = "NOTIFY_EVALUATOR"
				db.commit()
				notify_evaluator(task, db, start_time)

				# State: COMPLETE
				task.status = "COMPLETE"
				task.completed_at = datetime.utcnow()
				db.commit()
		except Exception as e:
			task.status = "FAILED"
			task.error_message = str(e)
			db.commit()
	finally:
		db.close()
def build_evaluation_payload(task: Task) -> dict:
	return EvaluationPayload(
		email=task.email,
		task=task.task_name,
		round=task.round,
		nonce=task.nonce,
		repo_url=task.repo_url,
		commit_sha=task.commit_sha,
		pages_url=task.pages_url
	).dict()

# Retry with exponential backoff: 2s, 4s, 8s, 16s, ... up to 10 minutes
@retry(
	stop=stop_after_delay(600),
	wait=wait_exponential(multiplier=2, min=2, max=16),
	retry=retry_if_exception_type(Exception)
)
def post_with_retry(url, payload):
	resp = requests.post(url, json=payload, timeout=10)
	if resp.status_code != 200:
		raise Exception(f"Non-200 response: {resp.status_code}")
	return resp

def notify_evaluator(task: Task, db, start_time):
	if not task.pages_url or not task.repo_url or not task.commit_sha:
		raise Exception("Missing required fields for evaluation notification.")
	# Get original evaluation_url from the DB if needed (assume stored in error_message for now)
	# In a real implementation, this should be a column or related table
	evaluation_url = getattr(task, 'evaluation_url', None)
	if not evaluation_url and hasattr(task, 'error_message') and task.error_message:
		# Hack: try to parse from error_message if stored there
		evaluation_url = task.error_message
	if not evaluation_url:
		raise Exception("No evaluation_url found for task.")
	payload = build_evaluation_payload(task)
	elapsed = time.time() - start_time
	remaining = max(0, 600 - elapsed)
	try:
		post_with_retry(evaluation_url, payload)
	except Exception as e:
		raise Exception(f"Failed to notify evaluator: {e}")

def enable_github_pages(task: Task, github_token: str):
	"""
	Enable GitHub Pages for the repo using the main branch root.
	"""
	if not github_token or not task.repo_url:
		return
	g = Github(github_token)
	repo_full_name = task.repo_url.split("github.com/")[-1].replace(".git", "")
	repo = g.get_repo(repo_full_name)
	repo.edit(has_pages=True)
	repo.update_branch_protection("main")
	repo.create_git_ref(ref="refs/heads/gh-pages", sha=repo.get_branch("main").commit.sha)
	repo.edit(default_branch="main")
	repo.pages_source(branch="main", path="/")

def verify_pages_deployment(task: Task) -> str:
	"""
	Poll the expected GitHub Pages URL until it returns 200 or timeout.
	"""
	if not task.repo_url:
		return None
	# Construct pages URL: https://<owner>.github.io/<repo>/
	repo_full_name = task.repo_url.split("github.com/")[-1].replace(".git", "")
	owner, repo = repo_full_name.split("/")
	pages_url = f"https://{owner}.github.io/{repo}/"
	timeout = 300  # 5 minutes
	interval = 10  # seconds
	elapsed = 0
	while elapsed < timeout:
		try:
			resp = requests.get(pages_url, timeout=5)
			if resp.status_code == 200:
				return pages_url
		except Exception:
			pass
		time.sleep(interval)
		elapsed += interval
	return pages_url  # Return even if not verified, for logging

def create_github_repo(task: Task, github_token: str) -> str:
	"""
	Create a new public GitHub repo using PyGithub and return the repo URL.
	"""
	if not github_token:
		return None
	g = Github(github_token)
	user = g.get_user()
	# Example naming: student-task-{nonce}-{round}
	repo_name = f"student-task-{task.nonce}-{task.round}-{uuid.uuid4().hex[:6]}"
	repo = user.create_repo(
		name=repo_name,
		description=f"Auto-generated repo for task {task.task_name}",
		private=False
	)
	return repo.clone_url

def push_to_github(task: Task, local_path: str, repo_url: str, github_token: str) -> str:
	"""
	Initialize git, commit, and push to the created repo. Return commit SHA.
	"""
	if not repo_url or not github_token:
		return None
	# Set up git config
	env = os.environ.copy()
	env["GIT_AUTHOR_NAME"] = task.email
	env["GIT_COMMITTER_NAME"] = task.email
	# Insert token into repo URL for authentication
	if repo_url.startswith("https://"):
		auth_repo_url = repo_url.replace("https://", f"https://{github_token}@")
	else:
		auth_repo_url = repo_url
	try:
		subprocess.run(["git", "init"], cwd=local_path, check=True, env=env)
		subprocess.run(["git", "add", "."], cwd=local_path, check=True, env=env)
		commit_msg = f"chore: initial commit for {task.task_name} (nonce: {task.nonce})"
		subprocess.run(["git", "commit", "-m", commit_msg], cwd=local_path, check=True, env=env)
		subprocess.run(["git", "remote", "add", "origin", auth_repo_url], cwd=local_path, check=True, env=env)
		subprocess.run(["git", "branch", "-M", "main"], cwd=local_path, check=True, env=env)
		subprocess.run(["git", "push", "-u", "origin", "main"], cwd=local_path, check=True, env=env)
		# Get commit SHA
		result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=local_path, check=True, capture_output=True, text=True, env=env)
		return result.stdout.strip()
	except Exception as e:
		return None

def generate_project_files(task: Task, target_dir: str):
	# index.html
	index_path = os.path.join(target_dir, "index.html")
	with open(index_path, "w", encoding="utf-8") as f:
		f.write(f"<html><body><p>{task.brief or ''}</p></body></html>")

	# README.md
	readme_path = os.path.join(target_dir, "README.md")
	with open(readme_path, "w", encoding="utf-8") as f:
		f.write(f"# Task Brief\n{task.brief or ''}\n\nNonce: {task.nonce}")

	# LICENSE (MIT License)
	license_path = os.path.join(target_dir, "LICENSE")
	mit_text = """MIT License\n\nCopyright (c) {year} {author}\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\nof this software and associated documentation files (the \"Software\"), to deal\nin the Software without restriction, including without limitation the rights\nto use, copy, modify, merge, publish, distribute, sublicense, and/or sell\ncopies of the Software, and to permit persons to whom the Software is\nfurnished to do so, subject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all\ncopies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\nIMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\nFITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\nAUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\nLIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\nOUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\nSOFTWARE.\n""".format(year="2025", author=task.email)
	with open(license_path, "w", encoding="utf-8") as f:
		f.write(mit_text)
