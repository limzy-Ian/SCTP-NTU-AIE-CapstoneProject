"""Persistent, source-cited Streamlit chat history stored in MySQL."""
from __future__ import annotations

import json
import re
import uuid

CHAT_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS chat_sessions (
      chat_id CHAR(36) NOT NULL PRIMARY KEY,
      title VARCHAR(120) NOT NULL,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      KEY idx_chat_sessions_updated (updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS chat_messages (
      message_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
      chat_id CHAR(36) NOT NULL,
      message_index INT UNSIGNED NOT NULL,
      role VARCHAR(16) NOT NULL,
      content LONGTEXT NOT NULL,
      sources_json JSON NULL,
      token_count INT UNSIGNED NOT NULL DEFAULT 0,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE KEY uq_chat_message_index (chat_id, message_index),
      CONSTRAINT fk_chat_messages_session FOREIGN KEY (chat_id)
        REFERENCES chat_sessions(chat_id) ON DELETE CASCADE,
      KEY idx_chat_messages_created (chat_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
)


def ensure_chat_schema(connection) -> None:
    cursor = connection.cursor()
    try:
        for statement in CHAT_SCHEMA:
            cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close()


def list_chats(connection, limit: int = 50) -> list[dict]:
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT chat_id, title, created_at, updated_at FROM chat_sessions "
            "ORDER BY updated_at DESC LIMIT %s",
            (limit,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()


def load_chat_messages(connection, chat_id: str) -> list[dict]:
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT role, content, sources_json, token_count, created_at "
            "FROM chat_messages WHERE chat_id=%s ORDER BY message_index",
            (chat_id,),
        )
        messages = cursor.fetchall()
        for message in messages:
            sources = message.get("sources_json")
            if isinstance(sources, str):
                try:
                    sources = json.loads(sources)
                except json.JSONDecodeError:
                    sources = []
            message["sources"] = sources or []
        return messages
    finally:
        cursor.close()


def create_chat(connection, first_question: str) -> str:
    chat_id = str(uuid.uuid4())
    title = re.sub(r"\s+", " ", first_question).strip()[:117]
    if len(first_question.strip()) > 117:
        title += "..."
    if not title:
        title = "New conversation"
    cursor = connection.cursor()
    try:
        cursor.execute("INSERT INTO chat_sessions (chat_id, title) VALUES (%s, %s)", (chat_id, title))
        connection.commit()
        return chat_id
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def append_chat_turn(connection, chat_id: str, user_content: str, assistant_content: str,
                     sources: list[dict], token_count: int = 0) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT COALESCE(MAX(message_index), 0) FROM chat_messages WHERE chat_id=%s", (chat_id,))
        next_index = int(cursor.fetchone()[0])
        cursor.executemany(
            """INSERT INTO chat_messages
               (chat_id, message_index, role, content, sources_json, token_count)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            [
                (chat_id, next_index + 1, "user", user_content, None, 0),
                (chat_id, next_index + 2, "assistant", assistant_content,
                 json.dumps(sources, ensure_ascii=True, default=str), max(0, int(token_count))),
            ],
        )
        cursor.execute("UPDATE chat_sessions SET updated_at=CURRENT_TIMESTAMP WHERE chat_id=%s", (chat_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def delete_chat(connection, chat_id: str) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM chat_sessions WHERE chat_id=%s", (chat_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
