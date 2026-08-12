"""DictionaryAI: a small terminal companion for learning vocabulary."""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    from backboard import BackboardClient
except ImportError:  # Gives a useful message instead of a cryptic import error.
    BackboardClient = None  # type: ignore[assignment,misc]


ASSISTANT_NAME = "DictionaryAI"
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "dictionaryAI.db"
ASSISTANT_PATH = BASE_DIR / "dictionaryAI.json"
LANGUAGE_FLAGS = {
    "english": "🇬🇧", "spanish": "🇪🇸", "french": "🇫🇷", "german": "🇩🇪",
    "italian": "🇮🇹", "portuguese": "🇵🇹", "russian": "🇷🇺", "japanese": "🇯🇵",
    "korean": "🇰🇷", "chinese": "🇨🇳", "mandarin": "🇨🇳", "turkish": "🇹🇷",
    "arabic": "🇸🇦", "azerbaijani": "🇦🇿", "azeri": "🇦🇿", "hindi": "🇮🇳",
}


def flag(language: str) -> str:
    return LANGUAGE_FLAGS.get(language.strip().lower(), "🌐")


def connect_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS preferences (
            id INTEGER PRIMARY KEY CHECK (id = 1), native_language TEXT NOT NULL,
            practice_language TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dictionary (
            id INTEGER PRIMARY KEY, original_word TEXT NOT NULL UNIQUE,
            native_definition TEXT NOT NULL, practice_word TEXT NOT NULL,
            practice_definition TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS practice_events (
            id INTEGER PRIMARY KEY, word_id INTEGER NOT NULL, practiced_on TEXT NOT NULL,
            FOREIGN KEY(word_id) REFERENCES dictionary(id)
        );
        CREATE TABLE IF NOT EXISTS statistics (
            id INTEGER PRIMARY KEY CHECK (id = 1), total_words INTEGER NOT NULL DEFAULT 0,
            practiced_words_total INTEGER NOT NULL DEFAULT 0, practiced_days INTEGER NOT NULL DEFAULT 0,
            current_practice_day_streak INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
        );
        """
    )
    return db


def ask(prompt: str) -> str:
    while True:
        answer = input(prompt).strip()
        if answer:
            return answer
        print("Please enter a value.")


def get_preferences(db: sqlite3.Connection) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM preferences WHERE id = 1").fetchone()


def save_preferences(db: sqlite3.Connection, native: str, practice: str) -> None:
    now = date.today().isoformat()
    db.execute(
        "INSERT INTO preferences(id,native_language,practice_language,updated_at) VALUES(1,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET native_language=excluded.native_language, "
        "practice_language=excluded.practice_language, updated_at=excluded.updated_at",
        (native, practice, now),
    )
    db.commit()


def json_from_reply(text: Any) -> dict[str, str]:
    """Accept JSON and JSON wrapped in a markdown code fence."""
    if isinstance(text, dict):
        return {str(k): str(v) for k, v in text.items()}
    if not isinstance(text, str):
        raise ValueError("The assistant returned an unsupported response")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("The assistant did not return JSON")
    value = json.loads(match.group(0))
    return {str(k): str(v) for k, v in value.items()}


async def load_or_create_assistant(client: Any) -> str:
    if ASSISTANT_PATH.exists():
        try:
            saved = json.loads(ASSISTANT_PATH.read_text(encoding="utf-8"))
            assistant_id = str(saved["assistant_id"])
            await client.get_assistant(assistant_id)
            return assistant_id
        except (OSError, ValueError, KeyError, TypeError):
            pass

    # Do not use the unsupported name= keyword: some SDK releases only expose
    # skip/limit even though the REST API supports name filtering.
    assistants = await client.list_assistants(skip=0, limit=200)
    for assistant in assistants:
        if getattr(assistant, "name", None) == ASSISTANT_NAME:
            assistant_id = str(getattr(assistant, "assistant_id"))
            ASSISTANT_PATH.write_text(json.dumps({"assistant_id": assistant_id}, indent=2) + "\n", encoding="utf-8")
            return assistant_id

    assistant = await client.create_assistant(
        name=ASSISTANT_NAME,
        system_prompt=("You are DictionaryAI, a precise and encouraging language tutor. "
                       "Help users learn vocabulary. Return requested vocabulary data as valid JSON only."),
    )
    assistant_id = str(getattr(assistant, "assistant_id"))
    ASSISTANT_PATH.write_text(json.dumps({"assistant_id": assistant_id}, indent=2) + "\n", encoding="utf-8")
    return assistant_id


async def translate_word(client: Any, assistant_id: str, word: str, native: str, practice: str) -> dict[str, str]:
    prompt = f"""For the {native} word {word!r}, provide vocabulary learning data for {practice}.
Return JSON with exactly these string keys: practice_word, native_definition, practice_definition.
Definitions should be concise and clear, and native_definition must be in {native};
practice_definition must be in {practice}. Do not add markdown or extra keys."""
    response = await client.send_message(prompt, assistant_id=assistant_id, json_output=True, memory="off")
    return json_from_reply(response.content)


def refresh_statistics(db: sqlite3.Connection) -> None:
    words = db.execute("SELECT COUNT(*) FROM dictionary").fetchone()[0]
    events = db.execute("SELECT COUNT(*) FROM practice_events").fetchone()[0]
    days = [date.fromisoformat(r[0]) for r in db.execute("SELECT DISTINCT practiced_on FROM practice_events ORDER BY practiced_on DESC")]
    practiced_days = len(days)
    streak = 0
    expected = date.today()
    for day in days:
        if day == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif day < expected:
            break
    db.execute("INSERT INTO statistics(id,total_words,practiced_words_total,practiced_days,current_practice_day_streak,updated_at) "
               "VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET total_words=excluded.total_words, "
               "practiced_words_total=excluded.practiced_words_total, practiced_days=excluded.practiced_days, "
               "current_practice_day_streak=excluded.current_practice_day_streak, updated_at=excluded.updated_at",
               (words, events, practiced_days, streak, date.today().isoformat()))
    db.commit()


async def learn(db: sqlite3.Connection, client: Any, assistant_id: str, native: str, practice: str) -> None:
    word = ask(f"Enter a word in {flag(native)} {native}: ")
    try:
        data = await translate_word(client, assistant_id, word, native, practice)
        required = {"practice_word", "native_definition", "practice_definition"}
        if not required <= data.keys():
            raise ValueError("incomplete response")
    except Exception as exc:
        print(f"Could not get a definition from DictionaryAI: {exc}")
        return
    db.execute("INSERT INTO dictionary(original_word,native_definition,practice_word,practice_definition,created_at) VALUES(?,?,?,?,?) "
               "ON CONFLICT(original_word) DO UPDATE SET native_definition=excluded.native_definition, "
               "practice_word=excluded.practice_word, practice_definition=excluded.practice_definition",
               (word, data["native_definition"], data["practice_word"], data["practice_definition"], date.today().isoformat()))
    db.commit(); refresh_statistics(db)
    print(f"\n{flag(native)} {word} → {flag(practice)} {data['practice_word']}\n{native}: {data['native_definition']}\n{practice}: {data['practice_definition']}\n")


def recap(db: sqlite3.Connection, native: str, practice: str) -> None:
    words = db.execute("SELECT * FROM dictionary ORDER BY RANDOM() LIMIT 5").fetchall()
    if not words:
        print("Your dictionary is empty. Learn a new word first."); return
    print("1. Native → practice\n2. Practice → native\n3. Practice with definitions")
    mode = ask("Recap type: ")
    if mode not in {"1", "2", "3"}:
        print("Please choose 1, 2, or 3."); return
    for item in words:
        question = item["original_word"] if mode == "1" else item["practice_word"]
        print(f"\nQuestion: {question}")
        ask("Your answer (press Enter when ready): ")
        if mode == "1": print(f"Answer: {item['practice_word']}")
        elif mode == "2": print(f"Answer: {item['original_word']}")
        else: print(f"{practice}: {item['practice_definition']}\n{native}: {item['native_definition']}")
        db.execute("INSERT INTO practice_events(word_id,practiced_on) VALUES(?,?)", (item["id"], date.today().isoformat()))
    db.commit(); refresh_statistics(db)


def show_statistics(db: sqlite3.Connection) -> None:
    refresh_statistics(db)
    row = db.execute("SELECT * FROM statistics WHERE id=1").fetchone()
    print(f"\nTotal words: {row['total_words']}\nPracticed words total: {row['practiced_words_total']}\n"
          f"Practiced days: {row['practiced_days']}\nCurrent practice day streak: {row['current_practice_day_streak']}\n")


async def app_main() -> int:
    if not os.getenv("BACKBOARD_API_KEY"):
        print("Error: set BACKBOARD_API_KEY before running DictionaryAI.", file=sys.stderr); return 1
    if BackboardClient is None:
        print("Error: install dependencies with 'pip install -r requirements.txt'.", file=sys.stderr); return 1
    db = connect_db()
    prefs = get_preferences(db)
    if prefs is None:
        native = ask("What is your native language? ")
        practice = ask("What language do you want to learn? ")
        save_preferences(db, native, practice)
    else:
        native, practice = prefs["native_language"], prefs["practice_language"]
    print(f"\nDictionaryAI {flag(native)} {native} → {flag(practice)} {practice}")
    try:
        client = BackboardClient(api_key=os.environ["BACKBOARD_API_KEY"])
        assistant_id = await load_or_create_assistant(client)
        while True:
            print("\n1. Learn new word\n2. Recap dictionary\n3. Statistics\n4. Exit")
            choice = input("Choose an option: ").strip()
            if choice == "1": await learn(db, client, assistant_id, native, practice)
            elif choice == "2": recap(db, native, practice)
            elif choice == "3": show_statistics(db)
            elif choice == "4": print("Goodbye!"); return 0
            else: print("Please choose 1, 2, 3, or 4.")
    except KeyboardInterrupt:
        print("\nGoodbye!"); return 0
    except Exception as exc:
        print(f"DictionaryAI error: {exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(app_main()))
