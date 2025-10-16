
from pydantic import BaseModel, HttpUrl, EmailStr
from typing import List, Optional, Any

class TaskRequest(BaseModel):
	email: EmailStr
	secret: str
	task: str
	round: int
	nonce: str
	brief: Optional[str] = None
	checks: Optional[List[Any]] = None
	evaluation_url: Optional[HttpUrl] = None
	attachments: Optional[List[Any]] = None

class EvaluationPayload(BaseModel):
	email: EmailStr
	task: str
	round: int
	nonce: str
	repo_url: HttpUrl
	commit_sha: str
	pages_url: Optional[HttpUrl] = None

class AcknowledgementResponse(BaseModel):
	status: str
	task: str
	nonce: str
