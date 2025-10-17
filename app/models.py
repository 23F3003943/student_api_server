
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class Task(Base):
	__tablename__ = "tasks"

	id = Column(Integer, primary_key=True, index=True)
	nonce = Column(String, unique=True, index=True, nullable=False)
	status = Column(String, nullable=False)
	email = Column(String, nullable=False)
	task_name = Column(String, nullable=False)
	round = Column(Integer, nullable=False)
	received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	repo_url = Column(String, nullable=True)
	commit_sha = Column(String, nullable=True)
	pages_url = Column(String, nullable=True)
	evaluation_url = Column(String, nullable=True)
	brief = Column(Text, nullable=True)
	error_message = Column(Text, nullable=True)
