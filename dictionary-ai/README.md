# DictionaryAI

DictionaryAI is a terminal vocabulary tutor powered by Backboard. It translates
words, explains them in both languages, quizzes you, and tracks your progress in
SQLite.

## Setup

From this directory, create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
export BACKBOARD_API_KEY="your-api-key"  # Windows PowerShell: $env:BACKBOARD_API_KEY="your-api-key"
```

The API key is read only from `BACKBOARD_API_KEY`; it is never stored by the
application. Run the app with:

```bash
python dictionary_ai.py
```

On the first run, enter your native and practice languages. The app creates one
Backboard assistant named `DictionaryAI` and stores its ID in `dictionaryAI.json`
for reuse. Local data is stored in `dictionaryAI.db` (both files are generated
next to the Python file).

## Using the app

Choose **Learn new word** and enter a word in your native language. Choose
**Recap dictionary** to practice native-to-practice, practice-to-native, or
practice definitions. Each recap records practice events used by **Statistics**
to calculate total words, practiced words, practiced days, and the current day
streak.
